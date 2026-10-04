from datetime import datetime

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import security
from app.core.logging import logger
from app.db.models import RevokedToken, User


async def get_user_by_email(db: AsyncSession, email: str) -> User | None:
    result = await db.execute(select(User).where(User.email == email))
    return result.scalar_one_or_none()


async def create_user(db: AsyncSession, email: str, password: str, country: str) -> User:
    user = User(
        email=email,
        hashed_password=security.hash_password(password),
        is_verified=False,
        country=country,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    logger.info("user_registered email=%s country=%s", email, country)
    return user


async def revoke_token(db: AsyncSession, jti: str, expires_at: datetime) -> None:
    await db.merge(RevokedToken(jti=jti, expires_at=expires_at))
    await db.execute(delete(RevokedToken).where(RevokedToken.expires_at < datetime.now()))
    await db.commit()
    logger.info("token_revoked jti=%s", jti)


async def is_token_revoked(db: AsyncSession, jti: str) -> bool:
    result = await db.execute(select(RevokedToken).where(RevokedToken.jti == jti))
    return result.scalar_one_or_none() is not None
