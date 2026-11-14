# Public Commercial Form Implementation Plan

> Execute inline using superpowers:executing-plans; the user has explicitly authorized the concrete transfer and removal.

**Goal:** Put the approved form in the public website and retire the temporary local intake.

**Architecture:** Preserve the public email transport and existing backend. Transfer the form body and the `update()` / `inputs()` functions; restore the dashboard URL.

**Tech Stack:** Embedded HTML/CSS/JavaScript, Flask, unittest, Chrome/CDP.

**Spec:** `docs/superpowers/specs/2026-11-13-public-commercial-form-design.md`.

## Constraints and review focus

Keep prior uncommitted work, report design, terms/privacy, email destination, draft key and return behavior. No deployment or messages. Work in the existing user-tested checkout; no commits. Watch stale residential/commercial values, annual/monthly conversion, unknown lease terms, export/email equality and removed local references.

## Task 1: Transfer and verify public intake

- [x] Extend `tests/brief_delivery_browser.mjs` and `.py` to exercise commercial delivery and real imports, with annual rent £24,000 normalizing to £2,000 monthly.
- [x] Update `tests/test_web_entrypoints.py` for the restored external link and retired local route. Observe expected failures.
- [x] Transfer the approved form body plus conditional controls and payload serialization into `web/public/index.html`. Keep its native email transport.
- [x] Remove the local route, dedicated files and obsolete harness; restore the original dashboard header URL.
- [x] Update README to describe the public commercial form.
- [x] Run browser checks, inspect desktop/tablet/mobile screenshots, run Python and Node suites and check the diff.
- [x] Obtain a scoped independent review and address material findings.

## Progress

Baseline of all touched existing files: `/tmp/lacewing-public-commercial-before`.
User instruction supplies the selected approach and authorization; no further approval gate is needed.


## Completion evidence

- Entrypoint tests first failed for the temporary link/route, then passed after restoration/removal.
- Browser test first failed because the public form lacked asset class. After transfer, residential, area and all three commercial payloads matched their JSON downloads and imported into temporary dashboard records.
- Independent review identified a public-delivery gap: unlike the retired local page, email transport did not expose backend rejection of partial rent-review/reletting pairs or incomplete positive VAT recovery. Added native validity checks; the new browser regression first failed on a review-month-only submission, then passed for all seven rejected combinations, zero values, clearing and enquiry-type changes. Scoped re-review found no remaining material issues.
- Final Python suite: 170 tests passed in 121.016 seconds. An earlier quiet run exited with SIGTERM and was not counted as verification. Node dashboard tests: 2 passed. Final public browser run passed, including desktop/tablet/mobile screenshots and file preview, with no outgoing email or paid calls.
- Dashboard HTML matches the original Git HEAD byte for byte. Public styles, surrounding content, native transport and confirmation logic match the scoped baseline. Terms/privacy links retain their public relative anchors.
- Taste inspection ran against the public contact page at 1440/768/390; all six screenshots and the three commercial screenshots were visually reviewed. The inspector reported two existing site-level rule failures (`tiny-text` for unchanged branding and a `no-title` false positive on the multipage shell) and six style warnings. These were not restyled: the public shell and typography are outside the approved form transfer. Changed form controls fit all three widths without horizontal overflow. No new direction, imagery or motion was introduced.
- Final diff whitespace check passed. No deployment, commits or customer-record changes. Upload the updated public index through the existing website deployment process when ready.
