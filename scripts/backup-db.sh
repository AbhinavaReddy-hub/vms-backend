#!/usr/bin/env bash
#
# Dump the Postgres container to a gzipped file and keep the last N.
#
# With the database now living on this instance rather than a managed service,
# backups are yours to run. The pgdata volume survives restarts, rebuilds and
# reboots - but NOT `docker compose down -v`, and not instance termination.
#
# Run manually:
#     bash scripts/backup-db.sh
#
# Run nightly at 02:30 (edit the path if you cloned somewhere else):
#     crontab -e
#     30 2 * * * cd /home/ubuntu/vms-backend && bash scripts/backup-db.sh >> /home/ubuntu/backup.log 2>&1
#
# Restore from a dump:
#     gunzip -c ~/vms-backups/vms-YYYYmmdd-HHMMSS.sql.gz \
#       | docker compose -f docker-compose.prod.yml exec -T db psql -U <user> -d <dbname>

set -euo pipefail

cd "$(dirname "$0")/.."

COMPOSE_FILE="docker-compose.prod.yml"
ENV_FILE=".env"
BACKUP_DIR="${BACKUP_DIR:-$HOME/vms-backups}"
KEEP="${KEEP:-7}"

if [ ! -f "$ENV_FILE" ]; then
  echo "ERROR: $ENV_FILE not found. Run this from the vms-backend directory." >&2
  exit 1
fi

# Read only the two values needed, rather than sourcing .env. Sourcing would
# break on unquoted values containing spaces (APP_NAME=Visitor Management
# System would run "Management" as a command) and would needlessly pull secrets
# into this shell's environment.
POSTGRES_USER=$(grep -E '^POSTGRES_USER=' "$ENV_FILE" | head -1 | cut -d= -f2-)
POSTGRES_DB=$(grep -E '^POSTGRES_DB=' "$ENV_FILE" | head -1 | cut -d= -f2-)

if [ -z "${POSTGRES_USER:-}" ] || [ -z "${POSTGRES_DB:-}" ]; then
  echo "ERROR: POSTGRES_USER / POSTGRES_DB missing from $ENV_FILE" >&2
  exit 1
fi

mkdir -p "$BACKUP_DIR"
OUT="$BACKUP_DIR/${POSTGRES_DB}-$(date +%Y%m%d-%H%M%S).sql.gz"

echo "==> Dumping database '$POSTGRES_DB' as '$POSTGRES_USER'"

# -T disables TTY allocation, required when running under cron (no terminal).
# The pipeline writes to a .partial file first and only renames on success, so
# an interrupted dump can never masquerade as a good backup.
docker compose -f "$COMPOSE_FILE" --env-file "$ENV_FILE" exec -T db \
  pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" \
  | gzip > "$OUT.partial"

mv "$OUT.partial" "$OUT"
echo "==> Wrote $OUT ($(du -h "$OUT" | cut -f1))"

# Prune old dumps, newest KEEP retained.
COUNT=$(find "$BACKUP_DIR" -name "${POSTGRES_DB}-*.sql.gz" -type f | wc -l)
if [ "$COUNT" -gt "$KEEP" ]; then
  find "$BACKUP_DIR" -name "${POSTGRES_DB}-*.sql.gz" -type f -printf '%T@ %p\n' \
    | sort -n | head -n "$((COUNT - KEEP))" | cut -d' ' -f2- \
    | while read -r old; do
        echo "==> Pruning $(basename "$old")"
        rm -f "$old"
      done
fi

echo "==> Done. $(find "$BACKUP_DIR" -name "${POSTGRES_DB}-*.sql.gz" | wc -l) backup(s) retained."
