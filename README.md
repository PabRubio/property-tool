# Property screening

Screen one property in England for a long-term rental investment. A local Python server gathers property evidence, calculates returns and generates a ten-page PDF for analyst review. The frontend uses plain HTML, CSS and JavaScript. Records are stored as JSON files; there is no database or automatic email delivery.

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

1. Submit the client property brief. A confirmation replaces the form, and refreshing opens a fresh form. The submission appears automatically in the analyst dashboard.
2. Select the submission, optionally add information for the AI, then click **Generate report**. This starts evidence gathering, calculations and PDF generation. If no usable rent is available, enter an estimate when prompted.
3. Review the PDF. Use **Tell the AI what to change** and **Update PDF** for titles, wording, presentation, property facts or financial assumptions. Changes to financial inputs recalculate the results.
4. Upload one **Cover photo** and up to ten **House photos**, then click **Add photos to PDF**. Uploads accept JPEG, PNG or WebP, up to 10 MB per image. Photo updates rebuild the existing PDF without calling PropertyData or starting the research pipeline.
5. Click **Approve & finalize** when satisfied. This requires a saved cover photo, saved photo changes and no pending AI instructions. Finalization records the review and downloads the PDF. Later edits reset approval. Send the finished report to the client yourself.

The dashboard reopens the last submission viewed in that browser. The bin icon on a submission deletes its JSON, photos, PDFs and history; deletion is disabled while processing. **Export JSON** downloads the full saved record, including inputs, evidence, calculations, report edits and approval information.

## Report contents

The PDF contains ten pages:

1. Cover photo, asking or proposed purchase price, acquisition costs and screening result.
2. Gross yield, net yield, cash-on-cash and a separate capital-growth scenario chart.
3. Investment calculation spreadsheet image and acquisition/financing breakdown.
4. Cash-flow spreadsheet image and annual projections.
5. Downside scenarios and exit results.
6. Property facts, rooms and the additional photo gallery.
7. Property sale history and historical England house-price context.
8. Comparable properties with dates and source links.
9. Written investment case, qualifications and risks.
10. Assumptions, due-diligence steps and the source register.

Long evidence lists and projections are condensed in the PDF. The full record remains available as JSON, and the full monthly cash-flow schedule is exported as CSV. Spreadsheet images are also downloadable as PNGs. Existing fictional records retain their demo watermark, including after approval.

## Evidence and calculations

PropertyData supplies area rents, sold-price statistics, asking prices per square foot, growth, demand and a property profile. Optional sale and rental valuations run only when their required property details are available. The app also queries HM Land Registry for transaction evidence and the UK House Price Index for historical England context. A listing URL is retained as a reference; the app does not scrape property portals or download their photographs.

Research snapshots are reused and refreshed after sixty days, or when explicitly requested through the backend. The model flags evidence older than thirty days. Paid requests are not automatically retried. Missing or failed sources remain recorded as evidence gaps.

Rental evidence is selected in this order: an explicit rent assumption, selected rental comparables, then the available area baseline. Candidate comparables are not automatically treated as analyst-verified matches. Area statistics and automated valuations are cross-checks, not proof of a property's achievable rent or value. Subject sale history requires a matching property identity.

The financial model calculates:

- Gross yield: scheduled annual rent divided by purchase price.
- Net yield on cost: stabilised income after vacancy and operating costs divided by acquisition cost, including refurbishment and contingency.
- Cash-on-cash: stabilised cash flow after debt payments, before income tax, divided by cash invested including reserves and upfront finance fees.
- Cash, interest-only or repayment financing; monthly cash flow, annual totals, downside scenarios, break-even rent, exit proceeds and approximate annual IRR.

Growth is a scenario assumption, not a rental yield or forecast. Income and disposal taxes are not automatically assessed; adviser-supplied budgets can be included. England purchase-tax settings and their source dates live in `config/tax_rules.json` and require maintenance. Defaults and missing evidence remain identified in the report. AI edits cannot directly overwrite computed results.

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
