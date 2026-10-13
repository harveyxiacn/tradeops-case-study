# TradeOps implementation and handoff — 2026-10-13

## Delivered

Local FastAPI/PostgreSQL quotation workflow: enquiries, immutable quotation versions, Decimal pricing, independent approval, stale-version conflicts, organisation checks, audit records, follow-up, currency-specific reports and current-approved CSV export. Browser create → submit → approve was verified. The UI is intentionally a one-line quote editor; API supports up to 50 lines. Selecting a quote now fills its current fields; multi-line UI editing is disabled to prevent silent line loss.

## Verification

- `python -m unittest discover -s tests`: **19 tests passed** (2.256 seconds, final review run). Tests cover the original 17 functions plus malformed nested payload and numeric storage bounds.
- Separate T18: pg_dump/pg_restore into a newly created isolated database, **6 tables / 83 rows**, counts and full-row SHA-256 digests matched. See `evidence/tradeops-backup-restore.json`.
- Earlier browser create-submit-approve: verified on a synthetic quotation. Subsequent form-backfill JavaScript received syntax validation; do not describe this as another full browser acceptance cycle.
- No load benchmark or production authentication test completed. Simulated role checks are not real multi-user identity validation.

## Run

Install dependencies from requirements.txt in a dedicated environment. Provide `.env.local` containing a PostgreSQL DSN for a new dedicated demo database (example in `.env.example`). The database must already exist; tables initialise at application start. From the repository: `python run.py`. Open http://127.0.0.1:8780. Stop only this application with Ctrl+C. Never reuse a production database for tests.

Tests create synthetic records and intentionally exercise failures. Use a dedicated demo/test database; the current repository configuration points to the newly created isolated database. Backup files and credentials remain ignored and outside public evidence.

## Architecture decision

Implemented vanilla HTML/CSS/JavaScript + FastAPI + PostgreSQL instead of introducing a new React build. Versioned quotation content is held as JSONB snapshots, with numeric totals and relational approval/audit records. This preserves historical bodies and reduces setup dependencies. The original architecture is a target design, not a claim that every listed technology was implemented.

## Residual work

Production identity/SSO, schema migrations, robust connection pooling, deployment monitoring, pagination controls in the browser (API pagination exists), full responsive/accessibility acceptance, and workload performance tests are not delivered. UI reports still expose structured details suitable for technical demonstration; a production business dashboard would require further UX work.

## Environment and boundaries

Windows; Python 3.13, FastAPI 0.136.1, Uvicorn 0.44.0, httpx 0.28.1. PostgreSQL demos additionally use PostgreSQL 16 and psycopg 3.3.3. The actual new database is bound to loopback port 55432, separate from the user's existing database service. Credentials are stored only in ignored local configuration; never commit them.

No public deployment, real customer data, employer adoption, purchase, repository commit or push is claimed. Browser role selection is a synthetic demonstration, not enterprise authentication. Independent third-party reproduction and clean-machine installation remain unverified.
