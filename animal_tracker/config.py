"""Settings read from environment variables."""

from __future__ import annotations

import os

from .alert import SmtpSettings


def smtp_from_env() -> SmtpSettings:
    """Gmail defaults; ALERT_SMTP_PASSWORD should be a Gmail app password."""
    username = os.environ["ALERT_SMTP_USERNAME"]
    return SmtpSettings(
        host=os.environ.get("ALERT_SMTP_HOST", "smtp.gmail.com"),
        port=int(os.environ.get("ALERT_SMTP_PORT", "587")),
        username=username,
        password=os.environ["ALERT_SMTP_PASSWORD"],
        sender=os.environ.get("ALERT_FROM", username),
        recipient=os.environ.get("ALERT_TO", username),
    )
