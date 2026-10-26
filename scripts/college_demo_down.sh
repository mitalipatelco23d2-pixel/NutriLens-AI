#!/usr/bin/env bash
set -euo pipefail

PID_FILE="/tmp/nutrilens_college_demo.pid"

echo "=== Stopping NutriLens X College Demo Environment ==="

if [ -f "${PID_FILE}" ]; then
    PID="$(cat "${PID_FILE}")"
    if kill -0 "${PID}" 2>/dev/null; then
        CMDLINE="$(ps -p "${PID}" -o cmd= 2>/dev/null || echo "")"
        if echo "${CMDLINE}" | grep -q "college_demo_daemon.py"; then
            echo "Stopping college demo server (PID ${PID})..."
            kill "${PID}" || true
            for i in {1..10}; do
                if ! kill -0 "${PID}" 2>/dev/null; then
                    break
                fi
                sleep 0.5
            done
            if kill -0 "${PID}" 2>/dev/null; then
                echo "Force killing PID ${PID}..."
                kill -9 "${PID}" || true
            fi
        else
            echo "Warning: PID ${PID} does not belong to NutriLens college demo daemon; refusing to terminate."
        fi
    fi
    rm -f "${PID_FILE}"
fi

echo "NutriLens X College Demo server is stopped."
