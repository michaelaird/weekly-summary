"""
Weekly Signal Aggregation from Newsletter RSS Feeds
Fetches RSS feeds from curated newsletters and asks Claude to find novel intersections.
"""

import json
import os
import re
import smtplib
from datetime import datetime, timedelta, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

import feedparser
import concurrent.futures
import markdown2
import requests
from bs4 import BeautifulSoup
from jinja2 import Environment, FileSystemLoader
from markupsafe import Markup

from runtime_adapters import RuntimePolicy, build_anthropic_client, create_email_sender


# ── Config ────────────────────────────────────────────────────────────────────

BASE_DIR = Path(__file__).parent
PROMPTS_DIR = BASE_DIR / "prompts"
TEMPLATES_DIR = BASE_DIR / "templates"
CONFIG_DIR = BASE_DIR / "config"
DOMAIN_CONFIG_PATH = CONFIG_DIR / "domains.json"

DEFAULT_DOMAIN_CONFIG = {
    "domains": [
        {"name": "architecture", "weight": 3, "description": "architecture, platform engineering, DDD, microservices, system design"},
        {"name": "regulation", "weight": 3, "description": "OSFI, open banking, PCI-DSS, privacy, FINTRAC, regulations"},
        {"name": "ai", "weight": 3, "description": "AI, developer productivity, agentic coding, governance, model risk"},
    ],
    "selection": {
        "per_domain_top": 3,
        "max_combined_articles": 8,
        "combined_threshold": 6,
    },
    "models": {
        "relevance_model": "claude-haiku-4-5",
        "deep_analysis_model": "claude-sonnet-5",
        "relevance_max_tokens": 10000,
        "deep_max_tokens": 10000,
    },
}

MODEL_USAGE_STATS: list[dict] = []
LAST_SELECTED_ARTICLES: list[dict] = []


def resolve_model_name(model_name: str | None) -> str:
    if not model_name:
        return "claude-haiku-4-5"
    return model_name.strip()


def record_model_usage(stage: str, model_name: str, usage: dict | None, *, max_tokens: int | None = None) -> dict:
    """Store a model usage snapshot for display in the generated email footer."""
    usage_map = usage or {}
    input_tokens = int(usage_map.get("input_tokens") or 0)
    output_tokens = int(usage_map.get("output_tokens") or 0)
    total_tokens = input_tokens + output_tokens
    stats = {
        "stage": stage,
        "model": model_name,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "total_tokens": total_tokens,
        "max_tokens": int(max_tokens) if max_tokens is not None else None,
    }
    MODEL_USAGE_STATS.append(stats)
    return stats


def get_model_usage_stats() -> list[dict]:
    return [dict(item) for item in MODEL_USAGE_STATS]


def extract_json_array_from_text(text: str) -> list[dict]:
    if not text or not text.strip():
        raise ValueError("Model returned empty content for article relevance scoring.")

    def find_matching_array_from_index(raw: str, start: int) -> tuple[int, int] | None:
        depth = 0
        in_string = False
        escape = False
        for idx in range(start, len(raw)):
            char = raw[idx]
            if in_string:
                if escape:
                    escape = False
                elif char == "\\":
                    escape = True
                elif char == '"':
                    in_string = False
                continue

            if char == '"':
                in_string = True
            elif char == "[":
                depth += 1
            elif char == "]":
                depth -= 1
                if depth == 0:
                    return start, idx
        return None

    def candidate_arrays(raw: str) -> list[str]:
        items: list[str] = []
        for idx, char in enumerate(raw):
            if char != "[":
                continue
            match = find_matching_array_from_index(raw, idx)
            if match is None:
                continue
            start, end = match
            items.append(raw[start : end + 1])
        return items

    candidates: list[str] = []
    fenced = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", text, flags=re.IGNORECASE)
    if fenced:
        fenced_text = fenced.group(1).strip()
        if fenced_text:
            candidates.append(fenced_text)

    candidates.extend(candidate_arrays(text))

    for candidate in candidates:
        try:
            parsed = json.loads(candidate)
            if isinstance(parsed, list):
                return parsed
        except json.JSONDecodeError:
            continue

    raise ValueError("Model did not return JSON for article relevance scoring.")


def require_env(name: str) -> str:
    value = os.environ.get(name)
    if value is None or not value.strip():
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value.strip()


def get_to_email() -> str:
    for name in ("TO_EMAIL", "RECIPIENT_EMAIL"):
        value = os.environ.get(name)
        if value and value.strip():
            return value.strip()
    raise RuntimeError("Missing recipient email. Set TO_EMAIL or RECIPIENT_EMAIL.")


def get_cc_email() -> str:
    value = os.environ.get("CC_EMAIL")
    return value.strip() if value else ""


def should_send_email() -> bool:
    return RuntimePolicy.from_environment().should_send_email()


def get_credentials_file_path() -> Path:
    return BASE_DIR / "credentials.json"


def read_credentials_file() -> dict:
    path = get_credentials_file_path()
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8")) or {}
    except json.JSONDecodeError:
        return {}


def can_use_live_anthropic() -> bool:
    return RuntimePolicy.from_environment().can_use_live_anthropic()


def get_anthropic_api_key() -> str:
    return RuntimePolicy.from_environment().get_anthropic_api_key()


def get_anthropic_runtime_client(*, live: bool | None = None):
    policy = RuntimePolicy.from_environment()
    runtime_live = policy.is_live if live is None else bool(live)
    if runtime_live and not policy.can_use_live_anthropic():
        runtime_live = False
    return build_anthropic_client(BASE_DIR, live=runtime_live, api_key=policy.get_anthropic_api_key(), policy=policy)


def write_debug_response_to_file(label: str, payload: str, *, stop_reason: str | None = None, usage: dict | None = None) -> Path:
    """Temporary helper for inspecting full Anthropic API responses during debugging."""
    debug_dir = BASE_DIR / "debug"
    debug_dir.mkdir(exist_ok=True)
    safe_label = re.sub(r"[^a-zA-Z0-9_.-]+", "_", label).strip("_") or "response"
    path = debug_dir / f"{safe_label}_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}.txt"

    metadata = {
        "stop_reason": stop_reason,
        "usage": usage,
        "payload": payload,
    }
    path.write_text(json.dumps(metadata, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"📝 Wrote debug response to {path}")
    return path


def get_gmail_username() -> str:
    return os.environ.get("GMAIL_USERNAME") or get_to_email()


def get_gmail_app_password() -> str:
    if should_send_email():
        return require_env("GMAIL_APP_PASSWORD")

    creds = read_credentials_file()
    app_password = creds.get("GMAIL_APP_PASSWORD") or creds.get("gmail_app_password")
    if app_password and app_password.strip():
        return app_password.strip()

    return "dummy-gmail-app-password-for-dry-run"


def load_domain_config() -> dict:
    if not DOMAIN_CONFIG_PATH.exists():
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        DOMAIN_CONFIG_PATH.write_text(json.dumps(DEFAULT_DOMAIN_CONFIG, indent=2), encoding="utf-8")
    return json.loads(DOMAIN_CONFIG_PATH.read_text(encoding="utf-8"))


def load_domain_names() -> list[str]:
    config = load_domain_config()
    return [domain["name"] for domain in config.get("domains", [])]


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
    {"name": "TechCrunch Fintech", "url": "https://techcrunch.com/tag/fintech/feed/", "category": "fintech"},
    {"name": "Bank of Canada News", "url": "https://www.bankofcanada.ca/utility/news/feed/", "category": "policy"},
    {"name": "Shopify Engineering", "url": "https://shopify.engineering/blog.atom", "category": "architecture"},
]


# ── Prompt loading ────────────────────────────────────────────────────────────

def load_prompt(filename: str) -> str:
    return (PROMPTS_DIR / filename).read_text(encoding="utf-8").strip()


def render_prompt_template(filename: str, *, config: dict | None = None, previous_signals: str = "") -> str:
    """Render a prompt template with runtime-injected config values."""
    config = config or load_domain_config()
    domain_defs = config.get("domains", [])
    domain_lines = []
    for index, domain in enumerate(domain_defs, start=1):
        domain_name = domain.get("name", f"domain_{index}")
        description = domain.get("description", "")
        if description:
            domain_lines.append(f"{index}. {domain_name}: {description}")
        else:
            domain_lines.append(f"{index}. {domain_name}")

    template = load_prompt(filename)
    rendered = template.replace("{{ domain_list }}", "\n".join(domain_lines))
    rendered = rendered.replace("{{ previous_signals }}", previous_signals)
    return rendered.strip()


# ── Feed aggregation ──────────────────────────────────────────────────────────

def _parse_entry_published(entry) -> datetime:
    try:
        if hasattr(entry, "published_parsed") and entry.published_parsed:
            return datetime(*entry.published_parsed[:6])
        if hasattr(entry, "updated_parsed") and entry.updated_parsed:
            return datetime(*entry.updated_parsed[:6])
        # fallback: try parsing a textual published field
        published_text = entry.get("published") or entry.get("updated")
        if published_text:
            try:
                return datetime.fromisoformat(published_text)
            except Exception:
                pass
    except Exception:
        pass
    return datetime.now()


def _normalize_entry(entry, feed_config: dict, cutoff_date: datetime) -> dict | None:
    pub_date = _parse_entry_published(entry)
    if pub_date <= cutoff_date:
        return None

    title = entry.get("title", "No title")
    link = entry.get("link") or entry.get("id") or "#"
    summary = (entry.get("summary") or entry.get("description") or "")
    try:
        summary = BeautifulSoup(summary, "html.parser").get_text(" ", strip=True)
    except Exception:
        summary = re.sub(r"\s+", " ", str(summary))
    summary = re.sub(r"\s+", " ", summary)[:200].strip()

    return {
        "title": title,
        "link": link,
        "summary": summary,
        "feed_name": feed_config["name"],
        "category": feed_config.get("category"),
        "published": pub_date,
    }


def _fetch_and_normalize_feed(feed_config: dict, cutoff_date: datetime, *, max_entries: int = 5, timeout: int = 10, max_retries: int = 2) -> list[dict]:
    headers = {"User-Agent": "WeeklySummaryBot/1.0 (+https://example.com)"}
    last_exc: Exception | None = None
    for attempt in range(1, max_retries + 1):
        try:
            print(f"  Fetching {feed_config['name']} (attempt {attempt})...")
            resp = requests.get(feed_config["url"], timeout=timeout, headers=headers, allow_redirects=True)
            resp.raise_for_status()
            feed = feedparser.parse(resp.content)
            break
        except Exception as exc:
            last_exc = exc
            if attempt < max_retries:
                continue
            print(f"  ✗ Error fetching {feed_config['name']}: {exc}")
            return []

    if not getattr(feed, "entries", None):
        print(f"    → No entries found for {feed_config['name']}")
        return []

    articles: list[dict] = []
    for entry in feed.entries[:max_entries]:
        try:
            record = _normalize_entry(entry, feed_config, cutoff_date)
            if record:
                articles.append(record)
        except Exception as exc:
            print(f"    ✗ Skipping malformed entry from {feed_config['name']}: {exc}")
            continue

    return articles


def fetch_feed_articles(days_back: int = 7) -> list[dict]:
    """Return recent feed entries with title, link, summary, and source metadata.

    This implementation fetches feeds in parallel using a bounded thread pool,
    normalizes entries, and applies per-feed timeout/retry guards.
    """
    cutoff_date = datetime.now() - timedelta(days=days_back)
    articles: list[dict] = []

    max_workers = min(6, max(2, len(FEEDS)))
    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as ex:
        futures = {ex.submit(_fetch_and_normalize_feed, fc, cutoff_date): fc for fc in FEEDS}
        for fut in concurrent.futures.as_completed(futures):
            try:
                result = fut.result()
                if result:
                    articles.extend(result)
            except Exception as exc:
                cfg = futures.get(fut) or {}
                print(f"  ✗ Unexpected error processing {cfg.get('name', '<unknown>')}: {exc}")

    return articles


def fetch_feeds(days_back: int = 7) -> str:
    """Compatibility wrapper for the legacy feed-summary text output."""
    articles = fetch_feed_articles(days_back=days_back)
    aggregated = []

    for article in articles:
        aggregated.append(
            f"  - {article['title']}\n"
            f"    Source: {article['feed_name']} ({article['category'].upper()})\n"
            f"    Link: {article['link']}\n"
            f"    Summary: {article['summary']}"
        )

    if not aggregated:
        return ""

    return "\n".join(aggregated)


def score_articles_by_heuristic(articles: list[dict], config: dict | None = None) -> list[dict]:
    """Deterministic fallback scoring used when no live model is available."""
    config = config or load_domain_config()
    domain_defs = config.get("domains", [])
    domain_names = [domain["name"] for domain in domain_defs]
    weights = {domain["name"]: int(domain.get("weight", 1)) for domain in domain_defs}

    keyword_map = {
        "architecture": ["architecture", "platform", "microservice", "ddd", "system design", "engineering", "api", "cloud", "distributed", "developer", "data architecture"],
        "regulation": ["regulation", "osfi", "open banking", "pci", "privacy", "fintrac", "banking", "bank", "compliance", "risk", "policy", "governance"],
        "ai": ["ai", "artificial intelligence", "machine learning", "model", "llm", "agentic", "governance", "automation", "developer productivity", "genai", "copilot", "llms"],
    }

    for article in articles:
        combined = 0
        scores = {domain: 0 for domain in domain_names}
        text = f"{article.get('title', '')} {article.get('summary', '')} {article.get('feed_name', '')}".lower()

        for domain in domain_names:
            hits = sum(1 for keyword in keyword_map.get(domain, []) if keyword.lower() in text)
            score = min(10, hits * 2)
            if domain == "architecture" and "engineering" in text:
                score = max(score, 5)
            if domain == "regulation" and any(term in text for term in ["bank", "policy", "compliance"]):
                score = max(score, 6)
            if domain == "ai" and any(term in text for term in ["ai", "model", "agentic", "llm"]):
                score = max(score, 6)
            scores[domain] = score
            combined += score * weights.get(domain, 1)

        article["domain_scores"] = scores
        article["combined_score"] = combined

    return articles


class ArticleAnalyzer:
    """Encapsulates runtime policy for model-backed article analysis and heuristic fallback."""

    def __init__(self, config: dict | None = None, *, use_live_model: bool | None = None):
        self.config = config or load_domain_config()
        self.runtime_policy = RuntimePolicy.from_environment()
        self.use_live_model = self.runtime_policy.should_send_email() if use_live_model is None else bool(use_live_model)
        self.live_model_available = self.use_live_model and self.runtime_policy.can_use_live_anthropic()

    def should_use_live_model(self) -> bool:
        return bool(self.live_model_available)

    def score_articles(self, articles: list[dict]) -> list[dict]:
        if not articles:
            return []

        domain_defs = self.config.get("domains", [])
        domain_names = [domain["name"] for domain in domain_defs]
        weights = {domain["name"]: int(domain.get("weight", 1)) for domain in domain_defs}
        model_name = resolve_model_name(self.config.get("models", {}).get("relevance_model", "claude-haiku-4-5"))
        max_tokens = int(self.config.get("models", {}).get("relevance_max_tokens", 10000))

        if not self.should_use_live_model():
            return score_articles_by_heuristic(articles, config=self.config)

        def score_all() -> list[dict]:
            prompt = [
                "You are scoring article relevance for a weekly architecture and banking AI newsletter.",
                "Assign a score from 0 to 10 for each configured domain and a combined score based on weighted importance.",
                "Return valid JSON only with this shape:",
                "[{\"title\": \"...\", \"link\": \"...\", \"domain_scores\": {\"architecture\": 0, \"regulation\": 0, \"ai\": 0}, \"combined_score\": 0}]",
                "",
                "Configured domains:",
                json.dumps(domain_names, indent=2),
                "",
                "Articles:",
            ]

            for article in articles:
                prompt.append(
                    json.dumps({
                        "title": article["title"],
                        "link": article["link"],
                        "summary": article["summary"] or article.get("feed_name", ""),
                    }, ensure_ascii=False)
                )

            client = get_anthropic_runtime_client(live=self.live_model_available)
            response = client.messages.create(
                model=model_name,
                max_tokens=max_tokens,
                system="Score each article for relevance to the configured domains. Be strict and only award high scores when the article meaningfully intersects the domain.",
                messages=[{"role": "user", "content": "\n".join(prompt)}],
            )

            text = "\n".join(block.text for block in response.content if getattr(block, "type", None) == "text")
            usage = getattr(response, "usage", None)
            if usage is not None:
                usage = {
                    "input_tokens": getattr(usage, "input_tokens", None),
                    "output_tokens": getattr(usage, "output_tokens", None),
                    "cache_creation_input_tokens": getattr(usage, "cache_creation_input_tokens", None),
                    "cache_read_input_tokens": getattr(usage, "cache_read_input_tokens", None),
                }

            record_model_usage("relevance_score", model_name, usage, max_tokens=max_tokens)
            write_debug_response_to_file(
                "anthropic_relevance_single_pass",
                text,
                stop_reason=getattr(response, "stop_reason", None),
                usage=usage,
            )
            return extract_json_array_from_text(text)

        for article in articles:
            article["domain_scores"] = {domain: 0 for domain in domain_names}
            article["combined_score"] = 0

        try:
            scored_results = score_all()
        except Exception:
            return score_articles_by_heuristic(articles, config=self.config)

        for result in scored_results:
            link = result.get("link")
            article = next((item for item in articles if item.get("link") == link), None)
            if article is None:
                continue

            domain_scores = {}
            for domain in domain_names:
                score = result.get("domain_scores", {}).get(domain, 0)
                domain_scores[domain] = max(0, min(10, int(score)))

            article["domain_scores"] = domain_scores
            article["combined_score"] = sum(domain_scores.get(domain, 0) * weights.get(domain, 1) for domain in domain_names)

        return articles

    def generate_deep_analysis(self, articles: list[dict]) -> str:
        if not articles:
            return "No deeply relevant articles selected for analysis."

        if not self.should_use_live_model():
            return generate_relevance_summary(articles, self.config)

        model_name = resolve_model_name(self.config.get("models", {}).get("deep_analysis_model", "claude-sonnet-5"))
        max_tokens = int(self.config.get("models", {}).get("deep_max_tokens", 10000))

        article_sections = []
        for index, article in enumerate(articles, 1):
            fallback_text = article.get("summary") or article.get("title") or ""
            content = article.get("full_text") or fetch_article_content(article["link"], fallback_text)
            article_sections.append(
                f"## Article {index}: {article['title']}\n"
                f"URL: {article['link']}\n"
                f"Scores: {article.get('domain_scores', {})}\n\n"
                f"{content[:8000]}"
            )

        system_prompt = render_prompt_template("system.txt", config=self.config)
        user_prompt = render_prompt_template("user.txt", config=self.config, previous_signals=load_signal_history())

        relevance_summary = generate_relevance_summary(articles, self.config)
        user_message = f"""
{relevance_summary}

{user_prompt}

Previous weeks' signals to avoid:
{load_signal_history()}

---

## Selected articles for deep analysis

{chr(10).join(article_sections)}
"""

        client = get_anthropic_runtime_client(live=self.live_model_available)
        response = client.messages.create(
            model=model_name,
            max_tokens=max_tokens,
            system=system_prompt,
            messages=[{"role": "user", "content": user_message}],
        )

        usage = getattr(response, "usage", None)
        if usage is not None:
            usage = {
                "input_tokens": getattr(usage, "input_tokens", None),
                "output_tokens": getattr(usage, "output_tokens", None),
                "cache_creation_input_tokens": getattr(usage, "cache_creation_input_tokens", None),
                "cache_read_input_tokens": getattr(usage, "cache_read_input_tokens", None),
            }
        record_model_usage("deep_analysis", model_name, usage, max_tokens=max_tokens)

        text_parts = [block.text for block in response.content if getattr(block, "type", None) == "text"]
        return "\n\n".join(text_parts).strip()

    def run_stage_pipeline(self, raw_articles: list[dict] | None = None, *, days_back: int | None = None) -> dict:
        """Run the weekly pipeline as explicit stages with clear data flow between them."""
        global LAST_SELECTED_ARTICLES
        stage_order = ["fetch", "score", "select", "enrich", "analyze", "email", "history"]

        pipeline = {
            "stage_order": stage_order,
            "raw_articles": list(raw_articles or []),
            "scored_articles": [],
            "selected_articles": [],
            "enriched_articles": [],
            "summary_md": "",
            "email_html": "",
            "signal_titles": [],
            "run_date": datetime.now().strftime("%B %d, %Y"),
        }

        if raw_articles is None:
            print("Stage 1/7: Feed fetch")
            raw_articles = fetch_feed_articles(days_back=days_back or 7)

        if not raw_articles:
            print("✗ No feed content fetched. Aborting.")
            LAST_SELECTED_ARTICLES = []
            return pipeline

        print("\nStage 2/7: Relevance scoring")
        scored_articles = self.score_articles(list(raw_articles))
        pipeline["scored_articles"] = scored_articles

        print("Stage 3/7: Candidate selection")
        selected = select_relevant_articles(
            scored_articles,
            threshold=int(self.config.get("selection", {}).get("combined_threshold", 6)),
            per_domain_top=int(self.config.get("selection", {}).get("per_domain_top", 3)),
            max_combined=int(self.config.get("selection", {}).get("max_combined_articles", 8)),
        )
        pipeline["selected_articles"] = selected
        LAST_SELECTED_ARTICLES = selected

        if not selected:
            print("✗ No articles crossed the relevance threshold.")
            return pipeline

        print("Stage 4/7: Article enrichment")
        enriched_articles = enrich_selected_articles(selected)
        pipeline["enriched_articles"] = enriched_articles

        print("Stage 5/7: Deep analysis")
        pipeline["summary_md"] = self.generate_deep_analysis(enriched_articles)

        if not pipeline["summary_md"]:
            return pipeline

        print("Stage 6/7: Email assembly")
        pipeline["email_html"] = build_email_html(
            pipeline["summary_md"],
            pipeline["run_date"],
            model_usage=get_model_usage_stats(),
            selected_articles=LAST_SELECTED_ARTICLES,
        )

        if should_send_email():
            try:
                print("Sending via Gmail SMTP...")
                subject = f"🔍 Weekly Signal Scan — Week {datetime.now().isocalendar()[1]} · {pipeline['run_date']}"
                send_email(subject, pipeline["email_html"])
            except Exception as exc:
                print(f"⚠️ Email send skipped because SMTP configuration is unavailable or invalid: {exc}")
        else:
            print("DRY_RUN=1: skipping email send")

        print("Stage 7/7: Signal-history update")
        signal_titles = extract_signal_titles(pipeline["summary_md"])
        pipeline["signal_titles"] = signal_titles
        if signal_titles:
            update_signal_history(pipeline["run_date"], signal_titles)
        else:
            print("⚠️  Could not extract signal titles")

        return pipeline


def score_articles_by_relevance(articles: list[dict], config: dict | None = None, *, use_live_model: bool = False) -> list[dict]:
    """Use a low-cost Anthropic model to assign domain relevance scores to each article."""
    return ArticleAnalyzer(config=config, use_live_model=use_live_model).score_articles(articles)


def select_relevant_articles(articles: list[dict], threshold: int | None = None, per_domain_top: int | None = None, max_combined: int | None = None) -> list[dict]:
    config = load_domain_config()
    selection_config = config.get("selection", {})
    threshold = threshold if threshold is not None else int(selection_config.get("combined_threshold", 6))
    per_domain_top = per_domain_top if per_domain_top is not None else int(selection_config.get("per_domain_top", 2))
    max_combined = max_combined if max_combined is not None else int(selection_config.get("max_combined_articles", 8))

    domain_names = [domain["name"] for domain in config.get("domains", [])]
    selected: list[dict] = []
    seen_links = set()

    # 1) Preserve the highest-scoring article(s) for each domain before considering overall combined rank.
    for domain in domain_names:
        ranked = sorted(
            articles,
            key=lambda item: (
                item.get("domain_scores", {}).get(domain, 0),
                item.get("combined_score", 0),
            ),
            reverse=True,
        )
        for article in ranked[:per_domain_top]:
            if article.get("link") not in seen_links:
                selected.append(article)
                seen_links.add(article.get("link"))

    # 2) Fill out remaining slots with the highest combined-score articles that are still distinct.
    remaining_slots = max(0, max_combined - len(selected))
    if remaining_slots > 0:
        combined_ranked = sorted(
            [article for article in articles if article.get("link") not in seen_links and article.get("combined_score", 0) >= threshold],
            key=lambda item: (
                item.get("combined_score", 0),
                max(item.get("domain_scores", {}).values() or [0]),
            ),
            reverse=True,
        )
        for article in combined_ranked[:remaining_slots]:
            if article.get("link") not in seen_links:
                selected.append(article)
                seen_links.add(article.get("link"))

    # 3) If more slots remain, fill with the highest-scoring distinct articles even if they sit just below threshold.
    if len(selected) < max_combined:
        fallback_ranked = sorted(
            [article for article in articles if article.get("link") not in seen_links],
            key=lambda item: (
                item.get("combined_score", 0),
                max(item.get("domain_scores", {}).values() or [0]),
            ),
            reverse=True,
        )
        for article in fallback_ranked:
            if article.get("link") not in seen_links:
                selected.append(article)
                seen_links.add(article.get("link"))
            if len(selected) >= max_combined:
                break

    return selected


def fetch_article_content(url: str, fallback_text: str = "") -> str:
    """Fetch and extract readable text from an article URL."""
    browser_headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Upgrade-Insecure-Requests": "1",
        "DNT": "1",
    }

    def blocked_by_anti_bot(text: str) -> bool:
        lowered = text.lower()
        return "just a moment" in lowered or "checking your browser" in lowered or "cloudflare" in lowered or "access denied" in lowered

    try:
        response = requests.get(url, timeout=20, headers=browser_headers, allow_redirects=True)
        if response.status_code == 403 and blocked_by_anti_bot(response.text):
            print(f"  ⚠️ Site rejected automated access for {url} (Cloudflare/403 challenge); using fallback summary.")
            return fallback_text[:15000]
        response.raise_for_status()
    except requests.exceptions.HTTPError as exc:
        print(f"  ✗ HTTP error fetching article content for {url}: {exc}")
        return fallback_text[:15000]
    except Exception as exc:
        print(f"  ✗ Unable to fetch article content for {url}: {exc}")
        return fallback_text[:15000]

    soup = BeautifulSoup(response.text, "html.parser")
    article_block = None
    for selector in ["article", "main", "div.post-content", "div.entry-content", "[role='main']"]:
        article_block = soup.select_one(selector)
        if article_block:
            break

    if article_block is None:
        article_block = soup

    text_chunks = []
    for tag in article_block.find_all(["p", "h1", "h2", "h3", "li"]):
        text = " ".join(tag.get_text(" ", strip=True).split())
        if len(text) > 30:
            text_chunks.append(text)

    full_text = "\n\n".join(text_chunks)
    if not full_text.strip():
        return fallback_text[:15000]

    return full_text[:15000]


def generate_relevance_summary(articles: list[dict], config: dict | None = None) -> str:
    """Generate a cheap relevance summary for the selected articles."""
    if not articles:
        return "No relevant articles found."

    config = config or load_domain_config()
    domain_names = [domain["name"] for domain in config.get("domains", [])]
    lines = ["## Relevance review"]
    for article in sorted(articles, key=lambda item: item.get("combined_score", 0), reverse=True):
        domain_summary = ", ".join(
            f"{domain}: {article.get('domain_scores', {}).get(domain, 0)}" for domain in domain_names
        )
        lines.append(f"- {article['title']} ({article['link']}) — combined {article.get('combined_score', 0)} | {domain_summary}")
    return "\n".join(lines)


def generate_deep_analysis(articles: list[dict], config: dict | None = None, *, use_live_model: bool = False) -> str:
    """Fetch full article content and run a deeper analysis using the premium model."""
    return ArticleAnalyzer(config=config, use_live_model=use_live_model).generate_deep_analysis(articles)


def enrich_selected_articles(articles: list[dict]) -> list[dict]:
    """Fetch and attach full text to the selected candidates for the deep-analysis stage."""
    enriched: list[dict] = []
    for article in articles:
        record = dict(article)
        fallback_text = record.get("summary") or record.get("title") or ""
        record["full_text"] = fetch_article_content(record.get("link", ""), fallback_text)
        enriched.append(record)
    return enriched


def run_stage_pipeline(raw_articles: list[dict] | None = None, *, config: dict | None = None, days_back: int | None = None, use_live_model: bool = False) -> dict:
    """Run the weekly pipeline as explicit stages with clear data flow between them."""
    analyzer = ArticleAnalyzer(config=config, use_live_model=use_live_model)
    if raw_articles is None:
        return analyzer.run_stage_pipeline(days_back=days_back)
    return analyzer.run_stage_pipeline(raw_articles, days_back=days_back)


# ── Claude signal generation ──────────────────────────────────────────────────

def generate_summary(feed_content: str) -> str:
    """Compatibility wrapper for the legacy single-input entry point."""
    if not feed_content or not feed_content.strip():
        return "No feed content available."

    article_rows = []
    for line in feed_content.splitlines():
        if "Link:" in line:
            continue
        if "Summary:" in line:
            continue
        if line.strip().startswith("-"):
            article_rows.append({
                "title": line.strip()[2:].strip(),
                "link": "",
                "summary": "",
                "domain_scores": {"architecture": 0, "regulation": 0, "ai": 0},
                "combined_score": 0,
            })

    if not article_rows:
        return "No structured article data available for deep analysis."

    return generate_deep_analysis(article_rows)


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


def prune_signal_history(history_text: str, datetime_value: str | None = None) -> str:
    """Drop history sections older than 90 days while preserving the most recent entries."""
    if not history_text.strip():
        return history_text.strip()

    reference = datetime.strptime(datetime_value or datetime.now().strftime("%B %d, %Y"), "%B %d, %Y")
    cutoff = reference - timedelta(days=90)
    sections: list[str] = []
    current_block: list[str] = []
    current_date: datetime | None = None

    for line in history_text.splitlines():
        if line.startswith("## Week of "):
            if current_block:
                if current_date is not None and current_date >= cutoff:
                    sections.append("\n".join(current_block).rstrip())
                current_block = []
            try:
                current_date = datetime.strptime(line.replace("## Week of ", ""), "%B %d, %Y")
            except ValueError:
                current_date = None
            current_block = [line]
            continue

        if current_block:
            current_block.append(line)

    if current_block:
        if current_date is not None and current_date >= cutoff:
            sections.append("\n".join(current_block).rstrip())

    if not sections:
        return "# Weak Signal History\n"

    return "\n\n".join(sections).rstrip() + "\n"


def update_signal_history(run_date: str, signal_titles: list[str]) -> None:
    """Append this week's signals to SIGNAL_HISTORY.md and prune entries older than 90 days."""
    history_file = BASE_DIR / "SIGNAL_HISTORY.md"

    new_entry = f"\n## Week of {run_date}\n"
    for i, title in enumerate(signal_titles, 1):
        new_entry += f"- Signal {i}: {title}\n"

    if history_file.exists():
        existing = history_file.read_text(encoding="utf-8")
        existing = prune_signal_history(existing, datetime_value=run_date)
    else:
        existing = "# Weak Signal History\n"

    updated = existing.rstrip() + new_entry
    history_file.write_text(updated, encoding="utf-8")
    print(f"✅ Updated SIGNAL_HISTORY.md with {len(signal_titles)} new signals")


# ── Email rendering ───────────────────────────────────────────────────────────

def build_email_html(body_md: str, run_date: str, model_usage: list[dict] | None = None, selected_articles: list[dict] | None = None) -> str:
    body_html = markdown2.markdown(
        body_md,
        extras=["fenced-code-blocks", "tables", "strike", "extra", "smarty"]
    )

    # Clean up excessive whitespace/newlines that markdown2 sometimes adds
    body_html = re.sub(r'>\s+<', '><', body_html)  # Remove whitespace between tags
    body_html = re.sub(r'\n\n+', '\n', body_html)   # Collapse multiple newlines

    relevance_html = ""
    if selected_articles:
        relevance_md = generate_relevance_summary(selected_articles)
        relevance_html = markdown2.markdown(
            relevance_md,
            extras=["fenced-code-blocks", "tables", "strike", "extra", "smarty"],
        )
        relevance_html = re.sub(r'>\s+<', '><', relevance_html)
        relevance_html = re.sub(r'\n\n+', '\n', relevance_html)
        relevance_html = f'<div class="relevance-summary">{relevance_html}</div>'

    # Post-process generated HTML to wrap any "Sources:" heading + list
    # into a container with class `sources` so the email template can style it.
    try:
        pattern = re.compile(r"(?:<(?:p|h[1-6])>\s*(?:<strong>)?\s*Sources\s*:\s*(?:</strong>)?\s*</(?:p|h[1-6])>\s*)(<ul>.*?</ul>)", re.IGNORECASE | re.DOTALL)
        body_html = pattern.sub(r"<div class=\"sources\">\1</div>", body_html)
    except Exception:
        # If post-processing fails for any reason, fall back to unmodified HTML
        pass

    env = Environment(loader=FileSystemLoader(str(TEMPLATES_DIR)), autoescape=True)
    template = env.get_template("email.html")
    return template.render(
        run_date=run_date,
        body_html=Markup(relevance_html + body_html),
        model_usage=model_usage or [],
    )


# ── Email sending via Gmail SMTP with App Password ──────────────────────────


def send_email(subject: str, html_body: str):
    username = get_gmail_username()
    app_password = get_gmail_app_password()
    to_email = get_to_email()
    cc_email = get_cc_email()

    sender = create_email_sender(live=should_send_email(), username=username, password=app_password, recipient=to_email)
    result = sender.send(subject, html_body)

    if result.get("status") == "dry-run":
        print(f"DRY_RUN: email not sent subject={subject!r} to {to_email}")
        return

    if cc_email:
        print(f"✅ Email sent to {to_email}, CC'd to {cc_email}")
    else:
        print(f"✅ Email sent to {to_email}")


# ── Main ──────────────────────────────────────────────────────────────────────

def run_relevance_and_deep_analysis(days_back: int = 7, *, use_live_model: bool = False) -> str:
    """Use a low-cost model to filter the feed, then a deeper model to analyze the selected articles."""
    global LAST_SELECTED_ARTICLES
    MODEL_USAGE_STATS.clear()

    config = load_domain_config()
    pipeline = run_stage_pipeline(config=config, days_back=days_back, use_live_model=use_live_model)

    selected = pipeline["selected_articles"]
    LAST_SELECTED_ARTICLES = selected
    if not selected:
        return ""

    print(f"Selected {len(selected)} candidate articles for deep analysis.")
    return pipeline["summary_md"]


def main():
    print("=== Weekly summary pipeline ===")
    MODEL_USAGE_STATS.clear()
    config = load_domain_config()
    pipeline = run_stage_pipeline(config=config, days_back=7, use_live_model=should_send_email())

    if not pipeline.get("summary_md"):
        return


if __name__ == "__main__":
    main()
