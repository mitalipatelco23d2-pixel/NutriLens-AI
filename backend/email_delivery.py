"""Transactional authentication email delivery without token or content logging."""

from __future__ import annotations

from html import escape

import httpx

from backend.settings import Settings, settings


class EmailDeliveryError(RuntimeError):
    """Raised when configured transactional delivery does not accept a message."""


def _send_resend(*, to: str, subject: str, html: str, config: Settings) -> None:
    response = httpx.post(
        "https://api.resend.com/emails",
        headers={
            "Authorization": f"Bearer {config.resend_api_key}",
            "Content-Type": "application/json",
        },
        json={
            "from": config.email_from,
            "to": [to],
            "subject": subject,
            "html": html,
        },
        timeout=8.0,
    )
    if response.status_code >= 300:
        raise EmailDeliveryError("Transactional email provider rejected the message.")


def _send(*, to: str, subject: str, html: str, config: Settings = settings) -> None:
    if config.email_provider == "resend" and config.resend_api_key and config.email_from:
        _send_resend(to=to, subject=subject, html=html, config=config)
        return
    raise EmailDeliveryError("Transactional email is not configured.")


def send_verification_email(
    *,
    email: str,
    display_name: str,
    token: str,
    otp: str | None = None,
    config: Settings = settings,
) -> None:
    link = f"{config.public_web_url.rstrip('/')}/login?mode=verify&token={token}"
    safe_name = escape(display_name)
    safe_link = escape(link, quote=True)
    otp_block = (
        f"<p>Your 6-digit verification code is: <strong>{escape(otp)}</strong></p>" if otp else ""
    )
    _send(
        to=email,
        subject="Verify your NutriLens X email",
        html=(
            f"<p>Hello {safe_name},</p>"
            f"{otp_block}"
            "<p>Or verify your email to finish creating your NutriLens X account.</p>"
            f'<p><a href="{safe_link}">Verify email</a></p>'
            "<p>This link and code expire soon. "
            "If you did not request it, you can ignore this email.</p>"
            "<p>NutriLens X</p>"
        ),
        config=config,
    )


def send_otp_email(*, email: str, display_name: str, otp: str, config: Settings = settings) -> None:
    safe_name = escape(display_name)
    safe_otp = escape(otp)
    _send(
        to=email,
        subject="Your NutriLens X verification code",
        html=(
            f"<p>Hello {safe_name},</p>"
            "<p>Your 6-digit verification code is:</p>"
            f"<h2 style='letter-spacing: 4px; font-size: 28px;'>{safe_otp}</h2>"
            "<p>This code expires in 10 minutes. Do not share it with anyone.</p>"
            "<p>NutriLens X</p>"
        ),
        config=config,
    )


def send_password_reset_email(
    *, email: str, display_name: str, token: str, config: Settings = settings
) -> None:
    link = f"{config.public_web_url.rstrip('/')}/login?mode=reset&token={token}"
    safe_name = escape(display_name)
    safe_link = escape(link, quote=True)
    _send(
        to=email,
        subject="Reset your NutriLens X password",
        html=(
            f"<p>Hello {safe_name},</p>"
            "<p>Use the secure link below to reset your NutriLens X password.</p>"
            f'<p><a href="{safe_link}">Reset password</a></p>'
            "<p>This one-time link expires soon. If you did not request it, "
            "secure your email account.</p>"
            "<p>NutriLens X</p>"
        ),
        config=config,
    )
