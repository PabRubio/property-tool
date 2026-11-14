# Commercial Screening Implementation Plan

> **For agentic workers:** Use superpowers:subagent-driven-development or superpowers:executing-plans to implement this plan task by task. Track results here.

**Goal:** Add single-unit commercial rental screening and a temporary direct local intake while preserving residential behavior.

**Architecture:** Extend the existing schema with a residential default and commercial branches. Reuse the financial engine and report layout, replacing residential evidence, lease assumptions and tax where necessary.

**Tech Stack:** Python 3.9+, Flask, plain HTML/CSS/JS, ReportLab, existing Codex/Firecrawl integration.

**Spec:** `docs/superpowers/specs/2026-11-12-commercial-screening-design.md`

## Global Constraints

- Keep dashboard appearance and `Client property form →` text.
- Keep public `web/public/index.html` and Un-static behavior unchanged.
- Support England, single-unit retail/offices/industrial commercial rentals only.
- Preserve residential validation, modelling and ten-page report appearance.
- Use existing dependencies and local security protections.
- No more than 10 live PropertyData calls; coordinator alone runs these.
- Work in current authorized workspace and leave changes reviewable, without publishing or altering customer records.

## Review Focus

Annual/weekly/monthly unit confusion; stale residential evidence on class changes; break/expiry before review; refundable VAT counted twice; incomplete financial inputs rendered as confident returns.

### Task 1: Schema and model contract

Files: `screening/schema.py`, new `screening/commercial.py`, `tests/test_commercial.py`.

Interfaces: `is_commercial(inputs)` checks `property.asset_class`; spec defines field names. Legacy default is residential. `commercial.assumptions(inputs, a, basis)` sets effective commercial assumptions; calculation helpers are consumed by finance.

- [x] Write schema tests for legacy inputs, each commercial subtype, annual normalization, wrong area basis, unsupported scope and conflicting rents; run red.
- [x] Implement typed optional fields and conditional requirements, preserving explicit zero and supplied provenance; run green.

### Task 2: Temporary local form

Files: new `web/brief.html`, `web/assets/local-intake.js`, optional local form stylesheet, `web/index.html`; route added in `app.py`; `tests/test_web_entrypoints.py`, new browser test.

Interfaces: GET `/brief`, GET `/api/config`, POST `/api/records` with `X-Local-Token`. Input fields follow Task 1.

- [x] Write endpoint/submission tests, confirm old link assertion fails for new contract.
- [x] Clone contact form, add conditional commercial controls, preserve residential and area flows, draft recovery and JSON export. Use standalone local transport. Switch only header href.
- [x] Verify desktop/mobile and direct submission; preserve public email tests.

### Task 3: Commercial evidence and research

Files: `screening/providers.py`, `screening/evidence.py`, `screening/comparisons.py`, `screening/market_evidence.py`, `screening/research.py`, `screening/codex_research.py`, `screening/estimates.py`, provider tests.

Interfaces: keep `gather`, `valuation`, and comparison-summary APIs; commercial source IDs remain explicit. No residential growth or rate context in commercial records.

- [x] Mock documented commercial responses and assert only eligible commercial requests occur, including unknown floor area/basis and provider failure cases.
- [x] Adapt request routing, normalization, compatible comparable matching and quoted research instructions.
- [x] Verify source provenance, no market-average subject rent fallback and evidence invalidation.

### Task 4: Cash flow and tax

Files: `screening/finance.py`, `screening/modelling.py`, `screening/costs.py`, `screening/partial_analysis.py`, `screening/decision.py`, `screening/tax_notes.py`, `config/tax_rules.json`, financial tests.

Interfaces: shared `analyse`, `project`, `stamp_duty`; effective assumptions carry `_asset_class` and commercial fields. Existing output keys remain; add VAT and business-rate rows/metrics without breaking residential exports.

- [x] Test £150k/£250k SDLT boundaries, company/nonresident commercial treatment and VAT-inclusive consideration.
- [x] Test full upfront VAT and one recovery event, lease break/expiry, rent-free months, review step, explicit reletting, vacancy rates and incomplete input handling.
- [x] Implement commercial defaults and cash schedules; update purchase ceilings and partial results with identical logic.
- [x] Run targeted and residential financial regressions.

### Task 5: Reports and pipeline integration

Files: report renderers, `screening/narrative.py`, `screening/preflight.py`, `app.py`, report tests.

Interfaces: consume existing model dictionaries plus commercial property/assumption fields. Maintain ten pages and existing visual design.

- [x] Add complete/incomplete commercial PDF tests, text checks excluding residential claims and lease/VAT content checks.
- [x] Branch report rows, market sections, tax/narrative prompts and edit enums. Update invalidation and cache versions for changed inputs.
- [x] Generate and inspect commercial PDF and verify residential report regressions.

### Task 6: Verification and documentation

Files: `README.md`, test artifacts under `/tmp`, this plan progress.

- [x] Run Python and Node regression suites and browser checks.
- [x] Run bounded live commercial PropertyData checks and a real Codex report in temporary records, count requests.
- [x] Obtain independent review, fix substantive issues, and rerun affected checks.
- [x] Document scope, temporary-link reversal, commercial assumptions and test results.

## Progress

- Baseline: 137 Python tests passed (52.7 seconds).
- User approved implementation and up to 10 live PropertyData calls; live calls used: 10 (budget exhausted, no further requests).
- Execution decision: proceed from the accepted recommendation; avoid repeating approval questions. Existing clean workspace remains the delivery location.

- Implementation complete: additive schema, isolated commercial evidence, lease/VAT/SDLT calculations, temporary direct intake, and ten-page commercial reports with companions and exports. Residential remains the default.
- Final Python regression run: 170 tests passed in 57.169 seconds. Report tests rerun after the final label clarification: 8 passed. Node import/photo checks: 2 passed.
- Local browser checks passed for residential, area-only, retail, offices and industrial submissions, unknown terms, explicit lease/VAT inputs, normalization, export and recovery. Existing public email-form browser checks also passed. Desktop/tablet/mobile screenshots inspected; taste inspector reported no failures.
- Independent review identified four substantive issues: incompatible selected rent comparisons, per-area quote normalization, operating-cost table schedule consistency, and unsupported break-even rent. Each received a failing regression test before the fix and passed afterward. Growth/lease labels were also clarified.
- Live PropertyData validation: three successful office calls at EC2A 4NE, one successful retail context call at that postcode, and six rejected requests for invalid sample postcodes. Industrial live coverage was not established; mocked industrial endpoint/report coverage passed. Failures count against the ten-call ceiling.
- A real Codex narrative generated successfully from saved live office evidence, producing the ten-page report, one-page source/internal companions, cash-flow CSV and calculation images. This exercised narrative generation, not a fresh end-to-end Firecrawl research run. Hypothetical subject data and generated artifacts remain under `/tmp/lacewing-commercial-live`; no customer records were changed.
- README documents commercial scope, modelling assumptions, direct form checks and the one-line navigation reversal. Public form files are unchanged. Work remains uncommitted in the authorized workspace; nothing was published.
