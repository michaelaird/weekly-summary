# Step 2: parallelize feed fetching and normalize article data

## Goal

Fetch feeds efficiently and normalize article metadata before any LLM work begins.

## Problem in the current code

The current `fetch_feed_articles()` function in [weekly_summary.py](../weekly_summary.py) loops through each feed serially and repeats a lot of metadata handling inline. Network latency is a major source of delay, and malformed entries create avoidable noise.

## Proposed changes

- Use a small worker pool for independent feed fetches
- Normalize article records immediately after retrieval
- Reject empty or stale items before they reach the scoring stage
- Preserve `feed_name`, `category`, `title`, `link`, and `summary` metadata
- Add timeout and retry guards per feed request

## Recommended behavior

For each feed:
- fetch the feed URL
- parse the entries
- keep only items published within the configured lookback window
- trim the summary to a reasonable length
- normalize the article record into a consistent structure

## Data contract

Each normalized article should look like:

```python
{
  "title": "...",
  "link": "...",
  "summary": "...",
  "feed_name": "...",
  "category": "...",
  "published": datetime,
}
```

## Implementation notes

- Keep feed parsing in a dedicated helper such as `fetch_feed_articles()` or a new `normalize_feed_entries()` helper
- Use a small fixed worker count so concurrency remains predictable
- Avoid broad exception swallowing; record per-feed failures and continue
- Log source-level failures cleanly so they are visible without cluttering the output

## Acceptance criteria

- feed fetches run concurrently within a bounded worker pool
- invalid or stale entries never reach scoring
- article metadata is standardized before scoring
- one bad feed does not prevent the others from finishing
- the fetch stage remains easy to test in isolation

## Next step

Proceed to [03-relevance-scoring-batches.md](./03-relevance-scoring-batches.md).
