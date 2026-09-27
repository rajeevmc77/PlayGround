"""table_counterparts pairs a table's PDF rows with its web rows by content,
not position: one row present on only one side (B.9.38.1.1 has 88 more on
the web) used to shift every row below it, so the cells compared were never
the same cells. Rows are aligned on their whole text; identical runs pair
one-to-one, a block of differing rows pairs by position inside the block
(so a table with no identical rows at all falls back to plain positional
pairing), and a row only one side has stays unpaired. Cells pair by column
within paired rows."""

from comparison.row_alignment import table_counterparts, table_pairs


# Tables within an article/note are paired the same way, on their titles:
# B.A-9.36.2.4.(1)'s web note has four untitled worked-example tables among
# its four captioned ones, so by position every PDF table met the wrong one.
def _titled(title):
    return {"type": "Table", "title": title, "children": []}


def test_tables_pair_on_their_titles_past_untitled_tables_only_one_side_has():
    pdf = [_titled("Values for K1 and K2"), _titled("Thermal Resistance Values(1)")]
    web = [
        _titled(""),
        _titled("Values for K_{1} and K_{2}"),
        _titled(""),
        _titled("Thermal Resistance Values^{(1)}"),
    ]
    assert table_pairs(pdf, web) == {0: 1, 1: 3}


def test_a_pdf_titles_forming_part_of_tail_is_ignored():
    pdf = [_titled("Rise for Treads Forming Part of Sentence 9.8.4.1.(1)")]
    assert table_pairs(pdf, [_titled(""), _titled("Rise for Treads")]) == {0: 1}


def test_tables_with_no_matching_titles_pair_by_position():
    pdf = [_titled(""), _titled("PDF only")]
    web = [_titled(""), _titled("Web only"), _titled("Extra")]
    assert table_pairs(pdf, web) == {0: 0, 1: 1}


def test_no_tables_on_one_side_pair_nothing():
    assert table_pairs([_titled("A")], []) == {}
    assert table_pairs([], [_titled("A")]) == {}


def _table(number, rows):
    return {
        "unified_number": number,
        "type": "Table",
        "children": [
            {
                "unified_number": f"{number}.Row{r + 1}",
                "type": "Row",
                "children": [
                    {
                        "unified_number": f"{number}.Row{r + 1}.Col{c + 1}",
                        "type": "Cell",
                        "content": text,
                    }
                    for c, text in enumerate(cells)
                ],
            }
            for r, cells in enumerate(rows)
        ],
    }


def test_identical_tables_pair_every_row_and_cell_with_its_own_number():
    rows = [["a", "1"], ["b", "2"]]
    counterparts = table_counterparts(_table("T", rows), _table("T", rows))
    assert counterparts["T.Row2"] == "T.Row2"
    assert counterparts["T.Row2.Col1"] == "T.Row2.Col1"


def test_a_row_only_the_web_has_no_longer_shifts_the_rows_below_it():
    pdf = _table("T", [["a", "1"], ["c", "3"]])
    web = _table("T", [["a", "1"], ["b", "2"], ["c", "3"]])
    counterparts = table_counterparts(pdf, web)
    assert counterparts["T.Row1"] == "T.Row1"
    assert counterparts["T.Row2"] == "T.Row3"
    assert counterparts["T.Row2.Col2"] == "T.Row3.Col2"


def test_a_row_only_the_pdf_has_is_unpaired_and_so_are_its_cells():
    pdf = _table("T", [["a", "1"], ["x", "9"], ["c", "3"]])
    web = _table("T", [["a", "1"], ["c", "3"]])
    counterparts = table_counterparts(pdf, web)
    assert counterparts["T.Row2"] is None
    assert counterparts["T.Row2.Col1"] is None
    assert counterparts["T.Row3"] == "T.Row2"


def test_differing_rows_pair_by_position_inside_their_block():
    """A row whose text differs a little (a typo, a note marker) sits in a
    'differing' block with its counterpart; pairing inside the block is by
    position, so it still meets the web row it corresponds to."""
    pdf = _table("T", [["a", "1"], ["b", "2(7)"], ["c", "3"]])
    web = _table("T", [["a", "1"], ["b", "2"], ["c", "3"]])
    counterparts = table_counterparts(pdf, web)
    assert counterparts["T.Row2"] == "T.Row2"
    assert counterparts["T.Row2.Col2"] == "T.Row2.Col2"


def test_a_table_with_no_identical_rows_falls_back_to_position():
    pdf = _table("T", [["p1"], ["p2"], ["p3"]])
    web = _table("T", [["w1"], ["w2"]])
    counterparts = table_counterparts(pdf, web)
    assert [counterparts[f"T.Row{n}"] for n in (1, 2, 3)] == ["T.Row1", "T.Row2", None]


def test_a_pdf_cell_beyond_the_paired_web_rows_width_is_unpaired():
    pdf = _table("T", [["a", "1", "extra"]])
    web = _table("T", [["a", "1"]])
    counterparts = table_counterparts(pdf, web)
    assert counterparts["T.Row1.Col2"] == "T.Row1.Col2"
    assert counterparts["T.Row1.Col3"] is None


def test_rows_align_on_text_with_whitespace_quotes_and_dashes_made_plain():
    pdf = _table("T", [["x"], ["fire- resistance – 1 h"], ["z"]])
    web = _table("T", [["new"], ["x"], ["fire-resistance - 1 h"], ["z"]])
    counterparts = table_counterparts(pdf, web)
    assert counterparts["T.Row2"] == "T.Row3"


def test_empty_tables_have_no_counterparts():
    assert table_counterparts(_table("T", []), _table("T", [])) == {}
