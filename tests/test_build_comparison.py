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

import build_comparison
from build_comparison import main, run
from image_compare.domain.models import ComparisonResult


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


def _score_every_image_pair(monkeypatch, similarity_percent):
    """Stands in for the phash step with a fixed score, so the threshold
    decision is what's under test."""
    monkeypatch.setattr(
        build_comparison,
        "compare_images",
        lambda stem, _pdf_bytes, _web_bytes: ComparisonResult(stem, 0, similarity_percent),
    )


def _rename_image(tmp_path, unified_number):
    for name in ("bcbc_pdf.json", "bcbc_web.json"):
        payload = json.loads((tmp_path / name).read_text())
        payload["images"][0]["unified_number"] = unified_number
        (tmp_path / name).write_text(json.dumps(payload))


def test_an_equation_passes_at_75_percent_where_a_figure_fails(tmp_path, monkeypatch):
    """A PDF formula raster (small, its own typeface) against the site's
    MathJax render tops out lower than a figure pair does: on the real data,
    correct equation pairs score a median 75% and no wrong pair reached 70%,
    so equations get their own 70% bar while figures keep 80%."""
    _score_every_image_pair(monkeypatch, 75.0)
    _write_fixtures(tmp_path)
    run(str(tmp_path))
    assert json.loads((tmp_path / "comparison.json").read_text())["statuses"]["V.P1.Fig1"] is False

    _rename_image(tmp_path, "V.P1.Eq1")
    run(str(tmp_path))
    assert json.loads((tmp_path / "comparison.json").read_text())["statuses"]["V.P1.Eq1"] is True


def test_an_equation_still_fails_below_70_percent(tmp_path, monkeypatch):
    _score_every_image_pair(monkeypatch, 69.9)
    _write_fixtures(tmp_path)
    _rename_image(tmp_path, "V.P1.Eq1")
    run(str(tmp_path))
    assert json.loads((tmp_path / "comparison.json").read_text())["statuses"]["V.P1.Eq1"] is False


def _table_payload(rows, root_key):
    def row(r, cells):
        return {
            "unified_number": f"V.Tbl1.Row{r + 1}",
            "citation": f"t-r{r + 1}",
            "type": "Row",
            "content": "",
            "children": [
                {
                    "unified_number": f"V.Tbl1.Row{r + 1}.Col{c + 1}",
                    "citation": f"t-r{r + 1}-c{c + 1}",
                    "type": "Cell",
                    "content": text,
                    "children": [],
                }
                for c, text in enumerate(cells)
            ],
        }

    table = {
        "unified_number": "V.Tbl1",
        "citation": "t",
        "type": "Table",
        "content": "",
        "children": [row(r, cells) for r, cells in enumerate(rows)],
    }
    tree = {"unified_number": "V", "citation": "volume", "content": "", "children": [table]}
    return {root_key: tree, "images": []}


def test_table_rows_pair_by_content_and_the_pairing_is_recorded(tmp_path):
    """The web has a row the PDF lacks; the PDF's second row pairs with the
    web's third, passes, and comparison.json records that counterpart (only
    pairings that differ from the same number are written) so the viewer can
    follow it."""
    (tmp_path / "bcbc_pdf.json").write_text(json.dumps(_table_payload([["x"], ["z"]], "volume")))
    web = _table_payload([["x"], ["y"], ["z"]], "tree")
    (tmp_path / "bcbc_web.json").write_text(json.dumps(web))

    run(str(tmp_path))

    result = json.loads((tmp_path / "comparison.json").read_text())
    assert result["statuses"]["V.Tbl1.Row2.Col1"] is True
    assert result["counterparts"] == {
        "V.Tbl1.Row2": "V.Tbl1.Row3",
        "V.Tbl1.Row2.Col1": "V.Tbl1.Row3.Col1",
    }


def test_an_unpaired_pdf_row_is_recorded_with_no_counterpart(tmp_path):
    pdf = _table_payload([["x"], ["extra"], ["z"]], "volume")
    (tmp_path / "bcbc_pdf.json").write_text(json.dumps(pdf))
    (tmp_path / "bcbc_web.json").write_text(json.dumps(_table_payload([["x"], ["z"]], "tree")))

    run(str(tmp_path))

    counterparts = json.loads((tmp_path / "comparison.json").read_text())["counterparts"]
    assert counterparts["V.Tbl1.Row2"] is None
    assert counterparts["V.Tbl1.Row3"] == "V.Tbl1.Row2"


def test_the_equation_threshold_is_recorded(tmp_path):
    _write_fixtures(tmp_path)
    run(str(tmp_path))
    assert (
        json.loads((tmp_path / "comparison.json").read_text())["equation_threshold_percent"] == 70.0
    )


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


def test_each_failed_item_is_recorded_with_why_it_differs(tmp_path):
    _write_fixtures(tmp_path, pdf_content="Class A roofing", web_content="Class B roofing")

    run(str(tmp_path))

    reasons = json.loads((tmp_path / "comparison.json").read_text())["reasons"]
    assert reasons["V.P1"]["kind"] == "text"
    assert reasons["V.P1"]["edits"][0]["pdf"][1] == "A"
    assert "V" not in reasons  # a container's ✗ comes from the item inside it


def test_a_comparison_where_everything_matches_records_no_reasons(tmp_path):
    _write_fixtures(tmp_path)

    run(str(tmp_path))

    assert json.loads((tmp_path / "comparison.json").read_text())["reasons"] == {}
