# Research Follow-through Implementation Plan

> Use superpowers:executing-plans inline and test-driven-development; one final independent review. The user approved the three fixes in conversation and explicitly requested implementation with Superpowers. No additional approval needed.

**Goal:** Attempt locality research early, retain concrete unfinished follow-ups, and stop for accurate reasons within the existing research budget.

**Architecture:** Extend the existing research round controller with a small persisted task list. Each proposed follow-up identifies a Firecrawl search query or page URL; actual tool results mark it checked or unavailable. Missing locality context seeds the first task. Pending tasks take precedence over early `done`/stagnation exits, while the existing hard deadline and actual tool-limit failures still stop research.

**Tech Stack:** Python 3.8, existing Codex app-server/Firecrawl transport, unittest mocks of external calls.

**Spec:** User-approved three-point plan immediately before “great go ahead using superpowers”: early amenities search; retain follow-ups until checked/unavailable; distinguish exhausted evidence from Firecrawl limits while keeping the five-minute target and ten-minute maximum.

## Global constraints

- Work in the existing authorised workspace; preserve prior uncommitted changes. Baseline: `/tmp/property-research-followups-baseline-2026-11-01`.
- No changes to PropertyData, valuation/fee calculations, report/dashboard layouts, authentication, photos or house-number research. AI-edit research access is a separate task.
- Keep 300-second target, 600-second maximum and existing per-round timeout. No second research loop, new dependency, automatic live generation, paid API call or server takeover.
- Save task states and stop reasons in the existing research audit. Preserve accepted evidence and inputs. Tool-limit runs must not be cached as successful exhausted research.

## Tasks

- [x] Write regression tests reproducing skipped amenities, dropped newer-schedule follow-ups, premature stagnation/done exits, duplicate actions, real quota errors and deadline handling. Run focused tests and observe failure.
- [x] Add `screening/research_tasks.py` for concrete task schema/identity, observed task outcomes and Firecrawl limit classification; wire it into `screening/codex_research.py`. Update only research-test fixtures where unrelated tests already assume locality work is complete.
- [x] Run focused and full Python/dashboard checks, verify original report calculations and saved-data hashes, update README, obtain final review and fix important findings with regression tests.

## Interfaces and implementation details

- `next_searches` becomes an array of `{tool, target, purpose}`: tool is `firecrawl_search` or `firecrawl_scrape`; target is the exact query or URL. Reject malformed proposals. Deduplicate by tool and normalized target, independent of wording. Preserve checked/unavailable tasks in the audit rather than requeue them when suggested again.
- `audit.follow_ups` records ID, tool, target, purpose, state, reason and round when attempted. `pending_follow_ups` and the first `priority_follow_up` are sent each round. New proposals cannot erase older pending entries. A successful matching call marks a task checked; failed calls mark it unavailable with a reason. Never treat task completion as proof of a property fact: existing evidence validation remains authoritative.
- Seed a locality query for the supplied postcode/address only when locality evidence is missing. Require this task first, read relevant pages and return the existing `property.nearby_places` finding. An accepted locality finding can also close the task when sourced directly without a search.
- Continue while concrete pending tasks remain, even after two rounds without newly accepted facts or a premature `done`. Otherwise retain the existing no-progress/exhausted-lead stopping rules. Hard timeouts retain pending tasks and are recorded as partial failure.
- Actual failed Firecrawl calls indicating quota/rate/credit limits end the run after processing that round's usable results; save `status=limited` and a clear reason. Do not infer limits from successful page text or generic `done` summaries. Successful cached/checkpoint evidence remains available; account setup is deferred.

## Review focus

- A follow-up must not vanish because its original gap was already filled or a later response omits it.
- Successful lookup with no new accepted facts must allow remaining concrete tasks to run; repeated identical proposals must not create an endless queue.
- A quota message inside ordinary webpage text must not stop research; real failed quota/tool calls must remain distinct from exhausted sources.
- Reused/cache evidence and missing/malformed outputs must not skip new required tasks or erase previous accepted facts.
- Time limits must still terminate unfinished work, preserving audit state; no cached success for interrupted or quota-limited runs.

## Verification ledger

- Pre-flight: task schema and controller share concrete actions; all new prompt fields are internal to research and do not enter report schemas. Approved scope is three controller fixes, not the separate editor feature.
- Baseline snapshot created; prior saved reports and source files will be compared against it.
- Tasks 1–2: regression run reproduced five failures and two errors before implementation (`/tmp/property-followups-red.log`); all nine focused regressions pass afterward (`/tmp/property-followups-focused.log`). Existing unrelated research/fee tests now explicitly seed locality context, so they continue to isolate their original behavior.
- Verification: `python3 -m unittest discover -s tests -q` — 98 tests passed; `node --test tests/review_photos.test.cjs` passed; changed Python modules compile; `git diff --check` clean.
- Preservation: compared 57 baseline hashes; only `screening/codex_research.py` changed among those paths. Saved records/PDFs, dashboard, PropertyData integration, cost/valuation calculations and report templates are unchanged. README explains the revised follow-through and stop statuses. External research has not been run.
- Final independent review: `research_followthrough_review` (GPT-6 Astra, high) found two important issues, no critical/minor findings. Both addressed in one fix pass:
  - Final: fixed loss of tasks on retry — `test_retry_retains_pending_tasks_and_history_after_accepting_a_fact` RED→GREEN; continuity uses supplied request and provider snapshot, so newly accepted facts do not invalidate pending work. Changed requests discard old tasks; quota-blocked actions are retried on a later attempt.
  - Final: fixed missed structured quota failures — `test_quota_envelopes_are_limited_even_without_object_data_or_text_content` RED→GREEN across null/list data, structured-only errors and long messages. Classification reads the full error before audit text truncation. Final focused suite: 13/13; full suite: 102/102.
- Final verification: full Python suite 102 passed in 24.310s (`/tmp/property-followups-final-suite.log`); Node dashboard suite passed; Python compile and whitespace checks passed. Repeated protected-file/hash comparison passed. Latest saved report's entire recalculated analysis equals the stored analysis, not only selected metrics.
- Final: Ruling: live Firecrawl compatibility/authentication remains unverified — review and tests are offline and account setup is explicitly deferred; the next generation must verify available quota and live results.
- Final: Ruling: existing general malformed model-output handling remains outside this change — it predates the controller fixes; this work does not guarantee recovery from arbitrary invalid model output.
- Final: Ruling: AI editor research, photos, house numbers, calculations and presentation remain unchanged — explicit approved scope; those deferred capabilities are not delivered here.
- Delivery: applied in the existing local workspace as requested; no commit, branch switch, merge, push, server restart or report regeneration performed. Baseline snapshot retained to protect the user's earlier uncommitted work.
