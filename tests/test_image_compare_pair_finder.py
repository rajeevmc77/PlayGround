from image_compare.parsing.pair_finder import find_pairs


def test_matches_files_with_same_stem_different_extension():
    result = find_pairs(["figure1.png"], ["figure1.jpg"])
    assert len(result.matched) == 1
    assert result.matched[0].stem == "figure1"
    assert result.matched[0].pdf_filename == "figure1.png"
    assert result.matched[0].web_filename == "figure1.jpg"


def test_only_the_last_extension_is_stripped_from_a_dotted_stem():
    result = find_pairs(
        ["nbc.divA.part1.appendix.appnote2b.figure1.png"],
        ["nbc.divA.part1.appendix.appnote2b.figure1.jpg"],
    )
    assert result.matched[0].stem == "nbc.divA.part1.appendix.appnote2b.figure1"


def test_pdf_file_with_no_web_counterpart_is_reported_as_pdf_only():
    result = find_pairs(["orphan.png"], [])
    assert result.matched == []
    assert result.pdf_only == ["orphan.png"]
    assert result.web_only == []


def test_web_file_with_no_pdf_counterpart_is_reported_as_web_only():
    result = find_pairs([], ["orphan.jpg"])
    assert result.matched == []
    assert result.pdf_only == []
    assert result.web_only == ["orphan.jpg"]


def test_empty_inputs_return_empty_result():
    result = find_pairs([], [])
    assert result.matched == []
    assert result.pdf_only == []
    assert result.web_only == []


def test_matched_pairs_are_sorted_by_stem_regardless_of_input_order():
    result = find_pairs(["b.png", "a.png"], ["a.jpg", "b.jpg"])
    assert [pair.stem for pair in result.matched] == ["a", "b"]


def test_unmatched_files_are_sorted():
    result = find_pairs(["z.png", "a.png"], [])
    assert result.pdf_only == ["a.png", "z.png"]


def test_matched_and_unmatched_can_coexist():
    result = find_pairs(["a.png", "pdf_only.png"], ["a.jpg", "web_only.jpg"])
    assert [pair.stem for pair in result.matched] == ["a"]
    assert result.pdf_only == ["pdf_only.png"]
    assert result.web_only == ["web_only.jpg"]
