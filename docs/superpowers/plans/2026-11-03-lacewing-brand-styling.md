# Lacewing brand styling implementation plan

> **For agentic workers:** Use superpowers:executing-plans to implement this plan task by task.

**Goal:** Apply the landing page's colours, logo and typography to the existing form, dashboard and reports.

**Architecture:** Keep the current HTML structures, JavaScript behaviour, report stories and page geometry. Bundle the existing brand assets and fonts locally; use shared CSS tokens for the interface and a small branding module for PDF/raster rendering.

**Tech stack:** Plain HTML/CSS/JavaScript, Flask, ReportLab, Pillow, locally bundled TrueType fonts.

**Spec:** The user's request in this conversation: visual styling only; preserve all wording, buttons, layout, report contents and pagination. The supplied website, now `web/public/index.html`, is the visual reference.

## Constraints

- Preserve all existing form fields, labels, validation, export/import and dashboard actions, including the + immediately beside Client submissions.
- Preserve the report's ten pages, page order, table/chart dimensions, text, figures, sources and companion one-page documents.
- Use deep green #012c21, green #0b3a30, gold #d9ad5f, darker gold #8a6628, ivory #f6f1e6 and ink #14211d from the landing page.
- Use Cormorant Garamond for headings and Inter for text/numbers; retain legibility and existing text sizes where practical.
- Bundle fonts and their licences; no runtime font downloads.
- Use the supplied logo/mark, including the existing transparent variant embedded in the landing page; do not invent or redraw branding.
- Preserve the existing session's uncommitted import work and relocated website/logo files. Work in the current workspace; no unrelated commits or publishing.

## Review focus

- Font loading offline and in PDFs, including pounds, percentages, dashes and bold text.
- Same wording, fields, controls and DOM ordering before and after.
- Long report narratives/comparison tables still fit their original pages.
- Focus/error/disabled/status states remain legible in the brand palette.
- Existing report presentation overrides still work.

## Tasks

- [x] Capture baseline HTML/CSS and sample report output for comparison.
- [x] Bundle Inter and Cormorant Garamond with source/licence information and extract the existing transparent mark.
- [x] Apply brand tokens, fonts and logo to form/dashboard without changing geometry or wording.
- [x] Add shared report branding; use it in the main PDF, companion PDFs, charts and exported calculation images, retaining layout and copy.
- [x] Verify PDF embedding, text/page preservation and existing styling overrides; run the regression suites.
- [x] Inspect form/dashboard at desktop/tablet/mobile and sample PDF pages; fix only styling regressions.
- [x] Review the completed diff and document the branding assets and verification results.

## Progress

- Initial inspection: existing form/dashboard share `web/assets/style.css`; main PDF uses `report_layout.py`; source/internal PDFs share `single_page`; report fonts currently use built-in Helvetica.
- Ruling: the user's fixed design and layout take precedence over skill suggestions to generate new compositions or rewrite copy.

- Completed: bundled locally licensed font instances and extracted the landing page's existing transparent mark; web styling and PDF/raster branding applied without changing geometry, labels or controls.
- Verified: `python3 -m unittest discover -s tests -q` — 128 tests passed; `node --test tests/review_import.test.cjs tests/review_photos.test.cjs` — both suites passed; `git diff --check` clean.
- Verified: Chrome at 1280/768/390px — identical DOM text and controls, no horizontal overflow, local fonts/logo load. Corrected the temporary browser check to request the actual heading weight (600); no product change was needed.
- Verified: original/current sample PDFs contain identical normalized text on each page; page counts remain 10+1+1. Inspected form/dashboard screenshots and representative report/source pages.
- Verified: actual form JSON export imports through the adjacent +; invalid imports retain browser alerts without inline sidebar errors; mobile + gap remains 8px.
- Final review: fresh reviewer found no issues. Independent dense comparison and 80-sentence narrative checks remain within their original page bounds.
- Follow-up authorized by user: refresh the three existing generated report sets using saved content, preserve their original dates and evidence windows, compare all PDF text and CSV data before updating dashboard artifact references. Completed for all three report sets.

- Existing-report refresh: staged all exports using original report dates; two older reports required temporary rendering compatibility for their original cost explanations and source labels. These one-off adjustments did not change application code or saved inputs/narratives.
- Existing-report verification: all nine PDFs preserve normalized per-page text, 10+1+1 page counts and reference destinations; all three CSVs are byte-identical. Only artifact references changed in each record. Previous exports and original-record snapshots remain in each record folder/history. All nine download endpoints serve the refreshed PDFs.
