# Step 8: protect the refactor with focused regression tests

## Goal

Lock the behavior down while improving concurrency and model batching.

## Problem in the current code

The repo has only a small existing test surface in [tests/test_email_config.py](../tests/test_email_config.py). The staged refactor should not rely on informal manual checks alone.

## Proposed changes

- cover feed normalization and validation
- cover candidate selection ordering
- cover fallback behavior when article extraction fails
- cover dry-run and email generation behavior
- cover signal extraction from the final markdown output

## Recommended test categories

1. Pure logic tests
   - article ranking
   - selection deduplication
   - score aggregation

2. Failure-path tests
   - empty feed list
   - invalid JSON from a model
   - failed content-fetch fallback

3. Output contract tests
   - final markdown still includes expected signal headings
   - HTML email still renders without crashing
   - dry-run path skips SMTP

## Implementation notes

- Prefer unit tests for deterministic logic over tests that mock too much behavior
- Keep the tests focused on real behavior, not just internal implementation details
- Add tests around the stage interfaces so the refactor remains safe

## Acceptance criteria

- the refactor does not regress the weekly-email behavior
- selection logic stays deterministic for the same input set
- failure handling is covered by automated tests
- the new pipeline stages are testable in isolation

## Completion criteria

The project is ready to move to the implementation phase once all staged documents are complete and the test suite covers the critical logic and failure paths.
