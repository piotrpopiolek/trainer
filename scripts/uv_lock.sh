#!/bin/bash
set -euo pipefail
apt-get update -qq
apt-get install -y -qq curl ca-certificates >/dev/null
curl -LsSf https://astral.sh/uv/0.7.12/install.sh | sh
export PATH="$HOME/.local/bin:$PATH"
cd /app
uv lock
