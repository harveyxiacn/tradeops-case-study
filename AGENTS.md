# Project instructions

Read README.md, START_HERE.md and docs/ before changing implementation. This repository currently contains planning documents and synthetic fixtures, not a completed application.

- Keep the assigned phase and product scope fixed. Preserve existing user changes.
- Mark planned, implemented, tested and externally deployed states separately. Never fabricate logs, test results, clients or performance measurements.
- Use synthetic or explicitly authorized data. Do not commit secrets, private conversations, customer files, model weights or unapproved voice/video samples.
- Reuse existing verified runtimes where appropriate. Do not reinstall drivers, download large models, terminate unrelated GPU processes or enable public access without explicit authorization.
- Run verification appropriate to the change. Report actual commands, outcomes, untested paths and residual risks. A fixture or mock check is not a real integration test.
- The initial remote repository and documentation push were authorized. Future feature work should remain local unless the user authorizes publishing or pushing it.
- Primary agent owns requirements, architecture, acceptance and final review. Do not start subagents unless separately authorized. If authorized, prefer luna_worker for deterministic small tasks and terra_worker for complex bounded tool work; require evidence and review results.
