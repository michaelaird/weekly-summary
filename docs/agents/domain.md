# Domain docs

This repo uses the single-context layout.

## Layout

- Root-level `CONTEXT.md` for repo-wide context and conventions
- `docs/adr/` for architecture decision records

## Consumer rules

- Read the root `CONTEXT.md` before making broad repo changes.
- Read relevant ADRs before making architecture decisions that might affect existing tradeoffs.
- When a change affects a domain boundary, update the relevant context or ADR rather than leaving the decision implicit.

## When to add multi-context

A multi-context layout is only needed if the repo grows into a monorepo or multi-package structure with independent domain contexts.
