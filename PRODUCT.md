# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Users

Primary: Lacewing analysts running the local Python dashboard to screen one English property at a time for an investor client, then sending the finished PDF. Investors are a secondary audience who enter the workflow through the public marketing site's enquiry form; they submit a brief (residential or commercial) or an area-and-budget enquiry and never touch the dashboard. Both audiences matter, but every generation, edit, approval and finalization action is the analyst's.

## Product Purpose

Turn one property brief into a finished, investor-ready investment assessment. For each submission the analyst produces three PDFs:

- a ten-page investment report (Signature Edition),
- a one-page Sources & Evidence companion, and
- a one-page Internal review.

Success is a complete PDF that the analyst can send to the investor without manual rewriting: every number cited to a source, every assumption disclosed, dependent figures withheld rather than fabricated when evidence is missing, and the layout rejecting overflow rather than silently clipping.

Area-and-budget enquiries are a lightweight parallel path: they save contact details and goal for manual follow-up and spend no API credits.

## Positioning

Lacewing produces a finished, ten-page investor-ready PDF (plus Sources and Internal review companions) from a short brief — not a dashboard of charts the investor has to interpret. A neighboring property-analytics tool can show the same raw PropertyData numbers, but it does not hand the investor a layout-checked, source-cited, finalizable PDF with disclosed modelling assumptions and separate internal review notes.

## Operating Context

- **Scope per submission.** One residential property, or one commercial retail / office / industrial unit, in England, for a long-term rental investment. Mixed-use buildings, multiple units, restaurants and pubs are rejected.
- **Analyst workflow.** Brief → intake check → generate report (PropertyData + Codex/Firecrawl research + calculations + PDF write) → review PDF → request edits with "Tell the AI what to change" → upload cover + up to ten house photos → **Approve & finalize**. Later edits reset approval.
- **Brief delivery.** The public form posts JSON to an Un-static endpoint and emails it to the receiving inbox. The analyst saves the JSON text as a `.json` file and imports it through **+** beside **Client submissions**.
- **Local, single-process.** The dashboard runs as one local Python server (`python app.py`, default port 8000). Records are JSON files under `data/records/<id>/`; there is no database and no hosted multi-user deployment. API keys stay on the analyst's machine.
- **Dashboard surfaces.** `/` and `/review` open the analyst dashboard (`web/index.html`); the public marketing site is `web/public/index.html` served separately. The dashboard reopens the last submission viewed in that browser.

## Capabilities and Constraints

**Evidence pipeline**

- PropertyData for residential (`property`, `rents`, `prices-per-sqf`, `growth`, `demand`, `valuation-sale`, `valuation-rent`, `demand-rent`, `sold-prices-per-sqf`, `build-cost`, `growth-psf`, plus conditional requests). Budget: 30–37 credits per residential run.
- PropertyData for commercial (`rents-commercial`, `valuation-commercial-rent`, `valuation-commercial-sale`, plus one nearby planning request when works are planned). Normally three credits when valuation inputs are eligible.
- HM Land Registry transactions and the England House Price Index as background evidence (no PropertyData credits).
- Codex CLI (ChatGPT subscription auth; no paid API fallback) for intake review, corrections, research orchestration, commentary writing and edit planning. Firecrawl via MCP for `firecrawl_search` and `firecrawl_scrape` only.
- Regional rental inflation shared across properties through a 24-hour local cache in `.research-cache`.

**Financial model**

- Calculates gross yield, net yield on cost, cash-on-cash, monthly cash flow, annual totals, downside scenarios, break-even rent, exit proceeds and approximate annual IRR for 3, 5 and 10 year horizons.
- Supports cash, interest-only and repayment financing, with fixed-rate periods of 2/3/5/10 years and an explicit stress scenario.
- England SDLT (residential and non-residential) sourced from `config/tax_rules.json` with dated settings that must be maintained. No automatic income/disposal tax assessment.
- Interest coverage reported at model and stress rates; no universal lender pass threshold is assumed.

**Reporting**

- Signature Edition: ten cream A4 pages, compact green masthead, Inter page titles, Cormorant section headings, split cover with large property photograph, vector charts drawn from saved calculations, selectable PDF cash-flow text.
- Both companions (Sources & Evidence, Internal review) are measured to remain exactly one page each. Overflow causes a visible editing error, never a silent cut or extra page.
- Fictional/demo records keep their watermark after approval.

**Durable constraints**

- Supplied values always take precedence over estimates. Explicit client facts are never overwritten by research. Missing dependent figures are marked unavailable, not inferred.
- Property identity changes invalidate dependent cached outputs; evidence older than 30 days is flagged; research snapshots refresh after 60 days.
- Area-only enquiries save contact details and goal, mark as **Needs follow-up**, and do not spend API credits or generate a PDF.
- Commercial scope cannot be expanded without reopening the API surface; a separate homebuyer form is explicitly deferred.

## Brand Commitments

- **Name:** Lacewing Analytics. Dashboard title remains **Property Screening**.
- **Palette:** deep green, gold, ivory.
- **Mark:** wing mark (bundled as `web/assets/brand-mark.webp` and `web/assets/logo.png`).
- **Typography:** Cormorant Garamond for headings, Inter for body. Fonts are bundled locally under `web/assets/fonts/` with their licences so the interface and PDFs work offline.
- **Report design:** the Signature Edition layout is approved; earlier regeneration restyles saved records to it via `python3 -m screening.restyle_reports`.
- Form, dashboard and reports all use the same Lacewing Analytics brand treatment.

No voice doctrine, tagline, legal-framing commitment or other binding verbal constraint has been recorded beyond those visual commitments. Future surface work must preserve the palette, mark, typography and Signature Edition report layout, but has latitude on written voice.

## Evidence on Hand

- `README.md` — authoritative long-form product specification, kept current by the maintainer.
- `web/public/index.html` — the live marketing site and public enquiry form, with the Lacewing Analytics landing content, Terms (`#terms`) and Privacy (`#privacy`) views.
- `web/index.html`, `web/assets/intake.js`, `web/assets/review.js`, `web/assets/style.css` — the analyst dashboard surfaces.
- `web/assets/logo.png` and `web/assets/brand-mark.webp` — supplied brand marks.
- `web/assets/fonts/` — bundled Cormorant Garamond and Inter with licences.
- `data/briefs/` and `data/previews/` — real example briefs and generated preview artifacts (gitignored at the records level; `.gitignore` excludes `data/`).
- `screening/report_layout.py`, `screening/reports.py`, `screening/narrative.py`, `screening/restyle_reports.py` — the shipped report composition code, including the Signature Edition layout.
- `config/tax_rules.json` — dated England purchase-tax settings used by the model (requires ongoing maintenance).
- No published testimonials, customer logos, press coverage, benchmarks or pricing claims have been captured here. Future design must not fabricate them.

## Product Principles

1. **Finished artifact, not a dashboard of charts.** The deliverable is three PDFs the analyst can send; anything that does not help produce or verify them is secondary.
2. **Cited, audited, or withheld.** Every number has a supplied input, a PropertyData record, or a quoted source behind it. When evidence is missing, dependent figures are marked unavailable and the report says so.
3. **Supplied facts win.** Client-supplied prices, rents, areas and budgets always take precedence over AI estimates, provider valuations and research findings. Research can never silently overwrite an analyst-confirmed value.
4. **Analyst stays in the loop.** Intake checks, correction history, edit history, photo gating and explicit **Approve & finalize** keep the analyst in control; no AI output is silently promoted to final.
5. **One property, England, long-term rental.** Scope is narrow on purpose: adding mixed-use, multi-unit, short-let or non-English scope requires reopening the API surface and the reporting scope deliberately.

## Accessibility & Inclusion

No product-specific accessibility standard has been recorded. Future surface work should meet WCAG 2.2 AA as a sensible floor for an investor-facing product, but this is a design-time default, not a confirmed requirement from the business.
