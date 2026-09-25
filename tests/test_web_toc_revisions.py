from web_toc.parsing.revisions import resolve_revisions

DATE = "2024-03-08"


def _revised_row(*revisions, **current):
    return {"id": "row393", "type": "body_row", "revised": True, **current, "revisions": list(revisions)}


_ORIGINAL = {"type": "original", "effective_date": "2024-03-08", "cells": [{"v": "orig"}]}
_AMENDED = {
    "type": "revision",
    "revision_id": "bc-mo-1",
    "sequence": 1,
    "effective_date": "2025-06-16",
    "status": "current",
    "cells": [{"v": "amended"}],
}
_DELETED = {**_AMENDED, "deleted": True, "cells": []}


def test_content_without_revisions_is_returned_unchanged():
    content = {"id": "s", "rows": [{"id": "r1", "cells": [1]}]}
    assert resolve_revisions(content, DATE) == content


def test_a_revised_item_takes_the_revision_in_effect_on_the_date():
    row = _revised_row(_ORIGINAL, _AMENDED, cells=[{"v": "amended"}])
    assert resolve_revisions(row, DATE) == {"id": "row393", "type": "body_row", "cells": [{"v": "orig"}]}
    assert resolve_revisions(row, "2025-06-16")["cells"] == [{"v": "amended"}]


def test_the_items_own_type_is_kept_not_the_revisions_type():
    row = _revised_row(_ORIGINAL)
    assert resolve_revisions(row, DATE)["type"] == "body_row"


def test_the_latest_of_several_effective_revisions_wins_by_date_then_sequence():
    second = {**_AMENDED, "sequence": 2, "cells": [{"v": "second"}]}
    row = _revised_row(_ORIGINAL, second, _AMENDED)
    assert resolve_revisions(row, "2026-01-01")["cells"] == [{"v": "second"}]


def test_an_item_deleted_by_the_date_is_dropped_from_its_list():
    content = {"rows": [{"id": "r1"}, _revised_row(_ORIGINAL, _DELETED), {"id": "r3"}]}
    assert resolve_revisions(content, "2025-07-01") == {"rows": [{"id": "r1"}, {"id": "r3"}]}
    assert len(resolve_revisions(content, DATE)["rows"]) == 3


def test_an_item_not_yet_in_effect_on_the_date_is_dropped():
    content = {"rows": [_revised_row(_AMENDED)]}
    assert resolve_revisions(content, DATE) == {"rows": []}


def test_revisions_nested_inside_a_chosen_revision_are_resolved_too():
    inner = _revised_row({**_ORIGINAL, "cells": [{"v": "inner-orig"}]}, _AMENDED)
    outer = {
        "id": "s1",
        "type": "sentence",
        "revised": True,
        "revisions": [{"type": "original", "effective_date": DATE, "rows": [inner]}],
    }
    resolved = resolve_revisions({"content": [outer]}, DATE)
    assert resolved["content"][0]["rows"][0]["cells"] == [{"v": "inner-orig"}]


def test_a_revised_root_that_is_deleted_resolves_to_none():
    assert resolve_revisions(_revised_row(_ORIGINAL, _DELETED), "2025-07-01") is None


def test_the_input_is_not_mutated():
    row = _revised_row(_ORIGINAL, _AMENDED, cells=[{"v": "amended"}])
    resolve_revisions({"rows": [row]}, DATE)
    assert row["cells"] == [{"v": "amended"}]
    assert "revisions" in row
