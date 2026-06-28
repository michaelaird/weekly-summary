"""
Weekly Weak Signal Summary
Runs every Friday at 6 AM Toronto time via GitHub Actions.
Uses Claude with native web search, sends results via Gmail API.
"""

import os
import base64
import json
import re
from datetime import datetime
from pathlib import Path
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import anthropic
import markdown2
from jinja2 import Environment, FileSystemLoader
from markupsafe import Markup
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from googleapiclient.discovery import build


# ── Config ────────────────────────────────────────────────────────────────────

TO_EMAIL         = os.environ["TO_EMAIL"]             # primary recipient
CC_EMAIL         = os.environ["CC_EMAIL"]             # CC recipient (for testing)
ANTHROPIC_API_KEY = os.environ["ANTHROPIC_API_KEY"]
GOOGLE_TOKEN_JSON = os.environ["GOOGLE_TOKEN_JSON"]   # base64-encoded token.json

SCOPES       = ["https://www.googleapis.com/auth/gmail.send"]
BASE_DIR     = Path(__file__).parent
PROMPTS_DIR  = BASE_DIR / "prompts"
TEMPLATES_DIR = BASE_DIR / "templates"


# ── Prompt loading ────────────────────────────────────────────────────────────

def load_prompt(filename: str) -> str:
    return (PROMPTS_DIR / filename).read_text(encoding="utf-8").strip()


def load_signal_history() -> str:
    """Load previous signal history to avoid repetition."""
    history_file = BASE_DIR / "SIGNAL_HISTORY.md"
    if history_file.exists():
        return history_file.read_text(encoding="utf-8").strip()
    return "(No history yet — first week of scanning.)"


def extract_signal_titles(summary_md: str) -> list[str]:
    """Extract signal titles from the markdown summary."""
    import re
    # Match patterns like "## 🔴 Signal 1: Title here" or "## Signal 1: Title here"
    pattern = r'^##\s*[^:]*Signal\s+\d+:\s*(.+)$'
    matches = re.findall(pattern, summary_md, re.MULTILINE)
    return [title.strip() for title in matches]


def update_signal_history(run_date: str, signal_titles: list[str]) -> None:
    """Append this week's signals to SIGNAL_HISTORY.md."""
    history_file = BASE_DIR / "SIGNAL_HISTORY.md"
    
    # Format the new entry
    new_entry = f"\n## Week of {run_date}\n"
    for i, title in enumerate(signal_titles, 1):
        new_entry += f"- Signal {i}: {title}\n"
    
    # Read existing history
    if history_file.exists():
        existing = history_file.read_text(encoding="utf-8")
    else:
        existing = "# Weak Signal History\n# Keep the past 4–8 weeks of signals here to help Claude avoid repetition.\n"
    
    # Append new entry
    updated = existing.rstrip() + new_entry
    
    # Write back
    history_file.write_text(updated, encoding="utf-8")
    print(f"✅ Updated SIGNAL_HISTORY.md with {len(signal_titles)} new signals")


# ── Claude API call ────────────────────────────────────────────────────────────

def generate_summary() -> str:
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    
    # Load previous signals to avoid repetition
    history = load_signal_history()

    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=2000,
        system=load_prompt("system.txt"),
        tools=[{
            "type": "web_search_20250305",
            "name": "web_search",
            "max_uses": 8,
        }],
        messages=[{"role": "user", "content": load_prompt("user.txt").format(previous_signals=history)}],
    )

    text_parts = [block.text for block in response.content if block.type == "text"]
    return "\n\n".join(text_parts).strip()


# ── Email rendering ───────────────────────────────────────────────────────────

def build_email_html(body_md: str, run_date: str) -> str:
    body_html = markdown2.markdown(
        body_md, 
        extras=["fenced-code-blocks", "tables", "strike"]
    )
    
    # Clean up excessive whitespace/newlines that markdown2 sometimes adds
    body_html = re.sub(r'>\s+<', '><', body_html)  # Remove whitespace between tags
    body_html = re.sub(r'\n\n+', '\n', body_html)   # Collapse multiple newlines

    env = Environment(loader=FileSystemLoader(str(TEMPLATES_DIR)), autoescape=True)
    template = env.get_template("email.html")
    return template.render(run_date=run_date, body_html=Markup(body_html))


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
    # Always refresh if we have a refresh_token (safer than checking expiry)
    if creds.refresh_token:
        try:
            creds.refresh(Request())
        except Exception as e:
            print(f"⚠️  Token refresh failed: {e}")
            print("Token may be expired or revoked. Re-run setup_gmail_token.py locally.")
            raise
    return creds


def send_email(subject: str, html_body: str):
    creds = get_credentials()
    service = build("gmail", "v1", credentials=creds)
    
    message = MIMEMultipart("alternative")
    message["to"] = TO_EMAIL
    message["from"] = TO_EMAIL
    message["cc"] = CC_EMAIL
    message["subject"] = subject
    message.attach(MIMEText(html_body, "html"))
    
    raw = base64.urlsafe_b64encode(message.as_bytes()).decode()
    service.users().messages().send(userId="me", body={"raw": raw}).execute()
    print(f"✅ Email sent to {TO_EMAIL}, CC'd to {CC_EMAIL}")


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
    
    # Extract and save signal titles to history for next week
    print("Updating signal history...")
    signal_titles = extract_signal_titles(summary_md)
    if signal_titles:
        update_signal_history(run_date, signal_titles)
    else:
        print("⚠️  Could not extract signal titles from summary")


if __name__ == "__main__":
    main()
