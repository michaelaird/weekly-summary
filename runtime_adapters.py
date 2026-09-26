import json
import os
import smtplib
from dataclasses import dataclass
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

import anthropic


def _looks_like_placeholder(value: str | None) -> bool:
    if not value:
        return False
    lowered = value.strip().lower()
    return lowered.startswith("dummy-") or "dry-run" in lowered or "example.com" in lowered


def _read_credentials_file(path: Path | None = None) -> dict:
    base_path = path or Path(__file__).resolve().parent
    credentials_path = base_path / "credentials.json"
    if not credentials_path.exists():
        return {}
    try:
        return json.loads(credentials_path.read_text(encoding="utf-8")) or {}
    except json.JSONDecodeError:
        return {}


@dataclass(frozen=True)
class RuntimePolicy:
    mode: str = "live"

    @classmethod
    def from_environment(cls, *, env: dict | None = None) -> "RuntimePolicy":
        env_map = env or os.environ
        value = str(env_map.get("DRY_RUN", "0")).strip().lower()
        mode = "dry-run" if value in {"1", "true", "yes", "y", "on"} else "live"
        return cls(mode=mode)

    @property
    def is_live(self) -> bool:
        return self.mode == "live"

    @property
    def is_dry_run(self) -> bool:
        return not self.is_live

    def should_send_email(self) -> bool:
        return self.is_live

    def can_use_live_anthropic(self) -> bool:
        if not self.is_live:
            return False

        env_key = os.environ.get("ANTHROPIC_API_KEY")
        if env_key and env_key.strip() and not _looks_like_placeholder(env_key):
            return True

        creds = _read_credentials_file()
        api_key = creds.get("ANTHROPIC_API_KEY") or creds.get("anthropic_api_key")
        return bool(api_key and api_key.strip() and not _looks_like_placeholder(api_key))

    def get_anthropic_api_key(self) -> str:
        if not self.is_live:
            return "dummy-anthropic-key-for-dry-run"

        env_key = os.environ.get("ANTHROPIC_API_KEY")
        if env_key and env_key.strip() and not _looks_like_placeholder(env_key):
            return env_key.strip()

        creds = _read_credentials_file()
        api_key = creds.get("ANTHROPIC_API_KEY") or creds.get("anthropic_api_key")
        if api_key and api_key.strip() and not _looks_like_placeholder(api_key):
            return api_key.strip()

        return "dummy-anthropic-key-for-dry-run"


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


@dataclass
class AnthropicClientAdapter:
    live: bool = True
    api_key: str | None = None
    base_dir: Path | None = None
    policy: RuntimePolicy | None = None

    def _build_client(self):
        policy = self.policy or RuntimePolicy.from_environment()
        runtime_live = self.live if self.live is not None else policy.is_live
        if not runtime_live:
            return DryRunAnthropic()

        api_key = self.api_key or policy.get_anthropic_api_key()
        if api_key and not _looks_like_placeholder(api_key):
            return anthropic.Anthropic(api_key=api_key)
        return DryRunAnthropic()

    @property
    def messages(self):
        return self._build_client().messages


@dataclass
class EmailSenderAdapter:
    live: bool = True
    username: str | None = None
    password: str | None = None
    recipient: str | None = None
    policy: RuntimePolicy | None = None

    def send(self, subject: str, html_body: str):
        policy = self.policy or RuntimePolicy.from_environment()
        if not (self.live if self.live is not None else policy.should_send_email()):
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


def build_anthropic_client(base_dir: Path | None = None, *, live: bool | None = None, api_key: str | None = None, policy: RuntimePolicy | None = None):
    return AnthropicClientAdapter(live=True if live is None and policy is None else bool(live) if live is not None else policy.is_live if policy else True, api_key=api_key, base_dir=base_dir, policy=policy or RuntimePolicy.from_environment())


def create_email_sender(*, live: bool | None = None, username: str | None = None, password: str | None = None, recipient: str | None = None, policy: RuntimePolicy | None = None):
    resolved_policy = policy or RuntimePolicy.from_environment()
    resolved_live = True if live is None and policy is None else bool(live) if live is not None else resolved_policy.is_live
    return EmailSenderAdapter(live=resolved_live, username=username, password=password, recipient=recipient, policy=resolved_policy)
