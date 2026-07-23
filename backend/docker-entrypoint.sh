#!/bin/sh
set -eu

mkdir -p /data/vault
chown -R taskman:taskman /data /app

if [ "$(id -u)" = "0" ]; then
  exec su taskman -s /bin/sh -c "$*"
fi

exec "$@"
