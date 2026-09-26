# Step 4: make candidate selection deterministic and explicit

## Goal

Keep the shortlist logic clear, stable, and easy to test.

## Problem in the current code

`select_relevant_articles()` in [weekly_summary.py](../weekly_summary.py) already has a sensible intent, but it is embedded in a large pipeline and is difficult to reason about in isolation. The selection policy is important because it determines what reaches the expensive deep-analysis step.

## Proposed changes

- keep the same ranking logic but move it into a dedicated stage
- define the selection policy in a single place
- preserve the “top per domain” logic followed by “best combined-score” fill
- ensure the result is deterministic and deduplicated by article link

## Recommended selection flow

1. Pick the highest-scoring article from each domain
2. Add distinct results until the per-domain quota is filled
3. Fill any remaining slots with the highest combined-score distinct articles
4. If still under quota, use a fallback selection based on overall score

## Implementation notes

- Keep selection parameters configurable via the existing domain config under `selection`
- Make candidate ranking helpers pure and testable
- Preserve the deduplication behavior against `seen_links`
- Track which article was selected for each domain for easier debugging

## Acceptance criteria

- the shortlist is deterministic for a fixed scored-input set
- the candidate count stays within `max_combined_articles`
- the stage function is easy to unit test with a synthetic article list
- the selected articles are the exact set sent to the deep-analysis stage

## Next step

Proceed to [05-article-enrichment.md](./05-article-enrichment.md).
