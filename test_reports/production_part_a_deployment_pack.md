# VASU MRF — Production Part A Deployment Pack

**Status: Not executable from Codex — handover prepared for Emergent Re-publish.**  
**Prepared:** 2026-07-23T16:21:18Z  
**Production contacted:** No  
**Production modified:** No  
**Data-write budget:** 0

Deployment, rollback, host, region, and cluster are controlled by Emergent and are unavailable to this repository. No further production change is authorized from Codex.

Handover artifacts: `test_reports/production_part_a_handover.md`, `test_reports/production_part_a_handover.json`, and `test_reports/production_part_a_task3b_code_package.tar.gz` with its SHA-256 file.

## 1. Exact scope

Part A is a planned, dormant production code promotion for the already-tested Task 3B Admin Access Console. Emergent identifies the published app as **Purchase Workflow 10**. Production remains untouched and Part A has not been executed. If approved later, it would promote the reviewed application artifact while preserving current production behavior:

- Backend access-console routes and guardrails from `backend/routers/access_security_v2.py`.
- Frontend Admin Access Console from `frontend/app/access-console.tsx`.
- Supporting frontend navigation/API/auth changes in `frontend/app/more.tsx`, `frontend/src/api.ts`, and `frontend/src/auth.tsx`.
- No Task 4 material-master changes.
- No database migration, seed, backfill, role assignment, invitation, activation, deactivation, session revocation, or user-record update.
- Production must remain `ACCESS_SECURITY_V2=0` for Part A. The new access-console routes remain unavailable in production until a separately approved enablement step.

### Explicit exclusions

- No production user or data edits.
- No production feature-flag enablement.
- No `mongorestore`, `mongoimport`, seed endpoint, or destructive database command.
- No production restart initiated from this pack.
- No Task 4 or Task 4 migration.

## 2. Production environment details

The local workspace does not contain production hostnames, cluster/region, credentials, or a production deployment command. These values must be resolved from the approved secret manager/release system at execution time; they must not be pasted into this document or committed.

| Field | Required value at execution | Local evidence / constraint |
|---|---|---|
| Application/API target | Purchase Workflow 10 | Emergent-confirmed published app |
| Frontend target | Purchase Workflow 10 | Emergent-confirmed published app |
| Cloud account/project | Emergent-managed platform value unavailable to repository | Not exposed locally |
| Region/cluster | Emergent-managed platform value unavailable to repository | Not exposed locally |
| `MONGO_URL` | Secret-manager injection only | Must not be printed |
| `DB_NAME` | Secret-manager injection only | Must not be printed; backup script hashes the name in its manifest |
| Runtime path | `/app/backend` (per local ops scripts) | Confirm on target before execution |
| Backup root | `/app/backup_artifacts/` | Must be off-tree, access-restricted, and outside the application release |
| `ACCESS_SECURITY_V2` | Absent from `/app/backend/.env`; effective Part A value must remain `0` | Required compatibility gate; do not add/change it |

Approval is blocked until the release owner records the release ID, operator, change window, and secret-manager reference in the change ticket. Host, region, cluster, and exact deployment command are Emergent-managed platform values unavailable to this repository.

## 3. Pre-deployment gates

1. Confirm change approval, maintenance window, release artifact checksum, and named rollback owner.
2. Confirm the target is production and the operator is using the approved production account; do not infer either from a hostname.
3. Confirm `ACCESS_SECURITY_V2=0` in the production runtime configuration.
4. Confirm the release contains only the Part A runtime files listed above; exclude test reports, local `.env` files, screenshots, and secrets.
5. Confirm staging regression evidence is attached: Task 3B **30 passed, 0 failed** (Task 3A.2: 14; Task 3B backend: 8; Task 3B frontend: 8).
6. Confirm no pending production user/data operation is bundled with the release.

## 4. Read-only production backup

The backup must complete before any release promotion. The repository-provided backup script is read-only against production and writes only to `/app/backup_artifacts/`.

```bash
cd /app
umask 077
test -n "$MONGO_URL" && test -n "$DB_NAME"
command -v mongodump
python3 /app/backend/scripts/backup_db.py
```

Do not echo `MONGO_URL`, `DB_NAME`, credentials, or connection strings. The script must produce:

```text
/app/backup_artifacts/backup_<UTCstamp>/dump/
/app/backup_artifacts/backup_<UTCstamp>/manifest.json
/app/backup_artifacts/backup_<UTCstamp>/checksums.sha256
/app/backup_artifacts/backup_<UTCstamp>.tar.gz
/app/backup_artifacts/backup_<UTCstamp>.tar.gz.sha256
```

Record the generated `<UTCstamp>`, tarball SHA-256, manifest SHA-256, estimated document count, collection count, index count, and operator in the change ticket. Verify before promotion:

```bash
BACKUP_DIR=/app/backup_artifacts/backup_<UTCstamp>
test -s "$BACKUP_DIR/manifest.json"
test -s "$BACKUP_DIR/checksums.sha256"
sha256sum -c "/app/backup_artifacts/backup_<UTCstamp>.tar.gz.sha256"
(cd "$BACKUP_DIR/dump" && sha256sum -c ../checksums.sha256)
```

If any check fails, stop. Do not promote the release.

## 5. Promotion procedure (approval-gated)

The local workspace has no production deployment CLI. The exact deployment command is **Emergent-managed platform value unavailable to repository**; the release owner must use the approved Emergent promotion mechanism. The promotion must be a code/artifact-only change with `ACCESS_SECURITY_V2=0` and zero database writes.

1. Attach the verified backup manifest/checksums to the change ticket.
2. Promote the approved release artifact to the production API/frontend targets.
3. Verify the runtime configuration still reports `ACCESS_SECURITY_V2=0`.
4. Complete the post-deployment validation below.
5. Close the change only after user/data invariants and health checks pass.

## 6. Rollback procedure

### Code/config rollback

1. Halt the promotion or route traffic away from the new artifact.
2. Restore the previously approved API and frontend artifact/image using the release system.
3. Restore the previous configuration, explicitly keeping `ACCESS_SECURITY_V2=0`.
4. Re-run health and compatibility checks.
5. Record the rollback reason, artifact checksums, timestamps, and operator.

### Data rollback boundary

Part A authorizes no production data writes, so no data rollback should be needed. Do **not** run `restore_to_staging.py` against production and do not run `mongorestore` as an automatic rollback. Any exceptional production restore requires a separate incident/change approval, an explicit target confirmation, and an additional backup.

## 7. Migration impact

**Migration required: No.**

- No collection/index/schema change.
- No user backfill or role normalization.
- No invitations, activations, deactivations, role changes, session revocations, or audit writes.
- Existing users and existing data remain untouched.
- With V2 disabled, existing legacy behavior remains the production behavior; `/api/users/role` compatibility is not changed by Part A.

## 8. User and data protection checks

Capture read-only before/after evidence in the change ticket:

- Existing-user count unchanged.
- Active-user count unchanged.
- Director count and role distribution unchanged.
- Invitation, pending-request, session, MRF, PO, GRN, DC, and audit-log counts unchanged.
- No production write audit events attributable to the deployment window.
- No `ACCESS_SECURITY_V2=1` configuration in any production API/frontend instance.
- No sample/test users or seed data present.
- Backup manifest and both checksum validations pass.
- Release artifact contains no `.env`, token, password, or private key.

Use read-only database queries supplied by the production operator/DBA; do not copy user emails or document contents into the ticket.

## 9. Post-deployment validation

Run from the approved production verification context:

1. API health/root endpoint returns HTTP 200.
2. Frontend loads successfully and static assets return without 5xx errors.
3. Existing authenticated user can perform a read-only `GET /api/auth/me`.
4. With `ACCESS_SECURITY_V2=0`, `/api/admin/access/*` remains unavailable (expected 404/feature-disabled response).
5. Existing legacy user-list/role behavior remains unchanged; do not submit a role mutation.
6. No new production users, invitations, sessions, or audit writes appear.
7. Error rate, latency, authentication failures, and database connection errors remain within the pre-change baseline for the agreed observation window.
8. If any check fails, execute code/config rollback and notify the release owner; do not modify user/data records to “repair” the deployment.

## 10. Approval record

Required before execution:

- Change/ticket ID: `________________`
- Release artifact/checksum: `________________`
- Production target/service: `________________`
- Account/region/cluster: `________________`
- Backup UTC stamp + tar SHA-256: `________________`
- Operator: `________________`
- Rollback owner: `________________`
- Approved change window: `________________`
- Approver: `________________`
- Approval timestamp: `________________`

**Current disposition: Not executable from Codex. Emergent Re-publish handover only; Part A is not executed. Keep `ACCESS_SECURITY_V2=0` until a separate Director-approved release.**
