# /// script
# requires-python = ">=3.12"
# dependencies = [
#     "pytest==9.1.1",
#     "pyyaml==6.0.3",
# ]
# ///
"""Run the retropack test suite through uv (security review F6).

The PEP 723 block above is the single source of truth for test dependencies —
exact pins, no `pip install` anywhere. hk and CI both run
`uv run scripts/run-tests.py`, so the env is identical locally and on runners;
run-tests.py.lock pins the transitive tree on top of the direct pins.
Extra pytest args pass through: `uv run scripts/run-tests.py -k watch`.
"""
import pathlib
import sys

import pytest

TESTS = pathlib.Path(__file__).resolve().parent.parent / "tests"
sys.exit(pytest.main([str(TESTS), "-q", *sys.argv[1:]]))
