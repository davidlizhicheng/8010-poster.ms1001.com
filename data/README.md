# Poster data directory

This directory contains runtime data and must be preserved across every code update.

- `poster.db`: SQLite database for users, sessions, credits, jobs, payments, invoices, and admin events.
- `config.json`: local runtime configuration, including API and payment QR settings.
- `payment-screenshots/`: uploaded payment screenshots. Admin screenshots are served from `/api/admin/payment-screenshot/<claim_id>`.
- `reference-images/`: uploaded generation reference images. Public direct URLs use `/api/reference-images/<job_id>/<filename>`.
- `admin_alerts.log`: append-only plain text admin event log.

Update rule: never delete or overwrite `data/` during deployment. Back up this directory before each release.
