---
id: ILEX-010
github_id: null
status: open
assignee: null
state: Queued
type: item
depends_on: [ILEX-009]
---

# ILEX-010 Integrate OpenAPI with frontend type generation

Final OpenAPI surface lock-in: regenerate `openapi.json` against the running backend, configure the FE's `openapi-typescript` against it, smoke-test a handful of TanStack Query hooks. CI gate fails on regen drift.

# Specification

Reference: [`docs/specs/SPEC.md`](../../docs/specs/SPEC.md) §2.6, §2.7, §3.9.

## Scope

- `drf-spectacular` settings tuning: tag groups per app, security schemes (session cookie), error response shapes, custom serializer extensions for `?format=csv` content negotiation
- Regenerate `openapi.json`; commit a snapshot in BE for offline FE generation
- FE `openapi-typescript` script wired into `IlexInventory-Client/package.json`; first generated types committed to `IlexInventory-Client/src/api/generated/`
- FE smoke: 2-3 query hooks (e.g., `useProductsList`, `useDashboard`, `useCommitSO`) compile and call against a local BE; types match what the BE returns
- BE CI gate: regenerate `openapi.json` and fail on diff (catches drift between code and committed schema)
- FE CI gate: regenerate types from committed `openapi.json` and fail on diff

## Dependencies

1. ILEX-009 (all endpoints — including CSV format negotiation — must be locked before final OpenAPI snapshot)
