"""
Weekly Signal Aggregation from Newsletter RSS Feeds
Fetches RSS feeds from curated newsletters and asks Claude to find novel intersections.
"""

import os
import base64
import json
import re
from datetime import datetime, timedelta
from pathlib import Path
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import anthropic
import feedparser
import markdown2
from jinja2 import Environment, FileSystemLoader
from markupsafe import Markup
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from googleapiclient.discovery import build


# ── Config ────────────────────────────────────────────────────────────────────

TO_EMAIL         = os.environ["TO_EMAIL"]
CC_EMAIL         = os.environ["CC_EMAIL"]
ANTHROPIC_API_KEY = os.environ["ANTHROPIC_API_KEY"]
GOOGLE_TOKEN_JSON = os.environ["GOOGLE_TOKEN_JSON"]

BASE_DIR     = Path(__file__).parent
PROMPTS_DIR  = BASE_DIR / "prompts"
TEMPLATES_DIR = BASE_DIR / "templates"

SCOPES = ["https://www.googleapis.com/auth/gmail.send"]

# Newsletter RSS feeds
FEEDS = [
    {"name": "ByteByteGo", "url": "https://blog.bytebytego.com/feed", "category": "architecture"},
    {"name": "Platform Engineering Weekly", "url": "https://theplatformengineering.substack.com/feed", "category": "architecture"},
    {"name": "The New Stack", "url": "https://thenewstack.io/feed/", "category": "architecture"},
    {"name": "Techdirt", "url": "https://feeds.feedburner.com/techdirt", "category": "policy"},
    {"name": "FinTech Futures", "url": "https://www.finextra.com/rss/headlines.aspx", "category": "fintech"},
    {"name": "Fintech Takes", "url": "https://fintechtakes.com/feed", "category": "fintech"},
    {"name": "The Neuron", "url": "https://www.theneuron.ai/feed", "category": "ai"},
    {"name": "Fintech Finance News", "url": "https://ffnews.com/feed", "category": "fintech"},
    {"name": "Shopify Engineering", "url": "https://shopify.engineering/blog.atom", "category": "architecture"},
]


# ── Prompt loading ────────────────────────────────────────────────────────────

def load_prompt(filename: str) -> str:
    return (PROMPTS_DIR / filename).read_text(encoding="utf-8").strip()


# ── Feed aggregation ──────────────────────────────────────────────────────────

def fetch_feeds(days_back: int = 7) -> str:
    """
    Fetch all RSS feeds and aggregate headlines from the past N days.
    Returns formatted text for Claude to analyze.
    """
    cutoff_date = datetime.now() - timedelta(days=days_back)
    aggregated = []
    
    for feed_config in FEEDS:
        try:
            print(f"  Fetching {feed_config['name']}...")
            feed = feedparser.parse(feed_config["url"])
            
            if not feed.entries:
                print(f"    → No entries found")
                continue
            
            feed_items = []
            for entry in feed.entries[:5]:  # Get last 5 items per feed
                # Try to parse publish date
                try:
                    pub_date = datetime(*entry.published_parsed[:6]) if hasattr(entry, 'published_parsed') else datetime.now()
                except:
                    pub_date = datetime.now()
                
                if pub_date > cutoff_date:
                    title = entry.get('title', 'No title')
                    link = entry.get('link', '#')
                    summary = entry.get('summary', '')[:200]  # First 200 chars of summary
                    feed_items.append(f"  - {title}\n    Link: {link}\n    Summary: {summary}")
            
            if feed_items:
                aggregated.append(f"\n## {feed_config['name']} ({feed_config['category'].upper()})\n")
                aggregated.extend(feed_items)
            
        except Exception as e:
            print(f"  ✗ Error fetching {feed_config['name']}: {e}")
    
    return "\n".join(aggregated)


# ── Claude signal generation ──────────────────────────────────────────────────

def generate_summary(feed_content: str) -> str:
    """
    Send aggregated feed content to Claude and ask for novel intersections.
    """
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    
    # Load signal history
    history = load_signal_history()
    
    # Updated prompt for feed-based analysis
    system_prompt = load_prompt("system.txt")
    
    user_message = f"""I've aggregated the latest headlines and summaries from 9 curated newsletters across architecture, fintech, AI, and policy.

Your task: Find 3–5 NON-OBVIOUS INTERSECTIONS or emerging patterns that span multiple newsletters.
Don't just summarize what each newsletter says. Instead, look for:
- Connections between signals that no single newsletter explicitly makes
- Patterns that only become visible when reading across all sources
- Weak signals: things that are mentioned once or twice but have major implications
- Contradictions or tensions between different sources (very valuable)

Here's what you should actively AVOID:
- Repeating headlines from the feeds verbatim
- Obvious industry trends that are already widely discussed
- Topics from previous weeks (see history below)

Previous weeks' signals to avoid:
{history}

---

## Latest Newsletter Headlines & Summaries

{feed_content}

---

Generate 3–5 signals in this format:

## 🔴 Signal [N]: [Title - 6–10 words, punchy]

**🎯 What's happening:** [2–3 sentences. Cite specific newsletters or trends from above.]

**⚠️ Why it's weak:** [1–2 sentences on why this isn't mainstream yet, even though it should be.]

**💡 So what:** [2–3 sentences of implications for architects and banks in Canada.]

---

End with "🧠 Architect's Lens" synthesizing a meta-pattern.
"""
    
    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=2500,
        system=system_prompt,
        messages=[{"role": "user", "content": user_message}],
    )
    
    text_parts = [block.text for block in response.content if block.type == "text"]
    return "\n\n".join(text_parts).strip()


def load_signal_history() -> str:
    """Load previous signal history to avoid repetition."""
    history_file = BASE_DIR / "SIGNAL_HISTORY.md"
    if history_file.exists():
        return history_file.read_text(encoding="utf-8").strip()
    return "(No history yet — first week of scanning.)"


def extract_signal_titles(summary_md: str) -> list[str]:
    """Extract signal titles from the markdown summary."""
    pattern = r'^##\s*[^:]*Signal\s+\d+:\s*(.+)$'
    matches = re.findall(pattern, summary_md, re.MULTILINE)
    return [title.strip() for title in matches]


def update_signal_history(run_date: str, signal_titles: list[str]) -> None:
    """Append this week's signals to SIGNAL_HISTORY.md."""
    history_file = BASE_DIR / "SIGNAL_HISTORY.md"
    
    new_entry = f"\n## Week of {run_date}\n"
    for i, title in enumerate(signal_titles, 1):
        new_entry += f"- Signal {i}: {title}\n"
    
    if history_file.exists():
        existing = history_file.read_text(encoding="utf-8")
    else:
        existing = "# Weak Signal History\n"
    
    updated = existing.rstrip() + new_entry
    history_file.write_text(updated, encoding="utf-8")
    print(f"✅ Updated SIGNAL_HISTORY.md with {len(signal_titles)} new signals")


# ── Email rendering ───────────────────────────────────────────────────────────

def build_email_html(body_md: str, run_date: str) -> str:
    body_html = markdown2.markdown(
        body_md, 
        extras=["fenced-code-blocks", "tables", "strike"]
    )
    
    body_html = re.sub(r'>\s+<', '><', body_html)
    body_html = re.sub(r'\n\n+', '\n', body_html)

    env = Environment(loader=FileSystemLoader(str(TEMPLATES_DIR)), autoescape=True)
    template = env.get_template("email.html")
    return template.render(run_date=run_date, body_html=Markup(body_html))


# ── Gmail sending ─────────────────────────────────────────────────────────────

def get_credentials() -> Credentials:
    """Reconstitute credentials from base64-encoded token."""
    token_data = json.loads(base64.b64decode(GOOGLE_TOKEN_JSON).decode("utf-8"))
    creds = Credentials(
        token=token_data.get("token"),
        refresh_token=token_data.get("refresh_token"),
        token_uri=token_data.get("token_uri", "https://oauth2.googleapis.com/token"),
        client_id=token_data.get("client_id"),
        client_secret=token_data.get("client_secret"),
        scopes=token_data.get("scopes", SCOPES),
    )
    if creds.refresh_token:
        try:
            creds.refresh(Request())
        except Exception as e:
            print(f"⚠️  Token refresh failed: {e}")
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
    subject  = f"🔍 Weekly Signal Scan — Week {week_num} · {run_date}"

    print("Fetching newsletter RSS feeds...")
    feed_content = fetch_feeds(days_back=7)
    
    if not feed_content.strip():
        print("✗ No feed content fetched. Aborting.")
        return

    print("\nAnalyzing feeds with Claude...")
    summary_md = generate_summary(feed_content)

    print("Building email...")
    html = build_email_html(summary_md, run_date)

    print("Sending via Gmail API...")
    send_email(subject, html)
    
    print("Updating signal history...")
    signal_titles = extract_signal_titles(summary_md)
    if signal_titles:
        update_signal_history(run_date, signal_titles)
    else:
        print("⚠️  Could not extract signal titles")


if __name__ == "__main__":
    main()
