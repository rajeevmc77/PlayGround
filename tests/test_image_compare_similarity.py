from image_compare.analysis.similarity import compare


def test_identical_hashes_are_100_percent_similar():
    result = compare("stem", "0000000000000000", "0000000000000000")
    assert result.hash_distance == 0
    assert result.similarity_percent == 100.0


def test_completely_different_hashes_are_0_percent_similar():
    result = compare("stem", "0000000000000000", "ffffffffffffffff")
    assert result.hash_distance == 64
    assert result.similarity_percent == 0.0


def test_partial_difference_computes_expected_distance_and_percent():
    # 0x1 differs from 0x0 in exactly one bit out of 64.
    result = compare("stem", "0000000000000000", "0000000000000001")
    assert result.hash_distance == 1
    assert result.similarity_percent == round((1 - 1 / 64) * 100, 1)


def test_distance_is_symmetric():
    forward = compare("stem", "00000000000000ff", "000000000000ff00")
    backward = compare("stem", "000000000000ff00", "00000000000000ff")
    assert forward.hash_distance == backward.hash_distance


def test_result_carries_the_given_stem():
    result = compare("my-stem", "0000000000000000", "0000000000000000")
    assert result.stem == "my-stem"
