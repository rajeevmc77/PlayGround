import json

from llm_compare.output.cache import VerdictCache, cache_key, pair_cache_key
from tests.llm_compare_support import prepared_pair


def test_the_key_is_stable_and_changes_with_every_component():
    base = cache_key(b"a", b"b", "v1", "m")
    assert base == cache_key(b"a", b"b", "v1", "m")
    assert (
        len(
            {
                base,
                cache_key(b"x", b"b", "v1", "m"),
                cache_key(b"a", b"x", "v1", "m"),
                cache_key(b"a", b"b", "v2", "m"),
                cache_key(b"a", b"b", "v1", "n"),
            }
        )
        == 5
    )


def test_parts_cannot_be_shifted_between_fields_to_collide():
    assert cache_key(b"ab", b"c", "v", "m") != cache_key(b"a", b"bc", "v", "m")


def test_pair_cache_key_uses_the_prepared_png_bytes():
    pair = prepared_pair()
    assert pair_cache_key(pair, "v1", "m") == cache_key(pair.pdf.png, pair.web.png, "v1", "m")


def test_entries_round_trip_through_a_file(tmp_path):
    path = tmp_path / "nested" / "cache.json"
    cache = VerdictCache(path)
    cache.put("k", {"verdict": "IDENTICAL", "differences": []})
    cache.save()
    assert VerdictCache(path).get("k") == {"verdict": "IDENTICAL", "differences": []}
    assert [p.name for p in path.parent.iterdir()] == ["cache.json"]


def test_a_missing_key_gives_none_and_a_memory_cache_never_writes(tmp_path):
    cache = VerdictCache()
    assert cache.get("nope") is None
    cache.put("k", {"x": 1})
    cache.save()
    assert cache.get("k") == {"x": 1}
    assert list(tmp_path.iterdir()) == []


def test_entries_that_are_not_objects_are_dropped_on_load(tmp_path):
    path = tmp_path / "cache.json"
    path.write_text(json.dumps({"good": {"x": 1}, "list": [1], "text": "IDENTICAL", "none": None}))
    cache = VerdictCache(path)
    assert cache.get("good") == {"x": 1}
    assert [cache.get(key) for key in ("list", "text", "none")] == [None, None, None]


def test_a_corrupt_file_loads_as_empty_and_is_overwritten_on_save(tmp_path):
    path = tmp_path / "cache.json"
    path.write_text("{not json")
    cache = VerdictCache(path)
    assert cache.get("k") is None
    cache.put("k", {"x": 1})
    cache.save()
    assert json.loads(path.read_text()) == {"k": {"x": 1}}
