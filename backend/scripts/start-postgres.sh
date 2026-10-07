#!/usr/bin/env bash
set -euo pipefail

task_backend_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
task_pg_bin="${PG_BIN:-$(dirname "$(command -v initdb)")}"
task_data_dir="$task_backend_dir/.local/postgres"
mkdir -p "$task_backend_dir/.local"

if [ ! -f "$task_data_dir/PG_VERSION" ]; then
  printf '%s\n' 'agent_autopsy' > "$task_backend_dir/.local/postgres-password"
  chmod 600 "$task_backend_dir/.local/postgres-password"
  "$task_pg_bin/initdb" -D "$task_data_dir" -U agent_autopsy \
    --auth=scram-sha-256 --pwfile="$task_backend_dir/.local/postgres-password" \
    --encoding=UTF8 --locale=C
fi

if ! "$task_pg_bin/pg_ctl" -D "$task_data_dir" status >/dev/null 2>&1; then
  "$task_pg_bin/pg_ctl" -D "$task_data_dir" -l "$task_backend_dir/.local/postgres.log" \
    -o '-h 127.0.0.1 -p 55432 -k /tmp' -w start
fi

export PGHOST=127.0.0.1 PGPORT=55432 PGUSER=agent_autopsy PGPASSWORD=agent_autopsy
for task_database in agent_autopsy agent_autopsy_test; do
  if [ "$("$task_pg_bin/psql" -d postgres -tAc "SELECT 1 FROM pg_database WHERE datname='$task_database'")" != "1" ]; then
    "$task_pg_bin/createdb" "$task_database"
  fi
done
printf 'Local development PostgreSQL is ready on 127.0.0.1:55432.\n'
