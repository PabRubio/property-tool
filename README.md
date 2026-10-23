# Property screening

Screen one property in England for a long-term rental investment, or save an area-and-budget enquiry for manual follow-up. A local Python server gathers property evidence, calculates returns and generates a ten-page PDF for analyst review. The frontend uses plain HTML, CSS and JavaScript. Records are stored as JSON files; there is no database or automatic email delivery.

## Run locally

Python 3.9.6 is compatible with the application. From the cloned project directory on macOS or Linux:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
cp .env.example .env
```

Edit `.env` to add your API keys, then start the server:

```bash
python app.py
```

Open [the client form](http://127.0.0.1:8000) or [the analyst dashboard](http://127.0.0.1:8000/review). Keep the terminal running; stop with Ctrl+C. For later sessions, activate `.venv` and run `python app.py` again. Change `PORT` in `.env` if port 8000 is already in use.

On Windows, create the environment with `py -m venv .venv` and activate it with `.venv\Scripts\activate` in Command Prompt. The remaining commands are the same, except use `copy .env.example .env`.

Opening `web/index.html` directly lets someone complete and download a brief as JSON. Use the form served by the local Python app to save submissions to the dashboard and run the pipeline.

## API configuration

For the full workflow, configure PropertyData and at least one AI provider in `.env`.

| Provider | API key setting | Optional model setting |
| --- | --- | --- |
| PropertyData | `PROPERTYDATA_API_KEY` | — |
| Claude | `ANTHROPIC_API_KEY` or `CLAUDE_API_KEY` | `ANTHROPIC_MODEL` |
| OpenAI | `OPENAI_API_KEY` | `OPENAI_MODEL` |
| Gemini | `GEMINI_API_KEY` or `GOOGLE_API_KEY` | `GEMINI_MODEL` |

The app selects the first configured writer in this order: Claude, OpenAI, Gemini. Model settings can specify a text model available to your account; otherwise the app attempts model discovery. Restart the server after changing `.env`. Set `REPORT_BRAND` to change the default report branding.

Without PropertyData, generation still attempts public research and can use a manually supplied rent. Without an AI key, it uses template commentary; AI editing requires a configured provider. Initial AI-writing failures fall back to template commentary. Failed AI edits keep the previous report.

Keys stay in the backend. AI requests include property information, financial assumptions, calculated results, evidence and analyst notes. Calculations run in Python; the AI writes commentary and proposes edits.

## Workflow

1. Submit the client property brief with property details, buyer circumstances and cash or expected mortgage terms. A confirmation replaces the form, and refreshing opens a fresh form. The submission appears automatically in the analyst dashboard.
2. Select the submission, optionally add information for the AI, then click **Generate report**. This starts evidence gathering, calculations and PDF generation. If no usable rent is available, a red error appears above **Generate report**. Check the property details and PropertyData connection, then retry; this refreshes the research.
3. Review the PDF. Use **Tell the AI what to change** and **Update PDF** for titles, wording, presentation, property facts or financial assumptions. Changes to financial inputs recalculate the results.
4. Upload one **Cover photo** and up to ten **House photos**, then click **Add photos to PDF**. Uploads accept JPEG, PNG or WebP, up to 10 MB per image. Photo updates rebuild the existing PDF without calling PropertyData or starting the research pipeline.
5. Click **Approve & finalize** when satisfied. This requires a saved cover photo, saved photo changes and no pending AI instructions. Finalization records the review and downloads the PDF. Later edits reset approval. Send the finished report to the client yourself.

An area-only enquiry asks for an area and purchase budget, saves the contact details and goal, and appears as **Needs follow-up**. It does not search for properties, generate a PDF or spend API credits. One optional checkbox permits contact about a feedback call or a testimonial request; it saves both contact preferences separately from the required terms acceptance. This form remains for England long-term rental investments; a separate homebuyer form is deferred. The `/terms` and `/privacy` links deliberately open blank placeholder pages. No testimonial publication permission is inferred.

The dashboard reopens the last submission viewed in that browser. The bin icon on a submission deletes its JSON, photos, PDFs and history; deletion is disabled while processing. **Export JSON** downloads the full saved record, including inputs, evidence, calculations, report edits and approval information.

## Report contents

The PDF contains ten pages:

1. Cover photo, asking or proposed purchase price, acquisition costs and screening result.
2. Gross yield, net yield, cash-on-cash and sale/rent valuations, growth assumptions and future-value scenarios.
3. Investment calculation spreadsheet image and acquisition/financing breakdown.
4. Cash-flow spreadsheet image and annual projections.
5. Downside scenarios, including 90% occupancy, and buying, renting and selling after 3, 5 and 10 years.
6. Property facts, rooms and the additional photo gallery.
7. Matched property sale history and local historical price context.
8. Comparable properties with dates and source links.
9. Written investment case, qualifications and risks.
10. Assumptions, due-diligence steps and the source register.

Long evidence lists and projections are condensed in the PDF. The full record remains available as JSON, and the full monthly cash-flow schedule is exported as CSV. Spreadsheet images are also downloadable as PNGs. Existing fictional records retain their demo watermark, including after approval.

## Evidence and calculations

New property briefs require the details needed to request sale and rent valuations: property type, bedrooms, floor area, construction age, condition, bathrooms, outdoor space and parking. Studios and converted flats use the flat model; bungalows use their detached/semi-detached/terraced attachment. The report flags these broader categories. New-build and confirmed tenure information filter the recorded-sale requests. The property profile runs first and can fill missing size, age, EPC and tenure only when the identity matches. It never overwrites client-supplied facts. House aliases and town formatting differences are accepted only with matching postcode, numbered street and no ambiguous flat/unit identifiers.

A complete successful research run budgets **30–32 PropertyData credits**, before the additional conditional requests below:

| Request | Credits |
| --- | ---: |
| `property` | 20 |
| `rents`, `prices-per-sqf`, `growth`, `demand` | 4 |
| `valuation-sale`, `valuation-rent` | 2 |
| `demand-rent`, `sold-prices-per-sqf`, `build-cost` | 3 |
| `growth-psf` | 1 |
| **Core requests** | **30** |
| `national-data` (regional rent inflation): fresh download / valid shared cache | 1 / 0 |
| `sold-prices`: broader search needed / sufficient existing comparisons | 1 / 0 |
| **Standard total** | **30–32** |

Regional rental inflation is shared between properties through a local cache in `.research-cache` inside the configured records directory (normally `data/records`, which is gitignored). It expires after 24 hours. A cached response must contain a usable dated observation for the property's verified region; corrupt, expired, future-dated or unusable entries are replaced. Unsuccessful or unusable downloads are not cached, and a failed refresh never silently substitutes expired data. Simultaneous reports in the local app share a single download. Each report retains the original retrieval timestamp, dataset dates and whether its source was cached; cache hits are not included in `paid_requests`. An explicit backend `refresh_evidence: true` also bypasses the shared cache.

The broader `sold-prices` search runs only when the existing evidence contains fewer than three qualifying distinct properties. Qualifying sales must have a positive price and source link, a sale date within the last 730 days (never in the future), known distance greater than zero and no more than one mile, matching type and bedroom count, and known floor area within 75–125% of the subject. Known subject tenure must match, and new-build subjects require new-build sales. The subject itself and repeat sales of the same address do not count. Missing facts do not qualify, so sparse, failed or weak size-filtered results still trigger the broader search. These remain candidates requiring analyst review. The saved `sold_search` decision records the qualifying count and whether the fallback ran.

Additional conditional requests each budget one credit: `prices` when fewer than three type/bedroom/size-compatible asking-price candidates are available; `planning-applications` when refurbishment is planned (ten results, within 0.25 miles, last three years, no decision filter); `floor-areas` and `energy-efficiency` only for gaps remaining after the profile; and `title` only for missing lease years with a single matched leasehold title. At most five such requests are added, so the overall budget is 30–37 credits where all core requests are eligible. Calls are paced to the lowest documented rate limit of twelve per thirty seconds. There is no area-yields request or extra address-match request. The saved evidence lists the requests attempted and their budgeted credits; this is not an account billing receipt. Actual provider billing can be lower for incomplete/no-match responses. Refurbishment is requested whether or not works are planned, when a valid floor area is available. Provider limits still apply: the documented minimum area is 300 sqft for valuations and 600 sqft for refurbishment. Inputs below those limits are not inflated to force a result. Missing or failed estimates are marked unavailable. A refurbishment reference is added to investment costs only when works are planned and no explicit budget was supplied; an explicit budget takes precedence, and contingency is shown separately. The estimate is not a contractor quote or a predicted value uplift.

The app also queries HM Land Registry for transactions and the England House Price Index as background evidence, without PropertyData credits. The report's historical chart uses the local growth series. Listing links remain references; the app does not scrape portals or download their photographs.

Research snapshots are reused and refreshed after sixty days, or when explicitly requested through the backend. When an API key is configured, the next Generate report action upgrades an older research snapshot with a fresh run of the new requests. Photo changes and AI edits do not perform this research upgrade. Evidence older than thirty days is flagged. Paid requests are not automatically retried. Photo changes, approval and report edits reuse the saved evidence; they do not trigger paid research. Changes to property identity invalidate evidence, and changes to valuation inputs or refurbishment specification discard the affected estimates rather than reuse stale results. Previously generated files remain intact until an explicit update; old models can be upgraded locally from saved evidence when a draft is rebuilt.

Monthly rent is selected in this order: explicit supplied rent, analyst-selected rental comparables, property-specific rental valuation, then a clearly provisional area average. Rental valuations with unknown units are withheld instead of guessing weekly versus monthly. Candidate comparables are ranked by available type, bedroom, size and distance information, and are not silently treated as analyst-verified matches. Property sale history requires matching identity. Asking-price and sold-price-per-square-foot requests use a floor-area band of 75–125% of the known subject area; the actual returned radius remains visible because searches can widen. Individual asking and sold comparisons are retained separately, with observed dates, dimensions, distance, listing age and links where supplied. Rental sample counts, radius and the middle 80% range describe the local sample, not a property valuation confidence interval. Sales/rental demand metrics remain area context and are not converted into vacancy assumptions. Matched council tax and environmental/designation facts are reported with their limits; nearby listed buildings do not establish the subject’s listed status. Council tax is not added again to operating costs, which already include an empty-period bills budget. Planning searches are limited nearby context, not a permission check. Missing fields are not treated as cleared checks.

The purchase price always remains the supplied listing/offer/proposed price when known. If unknown, a sale valuation can supply a clearly labelled provisional purchase scenario. Future sale scenarios start from the property-specific sale valuation when available, otherwise the purchase-price proxy. These two figures are not interchangeable.

The financial model calculates:

- Gross yield: scheduled annual rent divided by purchase price.
- Net yield on cost: stabilised income after vacancy and operating costs divided by acquisition cost, including refurbishment and contingency.
- Cash-on-cash: stabilised cash flow after debt payments, before income tax, divided by cash invested including reserves and upfront finance fees.
- Cash, interest-only or repayment financing using the supplied mortgage amount and rate. Legacy records can still use an explicit LTV assumption.
- Monthly cash flow, annual totals, downside scenarios, break-even rent, exit proceeds and approximate annual IRR for 3, 5 and 10 years of ownership and renting. The CSV contains a separate monthly schedule for each period. Interest-only comparisons beyond the supplied mortgage term are withheld until refinancing terms are known.

When no price-growth assumption is supplied, the model uses the annualised local historical change over at least two years as an explicitly labelled scenario. It does not claim to predict future growth. The sold-price-per-square-foot history cross-check compares annualised changes over common periods; opposite directions or a difference of at least two percentage points are flagged, and the rates are never averaged. It can supply an explicitly labelled fallback scenario when the main growth series is absent. Rent growth uses the latest dated annual rental-inflation observation for the verified English region from `national-data`, unless explicitly supplied. The basis distinguishes an observation date from a dataset publication date. Regional history is extrapolated as a scenario, not a forecast of this property’s future rent. Unmatched, ambiguous, stale (over eighteen months), future-dated or implausible observations are withheld; missing evidence produces a visible no-growth fallback and warning. An intentionally supplied zero is preserved. Income and disposal taxes are not automatically assessed; adviser-supplied budgets can be included. An absent income-tax budget appears as a dash in the spreadsheet and blank in the CSV, not as a zero tax liability. Buyer ownership/residency affects SDLT; not owning another property is not treated as automatic first-time-buyer relief for a rental purchase. England purchase-tax settings and their source dates live in `config/tax_rules.json` and require maintenance. Defaults and missing evidence remain identified in the report. AI edits cannot directly overwrite computed results.

## Storage and repository

```text
app.py                      Local server and pipeline orchestration
web/                        Client form, analyst dashboard and assets
screening/                  Data integrations, calculations, AI, photos and reports
config/tax_rules.json        Dated purchase-tax settings
.env.example                Blank API configuration template
requirements.txt            Python dependencies
data/records/<id>/           Local submission files (excluded from Git)
```

Each submission folder contains `record.json`, prior revisions in `history/`, uploaded photos and generated PDF/PNG/CSV files. Writes use atomic JSON replacement and process-local locks. Run a single local server process; this app is not configured as a hosted multi-user service.

`.gitignore` excludes `.env` and its variants, local credentials, `data/`, virtual environments, Python caches and editor files. Only the blank `.env.example` belongs in the repository. API keys and saved submissions are therefore not included when cloning: configure a new `.env` and copy `data/` separately if you want existing records. Back up `data/` before moving machines.
