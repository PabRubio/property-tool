# Commercial investment screening

The user approved adding single-unit commercial rental investments in England alongside residential screening, keeping the dashboard and report design. This implements that approved scope without another approval gate.

## Scope and approach

Extend the existing input, evidence and financial pipeline with `property.asset_class`, defaulting to `residential` for old records. Commercial types are `retail`, `offices`, and `industrial`. Reject mixed-use, multiple-unit and unsupported commercial categories. Share calculations and PDF layout; branch where the assumptions differ. A separate application duplicates too much. A cosmetic form-only change would retain incorrect residential data and tax.

Clone the current contact form into a local `/brief` page. Reuse its styling and fields, use local assets compatible with the existing CSP, and POST directly to `/api/records` with the local token. Change only the dashboard header link's destination, preserving its text. Keep the public website and its email delivery unchanged. Document reversal of the temporary link and route.

## Input contract

Property fields: `asset_class` (`residential`/`commercial`), `property_type` (existing residential types or three commercial types), `floor_area_basis` (`unknown`/`gia`/`nia`), `occupancy` (`unknown`/`vacant`/`let`), `unit_count` (1), `mixed_use` (false), `use_class` (text), `repair_responsibility` and `insurance_responsibility` (`unknown`/`landlord`/`tenant`/`shared`), and `rent_vat_status` (`unknown`/`exclusive`/`exempt`). Commercial bedrooms are null, not a fictional count. Ownership lease years remain distinct from the tenant lease.

Assumption fields: `annual_rent`, `lease_remaining_months`, `break_month`, `rent_review_month`, `rent_review_annual_rent`, `rent_free_months` (default 0), `reletting_void_months`, `reletting_annual_rent`, `business_rates_annual`, `rates_relief_months` (default 0), `purchase_vat_pct` (unknown, 0 or 20), `purchase_vat_recoverable_pct` (default 0), and `vat_recovery_month`. Month fields are integral. A supplied annual rent becomes the existing monthly rent divided by 12; conflicting explicitly supplied annual/monthly rents are rejected. Rents are net of any pass-through VAT; supplied costs include irrecoverable VAT.

Unknown occupancy, unknown initial vacant period for vacant property, unknown lease duration for let property, or unknown purchase VAT withhold dependent financial results. No automatic renewal after the earliest break/expiry: income stops unless both an explicit reletting delay and annual rent are supplied. Contractual review is one explicitly priced rent step; unsupported annual residential rent inflation is not used. Forecasts remain scenarios.

## Evidence and finance

Commercial PropertyData requests use `/rents-commercial`, `/valuation-commercial-rent`, `/valuation-commercial-sale`; floor area must be explicitly NIA for offices and GIA for shops/industrial. The API's asking-rent area average is context, not the subject rent. Valuation-sale is rent capitalisation, not completed-sale evidence. Retain source IDs and annual units. Do not call residential profiles, AVMs, growth, demand, rent inflation, Land Registry house-type queries or refurbishment estimators for commercial records. Reuse cited public research for exact property facts and commercial comparisons; compare subtype, area basis, size, location and lease conditions, never bedrooms. Optional identifiers/constraints can be researched with compatible endpoints or cited pages.

Use England non-residential SDLT (0% to £150,000; 2% to £250,000; 5% thereafter). Taxable consideration includes charged purchase VAT. Existing override covers adviser-confirmed complex/new-lease tax. Residential buyer surcharges and ATED wording do not apply. Full purchase VAT increases cash needed at completion; only explicitly recoverable VAT is credited in the specified month. No implicit VAT recovery. Business rates use a supplied annual empty-property budget and explicitly supplied relief months; no inferred relief eligibility. Tenant cost responsibility never implies landlord costs remain zero while vacant. Missing commercial budgets remain disclosed unpriced items, not residential allowances.

## Reports and editing

Keep ten pages, masthead, palette, photos, metrics, tables and export structure. Commercial reports show use, area measurement, occupancy and lease terms instead of bedrooms/bathrooms. Replace residential growth/context with commercial rental evidence and lease scenarios. Update companion PDFs, incomplete reports, tax notes, AI instructions and permitted edits consistently. Invalidate cached evidence and estimates when class/type/measurement changes. Existing saved residential reports remain readable and unchanged until regeneration.

## Validation and delivery

Baseline: 137 Python tests passed before edits. Add targeted tests for schema/import, monthly normalization, provider routing, VAT/SDLT boundaries, lease expiry/break/review/vacancy, missing-data withholding, stale evidence, commercial PDF text and browser submission. Run existing Python and Node suites, inspect desktop/mobile form screenshots and commercial PDF pages. User authorizes Codex and at most 10 live PropertyData calls total; coordinator tracks every paid call, with no automatic retry. Use temporary test records, never overwrite saved customer reports. Deliver uncommitted changes in the current clean workspace; no deployment or external messages.
