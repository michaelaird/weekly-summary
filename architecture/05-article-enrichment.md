# Step 5: enrich only the selected articles with full content

## Goal

Fetch and parse article content only for the shortlist, with bounded concurrency and safe fallbacks.

## Problem in the current code

The deep-analysis stage in [weekly_summary.py](../weekly_summary.py) currently fetches full content for every selected article in a sequence, and the extraction logic is tightly coupled to the rest of the pipeline. This is a natural place to improve throughput while reducing risk.

## Proposed changes

- run full-content fetches concurrently for the selected article shortlist
- enforce explicit timeouts for each HTTP request
- use a bounded worker pool for article enrichment
- fall back to summary text when extraction fails or a site blocks automated access

## Recommended behavior

For each selected article:
- fetch the page with browser-like headers
- parse with BeautifulSoup
- extract readable paragraphs/headings/list items
- cap the text length before sending to the model
- fall back to the existing summary text if extraction is poor or blocked

## Implementation notes

- Keep the HTTP logic in a dedicated fetch helper
- Isolate anti-bot and 403 handling so it does not break the pipeline
- Prefer a clear `full_text` or `fallback_text` result per article
- Keep content length under a safe bound to avoid oversized prompts

## Acceptance criteria

- article enrichment is parallelized, but only within a fixed small pool
- one failed article fetch does not stop the rest of the run
- extracts are small enough to be safe for the later LLM step
- fallback path remains consistent with the current behavior

## Next step

Proceed to [06-deep-analysis.md](./06-deep-analysis.md).
