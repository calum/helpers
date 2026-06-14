from __future__ import annotations

import os
import sys

ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

import pytest


def main() -> int:
    if os.environ.get("GITHUB_ACTIONS") == "true":
        print("GitHub Actions detected; skipping integration tests.")
        test_targets = ["scripts/gamebridge/tests/"]
    else:
        print("Running integration tests by default.")
        os.environ["GAMEBRIDGE_INTEGRATION"] = "1"
        test_targets = ["scripts/gamebridge/tests/", "scripts/gamebridge/tests/integration/"]

    return pytest.main(test_targets + ["-v"])


if __name__ == "__main__":
    raise SystemExit(main())
