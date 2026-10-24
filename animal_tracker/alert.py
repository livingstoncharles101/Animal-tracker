"""Build and send the alert email."""

from __future__ import annotations

import io
import smtplib
from dataclasses import dataclass
from datetime import datetime
from email.message import EmailMessage
from email.utils import make_msgid

from PIL import ImageDraw

from .analyze import Sighting


@dataclass
class SmtpSettings:
    host: str
    port: int
    username: str
    password: str
    sender: str
    recipient: str


def annotated_jpeg(sighting: Sighting) -> bytes:
    """The sighting's frame as JPEG bytes, with the animal boxed."""
    image = sighting.frame.image.copy()
    w, h = image.size
    x, y, bw, bh = sighting.detection.box
    draw = ImageDraw.Draw(image)
    draw.rectangle(
        [x * w, y * h, (x + bw) * w, (y + bh) * h],
        outline=(255, 64, 0),
        width=max(2, w // 300),
    )
    buf = io.BytesIO()
    image.save(buf, format="JPEG", quality=85)
    return buf.getvalue()


def build_alert(
    sighting: Sighting,
    camera: str,
    seen_at: datetime,
    sender: str,
    recipient: str,
    species: str | None = None,
    clip_url: str | None = None,
) -> EmailMessage:
    name = species or "Animal"
    when = seen_at.strftime("%-I:%M %p")
    msg = EmailMessage()
    msg["Subject"] = f"{name} at {camera}, {when}"
    msg["From"] = sender
    msg["To"] = recipient

    confidence = f"{sighting.detection.confidence:.0%}"
    lines = [
        f"{name} seen on {camera} at {seen_at:%Y-%m-%d %H:%M}.",
        f"Detector confidence: {confidence}.",
    ]
    if clip_url:
        lines.append(f"Clip: {clip_url}")
    msg.set_content("\n".join(lines))

    cid = make_msgid(domain="animal-tracker")
    link = f'<p><a href="{clip_url}">Watch the clip</a></p>' if clip_url else ""
    msg.add_alternative(
        f"<p><b>{name}</b> seen on <b>{camera}</b> at {seen_at:%Y-%m-%d %H:%M}.</p>"
        f'<p><img src="cid:{cid[1:-1]}" style="max-width:100%"></p>'
        f"<p>Detector confidence: {confidence}.</p>{link}",
        subtype="html",
    )
    msg.get_payload()[1].add_related(
        annotated_jpeg(sighting), maintype="image", subtype="jpeg", cid=cid
    )
    return msg


def send(msg: EmailMessage, settings: SmtpSettings) -> None:
    with smtplib.SMTP(settings.host, settings.port, timeout=30) as smtp:
        smtp.starttls()
        smtp.login(settings.username, settings.password)
        smtp.send_message(msg)
