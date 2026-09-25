"""Decides which of a page's tables the site has not finished lazy-loading.

The live site renders a long table 120 rows at a time, appending more each
time its last row scrolls into view. The content JSON says how many rows each
table really has, so "done" is a count comparison, not a guess.
"""


def short_tables(rendered: dict[str, int], expected: dict[str, int]) -> dict[str, list[int]]:
    """{table id: [rendered rows, expected rows]} for every table still short.
    A table not on the page at all counts as zero rendered rows."""
    return {
        table_id: [rendered.get(table_id, 0), rows]
        for table_id, rows in expected.items()
        if rendered.get(table_id, 0) < rows
    }
