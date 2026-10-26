#!/usr/bin/env bash
# ==========================================
# Function: Launch TeleMail from its own project directory.
# Method: Resolve this script location and forward arguments to Python.
# ==========================================
set -euo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")"
exec "${TELEMAIL_PYTHON:-python3}" -m maildesk "$@"
