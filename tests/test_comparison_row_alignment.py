"""table_counterparts pairs a table's PDF rows with its web rows by content,
not position: one row present on only one side (B.9.38.1.1 has 88 more on
the web) used to shift every row below it, so the cells compared were never
the same cells. Rows are aligned on their whole text; identical runs pair
one-to-one, a block of differing rows pairs by position inside the block
(so a table with no identical rows at all falls back to plain positional
pairing), and a row only one side has stays unpaired. Cells pair the same
way within paired rows."""

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


def test_rows_that_all_differ_a_little_pair_with_their_most_similar_counterpart():
    # Real case: Table 1.3.1.2. - the site writes "Note A-..." in every
    # row's last column, so no row matched exactly, the whole table was one
    # differing block paired by position, and each row only one side has
    # shifted every row below it (PDF "NFRC 200-2010" met web "NRC 1988").
    pdf = _table(
        "T",
        [
            ["ASTM", "A123", "Zinc Coating", "A-5.9.1.1."],
            ["ASTM", "A153", "Zinc Hardware", "A-9.20.16.1."],
            ["NFRC", "100", "U-factors", "9.36.2.2."],
        ],
    )
    web = _table(
        "T",
        [
            ["ASTM", "A123", "Zinc Coating", "Note A-5.9.1.1."],
            ["ASME", "B18", "Wood Screws", "Note A-9.23.3.1."],
            ["ASTM", "A153", "Zinc Hardware", "Note A-9.20.16.1."],
            ["NFRC", "100", "U-factors", "9.36.2.2. 9.36.2.3."],
        ],
    )

    counterparts = table_counterparts(pdf, web)

    assert [counterparts[f"T.Row{n}"] for n in (1, 2, 3)] == ["T.Row1", "T.Row3", "T.Row4"]
    assert counterparts["T.Row2.Col3"] == "T.Row3.Col3"


def test_dissimilar_rows_between_two_similar_pairs_still_pair_by_position():
    pdf = _table("T", [["ASTM", "A123", "Zinc"], ["p1"], ["NFRC", "100", "U"]])
    web = _table("T", [["ASTM", "A123", "Zinc", "x"], ["w1"], ["w2"], ["NFRC", "100", "U", "x"]])

    counterparts = table_counterparts(pdf, web)

    assert [counterparts[f"T.Row{n}"] for n in (1, 2, 3)] == ["T.Row1", "T.Row2", "T.Row4"]


def test_a_differing_block_with_as_many_rows_on_each_side_stays_by_position():
    # Real case: Table 3.1.8.17. - the PDF splits a spanning cell's text over
    # two rows where the web keeps it in the first, so the PDF's second row
    # looked most like the web's first. Equal counts mean no row is missing:
    # the rows correspond by position.
    pdf = _table("T", [["H"], ["Between a", "no limit"], ["dead end corridor", "45 min"]])
    web = _table("T", [["H"], ["dead end corridor", "45 min *"], ["Between a", "no limit *"]])

    counterparts = table_counterparts(pdf, web)

    assert [counterparts[f"T.Row{n}"] for n in (1, 2, 3)] == ["T.Row1", "T.Row2", "T.Row3"]


def test_a_pdf_cell_beyond_the_paired_web_rows_width_is_unpaired():
    pdf = _table("T", [["a", "1", "extra"]])
    web = _table("T", [["a", "1"]])
    counterparts = table_counterparts(pdf, web)
    assert counterparts["T.Row1.Col2"] == "T.Row1.Col2"
    assert counterparts["T.Row1.Col3"] is None


def test_cells_of_a_web_row_that_leaves_out_span_covered_positions_pair_by_content():
    # Real case: Table 9.36.6.3.-H - its JSON lists only the cells a row
    # starts, so a row under two rowspans starts at the PDF's third column.
    pdf = _table("T", [["", "", "3", "120", "100"]])
    web = _table("T", [["3", "120", "100"]])
    counterparts = table_counterparts(pdf, web)
    assert [counterparts[f"T.Row1.Col{n}"] for n in (1, 2, 3, 4, 5)] == [
        None,
        None,
        "T.Row1.Col1",
        "T.Row1.Col2",
        "T.Row1.Col3",
    ]


def test_a_pdf_cells_text_centred_over_the_columns_it_spans_pairs_with_the_web_cell():
    # The PDF places a colspan cell's text in the column it starts in - the
    # middle of its span; the site in the span's first column.
    pdf = _table("T", [["Total", "", "Step", ""]])
    web = _table("T", [["Total", "Step", "", ""]])
    counterparts = table_counterparts(pdf, web)
    assert counterparts["T.Row1.Col1"] == "T.Row1.Col1"
    assert counterparts["T.Row1.Col3"] == "T.Row1.Col2"


def test_empty_cells_never_anchor_a_rows_cell_pairing():
    # Real case: Table 9.23.13.7.-A - pairing the PDF's two empty cells with
    # two empty web cells mid-row dragged the rest of the row out of line.
    pdf = _table("T", [["", "", "Diagonal", "Gypsum"]])
    web = _table("T", [["HWP", "Storey", "Diagonal-", "Gypsum-", "", "", "Wood"]])
    counterparts = table_counterparts(pdf, web)
    assert [counterparts[f"T.Row1.Col{n}"] for n in (1, 2, 3, 4)] == [
        "T.Row1.Col1",
        "T.Row1.Col2",
        "T.Row1.Col3",
        "T.Row1.Col4",
    ]


def test_differing_cells_between_identical_ones_pair_by_position():
    pdf = _table("T", [["a", "2(7)", "x", "c"]])
    web = _table("T", [["a", "2", "y", "c"]])
    counterparts = table_counterparts(pdf, web)
    assert [counterparts[f"T.Row1.Col{n}"] for n in (1, 2, 3, 4)] == [
        "T.Row1.Col1",
        "T.Row1.Col2",
        "T.Row1.Col3",
        "T.Row1.Col4",
    ]


def test_rows_align_on_text_with_whitespace_quotes_and_dashes_made_plain():
    pdf = _table("T", [["x"], ["fire- resistance – 1 h"], ["z"]])
    web = _table("T", [["new"], ["x"], ["fire-resistance - 1 h"], ["z"]])
    counterparts = table_counterparts(pdf, web)
    assert counterparts["T.Row2"] == "T.Row3"


def test_empty_tables_have_no_counterparts():
    assert table_counterparts(_table("T", []), _table("T", [])) == {}
