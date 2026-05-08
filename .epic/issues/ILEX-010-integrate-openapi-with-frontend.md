---
id: ILEX-010
github_id: null
status: completed
assignee: null
state: Done
type: item
depends_on: [ILEX-009]
---

# ILEX-010 Integrate OpenAPI snapshot and BE drift gate

Lock the OpenAPI surface for the frontend: register the missing apps in `INSTALLED_APPS` so drf-spectacular discovers their tags, tune `SPECTACULAR_SETTINGS` (per-app tag groups, security scheme description, error envelope component, CSV-format query param convention), backfill `@extend_schema` decorators that are currently missing tag/error-envelope metadata, snapshot `openapi.json` to the repo, and add a CI gate that regenerates the snapshot and fails on diff. Frontend-side type generation and FE CI gate are tracked in the `IlexInventory-Web` repo (out of scope for this server repo per D0 — repo split).

# Specification

Reference: [`docs/specs/SPEC.md`](../../docs/specs/SPEC.md) §2.6, §2.7, §3.9.

## Operation: regenerate-openapi-snapshot
Route/Command: `python backend/manage.py spectacular --file backend/openapi.json --validate`

Generates the OpenAPI 3.1 schema from the live DRF view set and writes it to a tracked file. Run locally before committing schema-affecting changes; run in CI to detect drift between code and the committed snapshot.

### Preconditions
* `apps.sales` and `apps.financials` are listed in `INSTALLED_APPS` (otherwise their views are never imported on schema generation, since `urls.py` imports happen lazily and tag discovery walks `INSTALLED_APPS`).
* All `@extend_schema(...)` decorators carry the four required keys: `tags`, `summary`, `responses`, and (for endpoints that mutate or filter) `parameters` / `request`.
* Migration suite is up-to-date (no missing models on schema parse).

### Primary Use Case (developer regen)

#### Input
```
python backend/manage.py spectacular --file backend/openapi.json --validate
```

#### Workflow
* Django boot loads `INSTALLED_APPS`; drf-spectacular scans every registered DRF view for `@extend_schema`.
* `--validate` runs the OpenAPI 3.1 schema validator and exits non-zero on any structural error (missing `responses`, malformed `parameters`, etc.).
* Snapshot file `backend/openapi.json` is overwritten in place. Stable formatting (sorted keys, 2-space indent) is enforced via the `SPECTACULAR_SETTINGS["SORT_OPERATION_PARAMETERS"]` and a post-process write step.

#### Output
```
Schema generated successfully.
```

### CI Drift Use Case

#### Input
```
./scripts/check_openapi_drift.sh
```

#### Workflow
* Script generates the schema to a temp file using the same command.
* Diffs the temp file against the committed `backend/openapi.json`.
* Exit 0 on identical bytes; exit 1 and print the unified diff otherwise.
* Run from the existing CI test job (same place as `check_no_orm.sh`).

#### Output (drift detected)
```
check-openapi-drift: FAIL — committed openapi.json is stale. Re-run:
  python backend/manage.py spectacular --file backend/openapi.json --validate
--- backend/openapi.json
+++ /tmp/openapi.regen.json
@@ ...
```

### Edge Cases
* Missing `@extend_schema` on a view → drf-spectacular auto-generates a tag from the app label (`AutoSchema` default). Acceptable transitionally; CI snapshot will pin whatever it generates and the diff gate will catch any future change.
* `--validate` failure → command exits non-zero; developer reads the validator error (e.g., `Schema component 'X' missing required field 'type'`) and fixes the offending decorator.
* `apps.sales` / `apps.financials` not in `INSTALLED_APPS` → schema parses but tags appear ungrouped; the snapshot diff in step 1 surfaces this on first regen.

## Lib: spectacular settings extension
File: `backend/settings/base.py`

The existing `SPECTACULAR_SETTINGS` block (lines 149–165) already covers `TITLE`, `VERSION`, `OAS_VERSION: 3.1.0`, `SECURITY`, and `cookieAuth`. This issue extends it with:

### Keys added
* `TAGS` — explicit per-app tag list with one-line descriptions:
  - `auth`, `catalog`, `procurement`, `inventory`, `sales`, `financials`, `meta`
* `ENUM_NAME_OVERRIDES` — pin the names for the few enums shared across apps (movement `kind`, SO `status`, PO `status`) so renames don't cascade across the snapshot.
* `POSTPROCESSING_HOOKS` — register a single hook that injects the shared `ErrorResponse` schema component (`{ error: string, detail?: string, fields?: object }`) referenced from every 4xx response.
* `SORT_OPERATION_PARAMETERS: true` — deterministic parameter ordering for byte-stable diffs.
* `COMPONENT_SPLIT_REQUEST: true` — separate request/response schema components when serializers share a name (eliminates `WriteOnly`/`ReadOnly` warnings in the snapshot).

### Functions
* `inject_error_response_component(result, generator, request, public)` — postprocessing hook in a new module `backend/apps/core/openapi.py`. Given the generated schema dict, ensures `components.schemas.ErrorResponse` exists and replaces every 400/401/403/404/422 response shape (currently a free-form object) with `{ "$ref": "#/components/schemas/ErrorResponse" }`.

## Function: csv_format_query_parameter
File: `backend/apps/core/openapi.py`

Module-level constant `CSV_FORMAT_PARAMETER` — a reusable `OpenApiParameter` describing `?format=csv` for the four endpoints that support it (`/movements`, `/batches/{id}/recall-report`, `/financials/margin`, `/financials/dashboard`). Endpoints add it to their `@extend_schema(parameters=[...])` list. Documents the parameter once instead of duplicating the description across views.

## Function: register_missing_apps
File: `backend/settings/base.py`

Add `"apps.sales"` and `"apps.financials"` to `INSTALLED_APPS`. Currently both apps are wired only via `backend/urls.py` includes; their views are imported lazily through URL resolution but their app config is never loaded, which means drf-spectacular's tag discovery and any future Django app-level signals/checks miss them.

## Lib: check_openapi_drift
File: `scripts/check_openapi_drift.sh`

Bash script invoked from CI. Mirrors the shape of the existing `scripts/check_no_orm.sh`.

### Functions
* Generates schema to a temp file via `python backend/manage.py spectacular --file <tmp> --validate`.
* `diff -u backend/openapi.json <tmp>` — exit 0 on identical bytes, exit 1 with a unified diff and a remediation command otherwise.
* Cleans up the temp file on exit.

## External Dependencies

### drf-spectacular
Used for: OpenAPI 3.1 schema generation from DRF serializers and `@extend_schema` decorators.
Commands: `python backend/manage.py spectacular --file <path> --validate`

* Already a dependency since ILEX-001; no version bump needed for this issue.
* `--validate` invokes the bundled `openapi-spec-validator` (transitive dep of drf-spectacular).

# Plan

Each step ends with green `pytest`, `ruff`, and discipline grep gates. Steps are ordered so each one is independently shippable.

1. **Register `apps.sales` and `apps.financials` in `INSTALLED_APPS`**
   - Why: drf-spectacular's tag discovery walks `INSTALLED_APPS`, not `urls.py`. Without this fix the snapshot in step 4 would tag-group sales and financials operations under their auto-derived label rather than the explicit per-app tag, and any future app-level signal/check would silently skip them.
   - [ ] Add `"apps.sales"` and `"apps.financials"` to `INSTALLED_APPS` in `backend/settings/base.py`.
   - [ ] Test (`apps/core/tests/api/test_installed_apps.py`): assert that `django.apps.apps.get_app_config("sales")` and `get_app_config("financials")` resolve. Pure regression guard.
   - [ ] Run full pytest suite — must remain at the prior green count (no new failures from app-config registration).

2. **Add shared `ErrorResponse` component + postprocessing hook**
   - Why: the BE error envelope `{ error, detail?, fields? }` is documented in SPEC §2.6 but currently every 4xx response in the schema is `application/json` with a free-form object. Pinning a named component lets the FE generate one shared `ErrorResponse` type instead of re-deriving it per endpoint, and the diff gate (step 6) catches accidental envelope changes.
   - [ ] Create `backend/apps/core/openapi.py` with `ErrorResponse` schema dict and `inject_error_response_component(result, generator, request, public)` postprocessing hook.
   - [ ] Wire `SPECTACULAR_SETTINGS["POSTPROCESSING_HOOKS"]` in `backend/settings/base.py` to include the new hook.
   - [ ] Test (`apps/core/tests/unit/test_openapi_hook.py`): given a fake schema dict with one operation that has a 400 response of free-form shape, the hook rewrites it to `{ "$ref": "#/components/schemas/ErrorResponse" }` and ensures the component exists.
   - [ ] Test: hook is idempotent — running it twice on the same schema produces identical output.

3. **Backfill `tags` and CSV-format param on existing `@extend_schema` decorators**
   - Why: the spectacular tag list defined in step 4 is meaningful only if every operation declares which tag it belongs to. Currently no decorator passes `tags=` (grep confirmed zero matches), so spectacular falls back to auto-tagging by URL prefix — fragile and re-orders the snapshot when routes move. The `?format=csv` parameter is also undocumented today.
   - [ ] Add `CSV_FORMAT_PARAMETER` constant to `backend/apps/core/openapi.py`.
   - [ ] Add `tags=["catalog"]` to every `@extend_schema` in `apps/catalog/apis.py` (7 decorators).
   - [ ] Same for `apps/procurement/apis.py` (6, tag `procurement`), `apps/inventory/apis.py` (9, tag `inventory`), `apps/sales/apis.py` (8, tag `sales`), `apps/financials/apis.py` (2, tag `financials`), `apps/core/apis.py` (5, tags `auth` for login/logout/signup/me, `meta` for health).
   - [ ] On the four CSV-supporting endpoints (`/movements`, `/batches/{id}/recall-report`, `/financials/margin`, `/financials/dashboard`), append `CSV_FORMAT_PARAMETER` to the `parameters=[...]` list.
   - [ ] Test (`apps/core/tests/api/test_openapi_tags.py`): GET `/api/v1/openapi.json`; assert every path operation carries exactly one tag and that tag is in the canonical seven-element set. Asserts the four CSV endpoints declare the `format` query parameter with `enum: ["csv"]`.

4. **Extend `SPECTACULAR_SETTINGS` with TAGS, SORT, COMPONENT_SPLIT_REQUEST, ENUM_NAME_OVERRIDES**
   - Why: the snapshot in step 5 must be byte-stable across re-runs and across machines, otherwise the CI drift gate (step 6) flaps. `SORT_OPERATION_PARAMETERS` and `COMPONENT_SPLIT_REQUEST` together eliminate the two known sources of non-determinism (param order, request/response component name collisions). Explicit `TAGS` pins the tag-group ordering that the FE sidebar uses.
   - [ ] Add `TAGS` (seven entries with one-line descriptions), `SORT_OPERATION_PARAMETERS: True`, `COMPONENT_SPLIT_REQUEST: True`, and `ENUM_NAME_OVERRIDES` (movement kind, SO status, PO status) to `SPECTACULAR_SETTINGS` in `backend/settings/base.py`.
   - [ ] Test (`apps/core/tests/api/test_openapi_settings.py`): GET `/api/v1/openapi.json`; assert top-level `tags` array length == 7 and ordering matches the canonical list; assert at least one known split component pair exists (e.g., `ProductRequest` + `Product` separately) when `COMPONENT_SPLIT_REQUEST` is on.

5. **Snapshot `backend/openapi.json` and add the `spectacular` regen target**
   - Why: the snapshot is the artifact the FE consumes (per SPEC §2.7) and the input to the drift gate. Landing it as a tracked file before the gate means step 6 has something to diff against.
   - [ ] Run `python backend/manage.py spectacular --file backend/openapi.json --validate` against the local server; commit the result.
   - [ ] Confirm file is `OpenAPI 3.1.0`, has the seven tags, has the `ErrorResponse` component, and lists `cookieAuth` under `securitySchemes`.
   - [ ] Test (`apps/core/tests/api/test_openapi_snapshot.py`): assert `backend/openapi.json` exists, parses as JSON, top-level `openapi` field equals `"3.1.0"`, and `info.version` matches `SPECTACULAR_SETTINGS["VERSION"]`. (No byte-equality assertion here — that is the drift gate's job.)
   - [ ] Add a `.gitattributes` rule for `backend/openapi.json` (`text eol=lf`) so the diff gate is line-ending-agnostic across contributor platforms.

6. **CI drift gate `scripts/check_openapi_drift.sh`**
   - Why: without the gate, the snapshot rots on first decorator change and the FE generates types from a stale schema. The gate is cheap (one schema regen + one `diff -u`) and catches the entire class of drift bugs.
   - [ ] Add `scripts/check_openapi_drift.sh` mirroring `scripts/check_no_orm.sh` (set -euo pipefail; clear failure messaging; remediation command in the error path).
   - [ ] Make it executable (`chmod +x`).
   - [ ] Wire it into the standard local-validation flow used by ILEX-001..009 (the same place `check_no_orm.sh` is invoked).
   - [ ] Test (`apps/core/tests/api/test_openapi_drift_script.py`): subprocess-runs the script in a clean checkout; expects exit 0 and stdout `check-openapi-drift: OK`. Does NOT mutate the snapshot.
   - [ ] Manual verification: introduce a temporary `tags=["bogus"]` change to one decorator, re-run the script, expect exit 1 with a unified diff. Revert.

# Notes

- **FE-side scope is in `IlexInventory-Web`, not here.** The original SPEC §2.7 mentioned committing generated TS types under `IlexInventory-Client/src/api/generated/` and a FE CI gate. Per D0 (server-only repo) and the recorded memory note `project_repo_scope`, the FE work — `openapi-typescript` script wiring, generated-types commit, TanStack Query hook smoke test, FE CI drift gate — is tracked as a sibling issue in the FE repo. This issue ships **only** the BE half: a stable snapshot at `backend/openapi.json` plus a drift gate. The FE consumes the snapshot via a relative path or by pulling a tagged snapshot from this repo.
- **Why register sales/financials in INSTALLED_APPS now and not earlier.** ILEX-007 and ILEX-008 added the apps via `urls.py` includes only, which is enough to serve requests because Django imports view classes lazily through URL resolution. App-config-level features (signals, system checks, drf-spectacular's tag-group walk) silently skipped them. Surfaced now because step 3's tag backfill assumes app-level discovery; fixing it here keeps the surface change atomic with the schema work.
- **No new dependencies.** `drf-spectacular` and its `--validate` path (via `openapi-spec-validator`) are already pinned in `pyproject.toml`. No additional pip packages.
- **Why a postprocessing hook for `ErrorResponse` instead of `OpenApiResponse(response=ErrorResponseSerializer)` per decorator.** Two reasons: (1) the error envelope is owned by `apps.core.exceptions.exception_handler`, not by any single serializer, so co-locating the schema with the handler keeps the source of truth in one place; (2) per-decorator `responses={400: ErrorResponseSerializer, 401: ..., 404: ...}` would touch 37 decorators across 6 files for purely declarative metadata — a postprocessing hook does it once and stays in sync if a new decorator is added without the metadata. The trade-off is that the hook runs on every schema regen, but the cost is sub-millisecond on a ~37-operation schema.
- **`COMPONENT_SPLIT_REQUEST` will rename a few generated TS types.** Serializers used for both request and response (e.g., `ProductSerializer`) currently emit one schema component named `Product`; with split-request enabled they become `ProductRequest` (input) and `Product` (output). The FE's TanStack hooks already consume request/response separately, so the rename is additive on the BE and tightens FE typing on the FE side. Worth pinning now while the FE has zero generated types committed.
- **Snapshot lives at `backend/openapi.json`, not repo root.** Co-locates the artifact with the code that produces it, and the FE pulls it via the same relative path the spec uses (`../../IlexInventory-Server/backend/openapi.json` from the FE repo).
- **Drift gate is exit-code-only — no auto-regen-and-commit.** Auto-regen on CI hides intent: a developer who changes a serializer should regen the snapshot deliberately so the schema diff lands in the same PR as the code diff. The gate's failure message includes the exact remediation command.
- **`ENUM_NAME_OVERRIDES` justification.** Without overrides, drf-spectacular auto-names enums from the field path (e.g., `StockMovementsKindEnum`, `SalesOrdersStatusEnum`) which are stable so long as the field path is stable. Pinning explicit names (`MovementKind`, `SaleOrderStatus`, `PurchaseOrderStatus`) means renaming a field doesn't churn the FE's generated type names.
- **No dedicated `/docs` (Swagger UI) toggle in this issue.** SPEC §3.9 mentions `OPENAPI_PUBLIC_DOCS` env var for `/docs`; that toggle is part of the deploy pipeline (ILEX-011), not the schema lock-in. The schema endpoint `/api/v1/openapi.json` already shipped in ILEX-001.

# Journal

## 2026-05-08T20:50Z — Step 6: CI drift gate scripts/check_openapi_drift.sh

- Created `scripts/check_openapi_drift.sh` (mirrors check_no_orm.sh shape: set -euo pipefail, trap for temp cleanup, clear failure message, remediation command in error path).
- Made executable with chmod +x.
- Created `backend/apps/core/tests/api/test_openapi_drift_script.py` (1 test: subprocess runs script, expects exit 0 and "check-openapi-drift: OK").
- Manual verification: injecting `tags=["bogus"]` into catalog/apis.py causes exit 1 with unified diff; reverting restores exit 0.
- Gates: 484/484 tests green, ruff clean, check-no-orm OK, check-openapi-drift OK.

## 2026-05-08T20:30Z — Step 5: Snapshot backend/openapi.json + .gitattributes

- Generated `backend/openapi.json` via `python manage.py spectacular --format openapi-json --file backend/openapi.json`.
- Verified: openapi=3.1.0, version=0.1.0, 7 tags in canonical order, ErrorResponse component, cookieAuth in securitySchemes, 26 paths total.
- Created `.gitattributes` with `backend/openapi.json text eol=lf` for cross-platform byte-stable diffs.
- Created `backend/apps/core/tests/api/test_openapi_snapshot.py` (4 tests: file exists, parses as JSON, openapi=3.1.0, version matches settings).
- Gates: 483/483 tests green, ruff clean, check-no-orm OK.

## 2026-05-08T20:10Z — Step 4: TAGS, ENUM_NAME_OVERRIDES in SPECTACULAR_SETTINGS

- Added `TAGS` (7 entries with descriptions) to `SPECTACULAR_SETTINGS` in `backend/settings/base.py`.
- Added `ENUM_NAME_OVERRIDES` pinning `MovementKind` (["adjustment","write_off"]) and `ProductBaseUnit` (["g","ml","unit"]).
- Note: `SORT_OPERATION_PARAMETERS` and `COMPONENT_SPLIT_REQUEST` were already added in Step 2.
- Created `backend/apps/core/tests/api/test_openapi_settings.py` (3 tests: 7 tags, canonical order, Request-suffixed components exist).
- Gates: 479/479 tests green, ruff clean, check-no-orm OK.

## 2026-05-08T19:50Z — Step 3: Backfill tags and CSV-format param on @extend_schema decorators

- Added `tags=["catalog"]` to 7 decorators in `apps/catalog/apis.py`.
- Added `tags=["procurement"]` to 6 decorators in `apps/procurement/apis.py`.
- Added `tags=["inventory"]` to 9 decorators in `apps/inventory/apis.py`; replaced free-form `format` params with `CSV_FORMAT_PARAMETER` on `/movements` and `/batches/{batch_id}/recall-report`.
- Added `tags=["sales"]` to 8 decorators in `apps/sales/apis.py`.
- Added `tags=["financials"]` + `CSV_FORMAT_PARAMETER` to 2 decorators in `apps/financials/apis.py`.
- Added `tags=["auth"]` to 4 decorators and `tags=["meta"]` to 1 decorator in `apps/core/apis.py`.
- Added `from apps.core.openapi import CSV_FORMAT_PARAMETER` to inventory and financials apis.py.
- Created `backend/apps/core/tests/api/test_openapi_tags.py` (3 tests: every operation has exactly 1 tag, all tags in canonical 7-element set, 4 CSV endpoints declare format=csv enum).
- Gates: 476/476 tests green, ruff clean, check-no-orm OK.

## 2026-05-08T19:30Z — Step 2: ErrorResponse component + postprocessing hook

- Created `backend/apps/core/openapi.py` with `_ERROR_RESPONSE_SCHEMA`, `inject_error_response_component` hook, and `CSV_FORMAT_PARAMETER` constant.
- Wired `POSTPROCESSING_HOOKS` in `backend/settings/base.py` (includes drf_spectacular default enum hook + new hook).
- Added `SORT_OPERATION_PARAMETERS: True` and `COMPONENT_SPLIT_REQUEST: True` to `SPECTACULAR_SETTINGS`.
- Created `backend/apps/core/tests/unit/test_openapi_hook.py` (6 tests: inject, rewrite 400, rewrite 404, skip 200, idempotent, all 5 error statuses).
- Gates: 473/473 tests green, ruff clean, check-no-orm OK.

## 2026-05-08T19:10Z — Step 1: Register apps.sales and apps.financials in INSTALLED_APPS

- Added `"apps.sales"` and `"apps.financials"` to `INSTALLED_APPS` in `backend/settings/base.py`.
- Created `backend/apps/core/tests/api/test_installed_apps.py` (2 tests: get_app_config("sales") and get_app_config("financials")).
- Fixed 44 pre-existing ruff violations (E402/F401/F841) across 16 test files to clear the ruff gate.
- Gates: 467/467 tests green, ruff clean, check-no-orm OK.
