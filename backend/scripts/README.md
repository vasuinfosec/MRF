# Vasu MRF — Ops Scripts (Task 2)

Read-only against production. All artefacts land in `/app/backup_artifacts/`
(gitignored). Nothing here is committed with real secrets.

| Script | Purpose | Prod safety |
|---|---|---|
| `backup_db.py` | mongodump prod → BSON + manifest + SHA-256 + tarball | Read-only |
| `staging_guard.py` | Shared safety helper — refuses to write if target DB == prod | — |
| `restore_to_staging.py` | mongorestore INTO isolated staging DB only | Refuses prod write |
| `regression_baseline.py` | Spawns FastAPI on :8002 → staging DB → runs full smoke | Never touches prod |

## Usage

```bash
# 1. Take a backup of production (read-only)
python3 /app/backend/scripts/backup_db.py

# 2. Set staging env vars (in your shell, NOT in tracked .env)
export STAGING_MONGO_URL='mongodb://localhost:27017'
export STAGING_DB_NAME='vasu_mrf_staging'   # MUST differ from prod DB_NAME

# 3. Restore into staging & verify
python3 /app/backend/scripts/restore_to_staging.py \
   --backup-dir /app/backup_artifacts/backup_<stamp>

# 4. Run the regression baseline
python3 /app/backend/scripts/regression_baseline.py
```

## Rollback / removal of Task 2 artefacts

```bash
# Delete all backup artefacts
rm -rf /app/backup_artifacts/

# Drop the staging DB (only ever writable, never prod)
mongosh "$STAGING_MONGO_URL" --eval "db.getSiblingDB('$STAGING_DB_NAME').dropDatabase()"

# Remove the scripts themselves (optional)
rm -rf /app/backend/scripts/
```
