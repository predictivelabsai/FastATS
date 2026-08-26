"""Outbound email boundary. Console backend is the zero-config default; it
records the message without sending, so sequences run end-to-end in dev/tests."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass
class SendResult:
    status: str          # "sent" | "logged" | "error"
    provider: str
    detail: str = ""


class Emailer(Protocol):
    provider: str

    def send(self, *, to: str, subject: str, body: str, from_email: str) -> SendResult: ...


class ConsoleEmailer:
    provider = "console"

    def send(self, *, to: str, subject: str, body: str, from_email: str) -> SendResult:
        print(f"[email:console] to={to} from={from_email} subject={subject!r}")
        return SendResult(status="logged", provider=self.provider)


class SMTPEmailer:
    provider = "smtp"

    def __init__(self, *, host: str, port: int, user: str, password: str):
        self.host, self.port, self.user, self.password = host, port, user, password

    def send(self, *, to: str, subject: str, body: str, from_email: str) -> SendResult:
        import smtplib
        from email.message import EmailMessage
        message = EmailMessage()
        message["From"], message["To"], message["Subject"] = from_email, to, subject
        message.set_content(body)
        try:
            with smtplib.SMTP(self.host, self.port, timeout=30) as server:
                server.starttls()
                if self.user:
                    server.login(self.user, self.password)
                server.send_message(message)
            return SendResult(status="sent", provider=self.provider)
        except Exception as exc:  # pragma: no cover - network path
            return SendResult(status="error", provider=self.provider, detail=str(exc))


class PostmarkEmailer:
    provider = "postmark"

    def __init__(self, *, token: str):
        self.token = token

    def send(self, *, to: str, subject: str, body: str, from_email: str) -> SendResult:
        import httpx
        try:
            response = httpx.post(
                "https://api.postmarkapp.com/email",
                headers={"X-Postmark-Server-Token": self.token,
                         "Accept": "application/json"},
                json={"From": from_email, "To": to, "Subject": subject, "TextBody": body},
                timeout=30)
            if response.status_code >= 400:
                return SendResult(status="error", provider=self.provider, detail=response.text)
            return SendResult(status="sent", provider=self.provider)
        except Exception as exc:  # pragma: no cover - network path
            return SendResult(status="error", provider=self.provider, detail=str(exc))


def get_emailer(settings=None) -> Emailer:
    if settings is None:
        from config import settings as _settings
        settings = _settings
    if settings.email_backend == "postmark" and settings.postmark_api_token:
        return PostmarkEmailer(token=settings.postmark_api_token)
    if settings.email_backend == "smtp" and settings.smtp_host:
        return SMTPEmailer(host=settings.smtp_host, port=settings.smtp_port,
                           user=settings.smtp_user, password=settings.smtp_password)
    return ConsoleEmailer()
