# AI Editor Firecrawl Implementation Plan

> Use superpowers:executing-plans inline with test-driven-development and one final independent review. The user explicitly requested this previously deferred upgrade; implement in the existing workspace without another approval round.

**Goal:** Let Ask AI research the requested report edit using Firecrawl, validate and cite new evidence, and recalculate dependent results through the existing pipeline.

**Architecture:** Enable the existing isolated Firecrawl transport for the edit-planning turn. Add a structured research result alongside existing edit operations. Apply findings with the main report's quote/identity/estimate validators to the staged revision before recalculation and writing. Plain wording/style edits need no searches. One targeted turn retains the existing 180-second timeout; no automatic full-report research loop.

**Tech Stack:** Existing Python 3.8 Flask, Codex app-server, Firecrawl search/scrape, unittest.

**Spec:** User: “great, now fix the AI-editor please by adding firecrawl”, with prior requirement that the editor can research supported report topics beyond photos. Preserve the working dashboard, report layouts, PropertyData and deterministic calculation rules. Photos/house-number automation remains deferred.

## Constraints and approach

- Reuse the existing transport and evidence validators; no new MCP, dependencies, credentials, paid PropertyData call or automatic live edit.
- Enabling tools alone is insufficient: new evidence must reach the source register, analysis and commentary. Avoid a second general research loop that would revisit unrelated topics.
- Explicit input corrections remain analyst-supplied. Web facts/estimates use the evidence path and never silently replace supplied values. Prompt researches only the current request.
- Keep old findings, provider raw data, presentation, photos and artifacts. Save the complete revision only after validation and PDF generation succeed; failures preserve the prior report.
- Retain the 180-second planning turn timeout. Live quality/quota must be tested separately by the user.
- Baseline: `/tmp/property-editor-firecrawl-baseline-2026-11-01`; preserve all earlier uncommitted work. No commit or branch operation requested.

## Tasks

- [x] Add failing tests for Firecrawl-enabled planning, redacted contacts, cited amenities/cost updates, rejection of fabricated citations/search-only evidence, retention of unrelated facts/provider data, plain edits without research, and transactional route success/failure.
- [x] Add `screening/edit_research.py` for schema/context and validated evidence application; extend `screening/narrative.py:plan_revision` to return research results from the enabled transport; integrate in `app.py` before enrichment/recalculation and save its audit in edit history. Update the existing edit test's tuple and README.
- [x] Run focused/full Python tests, dashboard checks, compile/whitespace checks and baseline protection checks; obtain independent review and address important findings with failing regressions first.

## Review focus

- New external evidence must not become a supposedly supplied correction or bypass identity/quote validation.
- Rejected/failed research must preserve the previous report and must not claim a successful factual update.
- Edited inputs and researched facts must be applied before analysis, with current source IDs available to the writer and companion PDF.
- Existing provider facts, accepted findings, layouts and photos must survive a focused edit; normal formatting edits must not force broad research.
- Mixed identity/input/research requests and supported cost/valuation edits must keep provenance and stale-evidence handling correct.

## Verification ledger

- Design choice: one targeted editor turn with the existing validators; no general generation rerun. Existing local workspace and snapshot retained.
- RED: initial focused suite reproduced missing integration (five failures/one error); route regression showed research edits rejected by the old schema. Logs: `/tmp/property-editor-red.log`, `/tmp/property-editor-route-red.log`.
- GREEN: 11 focused tests pass (`/tmp/property-editor-green.log`), including complete Flask edit/PDF path and rollback after writer failure. Corrected two test assumptions after inspecting the existing code: amenities are read directly by the PDF template, and presentation settings include empty text/style defaults.
- Protected files: 58 baseline hashes checked; only `screening/narrative.py` differs among baseline screening/web/data paths. Saved reports, calculation rules, PropertyData and report templates unchanged. Node dashboard checks, compilation and whitespace checks pass. No external research call performed.
- Initial full suite: 113 tests passed in 51.839s (`/tmp/property-editor-full.log`).
- Final independent review (`editor_firecrawl_review`, GPT-6 Astra high): two important findings, no critical/minor findings. Both reproduced by failing tests (`/tmp/property-editor-review-red.log`) and addressed in one fix pass:
  - Invalidate stale provider valuation/build-cost and size-filtered outputs after a researched effective property change, before accepting new estimates. The researched-area regression now passes while unrelated provider data and new findings survive.
  - Verify proposed supplied-input corrections with a separate tools-disabled extraction that sees only the request and saved inputs/field choices. Its canonical changes must match; no new research response or proposed changes enter that extraction. The invented-fee bypass is rejected, while a legitimate mixed explicit fee correction/research request passes.
- Final: Ruling: input corrections add one tools-disabled check capped at 60 seconds — the tool-enabled planner must not turn a researched guess into a supplied value with precedence; this adds latency only when input changes are proposed and may reject ambiguous corrections.
- Final: Ruling: existing quote validators' semantic limits remain unchanged — the task reuses generation's evidence rules; automated checks cannot replace analyst review of whether a quotation supports a claim.
- Final: Ruling: live Firecrawl availability/latency/quality and photos/house-number automation remain untested/deferred — no real saved report or network research was run; the next live edit is still needed.
- Final GREEN: both important review findings RED→GREEN; 14 focused tests pass. Full suite: 116/116 passed in 48.105s (`/tmp/property-editor-final.log`); Node dashboard suite passed; changed Python files compile and `git diff --check` is clean. Repeated 58 baseline hashes confirm saved data/PDFs, dashboard, report templates, provider integration and financial calculations are unchanged. The latest saved report's full analysis recalculates identically.
- Delivery: local changes ready for the user's server restart and first live edit. No commits, branch operations, server takeover, external research call or saved report regeneration. Baseline snapshot retained with the user's earlier work.
