import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from fastapi.concurrency import run_in_threadpool

from app.core.config import settings
from app.core.logging import logger


def _send_sync(to: str, subject: str, html: str) -> None:
    from_user = settings.emails_from or settings.smtp_user
    if not settings.smtp_user or not settings.smtp_password or not from_user:
        logger.warning("SMTP not configured, skipping email send to %s", to)
        return

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = from_user
    msg["To"] = to
    msg.attach(MIMEText(html, "html", "utf-8"))

    with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=15) as smtp:
        smtp.starttls()
        smtp.login(settings.smtp_user, settings.smtp_password)
        smtp.sendmail(from_user, [to], msg.as_string())


async def send_email(to: str, subject: str, html: str) -> None:
    await run_in_threadpool(_send_sync, to, subject, html)


async def send_verification_email(to: str, token: str) -> None:
    link = f"{settings.frontend_url}/verify-email?token={token}"
    html = (
        "<p>Welcome! Please verify your email address by clicking the link below:</p>"
        f"<p><a href='{link}'>Verify my email</a></p>"
        f"<p>Or copy this link: {link}</p>"
        "<p>This link expires in 24 hours.</p>"
    )
    await send_email(to, "Verify your email", html)


async def send_password_reset_email(to: str, token: str) -> None:
    link = f"{settings.frontend_url}/reset-password?token={token}"
    html = (
        "<p>You requested a password reset. Click the link below to set a new password:</p>"
        f"<p><a href='{link}'>Reset my password</a></p>"
        f"<p>Or copy this link: {link}</p>"
        "<p>This link expires in 1 hour. If you did not request this, ignore this email.</p>"
    )
    await send_email(to, "Reset your password", html)
