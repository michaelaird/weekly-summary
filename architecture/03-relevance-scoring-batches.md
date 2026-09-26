# Step 3: score articles in smaller, bounded batches

## Goal

Reduce the size and fragility of Anthropic relevance calls.

## Problem in the current code

The `score_articles_by_relevance()` function in [weekly_summary.py](../weekly_summary.py) sends a large list of article objects in one model call. This creates several issues:

- higher latency
- more timeout risk
- more cost per request
- more parsing and schema drift risk

## Proposed changes

- keep the low-cost model but break scoring into smaller batches
- validate the model output schema before using it
- avoid scoring empty or invalid article payloads
- maintain the same domain configuration and weighting logic

## Recommended batching strategy

Use a small fixed batch size such as 5–10 articles per request. This keeps prompts bounded and improves fault isolation.

For each batch:
- include the configured domain names
- include article title, link, and summary
- require valid JSON output
- map the result back to the article records by link

## Output contract

Each scored article should include:
- `domain_scores`: mapping of domain name to integer 0–10
- `combined_score`: weighted total

## Implementation notes

- Create a helper for `score_article_batch(batch)`
- Preserve the existing model selection from `config/models`
- Add a strict JSON parser that fails gracefully and logs the malformed result
- Capture token usage per batch for debugging and optimization

## Acceptance criteria

- scoring work is chunked into bounded batches
- no single malformed model response poisons the whole job
- article scoring remains deterministic and attributable to the original article link
- output format remains compatible with `select_relevant_articles()`
- batch size can be tuned easily without rewriting core logic

## Next step

Proceed to [04-candidate-selection.md](./04-candidate-selection.md).
