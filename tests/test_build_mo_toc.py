import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from unittest.mock import patch

import pytest

from build_mo_toc import main, run


def test_run_writes_mo_pdf_json_not_mo_toc_json(tmp_path):
    fake_lines = [[]]
    with (
        patch("build_mo_toc.extract_all_pages", return_value=(fake_lines, [], [[]])),
        patch("build_mo_toc.write_images", return_value=[]),
    ):
        run(pdf_path="unused.pdf", output_dir=str(tmp_path))

    assert (tmp_path / "mo_pdf.json").exists()
    assert not (tmp_path / "mo_toc.json").exists()
    payload = json.loads((tmp_path / "mo_pdf.json").read_text())
    assert payload["volume"]["type"] == "Volume"


def test_main_exits_when_pdf_missing(tmp_path, monkeypatch):
    missing_pdf = str(tmp_path / "nope.pdf")
    monkeypatch.setattr(sys, "argv", ["build_mo_toc.py", missing_pdf])

    with pytest.raises(SystemExit) as exc_info:
        main()

    assert "No such file" in str(exc_info.value)
