import os
import unittest


class EmailConfigTests(unittest.TestCase):
    def test_email_lookup_accepts_recipient_alias(self):
        os.environ["TO_EMAIL"] = "to@example.com"
        os.environ.pop("RECIPIENT_EMAIL", None)

        import weekly_summary

        self.assertEqual(weekly_summary.get_to_email(), "to@example.com")

    def test_smtp_credentials_are_required(self):
        os.environ["GMAIL_USERNAME"] = "user@gmail.com"
        os.environ["GMAIL_APP_PASSWORD"] = "app-password"

        import weekly_summary

        self.assertEqual(weekly_summary.get_gmail_username(), "user@gmail.com")
        self.assertEqual(weekly_summary.get_gmail_app_password(), "app-password")

    def test_domain_config_supports_relevance_scoring(self):
        import weekly_summary

        domains = weekly_summary.load_domain_names()
        self.assertIn("architecture", domains)
        self.assertIn("regulation", domains)
        self.assertIn("ai", domains)

    def test_article_selection_respects_threshold_and_domain_top_pick(self):
        import weekly_summary

        articles = [
            {
                "title": "Architecture pattern A",
                "link": "https://example.com/a",
                "summary": "Platform engineering and DDD for bank teams.",
                "domain_scores": {"architecture": 9, "regulation": 2, "ai": 1},
            },
            {
                "title": "Architecture pattern B",
                "link": "https://example.com/b",
                "summary": "Platform trade-offs in architecture teams.",
                "domain_scores": {"architecture": 8, "regulation": 1, "ai": 2},
            },
            {
                "title": "Regulation note",
                "link": "https://example.com/c",
                "summary": "OSFI and open banking guidance.",
                "domain_scores": {"architecture": 1, "regulation": 10, "ai": 1},
            },
            {
                "title": "AI governance note",
                "link": "https://example.com/d",
                "summary": "Shadow AI governance and model risk. ",
                "domain_scores": {"architecture": 1, "regulation": 4, "ai": 9},
            },
            {
                "title": "Low relevance article",
                "link": "https://example.com/e",
                "summary": "General engineering article unrelated.",
                "domain_scores": {"architecture": 1, "regulation": 1, "ai": 1},
            },
        ]

        selected = weekly_summary.select_relevant_articles(articles, threshold=6, per_domain_top=2, max_combined=2)

        selected_titles = {item["title"] for item in selected}
        self.assertIn("Architecture pattern A", selected_titles)
        self.assertIn("Regulation note", selected_titles)
        self.assertIn("AI governance note", selected_titles)
        self.assertNotIn("Low relevance article", selected_titles)

    def test_supported_anthropic_model_ids_are_used_directly(self):
        import weekly_summary

        self.assertEqual(
            weekly_summary.resolve_model_name("claude-haiku-4-5"),
            "claude-haiku-4-5",
        )
        self.assertEqual(
            weekly_summary.resolve_model_name("claude-sonnet-5"),
            "claude-sonnet-5",
        )
        self.assertEqual(
            weekly_summary.resolve_model_name("   claude-haiku-4-5   "),
            "claude-haiku-4-5",
        )

    def test_dry_run_mode_skips_email_send(self):
        import weekly_summary

        os.environ["DRY_RUN"] = "1"
        self.assertFalse(weekly_summary.should_send_email())

        os.environ["DRY_RUN"] = "0"
        self.assertTrue(weekly_summary.should_send_email())

        os.environ.pop("DRY_RUN", None)
        self.assertTrue(weekly_summary.should_send_email())

    def test_relevance_scoring_uses_safe_batch_size(self):
        import weekly_summary

        config = weekly_summary.load_domain_config()
        self.assertEqual(config["selection"].get("relevance_batch_size", 4), 4)

    def test_extract_json_array_handles_fenced_claude_output(self):
        import weekly_summary

        sample = '''```json
[
  {
    "title": "Example",
    "link": "https://example.com",
    "domain_scores": {"architecture": 8, "regulation": 1, "ai": 0},
    "combined_score": 6.4
  }
]
```'''

        parsed = weekly_summary.extract_json_array_from_text(sample)
        self.assertEqual(parsed[0]["title"], "Example")
        self.assertEqual(parsed[0]["combined_score"], 6.4)

    def test_raw_batch_response_logging_for_anthropic_review(self):
        import json
        import os
        from datetime import datetime
        from pathlib import Path

        import anthropic
        import weekly_summary

        os.environ["DRY_RUN"] = "1"
        try:
            articles = weekly_summary.fetch_feed_articles(days_back=7)[:3]
            config = weekly_summary.load_domain_config()
            model_name = weekly_summary.resolve_model_name(config.get("models", {}).get("relevance_model", "claude-haiku-4-5"))
            max_tokens = int(config.get("models", {}).get("relevance_max_tokens", 10000))
            domain_names = [domain["name"] for domain in config.get("domains", [])]

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
                prompt.append(json.dumps({
                    "title": article["title"],
                    "link": article["link"],
                    "summary": article["summary"] or article.get("feed_name", ""),
                }, ensure_ascii=False))

            client = anthropic.Anthropic(api_key=weekly_summary.get_anthropic_api_key())
            response = client.messages.create(
                model=model_name,
                max_tokens=max_tokens,
                system="Score each article for relevance to the configured domains. Be strict and only award high scores when the article meaningfully intersects the domain.",
                messages=[{"role": "user", "content": "\n".join(prompt)}],
            )

            text = "\n".join(block.text for block in response.content if getattr(block, "type", None) == "text")

            output_dir = Path(weekly_summary.BASE_DIR) / "artifacts"
            output_dir.mkdir(exist_ok=True)
            timestamp = datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
            output_path = output_dir / f"anthropic_batch_review_{timestamp}.txt"
            output_path.write_text(text, encoding="utf-8")

            print("--- Anthropic raw batch response ---")
            print(text)
            print(f"--- Written to: {output_path} ---")
            print("--- End Anthropic raw batch response ---")

            parsed = weekly_summary.extract_json_array_from_text(text)
            self.assertIsInstance(parsed, list)
            self.assertGreater(len(parsed), 0)
        finally:
            os.environ.pop("DRY_RUN", None)


if __name__ == "__main__":
    unittest.main()
