# Step 1: define the contract and stage boundaries

## Goal

Lock down the interface for each stage before changing execution flow. This reduces ambiguity and makes the pipeline easier to reason about.

## Problem in the current code

The logic in [weekly_summary.py](../weekly_summary.py) is effectively a single large script with several responsibilities mixed together:

- feed fetching
- relevance scoring
- candidate selection
- full-content extraction
- deep analysis
- email rendering
- history updates

That makes the control flow harder to debug and harder to parallelize safely.

## Proposed design

Refactor the script into staged operations with narrow responsibilities:

1. Feed fetch stage
2. Relevance scoring stage
3. Candidate selection stage
4. Article enrichment stage
5. Deep analysis stage
6. Email assembly stage

Each stage should accept a clear input shape and emit a clear output shape. The project should preserve the weekly report contract while making the internal orchestration explicit.

## Recommended contract

### Feed fetch

Input: configured feed list and days-back window
Output: normalized article records with metadata

Required fields:
- title
- link
- summary
- feed_name
- category
- published

### Relevance scoring

Input: normalized articles
Output: same articles with domain_scores and combined_score

### Candidate selection

Input: scored articles
Output: shortlist of likely relevant article records

### Article enrichment

Input: shortlist
Output: same shortlist with full content or fallback text

### Deep analysis

Input: enriched shortlist
Output: markdown signal summary

### Email assembly

Input: final markdown summary
Output: HTML email ready for SMTP

## Implementation notes

- Keep the public entry point in `main()` and `run_relevance_and_deep_analysis()` stable
- Add internal helper functions that operate on pure data structures
- Avoid mixing rendering, selection, and network logic in the same function
- Keep the config objects and domain names in one source of truth, currently in [config/domains.json](../config/domains.json)

## Acceptance criteria

- each stage has a single responsibility
- execution order is easy to read
- output from one stage is explicitly consumed by the next stage
- no stage depends on hidden global state beyond the agreed config and runtime context
- the email and signal-history behavior remain intact

## Next step

Proceed to [02-feed-fetch-and-normalization.md](./02-feed-fetch-and-normalization.md).
