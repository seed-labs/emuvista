"""Email delivery for account verification."""

from __future__ import annotations

import smtplib
from email.message import EmailMessage

from .settings import settings


class EmailNotConfigured(RuntimeError):
    pass


def send_verification_code(email: str, code: str) -> None:
    if not settings.email_host:
        raise EmailNotConfigured("Stock Service email delivery is not configured")

    message = EmailMessage()
    message["Subject"] = "Verify your Stock Service account"
    message["From"] = settings.email_from
    message["To"] = email
    message.set_content(
        "Your Stock Service verification code is {}. It expires in {} minutes.\n".format(
            code, max(1, (settings.verification_ttl_seconds + 59) // 60)
        )
    )

    with smtplib.SMTP(settings.email_host, settings.email_port, timeout=10) as smtp:
        if settings.email_starttls:
            smtp.starttls()
        if settings.email_user:
            smtp.login(settings.email_user, settings.email_password)
        smtp.send_message(message)
