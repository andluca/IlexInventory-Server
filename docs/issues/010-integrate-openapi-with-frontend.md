# 010 — Integrate OpenAPI with frontend type generation

## Overview

Final OpenAPI surface lock-in: regenerate `openapi.json` against the running backend, configure FE's `openapi-typescript` against it, smoke-test a handful of TanStack Query hooks. CI gate fails on regen drift.

**Scope:**
- `drf-spectacular` settings tuning: tag groups per app, security schemes (session cookie), error response shapes, custom serializer extensions for the `?format=csv` content negotiation
- Regenerate `openapi.json`; commit a snapshot in BE for offline FE generation
- FE `openapi-typescript` script wired into `IlexInventory-Client/package.json`; first generated types committed to `IlexInventory-Client/src/api/generated/`
- FE smoke: 2-3 query hooks (e.g., `useProductsList`, `useDashboard`, `useCommitSO`) compile and call against a local BE; types match what the BE returns
- BE CI gate: regenerate `openapi.json` and fail on diff (catches drift between code and committed schema)
- FE CI gate: regenerate types from committed `openapi.json` and fail on diff

**Reference:** SPEC §2.6, §2.7, §3.9.

**Depends on:** 009.
