import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, UploadFile, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.core.logging import logger
from app.db.database import get_db
from app.db.models import Resume, User
from app.middleware.rate_limit import rate_limit
from app.schemas.resume import CurrentResumeResponse, ResumeResponse
from app.workers import tasks as worker_tasks

router = APIRouter(prefix="/resumes", tags=["resumes"])

UPLOAD_DIR = Path("uploads/resumes")
MAX_UPLOAD_SIZE = 10 * 1024 * 1024  # 10 MB
ALLOWED_CONTENT_TYPES = {"application/pdf"}


def _validate_pdf(file: UploadFile, content: bytes) -> None:
    if not file.filename or not file.filename.lower().endswith(".pdf"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Only PDF files are allowed",
        )
    if file.content_type not in ALLOWED_CONTENT_TYPES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Only PDF files are allowed (invalid content type)",
        )
    if not content.startswith(b"%PDF-"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid PDF file",
        )


@router.post(
    "/upload",
    response_model=ResumeResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(rate_limit(limit=10, window_seconds=60))],
)
async def upload_resume(
    file: UploadFile,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    content = await file.read()
    if len(content) > MAX_UPLOAD_SIZE:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="File too large (max 10 MB)",
        )
    _validate_pdf(file, content)

    user_dir = UPLOAD_DIR / str(current_user.id)
    user_dir.mkdir(parents=True, exist_ok=True)
    pdf_path = user_dir / f"{uuid.uuid4()}.pdf"
    pdf_path.write_bytes(content)

    # New upload becomes the current resume; previous ones lose the flag
    current_resumes = (
        (
            await db.execute(
                select(Resume).where(
                    Resume.user_id == current_user.id, Resume.is_current.is_(True)
                )
            )
        )
        .scalars()
        .all()
    )
    for resume in current_resumes:
        resume.is_current = False

    resume = Resume(
        user_id=current_user.id,
        original_filename=file.filename,
        pdf_path=str(pdf_path),
        status="pending",
        is_current=True,
    )
    db.add(resume)
    await db.commit()
    await db.refresh(resume)

    worker_tasks.convert_resume_pdf.delay(str(resume.id))
    logger.info(
        "resume_uploaded user_id=%s resume_id=%s filename=%s",
        current_user.id,
        resume.id,
        file.filename,
    )
    return resume


@router.get("", response_model=list[ResumeResponse])
async def list_resumes(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Resume)
        .where(Resume.user_id == current_user.id)
        .order_by(Resume.created_at.desc())
    )
    return result.scalars().all()


@router.get("/current", response_model=CurrentResumeResponse)
async def get_current_resume(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Resume)
        .where(Resume.user_id == current_user.id, Resume.is_current.is_(True))
        .order_by(Resume.created_at.desc())
    )
    resume = result.scalars().first()
    if not resume:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No resume uploaded yet",
        )
    return resume
