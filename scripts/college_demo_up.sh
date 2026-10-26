#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

PID_FILE="/tmp/nutrilens_college_demo.pid"
LOG_FILE="/tmp/nutrilens_college_demo.log"

echo "=== Starting NutriLens X College Demo Environment ==="

if [ -f "${PID_FILE}" ]; then
    PID="$(cat "${PID_FILE}")"
    if kill -0 "${PID}" 2>/dev/null; then
        # Check command line of existing PID to verify ownership
        CMDLINE="$(ps -p "${PID}" -o cmd= 2>/dev/null || echo "")"
        if echo "${CMDLINE}" | grep -q "college_demo_daemon.py"; then
            echo "College demo server is already running with PID ${PID}."
            exit 0
        else
            echo "PID in ${PID_FILE} does not match college demo. Cleaning stale PID file."
            rm -f "${PID_FILE}"
        fi
    else
        echo "Cleaning stale PID file."
        rm -f "${PID_FILE}"
    fi
fi

# Check if port 8000 is occupied
OCCUPIED_PID="$(lsof -ti:8000 2>/dev/null || true)"
if [ -n "${OCCUPIED_PID}" ]; then
    # Verify if the occupied process is actually an untracked college_demo_daemon.py
    for p in ${OCCUPIED_PID}; do
        P_CMD="$(ps -p "${p}" -o cmd= 2>/dev/null || echo "")"
        if echo "${P_CMD}" | grep -q "college_demo_daemon.py"; then
            echo "Found running college demo on port 8000 with PID ${p}. Updating PID file."
            echo "${p}" > "${PID_FILE}"
            exit 0
        fi
    done
    echo "PORT_8000_OCCUPIED_BY_OTHER_PROCESS"
    exit 1
fi

VENV_PYTHON="/tmp/fast-venv-312/bin/python"
if [ ! -x "${VENV_PYTHON}" ]; then
    if [ -x "${REPO_ROOT}/.venv/bin/python" ]; then
        VENV_PYTHON="${REPO_ROOT}/.venv/bin/python"
    elif command -v python3 >/dev/null 2>&1; then
        VENV_PYTHON="$(command -v python3)"
    else
        echo "Error: Python interpreter not found." >&2
        exit 1
    fi
fi

cd "${REPO_ROOT}"

echo "Launching daemon with ${VENV_PYTHON}..."
"${VENV_PYTHON}" -c "
import subprocess
import os

env = os.environ.copy()
env['APP_ENVIRONMENT'] = 'development'
env['COLLEGE_DEMO_MODE'] = 'true'
env['PERSISTENCE_BACKEND'] = 'postgres'
env['RATE_LIMIT_BACKEND'] = 'memory'

with open('/tmp/nutrilens_college_demo.log', 'a') as log:
    proc = subprocess.Popen(
        ['${VENV_PYTHON}', 'scripts/college_demo_daemon.py'],
        cwd='${REPO_ROOT}',
        env=env,
        stdout=log,
        stderr=log,
        start_new_session=True
    )
    with open('/tmp/nutrilens_college_demo.pid', 'w') as pid_file:
        pid_file.write(str(proc.pid))
"

echo "Waiting for server to become responsive..."
for i in {1..30}; do
    if curl -s http://127.0.0.1:8000/health >/dev/null 2>&1; then
        echo "NutriLens X College Demo server is UP (PID: $(cat "${PID_FILE}"))."
        echo "Logs: ${LOG_FILE}"
        exit 0
    fi
    sleep 0.5
done

echo "Error: Server failed to start within 15 seconds. Last 20 lines of log:" >&2
tail -n 20 "${LOG_FILE}" >&2
exit 1
