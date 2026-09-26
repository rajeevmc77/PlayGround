"""build_comparison.py joins bcbc_pdf.json and bcbc_web.json on unified_number
and writes output/comparison.json - these tests lay out tiny fixture JSON
(plus two real, deliberately-identical raster images so the phash step has
real bytes to hash) and read back what it writes."""

import io
import json
import sys
from pathlib import Path

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from build_comparison import main, run


def _png_bytes(color) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (40, 40), color).save(buf, format="PNG")
    return buf.getvalue()


def _write_fixtures(
    tmp_path, pdf_content="same text", web_content="same text", pdf_emphasis=(), web_emphasis=()
):
    pdf_payload = {
        "volume": {
            "unified_number": "V",
            "citation": "volume",
            "content": "",
            "children": [
                {
                    "unified_number": "V.P1",
                    "citation": "part1",
                    "content": pdf_content,
                    "emphasis": list(pdf_emphasis),
                    "children": [],
                }
            ],
        },
        "images": [
            {
                "unified_number": "V.P1.Fig1",
                "owner_citation": "part1",
                "image_path": "images/img_0.png",
            }
        ],
    }
    web_payload = {
        "tree": {
            "unified_number": "V",
            "citation": "volume",
            "content": "",
            "children": [
                {
                    "unified_number": "V.P1",
                    "citation": "part1",
                    "content": web_content,
                    "emphasis": list(web_emphasis),
                    "children": [],
                }
            ],
        },
        "images": [
            {
                "unified_number": "V.P1.Fig1",
                "owner_citation": "part1",
                "local_path": "web_images/fig1.png",
            }
        ],
    }
    (tmp_path / "bcbc_pdf.json").write_text(json.dumps(pdf_payload))
    (tmp_path / "bcbc_web.json").write_text(json.dumps(web_payload))
    (tmp_path / "images").mkdir()
    (tmp_path / "web_images").mkdir()
    (tmp_path / "images" / "img_0.png").write_bytes(_png_bytes((10, 20, 30)))
    (tmp_path / "web_images" / "fig1.png").write_bytes(_png_bytes((10, 20, 30)))


def test_writes_comparison_json_with_matching_text_and_images(tmp_path):
    _write_fixtures(tmp_path)

    run(str(tmp_path))

    result = json.loads((tmp_path / "comparison.json").read_text())
    assert result["threshold_percent"] == 80.0
    assert result["statuses"]["V.P1"] is True
    assert result["statuses"]["V.P1.Fig1"] is True
    assert result["statuses"]["V"] is True


def test_mismatched_text_fails_the_node_but_not_its_matching_image(tmp_path):
    _write_fixtures(
        tmp_path, pdf_content="pdf-only text here", web_content="completely different web text"
    )

    run(str(tmp_path))

    result = json.loads((tmp_path / "comparison.json").read_text())
    assert result["statuses"]["V.P1"] is False
    assert result["statuses"]["V.P1.Fig1"] is True


def test_text_differing_only_in_whitespace_passes(tmp_path):
    _write_fixtures(
        tmp_path, pdf_content="fire- resistance  rating", web_content="fire-resistance rating"
    )

    run(str(tmp_path))

    assert json.loads((tmp_path / "comparison.json").read_text())["statuses"]["V.P1"] is True


def test_a_one_character_text_difference_fails(tmp_path):
    _write_fixtures(tmp_path, pdf_content="Class A roofing", web_content="Class B roofing")

    run(str(tmp_path))

    assert json.loads((tmp_path / "comparison.json").read_text())["statuses"]["V.P1"] is False


def test_the_same_text_with_different_italics_fails(tmp_path):
    _write_fixtures(
        tmp_path,
        pdf_content="a new building",
        web_content="a new building",
        pdf_emphasis=[[6, 14, "i"]],
    )

    run(str(tmp_path))

    assert json.loads((tmp_path / "comparison.json").read_text())["statuses"]["V.P1"] is False


def test_missing_image_file_on_disk_fails_that_image_without_erroring(tmp_path):
    _write_fixtures(tmp_path)
    (tmp_path / "web_images" / "fig1.png").unlink()

    run(str(tmp_path))

    result = json.loads((tmp_path / "comparison.json").read_text())
    assert result["statuses"]["V.P1.Fig1"] is False


def test_missing_web_toc_json_fails_every_node(tmp_path):
    _write_fixtures(tmp_path)
    (tmp_path / "bcbc_web.json").unlink()

    run(str(tmp_path))

    result = json.loads((tmp_path / "comparison.json").read_text())
    assert result["statuses"]["V.P1"] is False


def test_custom_threshold_percent_is_recorded(tmp_path):
    _write_fixtures(tmp_path)

    run(str(tmp_path), threshold_percent=90.0)

    result = json.loads((tmp_path / "comparison.json").read_text())
    assert result["threshold_percent"] == 90.0


def test_main_parses_output_dir_and_threshold_percent_arguments(tmp_path, monkeypatch):
    _write_fixtures(tmp_path)
    monkeypatch.setattr(
        sys,
        "argv",
        ["build_comparison.py", "--output-dir", str(tmp_path), "--threshold-percent", "50"],
    )

    main()

    result = json.loads((tmp_path / "comparison.json").read_text())
    assert result["threshold_percent"] == 50.0
