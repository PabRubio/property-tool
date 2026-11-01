# Codex dashboard implementation plan

> **For agentic workers:** Use superpowers:executing-plans. Implement and verify each stage before continuing.

**Goal:** Replace the dashboard's Claude calls with subscription-authenticated Codex app-server, using only Firecrawl for iterative research and supported price/rent estimates.

**Architecture:** Preserve the existing Python pipeline and JSON contracts. Add a small app-server transport and a Codex research adapter. Feed validated evidence and labelled estimates into existing calculations and report fields.

**Tech Stack:** Python standard library, existing Flask/reportlab application, installed Codex CLI, hosted Firecrawl MCP.

**Spec:** User-approved four-step plan in this conversation, including the subsequent approval to implement.

## Global constraints

- Do not change PropertyData integration (`screening/providers.py`).
- Do not change dashboard assets, report layout, sources layout, review layout, or photo handling.
- Preserve ten report pages and two one-page companions.
- Dashboard runtime loads no skills, plugins, other MCPs, or browser tools.
- Research targets five minutes and has a configurable ten-minute ceiling; stop on sufficient evidence or repeated dead ends.
- Never overwrite supplied inputs with research or estimates. Never invent property identity.
- Preserve previous artifacts on failure. No automatic paid-provider fallback.
- User requested a small, direct implementation. Work in the clean existing checkout, keep changes reviewable and uncommitted, and do not introduce a separate deployment or checkout workflow.

## Review focus

- Authentication failure or quota exhaustion preserves the previous report.
- Personal Codex configuration cannot introduce unrelated tools or instructions.
- Research timeout preserves validated findings and stops the child process.
- Citations and estimates remain tied to observed evidence, correct units, and the current property.
- Existing record edits invalidate affected research estimates and retain layout/pagination.

## Task 1: Codex transport and provider routing

Files: new `screening/codex.py`, provider routing in `screening/narrative.py`, `screening/preflight.py`, `screening/incomplete_report.py`, `app.py`; tests in `tests/test_codex.py`.

Interface: `run(system, packet, schema, model=None, research=False, timeout=180, progress=None)` returns structured output and observed tool evidence. Existing `call_model` continues returning the schema object.

- [x] Add failing tests for real JSON-RPC stream handling, failed/incomplete turns, timeout cleanup, runtime isolation, and default Codex routing without API keys.
- [x] Implement the transport and route all existing AI tasks through the same provider interface.
- [x] Run focused tests and the existing regression suite before research changes.

## Task 2: Firecrawl research and supported estimates

Files: new `screening/codex_research.py`; Codex branch in `screening/research.py`; estimate consumption in `screening/finance.py` and invalidation in `screening/evidence.py`.

Interface: the existing `research(record, provider, progress, refresh)` entry point continues mutating only evidence. Store estimates separately from PropertyData results and supplied inputs.

- [x] Add failing tests for source-backed findings, iterative follow-up, timeout/dead-end handling, rejected invented citations, and estimates filling blank price/rent without replacing supplied values.
- [x] Implement bounded research rounds with Firecrawl search/scrape, preserving observed sources and progress between rounds.
- [x] Label supported estimates and their uncertainty in existing basis/commentary fields; preserve calculation formulas.
- [x] Run focused tests, including invalidation after property edits.

## Task 3: Integration and layout verification

Files: configuration example and README; focused regression tests.

- [x] Document local Codex sign-in, model choice, Firecrawl, and research time settings.
- [x] Run all Python tests and dashboard photo tests.
- [x] Regenerate a copy of the latest record and compare report/companion page counts and layout against the unchanged renderer; leave saved user files untouched.
- [x] Exercise live app-server authentication and Firecrawl without calling PropertyData.
- [x] Obtain one fresh code review and address material findings.

## Progress

- Baseline: 52 Python tests passed in 17.792 seconds.
- Runtime schema checked against installed Codex CLI 0.165.0 and official configuration schema.
- Task 1: complete. Seven adapter tests passed; full suite 59 passed in 18.200 seconds. Live ChatGPT-authenticated app-server returned structured output.
- Task 2: complete. Eight research/estimate tests passed after an additional wrong-property rejection check. Prior full regression: 66 passed in 18.473 seconds.
- Shared interface: transport returns output/tool_calls/model; research consumes this shape and stores source evidence separately. Estimate validation lives in `screening/estimates.py` to avoid coupling financial calculations to the app-server transport.
- Existing research identity bug found by new tests: a full matching street address with postcode supplied separately was rejected. Exact normalized address/postcode equality now qualifies; unrelated addresses remain rejected.
- Live Firecrawl smoke: successful search followed by scrape of Durham Council's council-tax page; only Firecrawl calls observed.
- Task 3: complete. Final Python suite: 73 tests passed in 17.396 seconds. Dashboard photo test passed; `git diff --check` clean.
- Live research on a temporary copy completed two rounds in 157.7 seconds. Actual returned passages exposed Markdown/escaped-newline/elided-quote handling; regression fixes preserve supported comparisons while retaining unknown identities and units. Replaying observed tool results accepted three comparison rows. Codex commentary then rendered ten report pages and two one-page companions.
- Original report comparison: all twelve pages rendered identically, pixel for pixel, when the original generation date and original uploaded cover photo were supplied. All eleven tracked PropertyData, renderer, photo and dashboard files remain byte-identical to HEAD. Original saved record/artifacts were left untouched.
- Live estimate check on a temporary copy with blank price/rent accepted a supported sale-value scenario. Codex withheld a rent estimate because the supplied candidates' whole-property basis was unconfirmed; this limitation remains visible. Offline tests verify accepted monthly-house estimates and reject weekly/room units.
- Final fresh review identified four Important issues: substring house-number matching, invented rental units, changed comparison facts retaining estimates, and stale estimates entering the writer packet. Each was reproduced in a failing regression and fixed; all tests now pass.
- Review isolation concern: explicitly disabled JS REPL, memory tool and inherited notification commands. A final live run with these settings successfully used Firecrawl search. No personal configuration files were changed.
- Ruling: no extra review/deployment/merge workflow is needed. Changes remain uncommitted in the user's checkout, as requested by this plan; restarting the local dashboard server loads them.
- User follow-up: removed the direct OpenAI, Claude and Gemini API clients, model discovery, native-search adapters, provider-selection setting and local/example key settings. Codex is now the only AI provider. Historical report provenance and defensive secret redaction remain intact; PropertyData is unchanged.
- Follow-up verification: 75 Python tests passed in 19.371 seconds; dashboard photo test passed; fresh focused review found no actionable issues or executable legacy API paths. All updated model-call signatures were checked. Existing report data and layout files remain unchanged.
