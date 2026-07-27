# Production Part A — Emergent Re-publish Handover

**Disposition:** Not executable from Codex  
**Published app:** Purchase Workflow 10  
**Production status:** Untouched; no connection, deployment, restart, or data change performed  
**Feature flag:** Keep `ACCESS_SECURITY_V2=0` until a separate Director-approved release

## Tested code package

- Archive: `test_reports/production_part_a_task3b_code_package.tar.gz`
- SHA-256: `test_reports/production_part_a_task3b_code_package.tar.gz.sha256`
- Contents are limited to the reviewed Task 3B runtime files, retained security tests, frontend contract test, and local test evidence. No `.env`, credentials, database dump, or sample data is included.

### Runtime files

- `backend/routers/access_security_v2.py`
- `frontend/app/access-console.tsx`
- `frontend/app/more.tsx`
- `frontend/src/api.ts`
- `frontend/src/auth.tsx`

### Evidence files

- `backend/tests/test_task3a2_access_security.py`
- `backend/tests/test_task3b_access_console.py`
- `frontend/tests/task3b_access_console.test.mjs`
- `backend/scripts/task3b_test_report.py`
- `test_reports/task3b_test_report.json`
- `test_reports/task3b_test_report.md`

## Change summary

- Adds the Task 3B Admin Access Console UI and feature-gated access-management routes.
- Preserves legacy behavior while `ACCESS_SECURITY_V2=0`.
- Retains Director protection, roles[] authority, self-elevation/self-deactivation prevention, session/history controls, and last-active-Director protection.
- No schema migration, seed, user update, role update, session mutation, or production data write is part of Part A.

## Test evidence

- Task 3A.2 retained security: 14 passed, 0 failed.
- Task 3B backend integration/security: 8 passed, 0 failed.
- Task 3B frontend contracts: 8 passed, 0 failed.
- Consolidated: 30 passed, 0 failed.

Reports: `test_reports/task3b_test_report.json` and `test_reports/task3b_test_report.md`.

## Backup references

The repository backup procedure is read-only and must be executed by the Emergent-controlled operator before Re-publish:

```bash
cd /app
umask 077
test -n "$MONGO_URL" && test -n "$DB_NAME"
command -v mongodump
python3 /app/backend/scripts/backup_db.py
```

Expected artifacts:

- `/app/backup_artifacts/backup_<UTCstamp>/manifest.json`
- `/app/backup_artifacts/backup_<UTCstamp>/checksums.sha256`
- `/app/backup_artifacts/backup_<UTCstamp>.tar.gz`
- `/app/backup_artifacts/backup_<UTCstamp>.tar.gz.sha256`

Codex did not connect to production and did not create a production backup. Do not place production secrets or backup contents into this repository or archive.

## Emergent Re-publish handover instructions

1. In Emergent, confirm the target is the published app **Purchase Workflow 10** and record the platform-managed release identifier.
2. Verify the Emergent-managed host, region, cluster, deployment command, and rollback command in the platform UI; these values are unavailable to the repository and are not inferred here.
3. Verify the backup succeeds and checksum/manifest checks pass before promotion.
4. Re-publish the tested archive as a code/artifact-only release. Do not run migrations, seed data, restore databases, or modify supervisor units.
5. Keep `/app/backend/.env` without an `ACCESS_SECURITY_V2` line / effective value `0`.
6. Run the platform health, frontend, legacy-auth, and V2-disabled smoke checks from the existing deployment pack.
7. If validation fails, use Emergent’s platform rollback command to restore the prior artifact/config; do not repair by changing users or data.
8. Enable `ACCESS_SECURITY_V2=1` only through a separate Director-approved release with its own backup, approval, and validation record.

**Handover complete. Part A remains not executable from Codex.**
