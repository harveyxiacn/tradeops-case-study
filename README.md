# TradeOps — Quotation & Approval Case Study

A synthetic trade-quotation workflow that models the parts of a commercial process that go wrong in practice: versions, approvals, currency and audit. It is a self-contained business-analysis case study with a working backend and minimal UI, not a client delivery.

**Status: implemented and locally verified.** 19/19 tests pass against a local PostgreSQL 16 instance (2026-10-13), and a 6-table / 83-row backup-restore round-trip was verified by SHA-256. Not deployed to production; simulated roles are not real multi-user authentication.

## What it demonstrates

- **Versioned quotations** — every quotation is an immutable version; an approval on a stale version is rejected rather than silently overwritten.
- **Separation of duty** — the requester cannot approve their own quotation; role checks (sales / operations / approver) gate each action, and organisations are isolated.
- **Money and rules** — amounts use `Decimal`, not floats; currency conversion, discount bounds and a 48-hour validity rule are enforced in SQL and in the service.
- **Audit and rollback** — every write leaves an audit record inside the same transaction, so a failed audit rolls the whole change back.
- **Safe export** — approved quotations export to CSV with formula-injection defence.

## Run it

```bash
python -m venv .venv && . .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env.local                          # set the local demo dsn
python run.py                                        # app on http://127.0.0.1:8780
python -m pytest tests/ -q                           # 19 tests
```

## Evidence

- [`evidence/test-results.json`](evidence/test-results.json) — per-test results.
- [`evidence/tradeops-backup-restore.json`](evidence/tradeops-backup-restore.json) — 6-table / 83-row backup-restore verification.

## Honest limitations

- No production identity/SSO, schema migrations, connection pooling or deployment monitoring.
- The demo's role selector is a simulated identity, not multi-user auth; multi-line editing is disabled by design.
- Uses synthetic data only; the numbers in the UI are not a client's.

See [`docs/release-review-20261013.md`](docs/release-review-20261013.md) for the full review and [`docs/`](docs/index.md) for the design notes.
