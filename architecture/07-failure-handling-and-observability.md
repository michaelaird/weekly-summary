# Step 7: add failure isolation, retries, and observability

## Goal

Make the pipeline robust under external variability without making it harder to debug.

## Problem in the current code

The script currently has good output logic, but it has limited safety boundaries around network calls and model responses. A timeout or malformed JSON can create a large failure surface.

## Proposed changes

- add retries with exponential backoff for transient HTTP/model failures
- enforce per-task timeout settings for RSS fetches and article fetches
- validate JSON responses before using them
- emit targeted logging so each worker failure is easy to trace
- keep a model usage summary for later review in the final email footer

## Recommended guardrails

- small fixed concurrency for network tasks
- explicit operation boundaries around each model invocation
- fail-soft behavior for a single article or feed
- keep the top-level run resilient enough to continue if a subset fails

## Implementation notes

- Centralize retry logic in helper functions rather than scattering it across the pipeline
- Log enough detail to know which feed, article, or batch failed without dumping huge payloads
- Keep the observability output explicit and human-readable, especially in local dry runs

## Acceptance criteria

- transient failures recover automatically
- a single bad feed or article does not block the entire workflow
- invalid model output is surfaced early and logged clearly
- the run remains debuggable even with parallel work

## Next step

Proceed to [08-testing-and-validation.md](./08-testing-and-validation.md).
