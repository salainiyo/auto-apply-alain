import hashlib
from datetime import datetime, timedelta, timezone
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import logger
from app.db.models import JobMatch, Resume, Role, User
from app.services import job_sources

JOB_EXPIRY_DAYS = 60  # postings older than this are considered expired


def job_fingerprint(company: str, title: str, url: str, posted_at: datetime | None) -> str:
    raw = f"{(company or '').lower().strip()}|{(title or '').lower().strip()}|{(url or '').lower().strip()}|{posted_at.isoformat() if posted_at else 'no-date'}"
    return hashlib.sha256(raw.encode()).hexdigest()


def is_expired(listing: dict, now: datetime | None = None) -> bool:
    """A job is expired when its posting date is missing or too old."""
    posted_at = listing.get("posted_at")
    if not posted_at:
        return True
    now = now or datetime.now(timezone.utc)
    if posted_at.tzinfo is None:
        posted_at = posted_at.replace(tzinfo=timezone.utc)
    return posted_at < now - timedelta(days=JOB_EXPIRY_DAYS)


def determine_locality(listing: dict, country: str) -> str | None:
    """local = job in the user's residence country; remote = anywhere.

    Returns None for on-site jobs outside the residence country (not relevant).
    """
    if listing.get("is_remote"):
        return "remote"

    location = (listing.get("location") or "").lower()
    if country and country.lower() in location:
        return "local"
    return None


async def get_current_resume(db: AsyncSession, user_id) -> Resume | None:
    result = await db.execute(
        select(Resume)
        .where(Resume.user_id == user_id, Resume.is_current.is_(True))
        .order_by(Resume.created_at.desc())
    )
    return result.scalars().first()


async def get_roles_for_resume(db: AsyncSession, resume_id) -> list[Role]:
    result = await db.execute(
        select(Role).where(Role.resume_id == resume_id).order_by(Role.created_at.asc())
    )
    return list(result.scalars().all())


async def existing_fingerprints(db: AsyncSession, user_id) -> set[str]:
    result = await db.execute(select(JobMatch.fingerprint).where(JobMatch.user_id == user_id))
    return set(result.scalars().all())


def collect_listings_for_role(role: Role, country: str) -> list[dict]:
    """Query every source for one role. Sources fail soft (errors -> empty list)."""
    keywords = role.keywords or role.title
    listings: list[dict] = []

    for fetch in (
        job_sources.fetch_remotive,
        job_sources.fetch_remoteok,
        job_sources.fetch_arbeitnow,
    ):
        for listing in fetch(keywords):
            if job_sources.matches_keyword(listing["title"], listing["company"], keywords):
                listings.append(listing)

    for listing in job_sources.scrape_weworkremotely(keywords):
        if job_sources.matches_keyword(listing["title"], listing["company"], keywords):
            listings.append(listing)

    # web search for in-country local postings, kept alongside the free-API results
    listings.extend(job_sources.fetch_web_local(keywords, country))

    return listings


async def search_jobs_for_user(db: AsyncSession, user_id) -> list[JobMatch]:
    """Search all sources for the roles of the user's current resume.

    - filters out expired jobs
    - keeps remote jobs and jobs in the user's residence country
    - dedups via fingerprint: never re-presents a known job; a reopened
      position (new posting date) gets a new fingerprint and re-enters Available
    """
    user = await db.get(User, user_id)
    if not user:
        return []

    try:
        resume = await get_current_resume(db, user_id)
        if not resume:
            return []

        roles = await get_roles_for_resume(db, resume.id)
        if not roles:
            return []

        known = await existing_fingerprints(db, user_id)

        new_matches: list[JobMatch] = []
        seen_this_run: set[str] = set()

        for role in roles:
            for listing in collect_listings_for_role(role, user.country):
                if is_expired(listing):
                    continue

                locality = determine_locality(listing, user.country)
                if locality is None:
                    continue

                fingerprint = job_fingerprint(
                    listing["company"], listing["title"], listing["url"], listing["posted_at"]
                )
                if fingerprint in known or fingerprint in seen_this_run:
                    continue

                seen_this_run.add(fingerprint)
                new_matches.append(
                    JobMatch(
                        user_id=user_id,
                        role_id=role.id,
                        title=listing["title"][:255],
                        company=listing["company"][:255],
                        location=listing["location"],
                        url=listing["url"][:512],
                        source=listing["source"],
                        job_type=listing["job_type"],
                        is_remote=listing["is_remote"],
                        locality=locality,
                        posted_at=listing["posted_at"],
                        fingerprint=fingerprint,
                        status="available",
                    )
                )

        for match in new_matches:
            db.add(match)
        if new_matches:
            await db.commit()
            logger.info(
                "job_matches_found user_id=%s count=%s", user_id, len(new_matches)
            )
        return new_matches
    finally:
        # always record that a search ran, even when nothing matched
        try:
            user.last_search_at = datetime.now(timezone.utc)
            await db.commit()
        except Exception as exc:
            logger.warning("search_timestamp_save_failed error=%s", exc)
