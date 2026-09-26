from comparison.text_similarity import matches, similarity_percent


def test_identical_text_is_100_percent_similar():
    assert similarity_percent("Hello world", "Hello world") == 100.0


def test_both_empty_is_treated_as_a_trivial_match():
    assert similarity_percent("", "") == 100.0
    assert matches("", "") is True


def test_completely_different_text_scores_low():
    assert similarity_percent("abcdefgh", "zyxwvuts") < 50.0


def test_whitespace_and_case_differences_do_not_affect_similarity():
    assert similarity_percent("Part 3  Fire Protection", "part 3 fire protection") == 100.0


def test_matches_is_true_at_or_above_the_threshold():
    a, b = "almost the same text here", "almost the same text herr"
    assert matches(a, b, threshold_percent=80.0) is True


def test_matches_is_false_below_the_threshold():
    a, b = "completely unrelated content", "totally different words"
    assert matches(a, b, threshold_percent=80.0) is False


def test_matches_defaults_to_80_percent_threshold():
    assert matches("x" * 8, "y" * 8) is False


def test_normalizes_away_stray_whitespace_before_punctuation():
    # The PDF and web extraction pipelines disagree on whether a citation
    # like "3.2.8." gets a space before the trailing period - purely
    # cosmetic, not a real content difference.
    a, b = "see Subsection 3.2.8., provided", "see Subsection 3.2.8 ., provided"
    assert similarity_percent(a, b) == 100.0


def test_one_sided_empty_content_is_not_a_trivial_match():
    assert matches("some real content", "") is False
