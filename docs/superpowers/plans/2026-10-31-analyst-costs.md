# Analyst cost estimates and consistent risks

> Execute inline using superpowers:executing-plans and test-driven-development. User approved the design in conversation, including an all-in purchase legal budget; no additional approval required.

**Goal:** Estimate purchase legal/survey fees, local management and property-appropriate maintenance, with explanations, while preserving the existing 10+1+1-page reports.

**Architecture:** Extend the existing bounded research checkpoint with separately validated cost estimates. Never modify client inputs or PropertyData. Supplied costs win; missing research retains disclosed fallbacks. Calculate all financial effects in Python. Keep the report writer's five risk topics consistent, and show Analyst instead of Codex in all PDF text.

**Spec:** Approved conversation: legal fees include VAT and routine searches/disbursements, excluding separately calculated SDLT; legal/survey fallbacks remain £2,000/£600. Survey choice reflects property needs. Management reflects comparable local service scope and VAT. Maintenance selects percentage of rent for flats or value for older/freehold houses and explains age/type/condition and exclusions. No layout redesign, house-number work or automatic photos.

## Implementation decisions

- Cost evidence is separate from price/rent scenarios, so new fee citations cannot invalidate a valuation. Fee/management estimates require a quote from an actually read source. Maintenance may be a clearly labelled allowance based on supplied facts, without claiming a survey.
- Preserve explicit input overrides. Fallback management keeps the existing tenancy-dependent rate. If maintenance estimation fails, use a disclosed 1% of value allowance for older/freehold houses when value exists; otherwise retain a disclosed 5% rent allowance. These are fallback assumptions, not researched rates.
- Annual value-based maintenance uses the initial valuation (or disclosed purchase-price proxy) and subsequent cost inflation. It does not fluctuate with stressed rent or an alternative bid for the same property.
- Keep source evidence, selected survey scope and uncertainty in JSON; show concise reasons and calculation bases in existing report tables.
- Existing reports and photos remain unchanged; checks generate only temporary artifacts. Work in the existing uncommitted workspace; no commit, server takeover or paid PropertyData refresh.

## Tasks

- [x] Tests: source validation, overrides/fallbacks, both maintenance bases, partial inputs, stress/break-even/bidding, PDF labels/pages and consistent risk structure.
- [x] Add cost estimate validation and integrate it into existing research rounds without adding a second research loop or extending budgets.
- [x] Wire estimates into effective assumptions and every financial calculation; keep inputs unchanged.
- [x] Update report wording/cost explanations and require the five risk topics: financing, occupancy/permissions, cost assumptions, exclusions/taxes, environmental/designation uncertainty.
- [x] Run the full Python and dashboard suites, render both existing reports into temporary folders, review changes and verify saved-data hashes.

## Review focus

Reject fabricated source quotes and stale or differently scoped estimates. Avoid fee/SDLT and service-charge/maintenance double counting. Respect explicit costs even when equal to defaults. Never vary value-based maintenance with rent stress. Preserve partial independent figures and existing page counts. Keep real provider names in internal transport configuration.

## Verification ledger

- Initial cost tests failed on the absent module; implementation passed all seven initial cases. Added source/scope/checkpoint/partial-input regressions and corrected the new-schema default mismatch found while rendering original saved briefs.
- `test_saved_briefs_without_new_basis_field_consume_estimates`: RED (accepted cost fell back to £2,000) → GREEN after fingerprint defaults were normalized.
- Final independent review: two important findings, both fixed; no deferred minor findings.
- Final: fixed stale letting/cost-scope estimates — `test_letting_and_cost_scope_notes_invalidate_previous_estimates` RED→GREEN, suite 89/89.
- Final: fixed unsupported source-free maintenance quotation — `test_source_free_maintenance_cannot_claim_a_survey_quote` RED→GREEN, suite 89/89.
- Review scope decision: the five-topic guarantee applies to the AI writer. The pre-existing deterministic emergency template remains a calculation-led fallback; it does not offer the same topic guarantee. Earlier rollback/API migration changes were outside this task's baseline and were left intact.
- Full Python suite: 89 tests passed. Dashboard Node tests, Python compilation and `git diff --check` passed. Tests are offline; no live Codex/Firecrawl or paid PropertyData calls were made.
- Both original saved records rendered into `/tmp/property-costs-layout-check` with synthetic cost fixtures. All four test estimates reached the effective assumptions; each PDF set remained 10+1+1 pages and contained no Codex display text. Purchase-cost and running-cost pages were visually checked. These are layout fixtures, not new client reports or live fee research.
- Saved data/dashboard hashes matched `/tmp/property-costs-baseline-2026-10-31/hashes.json`; provider, evidence, comparisons and Codex transport files were unchanged. Changes stay in the existing workspace; no commit, server restart or saved-report regeneration.
