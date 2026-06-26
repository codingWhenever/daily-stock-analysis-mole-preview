#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

MODE="${1:-}"
PYTHON_BIN="${PYTHON_BIN:-python3}"
VENV_DIR="${VENV_DIR:-.venv}"
PORT="${PORT:-8000}"
HOST="${HOST:-0.0.0.0}"
LOG_FILE="logs/codespaces-webui.log"
PASSWORD_FILE="data/.preview_admin_password"

mkdir -p data logs reports

sha_file() {
  shasum -a 256 "$1" | awk '{print $1}'
}

ensure_python_deps() {
  if [ ! -x "$VENV_DIR/bin/python" ]; then
    "$PYTHON_BIN" -m venv "$VENV_DIR"
  fi

  local req_hash
  req_hash="$(sha_file requirements.txt)"
  local marker="$VENV_DIR/.codespaces_requirements.sha"
  if [ ! -f "$marker" ] || [ "$(cat "$marker")" != "$req_hash" ]; then
    "$VENV_DIR/bin/python" -m pip install --upgrade pip wheel setuptools
    "$VENV_DIR/bin/python" -m pip install -r requirements.txt
    echo "$req_hash" > "$marker"
  fi
}

ensure_web_build() {
  pushd apps/dsa-web >/dev/null
  local lock_hash
  lock_hash="$(sha_file package-lock.json)"
  local marker="node_modules/.codespaces_package_lock.sha"
  if [ ! -d node_modules ] || [ ! -f "$marker" ] || [ "$(cat "$marker")" != "$lock_hash" ]; then
    npm ci
    mkdir -p node_modules
    echo "$lock_hash" > "$marker"
  fi
  npm run build
  popd >/dev/null
}

write_preview_env() {
  "$VENV_DIR/bin/python" - <<'PY'
from pathlib import Path

env_path = Path(".env")
if env_path.exists():
    lines = env_path.read_text().splitlines()
else:
    lines = []

updates = {
    "WEBUI_ENABLED": "true",
    "WEBUI_HOST": "0.0.0.0",
    "WEBUI_PORT": "8000",
    "WEBUI_AUTO_BUILD": "false",
    "ADMIN_AUTH_ENABLED": "true",
    "DATABASE_PATH": "./data/stock_analysis.db",
    "LOG_DIR": "./logs",
    "SCHEDULE_ENABLED": "false",
    "RUN_IMMEDIATELY": "false",
    "SCHEDULE_RUN_IMMEDIATELY": "false",
    "STOCK_LIST": "510300,159915,VOO,QQQ,SPY",
}

seen = set()
out = []
for line in lines:
    if not line or line.lstrip().startswith("#") or "=" not in line:
        out.append(line)
        continue
    key = line.split("=", 1)[0].strip()
    if key in updates:
        out.append(f"{key}={updates[key]}")
        seen.add(key)
    else:
        out.append(line)

for key, value in updates.items():
    if key not in seen:
        out.append(f"{key}={value}")

env_path.write_text("\n".join(out).rstrip() + "\n")
PY
}

ensure_preview_password() {
  "$VENV_DIR/bin/python" - <<'PY'
from pathlib import Path
import secrets

from src.config import setup_env

setup_env()

from src.auth import has_stored_password, refresh_auth_state, rotate_session_secret, set_initial_password

password_path = Path("data/.preview_admin_password")
password_path.parent.mkdir(parents=True, exist_ok=True)

if not has_stored_password():
    password = secrets.token_urlsafe(14)
    error = set_initial_password(password)
    if error:
        raise SystemExit(error)
    password_path.write_text(password + "\n")
    password_path.chmod(0o600)
    rotate_session_secret()
else:
    refresh_auth_state()
    if not password_path.exists():
        password_path.write_text("password already set; run python -m src.auth reset_password inside the codespace if needed\n")
        password_path.chmod(0o600)
PY
}

is_server_running() {
  "$VENV_DIR/bin/python" - <<PY >/dev/null 2>&1
import urllib.request
urllib.request.urlopen("http://127.0.0.1:${PORT}/api/health", timeout=2).read()
PY
}

start_server() {
  if is_server_running; then
    echo "DSA Web preview is already running on port ${PORT}."
    return
  fi

  nohup env WEBUI_AUTO_BUILD=false \
    "$VENV_DIR/bin/python" main.py --serve-only --host "$HOST" --port "$PORT" \
    >> "$LOG_FILE" 2>&1 &

  for _ in $(seq 1 60); do
    if is_server_running; then
      echo "DSA Web preview is running on port ${PORT}."
      echo "Preview admin password is stored at ${PASSWORD_FILE} inside the codespace."
      return
    fi
    sleep 2
  done

  echo "DSA Web preview did not become healthy. Last log lines:" >&2
  tail -80 "$LOG_FILE" >&2 || true
  exit 1
}

ensure_python_deps
ensure_web_build
write_preview_env
ensure_preview_password

case "$MODE" in
  --setup-only)
    echo "Codespaces preview setup complete."
    ;;
  --serve-only|"")
    start_server
    ;;
  *)
    echo "Unknown mode: $MODE" >&2
    exit 2
    ;;
esac
