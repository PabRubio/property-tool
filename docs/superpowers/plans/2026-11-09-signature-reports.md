# Signature reports implementation plan

> **For agentic workers:** Use superpowers:executing-plans to implement and verify these tasks.

**Goal:** Generate future property reports in the approved Signature Edition and refresh all three current saved reports without changing their analysis.

**Architecture:** Keep the existing ReportLab renderer, financial model, editor and transactional artifact publication. Add reusable measured print compositions and vector charts; arrange the existing page content to match the approved PDF. Refresh saved PDFs through a separate local command with snapshots and unchanged analysis timestamps.

**Tech Stack:** Python, ReportLab, Pillow, existing Poppler verification tools. No new runtime dependencies.

**Spec:** The Signature Edition, approved by the user on 2026-11-09 and implemented in `screening/report_layout.py` and `screening/report_visuals.py`. Cream #f6f1e6, green #012c21, gold #d9ad5f; compact 42-point masthead, Inter titles/body, Cormorant section headings, split cover, ten A4 pages, nine supplemental charts when data is available. The exploratory design PDFs were removed after selection.

## Global constraints

- Preserve all calculations, evidence, original page subjects, links and narrative wording.
- Keep ten pages; measure content and reject overflow without truncating it.
- Preserve explicit report editor settings, review/demo labels and existing draft/final photo behavior.
- Retain original design PDFs and historical reports.
- Work in the current checkout to update the user's running local project; do not stage, commit or publish.

## Review focus

- Missing financial inputs: explicit unavailable values, never invented zero-valued charts.
- Positive, negative and zero scenarios: truthful baselines, labels and no division by zero.
- Long commentary and uploaded photos: measured layout, preserved links and no clipped content.
- Saved report refresh: no recalculation, re-research, revision change, approval loss or changed evidence date.
- Failed refresh: previous record/artifacts remain usable; reruns are idempotent.

## Task 1 — Standard renderer

Files: `screening/report_layout.py`, new `screening/report_visuals.py`, `tests/test_signature_reports.py`.

- [x] Add failing output checks for Signature metadata, compact masthead, split cover, vector cash-flow data and chart coverage.
- [x] Implement responsive tables, measured columns/panels, cover and vector charts using saved values.
- [x] Rearrange each existing page within its existing subject; preserve text and citation order.
- [x] Run focused report/editor tests and render Bromley for comparison against the approved PDF.

## Task 2 — Saved report refresh

Files: new `screening/restyle_reports.py`, date plumbing in report/comparison/reference rendering, `tests/test_signature_reports.py`.

- [x] Add tests for unchanged record data/revision/approval, preserved original date, snapshots, failure behavior and repeat execution.
- [x] Implement `restyle_report(store, record_id)` and CLI `python3 -m screening.restyle_reports --root data/records`.
- [x] Publish only a new main PDF and its presentation metadata; keep companion exports and all historical files.

## Task 3 — Verify and apply

- [x] Run complete Python and JavaScript suites; inspect every Bromley page and representative Durham pages.
- [x] Obtain one independent final code review and resolve substantive findings.
- [x] Refresh the three saved current reports; compare original and new text, values, links and protected JSON fields.
- [x] Document the command and the new default design in README; report exact verification results and paths.

## Evidence

- Baseline: 131 Python tests passed before changes.
- Regression checks demonstrated missing Signature metadata and missing refresh behavior before implementation, then passed.
- Independent final review identified editable heading indexing, wrapped page-title overlap and unmeasured chart text. All were fixed; regression tests reproduce the latter two failures and verify all three cases. The accent override now affects chart accents.
- Full suite after review fixes: 137 Python tests passed; both JavaScript tests passed. Final styling pass verification is recorded below.
- All three candidate reports rendered at ten A4 pages. Financial-token comparison found no original value missing from any page; every original URL survived. All 30 pages were visually inspected, including full-size Bromley pages.
- Historical Durham output uses the current pre-existing renderer's “Analyst” wording and saved cost-scope descriptions; the saved JSON and the financial values remain unchanged.
- Work stayed in the existing checkout; no branch, staging, commit or publication was needed. The approved PDF supplied the design and the user authorized implementation and local refresh.

- Final verification: all 137 Python tests passed after the final styling changes; 2 JavaScript tests passed; `git diff --check` clean.
- Applied the refresh to all 3 current saved reports. Their PDFs have ten A4 pages and exactly match the reviewed text; inputs, evidence, analysis, narrative, revision, approval, assessment timestamps, source registers and prior files were verified unchanged. Snapshots were verified against the complete pre-refresh records. A second CLI run made zero updates.
- No deferred review findings. Layout adaptation is bounded and explicit font-scale overrides remain exact; excessive content still fails before publication.
