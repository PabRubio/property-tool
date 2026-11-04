# Un-static brief delivery implementation plan

**Goal:** Deliver the existing investor brief as JSON text through the user's account-free Un-static endpoint, preserving the form and local dashboard workflow.

**Spec:** The user supplied `https://forms.un-static.com/forms/ac1ba609175f688c47e9908a6e4d9060d24ecf30` and confirmed that JSON inside Un-static's notification email is acceptable. Submit only the JSON contents; no attachment or extra contact/message fields. The provider controls the notification subject and template.

**Architecture:** Keep the public website self-contained. Use a native URL-encoded POST with one `message` field containing the same version-2 JSON as the export button. Un-static handles CAPTCHA and delivery. Its configured success destination is `https://lacewinganalytics.co.uk/?submitted=1#contact`; show the existing success panel only when this tab has a pending Un-static submission. Keep the dashboard's existing file import.

**Scope:** Work in the current workspace, preserving earlier uncommitted work. Keep all design, visible copy, legal text and report content unchanged. No account creation, publication, live email submission, worktree or commit is needed. The user will test actual delivery after registration/activation.

**Files:** `web/assets/intake.js`, the embedded equivalent and form action in `web/public/index.html`, `README.md`, and the existing browser tests renamed to `tests/brief_delivery_browser.py` / `.mjs`.

## Task: Replace delivery and verify the existing workflow

- [x] Inspect the current submission, export/import and provider documentation.
- [x] Adapt the browser tests for one JSON text field, no attachment, the supplied endpoint and fixed success return; verify they fail before implementation.
- [x] Replace transport and return handling. Retain validation, duplicate protection, draft restoration, Back/retry and JSON download.
- [x] Verify property/area briefs and special characters against downloaded JSON and the real local import API using temporary records.
- [x] Check that bare/reused success URLs and cancelled submissions do not show success or clear drafts. Check storage restrictions, preparation failures and local-file preview.
- [x] Update setup/testing instructions and run relevant browser, Node and Python checks.
- [x] Review the changes and verify the landing page's remaining markup/styles and legal text match the baseline.

**Return limitations:** A static callback is a UI signal, not proof of email delivery. Consume the pending flag and URL marker once. Clear pending state on Back/ordinary page loads to avoid a later unrelated callback being mistaken for success. If session storage is blocked, still submit the brief but conservatively leave the form visible on return. Local testing of the return needs Un-static's success destination temporarily set to the matching localhost origin; restore the live URL afterwards.

**References:** https://un-static.com/for-ai/, https://un-static.com/feature-comparison/ and https://forms.un-static.com/register-form (checked 2026-11-04).

**Verification:** Browser checks failed before implementation, then passed with the single JSON field and return handling. Both outgoing brief types imported through the real dashboard API using temporary records. All 130 Python tests and both Node suites passed. JavaScript syntax and `git diff --check` passed. Baseline comparison confirms the public HTML changed only in its form action/encoding and embedded intake script. An independent read-only review found no Critical, Important or Minor issues.

**Remaining live acceptance:** Endpoint activation, provider-side Success Destination, CAPTCHA, inbox delivery and JSON preservation within the provider's actual email remain unverified. No live submission/email was sent. Follow the README's real submission and emailed-JSON import check. Provider subject/headings/footer were explicitly accepted as provider-controlled; earlier unrelated dashboard/report work was outside this review.
