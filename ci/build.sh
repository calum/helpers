#!/usr/bin/env bash
set -euo pipefail

echo "====== RuneLite Build & Test ======"

chmod +x ./gradlew
./gradlew --no-daemon testAll

echo "\n====== Build & Test Complete ======"

