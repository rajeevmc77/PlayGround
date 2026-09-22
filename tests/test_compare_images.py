from pathlib import Path

import compare_images
from image_compare.domain.models import ComparisonResult, MatchedStem, PairingResult

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def test_format_report_lists_matched_pairs_with_similarity():
    pairing = PairingResult(matched=[MatchedStem("a", "a.png", "a.jpg")])
    results = [ComparisonResult(stem="a", hash_distance=2, similarity_percent=96.9)]
    report = compare_images.format_report(pairing, results)
    assert "a" in report
    assert "96.9" in report
    assert "2" in report


def test_format_report_lists_pdf_only_and_web_only_files():
    pairing = PairingResult(pdf_only=["orphan.png"], web_only=["other.jpg"])
    report = compare_images.format_report(pairing, [])
    assert "orphan.png" in report
    assert "other.jpg" in report


def test_format_report_on_fully_matched_input_has_no_unmatched_section_noise():
    pairing = PairingResult(matched=[MatchedStem("a", "a.png", "a.jpg")])
    results = [ComparisonResult(stem="a", hash_distance=0, similarity_percent=100.0)]
    report = compare_images.format_report(pairing, results)
    assert "none" in report.lower()


def test_build_comparison_against_the_real_sample_folder():
    pairing, results = compare_images.build_comparison(
        PROJECT_ROOT / "compare-images" / "pdf", PROJECT_ROOT / "compare-images" / "web"
    )
    assert pairing.pdf_only == []
    assert pairing.web_only == []
    by_stem = {result.stem: result for result in results}
    assert by_stem["nbc.divA.part1.appendix.appnote2b.figure1"].hash_distance == 26
    assert by_stem["nbc.divA.part1.appendix.appnote6.figure1"].hash_distance == 2
    assert by_stem["nbc.divA.part1.appendix.appnote7.div18.figure1"].hash_distance == 2
