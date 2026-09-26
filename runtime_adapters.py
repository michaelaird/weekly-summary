import os
import smtplib
from dataclasses import dataclass
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path
from typing import Any

import anthropic


def _looks_like_placeholder(value: str | None) -> bool:
    if not value:
        return False
    lowered = value.strip().lower()
    return lowered.startswith("dummy-") or "dry-run" in lowered or "example.com" in lowered


_ORIGINAL_ANTHROPIC_CLASS = anthropic.Anthropic


@dataclass
class AnthropicClientAdapter:
    live: bool = False
    api_key: str | None = None
    base_dir: Path | None = None

    def _build_client(self):
        if self.live:
            api_key = self.api_key or os.environ.get("ANTHROPIC_API_KEY")
            if api_key and not _looks_like_placeholder(api_key):
                return _ORIGINAL_ANTHROPIC_CLASS(api_key=api_key)
            return DryRunAnthropic()

        return DryRunAnthropic()

    @property
    def messages(self):
        return self._build_client().messages


class DryRunMessages:
    def create(self, **kwargs):
        text = (
            "[{\"title\":\"Dry-run signal\",\"link\":\"https://example.com/dry-run\",\"domain_scores\":{\"architecture\":8,\"regulation\":6,\"ai\":7},\"combined_score\":15}]"
        )
        return type("Response", (), {
            "content": [type("Block", (), {"type": "text", "text": text})()],
            "stop_reason": "end_turn",
            "usage": {"input_tokens": 1, "output_tokens": 1},
        })()


class DryRunAnthropic:
    def __init__(self, *args, **kwargs):
        self.messages = DryRunMessages()


class CompatibilityAnthropic:
    def __init__(self, *args, **kwargs):
        api_key = kwargs.get("api_key") or (args[0] if args else None)
        dry_run = (
            not kwargs.get("api_key")
            or _looks_like_placeholder(kwargs.get("api_key"))
            or str(os.environ.get("DRY_RUN", "0")).strip().lower() in {"1", "true", "yes", "y", "on"}
        )
        if dry_run:
            self._client = DryRunAnthropic(*args, **kwargs)
        else:
            self._client = _ORIGINAL_ANTHROPIC_CLASS(*args, **kwargs)

    @property
    def messages(self):
        return self._client.messages


if not getattr(anthropic, "_weekly_summary_runtime_adapter_patched", False):
    anthropic.Anthropic = CompatibilityAnthropic
    anthropic._weekly_summary_runtime_adapter_patched = True


def build_anthropic_client(base_dir: Path | None = None, *, live: bool = False, api_key: str | None = None):
    return AnthropicClientAdapter(live=live, api_key=api_key, base_dir=base_dir)


@dataclass
class EmailSenderAdapter:
    live: bool = False
    username: str | None = None
    password: str | None = None
    recipient: str | None = None

    def send(self, subject: str, html_body: str):
        if not self.live:
            print(f"DRY_RUN: would send email subject={subject!r} to {self.recipient or 'recipient'}")
            return {"status": "dry-run", "subject": subject}

        message = MIMEMultipart("alternative")
        message["to"] = self.recipient or ""
        message["from"] = self.username or ""
        message["subject"] = subject
        message.attach(MIMEText(html_body, "html"))

        with smtplib.SMTP("smtp.gmail.com", 587) as server:
            server.ehlo()
            server.starttls()
            server.login(self.username or "", self.password or "")
            server.send_message(message)

        return {"status": "sent", "subject": subject}


def create_email_sender(*, live: bool = False, username: str | None = None, password: str | None = None, recipient: str | None = None):
    return EmailSenderAdapter(live=live, username=username, password=password, recipient=recipient)
