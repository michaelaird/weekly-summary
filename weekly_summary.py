"""
Weekly Weak Signal Summary
Runs every Friday at 6 AM Toronto time via GitHub Actions.
Uses Claude with native web search, sends results via Gmail API.
"""

import os
import base64
import json
from datetime import datetime
from pathlib import Path

import anthropic
import markdown2
import yagmail
from jinja2 import Environment, FileSystemLoader
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request


# ── Config ────────────────────────────────────────────────────────────────────

RECIPIENT_EMAIL  = os.environ["RECIPIENT_EMAIL"]      # your Gmail address
ANTHROPIC_API_KEY = os.environ["ANTHROPIC_API_KEY"]
GOOGLE_TOKEN_JSON = os.environ["GOOGLE_TOKEN_JSON"]   # base64-encoded token.json

SCOPES       = ["https://www.googleapis.com/auth/gmail.send"]
BASE_DIR     = Path(__file__).parent
PROMPTS_DIR  = BASE_DIR / "prompts"
TEMPLATES_DIR = BASE_DIR / "templates"


# ── Prompt loading ────────────────────────────────────────────────────────────

def load_prompt(filename: str) -> str:
    return (PROMPTS_DIR / filename).read_text(encoding="utf-8").strip()


# ── Claude API call ────────────────────────────────────────────────────────────

def generate_summary() -> str:
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=2000,
        system=load_prompt("system.txt"),
        tools=[{
            "type": "web_search_20250305",
            "name": "web_search",
            "max_uses": 8,
        }],
        messages=[{"role": "user", "content": load_prompt("user.txt")}],
    )

    text_parts = [block.text for block in response.content if block.type == "text"]
    return "\n\n".join(text_parts).strip()


# ── Email rendering ───────────────────────────────────────────────────────────

def build_email_html(body_md: str, run_date: str) -> str:
    body_html = markdown2.markdown(body_md, extras=["fenced-code-blocks", "tables"])

    env = Environment(loader=FileSystemLoader(str(TEMPLATES_DIR)), autoescape=True)
    template = env.get_template("email.html")
    return template.render(run_date=run_date, body_html=body_html)


# ── Gmail sending ─────────────────────────────────────────────────────────────

def get_credentials() -> Credentials:
    """Reconstitute credentials from base64-encoded token stored as a GitHub secret."""
    token_data = json.loads(base64.b64decode(GOOGLE_TOKEN_JSON).decode("utf-8"))
    creds = Credentials(
        token=token_data.get("token"),
        refresh_token=token_data.get("refresh_token"),
        token_uri=token_data.get("token_uri", "https://oauth2.googleapis.com/token"),
        client_id=token_data.get("client_id"),
        client_secret=token_data.get("client_secret"),
        scopes=token_data.get("scopes", SCOPES),
    )
    if creds.expired and creds.refresh_token:
        creds.refresh(Request())
    return creds


def send_email(subject: str, html_body: str):
    creds = get_credentials()
    yag = yagmail.SMTP(oauth2_file=None, oauth2_credentials=creds, user=RECIPIENT_EMAIL)
    yag.send(to=RECIPIENT_EMAIL, subject=subject, contents=html_body)
    print(f"✅ Email sent to {RECIPIENT_EMAIL}")


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    run_date = datetime.now().strftime("%B %d, %Y")
    week_num = datetime.now().isocalendar()[1]
    subject  = f"🔍 Weak Signal Scan — Week {week_num} · {run_date}"

    print("Generating summary with Claude + web search...")
    summary_md = generate_summary()

    print("Building email...")
    html = build_email_html(summary_md, run_date)

    print("Sending via Gmail API...")
    send_email(subject, html)


if __name__ == "__main__":
    main()
