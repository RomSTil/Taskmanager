#!/bin/sh
set -eu

mkdir -p /backups

while true; do
  stamp="$(date -u +%Y%m%d-%H%M%S)"
  target="/backups/$stamp"
  mkdir -p "$target"
  pg_dump --format=custom --file="$target/postgres.dump"
  tar -czf "$target/vault.tar.gz" -C /data vault
  sha256sum "$target/postgres.dump" "$target/vault.tar.gz" > "$target/SHA256SUMS"
  find /backups -mindepth 1 -maxdepth 1 -type d -mtime "+${BACKUP_RETENTION_DAYS:-14}" -exec rm -rf -- {} +
  sleep 86400
done
