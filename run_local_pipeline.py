import os
import sys
from pathlib import Path

# Ensure workspace root is in path
ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

import runtime_adapters
import weekly_summary

# Override email send to avoid sending real emails during local runs
def _no_send(self, subject: str, html_body: str):
    print(f"OVERRIDE: skipping SMTP send for subject={subject!r}")
    return {"status": "dry-run", "subject": subject}

runtime_adapters.EmailSenderAdapter.send = _no_send

if __name__ == "__main__":
    print("=== Running local pipeline (Anthropic from credentials.json) ===")
    # Ensure DRY_RUN env is not set so Anthropic client uses credentials.json
    os.environ.pop("DRY_RUN", None)
    # Run pipeline with live model enabled
    summary = weekly_summary.run_relevance_and_deep_analysis(days_back=7, use_live_model=True)
    print("=== Pipeline complete ===")
    if summary:
        print(summary[:2000])
    else:
        print("(no summary generated)")
