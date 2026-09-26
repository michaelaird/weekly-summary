# Step 6: narrow the deep-analysis tasks to the final shortlist

## Goal

Reduce prompt size and cost in the premium analysis stage while preserving signal quality.

## Problem in the current code

The deep-analysis function gathers a long combined article bundle into one large prompt, which increases the chance of timeouts and overrun. This is the single most expensive part of the pipeline and should be the most carefully bounded.

## Proposed changes

- run analysis on the shortlist, not the full article universe
- prefer article-by-article analysis or a small batch of 2–3 articles per prompt
- keep the prompt constrained to the exact context needed for the signal output
- merge the per-article outputs into a final summary with deterministic rules

## Recommended structure

1. Select the final candidate set
2. Enrich each article with readable text
3. Analyze each article in a focused prompt
4. Merge article-level findings into final weekly signals

## Implementation notes

- Keep the system prompt and user prompt templates in [prompts/system.txt](../prompts/system.txt) and [prompts/user.txt](../prompts/user.txt)
- Ensure the user message includes only the relevant article content and the signal history needed for novelty checks
- Do not send full raw feed content into the premium model
- Keep the final summary extraction stable and parseable

## Acceptance criteria

- the premium model sees only the shortlist and relevant context
- large bundled prompts are replaced with narrower, safer inputs
- final output still reflects the same signal-generation intent
- model cost is lowered without reducing answer quality materially

## Next step

Proceed to [07-failure-handling-and-observability.md](./07-failure-handling-and-observability.md).
