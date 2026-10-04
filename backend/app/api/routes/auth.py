from datetime import datetime, timezone

import jwt as pyjwt
from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.core import security
from app.core.logging import logger
from app.core.security import (
    ACCESS_TOKEN_TYPE,
    EMAIL_VERIFY_TOKEN_TYPE,
    PASSWORD_RESET_TOKEN_TYPE,
    REFRESH_TOKEN_TYPE,
)
from app.db.database import get_db
from app.db.models import User
from app.middleware.rate_limit import rate_limit
from app.schemas.auth import (
    AccessTokenResponse,
    ChangePasswordRequest,
    ForgotPasswordRequest,
    LoginRequest,
    MessageResponse,
    RefreshRequest,
    RegisterRequest,
    ResetPasswordRequest,
    TokenResponse,
    VerifyEmailRequest,
)
from app.services import auth_service, email_service

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post(
    "/register",
    response_model=MessageResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(rate_limit(limit=10, window_seconds=60))],
)
async def register(body: RegisterRequest, db: AsyncSession = Depends(get_db)):
    existing = await auth_service.get_user_by_email(db, body.email)
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Email already registered",
        )

    user = await auth_service.create_user(db, body.email, body.password, body.country)
    token = security.create_email_verify_token(str(user.id))
    try:
        await email_service.send_verification_email(user.email, token)
    except Exception:
        logger.exception("verification_email_failed email=%s", user.email)

    return {
        "message": "Registration successful. Please check your email to verify your account."
    }


@router.post(
    "/verify-email",
    response_model=MessageResponse,
    dependencies=[Depends(rate_limit(limit=10, window_seconds=60))],
)
async def verify_email(body: VerifyEmailRequest, db: AsyncSession = Depends(get_db)):
    try:
        payload = security.decode_token(body.token)
    except pyjwt.ExpiredSignatureError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Verification link has expired"
        )
    except pyjwt.InvalidTokenError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid verification token"
        )

    if payload.get("type") != EMAIL_VERIFY_TOKEN_TYPE:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid verification token"
        )

    from uuid import UUID

    try:
        user_id = UUID(payload.get("sub", ""))
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid verification token"
        )

    user = await db.get(User, user_id)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid verification token"
        )

    if user.is_verified:
        return {"message": "Email is already verified"}

    user.is_verified = True
    await db.commit()
    logger.info("email_verified email=%s", user.email)
    return {"message": "Email verified successfully. You can now log in."}


@router.post(
    "/login",
    response_model=TokenResponse,
    dependencies=[Depends(rate_limit(limit=5, window_seconds=60))],
)
async def login(body: LoginRequest, db: AsyncSession = Depends(get_db)):
    user = await auth_service.get_user_by_email(db, body.email)
    if not user or not security.verify_password(user.hashed_password, body.password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
        )

    if not user.is_verified:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Email not verified. Please verify your email first.",
        )

    access_token = security.create_access_token(str(user.id))
    refresh_token = security.create_refresh_token(str(user.id))
    logger.info("user_logged_in email=%s", user.email)
    return {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "token_type": "bearer",
    }


@router.post(
    "/refresh",
    response_model=AccessTokenResponse,
    dependencies=[Depends(rate_limit(limit=10, window_seconds=60))],
)
async def refresh(body: RefreshRequest, db: AsyncSession = Depends(get_db)):
    try:
        payload = security.decode_token(body.refresh_token)
    except pyjwt.ExpiredSignatureError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Refresh token has expired"
        )
    except pyjwt.InvalidTokenError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid refresh token"
        )

    if payload.get("type") != REFRESH_TOKEN_TYPE:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token type"
        )

    from uuid import UUID

    try:
        user_id = UUID(payload.get("sub", ""))
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid refresh token"
        )

    user = await db.get(User, user_id)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found"
        )

    access_token = security.create_access_token(str(user.id))
    return {"access_token": access_token, "token_type": "bearer"}


@router.post(
    "/logout",
    response_model=MessageResponse,
    dependencies=[Depends(rate_limit(limit=10, window_seconds=60))],
)
async def logout(
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    auth_header = request.headers.get("authorization", "")
    token = auth_header.split(" ", 1)[1] if " " in auth_header else auth_header
    payload = security.decode_token(token)
    jti = payload.get("jti", "")
    exp = datetime.fromtimestamp(payload.get("exp", 0), tz=timezone.utc)

    await auth_service.revoke_token(db, jti, exp)
    return {"message": "Logged out successfully"}


@router.post(
    "/forgot-password",
    response_model=MessageResponse,
    dependencies=[Depends(rate_limit(limit=5, window_seconds=60))],
)
async def forgot_password(body: ForgotPasswordRequest, db: AsyncSession = Depends(get_db)):
    user = await auth_service.get_user_by_email(db, body.email)
    if user:
        token = security.create_password_reset_token(str(user.id))
        try:
            await email_service.send_password_reset_email(user.email, token)
        except Exception:
            logger.exception("password_reset_email_failed email=%s", user.email)

    return {"message": "If that email exists, a password reset link has been sent."}


@router.post(
    "/reset-password",
    response_model=MessageResponse,
    dependencies=[Depends(rate_limit(limit=5, window_seconds=60))],
)
async def reset_password(body: ResetPasswordRequest, db: AsyncSession = Depends(get_db)):
    try:
        payload = security.decode_token(body.token)
    except pyjwt.ExpiredSignatureError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Reset link has expired"
        )
    except pyjwt.InvalidTokenError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid reset token"
        )

    if payload.get("type") != PASSWORD_RESET_TOKEN_TYPE:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid reset token"
        )

    from uuid import UUID

    try:
        user_id = UUID(payload.get("sub", ""))
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid reset token"
        )

    user = await db.get(User, user_id)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid reset token"
        )

    user.hashed_password = security.hash_password(body.new_password)
    await db.commit()
    logger.info("password_reset email=%s", user.email)
    return {"message": "Password reset successfully. You can now log in."}


@router.post(
    "/change-password",
    response_model=MessageResponse,
    dependencies=[Depends(rate_limit(limit=5, window_seconds=60))],
)
async def change_password(
    body: ChangePasswordRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if not security.verify_password(
        current_user.hashed_password, body.current_password
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Current password is incorrect",
        )

    current_user.hashed_password = security.hash_password(body.new_password)
    await db.commit()
    logger.info("password_changed email=%s", current_user.email)
    return {"message": "Password changed successfully"}
