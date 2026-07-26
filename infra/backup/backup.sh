#!/bin/sh
# Nightly encrypted pg_dump placeholder (FR-081a). Real script lands in ops-backup-purge.
set -eu
echo "backup.fail reason=not_implemented" >&2
exit 1
