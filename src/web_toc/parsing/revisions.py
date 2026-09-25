"""Reads the site's content JSON as of one effective date.

A revised item (`"revised": true`) keeps its *current* version in its own
fields and its history in `revisions`: an "original" plus dated amendments,
some of which delete the item. The saved pages are rendered for one date, so
the JSON must be read as of that same date for its structure (a table's
rows and cells, a sentence's clauses) to line up with what was rendered.
Pure: returns a new structure, never mutates its input.
"""

# Bookkeeping fields of a revision entry - never copied onto the item.
_REVISION_META = frozenset(
    {
        "type",
        "revision_type",
        "revision_id",
        "sequence",
        "effective_date",
        "status",
        "deleted",
        "change_summary",
        "note",
    }
)
# The item's own history markers - dropped once one version is chosen.
_ITEM_HISTORY = frozenset({"revisions", "revised"})
_DROPPED = object()


def _in_effect(revisions: list[dict], date: str) -> dict | None:
    effective = [r for r in revisions if r.get("effective_date", "") <= date]
    if not effective:
        return None
    return max(effective, key=lambda r: (r.get("effective_date", ""), r.get("sequence", 0)))


def _without(fields: dict, keys: frozenset) -> dict:
    return {key: value for key, value in fields.items() if key not in keys}


def _as_of(item: dict, date: str):
    """The item itself, or - if revised - the version in effect on `date`."""
    if not isinstance(item.get("revisions"), list):
        return item
    revision = _in_effect(item["revisions"], date)
    if revision is None or revision.get("deleted"):
        return _DROPPED
    return {**_without(item, _ITEM_HISTORY), **_without(revision, _REVISION_META)}


def _resolve_list(items: list, date: str) -> list:
    resolved = (_resolve(item, date) for item in items)
    return [item for item in resolved if item is not _DROPPED]


def _resolve(node, date: str):
    if isinstance(node, list):
        return _resolve_list(node, date)
    if not isinstance(node, dict):
        return node
    node = _as_of(node, date)
    if node is _DROPPED:
        return _DROPPED
    return {key: _resolve(value, date) for key, value in node.items()}


def resolve_revisions(content, date: str):
    """`content` as it stood on `date` (ISO yyyy-mm-dd); None if the whole
    item was deleted, or not yet in effect, on that date."""
    resolved = _resolve(content, date)
    return None if resolved is _DROPPED else resolved
