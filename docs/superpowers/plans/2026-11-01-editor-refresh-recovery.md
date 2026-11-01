# Update PDF refresh recovery

User requested removal of the recurring refresh-before-saving interruption, then requested Git commands to commit all session changes. Implement the already-specified behavior directly with Superpowers debugging/TDD and final review; no approval or actual commit required.

Root causes verified in code: restarting Flask replaces the local CSRF token, but the dashboard loads config only at startup; Update PDF submits its cached record revision while other actions can advance the saved revision. Both server guards reject before starting an edit.

Scope: frontend automatically renews a rejected token once; Update PDF fetches the latest record and retries exactly one known revision rejection. Keep the typed instruction, all backend security/concurrency checks, photo conflict protection, and no retries for ambiguous network failures. No server/PDF/research/calculation changes.

Baseline: `/tmp/property-editor-refresh-baseline-2026-11-01`. Changed `web/assets/review.js`, its existing Node test fixture/suite and README.

- [x] Reproduce the two stale-state failures plus bounded retries/running-job cases: six new tests fail before the change; six original dashboard tests pass.
- [x] Implement token renewal and current-revision edit submission. All 12 dashboard tests pass (`/tmp/property-refresh-green.log`).
- [x] Complete regression checks and independent review; provide commit commands, leave staging/commit to the user.

Review focus: retry only requests known to be rejected before mutation; bound token/revision retries; preserve pending input/photos; do not weaken security/concurrency protections.

No live request, server restart, saved report mutation, staging or commit performed.

Final independent review (`editor_refresh_review`, GPT-6 Astra high): ready; no critical/important findings. Reviewer independently reran the Node checks and confirmed bounded retries only for pre-mutation rejections, fresh token headers, retained inputs/photos and intact backend guards.

Final: minor (deferred): dedicated rejected-fetch regression test; the implementation propagates network failures without retry, verified by code review, but the current failure test covers an unrelated HTTP error.

Final: Ruling: review is scoped to this frontend change; unrelated earlier session changes and live browser/server-restart interaction were not re-reviewed. Server-restart and stale-revision cases are simulated by the real dashboard JS tests.

Verification: 12 dashboard tests passed; full Python suite 126/126 passed in 37.878s (`/tmp/property-refresh-python.log`); whitespace check clean. Confirmed `.env` and saved `data/records` are ignored by Git. Final response supplies staging/review/commit commands for all session code/docs; none executed by the agent.
