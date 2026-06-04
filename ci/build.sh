#!/usr/bin/env bash
set -euo pipefail

if command -v python3 >/dev/null 2>&1; then
    PYTHON=python3
elif command -v python >/dev/null 2>&1; then
    PYTHON=python
else
    echo "ERROR: Python is not installed or not on PATH." >&2
    exit 1
fi

echo "====== GameBridge Build & Test ======"

echo "\n[1/3] Installing Python test dependencies..."
$PYTHON -m pip install --upgrade pip setuptools
$PYTHON -m pip install -r scripts/gamebridge/requirements.txt

echo "[2/3] Running Python unit tests..."
$PYTHON -m pytest scripts/gamebridge/tests/ -v

echo "[3/3] Running Java build and tests..."
chmod +x ./gradlew
./gradlew --no-daemon testAll

echo "\n====== Build & Test Complete ======"

