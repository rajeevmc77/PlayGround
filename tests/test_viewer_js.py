"""Runs the viewer's pure JavaScript helpers' own tests (tests/js/, Node's
built-in test runner) as part of the normal pytest suite."""

import shutil
import subprocess
from pathlib import Path

import pytest

JS_TESTS = Path(__file__).resolve().parent / "js"


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js is not installed")
def test_viewer_js_unit_tests_pass():
    files = sorted(str(path) for path in JS_TESTS.glob("*.test.mjs"))
    result = subprocess.run(["node", "--test", *files], capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stdout + result.stderr
