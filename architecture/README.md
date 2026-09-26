# Architecture refactor plan

This directory captures a staged refactor plan for the weekly summary pipeline in [weekly_summary.py](../weekly_summary.py). The goal is to improve runtime stability, reduce Anthropic timeout risk, and lower unnecessary token spend without over-engineering into a full autonomous agent system.

## Core direction

The project should evolve from a single sequential script into a small, explicit pipeline with bounded parallelism and smaller model calls. The refactor is intentionally incremental and keeps the public behavior of the weekly report stable.

## Design principles

- Stability first, then signal quality, then token efficiency
- Smaller LLM tasks are safer than giant prompts
- Parallelism is bounded and stage-based, not autonomous
- Failures should be isolated to a single stage
- The weekly email output remains the contract that must not regress

## Staged plan

1. [01-contract-and-stage-boundaries.md](./01-contract-and-stage-boundaries.md) — define the stable interfaces and stage separation
2. [02-feed-fetch-and-normalization.md](./02-feed-fetch-and-normalization.md) — parallelize feed collection and normalize metadata
3. [03-relevance-scoring-batches.md](./03-relevance-scoring-batches.md) — reduce prompt size and score articles in bounded batches
4. [04-candidate-selection.md](./04-candidate-selection.md) — preserve deterministic selection logic for shortlisted articles
5. [05-article-enrichment.md](./05-article-enrichment.md) — fetch article content concurrently with timeouts and fallbacks
6. [06-deep-analysis.md](./06-deep-analysis.md) — run the premium analysis on a small shortlist with narrow prompts
7. [07-failure-handling-and-observability.md](./07-failure-handling-and-observability.md) — add retries, timeouts, and readable diagnostics
8. [08-testing-and-validation.md](./08-testing-and-validation.md) — protect the refactor with focused regression tests

## Recommended execution order

Start with the contract and stage boundaries, then move through feed fetching, scoring, selection, enrichment, analysis, and validation. This order minimizes breakage while making the largest reliability gains early.

## Non-goals

- building a fully autonomous multi-agent runner
- introducing dynamic planning loops that are harder to debug
- replacing the current email flow with a new interface
- broad rewriting of external behavior in [README.md](../README.md)

## Success criteria

The refactor is successful when:

- the pipeline completes more reliably under network and model variability
- no single article or failed fetch blocks the full run
- the Anthropic payloads are smaller and easier to validate
- the output email remains unchanged from the user's perspective
- the run remains easy to debug locally and in GitHub Actions
