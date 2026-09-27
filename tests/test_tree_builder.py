from mo_toc.domain.models import BBox
from mo_toc.parsing.pdf_source import PageLine
from mo_toc.parsing.tree_builder import build_tree, build_tree_from_lines


class FakePdfSource:
    """Minimal PdfSource stand-in: pages[i] is a list of PageLine for page i."""

    def __init__(self, pages: list[list[PageLine]]):
        self._pages = pages

    @property
    def page_count(self):
        return len(self._pages)

    def page_lines(self, page_index):
        return self._pages[page_index]

    def page_images(self, page_index):
        return []

    def extract_image(self, xref):
        raise NotImplementedError


def line(y0, x0, text, font):
    return PageLine(bbox=(x0, y0, x0 + 300, y0 + 10), text=text, font=font)


BLACK, BOLD, BODY = "Arial-Black", "Arial-BoldMT", "BookAntiqua"


def _document_fixture():
    return [
        [line(50, 40, "Random front matter text.", BODY)],  # page 0: FrontMatter
        [line(50, 40, "Division A", BLACK)],  # page 1
        [
            line(50, 40, "Part 1", BLACK),
            line(70, 40, "Compliance", BLACK),
            line(90, 40, "Section  1.1.   General", BLACK),
            line(110, 40, "1.1.1. Application", BLACK),
            line(130, 40, "1.1.1.1. Application of this Code", BLACK),
            line(150, 40, "1) Fire protection shall conform to NFPA 303.", BODY),
        ],  # page 2
        [
            line(50, 40, "Notes to Part 1", BLACK),
            line(70, 40, "A-1.1.1.1. Some note text.", BODY),
        ],  # page 3
        [
            line(50, 40, "Figure 1.1.1.1.-A", BOLD),
            line(70, 40, "Sample figure title", BOLD),
        ],  # page 4
        [line(50, 40, "PROVINCE OF BRITISH COLUMBIA", BOLD)],  # page 5: BackMatter
    ]


def test_front_matter_precedes_first_division():
    root, _captions = build_tree(FakePdfSource(_document_fixture()))
    assert root.children[0].type == "FrontMatter"
    assert root.children[0].page == 1


def test_build_tree_from_lines_matches_build_tree_for_the_same_document():
    pages = _document_fixture()

    from_source = build_tree(FakePdfSource(pages))
    from_lines = build_tree_from_lines(pages, len(pages))

    assert from_lines == from_source


def test_division_part_section_subsection_article_nest_correctly():
    root, _captions = build_tree(FakePdfSource(_document_fixture()))
    division = root.children[1]
    assert division.type == "Division" and division.identifier == "A"
    part = division.children[0]
    assert part.type == "Part"
    assert part.title == "Compliance"  # folded from a separate Arial-Black block
    section = part.children[0]
    assert section.type == "Section" and section.citation == "A-1.1."
    subsection = section.children[0]
    assert subsection.type == "Subsection"
    article = subsection.children[0]
    assert article.type == "Article" and article.citation == "A-1.1.1.1."


def test_article_body_segmented_into_sentence():
    root, _captions = build_tree(FakePdfSource(_document_fixture()))
    article = root.children[1].children[0].children[0].children[0].children[0]
    assert len(article.children) == 1
    assert article.children[0].type == "Sentence"
    assert article.children[0].citation == "A-1.1.1.1.(1)"


def test_notes_container_holds_note():
    root, _captions = build_tree(FakePdfSource(_document_fixture()))
    # NotesContainer shares Part's own RANK (2), so the stack-close rule that
    # lets consecutive Parts close each other also closes the current Part
    # when "Notes to Part" is hit - it nests as a sibling of Part under
    # Division, not as a child of Part.
    division = root.children[1]
    notes_container = division.children[1]
    assert notes_container.type == "NotesContainer"
    assert notes_container.children[0].type == "Note"
    # rstrip(".") removes the one trailing dot the RE_NOTE_ENTRY token includes
    assert notes_container.children[0].identifier == "A-1.1.1.1"


def _notes_page(*entries):
    return [
        [line(50, 40, "Division B", BLACK)],
        [line(50, 40, "Notes to Part 9", BLACK)]
        + [line(70 + 20 * i, 40, text, BODY) for i, text in enumerate(entries)],
    ]


def test_a_note_on_a_table_keeps_the_tables_number_in_its_identifier():
    # Real cases (pages 606-1543): the identifier stopped at the first space,
    # so all 22 "A-Table ..." notes became "A-Table", collided, and never met
    # their web notes ("A-Table 9.23.3.5.-B").
    pages = _notes_page(
        "A-Table 4.1.2.1.Importance Categories for Buildings.",
        "A-Table 4.1.8.5.-AServiceability Limit States for Earthquake.",
        "A-Table 9.6.1.3   Glass in Doors. Maximum areas in Table 9.6.1.3.",
        "A-Table 9.23.3.5.-B   Alternative Nail Sizes. Where power nails",
        "A-Tables 9.36.2.8.-A and -B   Multiple Applicable Requirements.",
    )
    root, _captions = build_tree_from_lines(pages, len(pages))
    notes = root.children[1].children[0].children
    assert [(n.identifier, n.title) for n in notes] == [
        ("A-Table 4.1.2.1", "Importance Categories for Buildings."),
        ("A-Table 4.1.8.5.-A", "Serviceability Limit States for Earthquake."),
        ("A-Table 9.6.1.3", "Glass in Doors. Maximum areas in Table 9.6.1.3."),
        ("A-Table 9.23.3.5.-B", "Alternative Nail Sizes. Where power nails"),
        ("A-Tables 9.36.2.8.-A and -B", "Multiple Applicable Requirements."),
    ]
    assert notes[3].citation == "Note:A-Table 9.23.3.5.-B"


def test_a_notes_identifier_ends_where_its_title_begins_even_with_no_space():
    # Real cases (Division B Parts 4-6, pages 606-709): the identifier ran to
    # the first space, so "A-4.1.2.2.(1)Loads Not Listed." became note
    # "A-4.1.2.2.(1)Loads" and never met the web's "A-4.1.2.2.(1)".
    pages = _notes_page(
        "A-4.1.2.2.(1)Loads Not Listed.The intent of Sentence 4.1.2.2.(1)",
        "A-6.2.1.1.Good Engineering Practice.",
        "A-4.1.7.8.(2) and (3)Exposure Factor for Dynamic Procedure.",
        "A-9.25.3.4. and 9.25.3.6.   Air Leakage and Soil Gas Control.",
        "A-3.8.2.3.(5) and (6) and 3.8.3.22.(1) and (4) Signs.",
        "A-3.1.6.4.(3) to (6) Encapsulation.",
        "A-9.10.3.1.(1)(c) Fire-Resistance Ratings.",
        # Page 472: a period after the provision's references.
        "A-3.8.5.7.(1)(c) and (d). Plumbing Systems. Plumbing systems",
        "A-3.8.5.7.(1)(e).   Reinforced Grab Bar Location. This provision",
    )
    root, _captions = build_tree_from_lines(pages, len(pages))
    notes = root.children[1].children[0].children
    assert [n.identifier for n in notes] == [
        "A-4.1.2.2.(1)",
        "A-6.2.1.1",
        "A-4.1.7.8.(2) and (3)",
        "A-9.25.3.4. and 9.25.3.6",
        "A-3.8.2.3.(5) and (6) and 3.8.3.22.(1) and (4)",
        "A-3.1.6.4.(3) to (6)",
        "A-9.10.3.1.(1)(c)",
        "A-3.8.5.7.(1)(c) and (d)",
        "A-3.8.5.7.(1)(e)",
    ]
    assert notes[0].title == "Loads Not Listed.The intent of Sentence 4.1.2.2.(1)"


def test_a_line_that_is_no_note_identifier_does_not_open_a_note():
    # Real case: page 1537's "R-value (R)" line opened note "R-value~2".
    pages = _notes_page("A-9.36.1.3.(6) Exemptions. Examples", "R-value (R) of the assembly")
    root, _captions = build_tree_from_lines(pages, len(pages))
    assert [n.identifier for n in root.children[1].children[0].children] == ["A-9.36.1.3.(6)"]


def test_heading_records_literal_heading_words():
    volume, _ = build_tree_from_lines(
        [
            [
                line(50, 40, "Division A", BLACK),
                line(70, 40, "Part 1", BLACK),
                line(90, 40, "Compliance", BLACK),
                line(110, 40, "Section 1.1. General", BLACK),
                line(130, 40, "1.1.1.1. Application of this Code", BLACK),
            ]
        ],
        1,
    )
    division = volume.children[1]
    part = division.children[0]
    section = part.children[0]
    article = section.children[0]
    assert division.heading == "Division A"
    assert (part.heading, part.title) == ("Part 1", "Compliance")
    assert (section.heading, section.title) == ("Section 1.1.", "General")
    assert (article.heading, article.title) == ("1.1.1.1.", "Application of this Code")


def test_heading_collapses_internal_whitespace():
    volume, _ = build_tree_from_lines(
        [
            [
                line(50, 40, "Division A", BLACK),
                line(70, 40, "Part 3", BLACK),
                line(90, 40, "Section  3.9.   General", BLACK),
            ]
        ],
        1,
    )
    section = volume.children[1].children[0].children[0]
    assert section.heading == "Section 3.9."


def test_table_group_and_back_matter_have_no_heading_words():
    volume, _ = build_tree_from_lines(
        [
            [
                line(50, 40, "Division B", BLACK),
                line(70, 40, "Part 9", BLACK),
                line(90, 40, "Span Tables", BLACK),
            ],
            [line(50, 40, "PROVINCE OF BRITISH COLUMBIA", BOLD)],
        ],
        2,
    )
    table_group = volume.children[1].children[0].children[0]
    back_matter = volume.children[-1]
    assert (table_group.type, table_group.heading) == ("TableGroup", "")
    assert (back_matter.type, back_matter.heading) == ("BackMatter", "")


def test_notes_container_title_is_notes_to_part_n():
    volume, _ = build_tree_from_lines(
        [
            [
                line(50, 40, "Division A", BLACK),
                line(70, 40, "Part 1", BLACK),
                line(90, 40, "Compliance", BLACK),
                line(110, 40, "Notes to Part 1", BLACK),
                line(130, 40, "Compliance", BLACK),
                line(150, 40, "A-1.1.1.1.(3) Factory-Constructed Buildings.", BODY),
            ]
        ],
        1,
    )
    notes = volume.children[1].children[1]
    assert notes.type == "NotesContainer"
    assert notes.title == "Notes to Part 1"
    assert notes.heading == "Notes to Part 1"
    assert notes.children[0].heading == "A-1.1.1.1.(3)"


def test_note_bbox_spans_continuation_lines_on_same_page():
    pages = [
        [line(50, 40, "Random front matter text.", BODY)],  # page 0: FrontMatter
        [line(50, 40, "Division A", BLACK)],  # page 1
        [line(50, 40, "Part 1", BLACK)],  # page 2
        [
            line(50, 40, "Notes to Part 1", BLACK),
            line(70, 40, "A-1.1.1.1. First line of the note.", BODY),
            line(90, 40, "Second line continuing the same note.", BODY),
        ],  # page 3
    ]
    root, _captions = build_tree(FakePdfSource(pages))
    note = root.children[1].children[1].children[0]
    # The trigger line alone spans y0=70..y1=80; the highlight must reach
    # down to the continuation line's bottom edge (y1=100), not stop at the
    # first line.
    assert note.bbox == BBox(40, 70, 340, 100)


def _note_pages(*pages):
    return [
        [line(50, 40, "Division A", BLACK)],
        [line(50, 40, "Notes to Part 1", BLACK)] + list(pages[0]),
        *[list(page) for page in pages[1:]],
    ]


def _first_note(pages):
    root, _captions = build_tree_from_lines(pages, len(pages))
    return root.children[1].children[0].children[0]


def test_a_notes_content_is_its_body_after_the_title_across_lines_and_pages():
    pages = _note_pages(
        [
            line(70, 40, "A-9.15.3.4.(2)   Footing Sizes. The footing sizes in", BODY),
            line(90, 40, "Table 9.15.3.4. are based on typical construction.", BODY),
            line(713, 500, "706", "TimesNewRomanPSMT"),  # running footer
        ],
        [line(50, 40, "Where these spans exceed 4.9 m, see below.", BODY)],
    )
    note = _first_note(pages)
    assert note.content == (
        "The footing sizes in Table 9.15.3.4. are based on typical construction."
        " Where these spans exceed 4.9 m, see below."
    )


def test_a_note_title_wrapping_onto_its_next_line_is_left_out_of_its_content():
    pages = _note_pages(
        [
            line(70, 40, "A-9.25.4.2.(2)   Insulation and Vapour Barriers in", BODY),
            line(90, 40, "Heated Crawl Spaces. In the summer, solar heating", BODY),
        ]
    )
    assert _first_note(pages).content == "In the summer, solar heating"


def test_a_note_title_followed_with_no_space_ends_at_its_period():
    pages = _note_pages(
        [line(70, 40, "A-4.1.1.3.(1)Structural Integrity.The requirements apply.", BODY)]
    )
    assert _first_note(pages).content == "The requirements apply."


def test_a_notes_content_keeps_its_bold_and_italic():
    pages = _note_pages(
        [
            PageLine(
                bbox=(40, 70, 340, 80),
                text="A-3.1.2.3.(1) Arena Regulation. An arena is regulated.",
                font=BODY,
                emphasis=((35, 40, "i"),),  # "arena"
            )
        ]
    )
    note = _first_note(pages)
    assert (note.content, note.emphasis) == ("An arena is regulated.", [(3, 8, "i")])


def test_a_note_with_nothing_after_its_title_has_no_content():
    pages = _note_pages([line(70, 40, "A-Table 4.1.5.3.Considerations for Live Loads.", BODY)])
    assert _first_note(pages).content == ""


def _bold(y0, text):
    return PageLine(
        bbox=(40, y0, 340, y0 + 10), text=text, font=BOLD, emphasis=((0, len(text), "b"),)
    )


def test_a_figure_caption_inside_a_note_is_part_of_its_text_where_it_stands():
    # Real case: A-3.6.5.6.(2) - the site keeps a figure's caption in the
    # note's text, in bold, where the figure stands.
    pages = _note_pages(
        [
            line(70, 40, "A-3.6.5.6.(2)   Clearances. Applicable to furnaces.", BODY),
            _bold(90, "Figure A-3.6.5.6.(2)"),
            _bold(102, "Clearance for warm-air supply ducts"),
            line(120, 40, "Where the clearance is 75 mm or less.", BODY),
        ]
    )
    note = _first_note(pages)
    identifier, title = "Figure A-3.6.5.6.(2)", "Clearance for warm-air supply ducts"
    caption = f"{identifier} {title}"
    after = "Where the clearance is 75 mm or less."
    assert note.content == f"Applicable to furnaces. {caption} {after}"
    start = note.content.index("Figure")
    title_start = start + len(identifier) + 1
    assert note.emphasis == [
        (start, start + len(identifier), "b"),
        (title_start, title_start + len(title), "b"),
    ]


def test_a_table_caption_inside_a_note_stays_out_of_its_text():
    pages = _note_pages(
        [
            line(70, 40, "A-9.23.4.3.   Spans for Steel Beams. The spans reflect a balance.", BODY),
            _bold(90, "Table A-9.23.4.3."),
            _bold(102, "Spans for Steel Beams"),
        ]
    )
    assert _first_note(pages).content == "The spans reflect a balance."


def test_a_note_whose_title_never_ends_in_a_period_has_no_content():
    pages = _note_pages([line(70, 40, "A-9.1.1.1.(1)   Application of Part 9", BODY)])
    assert _first_note(pages).content == ""


def test_continuation_line_attaches_to_the_currently_open_note():
    pages = [
        [line(50, 40, "Random front matter text.", BODY)],  # page 0: FrontMatter
        [line(50, 40, "Division A", BLACK)],  # page 1
        [line(50, 40, "Part 1", BLACK)],  # page 2
        [
            line(50, 40, "Notes to Part 1", BLACK),
            line(70, 40, "A-1.1.1.1. First note first line.", BODY),
            line(90, 40, "A-1.1.1.2. Second note first line.", BODY),
            line(110, 40, "Second note continuation line.", BODY),
        ],  # page 3
    ]
    root, _captions = build_tree(FakePdfSource(pages))
    first_note, second_note = root.children[1].children[1].children
    assert first_note.bbox == BBox(40, 70, 340, 80)
    assert second_note.bbox == BBox(40, 90, 340, 120)


def test_stray_line_before_first_note_entry_is_ignored():
    pages = [
        [line(50, 40, "Random front matter text.", BODY)],  # page 0: FrontMatter
        [line(50, 40, "Division A", BLACK)],  # page 1
        [line(50, 40, "Part 1", BLACK)],  # page 2
        [
            line(50, 40, "Notes to Part 1", BLACK),
            line(70, 40, "Some intro text before any note entry.", BODY),
            line(90, 40, "A-1.1.1.1. First note.", BODY),
        ],  # page 3
    ]
    root, _captions = build_tree(FakePdfSource(pages))
    notes_container = root.children[1].children[1]
    assert len(notes_container.children) == 1
    assert notes_container.children[0].identifier == "A-1.1.1.1"


def test_figure_caption_captured_with_owner_citation():
    _root, captions = build_tree(FakePdfSource(_document_fixture()))
    assert len(captions) == 1
    assert captions[0].kind == "Figure"
    assert captions[0].identifier == "1.1.1.1.-A"
    assert captions[0].title == "Sample figure title"


def test_backmatter_opens_only_after_first_division_seen():
    root, _captions = build_tree(FakePdfSource(_document_fixture()))
    assert root.children[-1].type == "BackMatter"


def test_figure_caption_bbox_covers_full_title_block_not_just_identifier_line():
    # Confirmed real-document case (Part 4 wind-load figures, e.g. Figure
    # 4.1.7.6.-A on page 516): a caption's title routinely wraps across two
    # or three lines below the "Figure ..." identifier line. If bbox stops
    # at the identifier line alone, image_matcher measures the gap to the
    # image from the wrong edge - 30-40pt too high up the page - and can
    # push a genuinely close image past MAX_CAPTION_GAP.
    pages = _document_fixture()
    pages.append(
        [
            line(400, 40, "Figure 1.1.1.1.-B", BOLD),
            line(420, 40, "First title line", BOLD),
            line(440, 40, "Second title line", BOLD),
        ]
    )
    _root, captions = build_tree(FakePdfSource(pages))
    caption = captions[-1]
    assert caption.identifier == "1.1.1.1.-B"
    assert caption.bbox.y1 == 450  # bottom of "Second title line" (y0=440, +10), not 410


def test_backmatter_marker_before_any_division_is_not_a_heading():
    pages = [
        [line(50, 40, "PROVINCE OF BRITISH COLUMBIA", BOLD)],
        [line(50, 40, "Division A", BLACK)],
    ]
    root, _captions = build_tree(FakePdfSource(pages))
    assert root.children[0].type == "FrontMatter"
    assert len([c for c in root.children if c.type == "BackMatter"]) == 0


def test_end_page_never_precedes_start_page_for_siblings_sharing_a_page():
    # Two Articles under the same Subsection both start on page index 2 (the
    # norm in a code book - several Articles often share a page). Before the
    # clamp in _finalize_end_pages, the first sibling's end_page was computed
    # as the second sibling's start page minus 1, landing BEFORE its own
    # start page whenever siblings share a page.
    pages = [
        [line(50, 40, "Random front matter text.", BODY)],  # page 0
        [line(50, 40, "Division A", BLACK)],  # page 1
        [
            line(50, 40, "Part 1", BLACK),
            line(70, 40, "Compliance", BLACK),
            line(90, 40, "Section  1.1.   General", BLACK),
            line(110, 40, "1.1.1. Application", BLACK),
            line(130, 40, "1.1.1.1. Application of this Code", BLACK),
            line(150, 40, "1.1.1.2. Second Article", BLACK),
        ],  # page index 2 (page number 3): two Articles sharing the same page
    ]
    root, _captions = build_tree(FakePdfSource(pages))
    subsection = root.children[1].children[0].children[0].children[0]
    article_1, article_2 = subsection.children
    assert article_1.citation == "A-1.1.1.1." and article_2.citation == "A-1.1.1.2."
    assert article_1.page == article_2.page == 3
    assert article_1.end_page >= article_1.page
    assert article_2.end_page >= article_2.page


def test_consumed_line_indices_are_excluded_from_article_body():
    pages = [
        [
            line(50, 40, "Part 1", BLACK),
            line(70, 40, "Compliance", BLACK),
            line(90, 40, "Section  1.1.   General", BLACK),
            line(110, 40, "1.1.1. Application", BLACK),
            line(130, 40, "1.1.1.1. Application of this Code", BLACK),
            line(150, 40, "1) Real sentence text.", BODY),
            line(170, 40, "This line is inside a detected table.", BODY),
        ],
    ]
    without_skip, _ = build_tree_from_lines(pages, len(pages))
    with_skip, _ = build_tree_from_lines(pages, len(pages), consumed_by_page={0: {6}})

    article_without = without_skip.children[0].children[0].children[0].children[0].children[0]
    article_with = with_skip.children[0].children[0].children[0].children[0].children[0]

    # Without the skip-set, the stray line still gets swept into the
    # sentence's continuation content (the bug body_segmenter now fixes
    # would otherwise hide this, so this test also guards Task 3's fix).
    assert "detected table" in article_without.children[0].content
    assert "detected table" not in article_with.children[0].content


def test_trailing_bare_page_number_is_not_absorbed_into_sentence_content():
    # The PDF's own running footer is a bare page number rendered as the
    # very last line on the page. It carries no heading/marker shape, so it
    # falls through to plain body text and, when a Sentence's continuation
    # spans the page break, gets wedged into the middle of its content -
    # e.g. "...using the formula 16 where Is=..." where "16" is the footer,
    # not part of the sentence.
    pages = [
        [
            line(50, 40, "Part 1", BLACK),
            line(70, 40, "Compliance", BLACK),
            line(90, 40, "Section  1.1.   General", BLACK),
            line(110, 40, "1.1.1. Application", BLACK),
            line(130, 40, "1.1.1.1. Application of this Code", BLACK),
            line(150, 40, "1) Fire protection shall conform to the formula", BODY),
            line(713, 40, "16", BODY),  # trailing footer page number
        ],
        [
            line(50, 40, "where Is is the importance factor.", BODY),
        ],
    ]
    root, _captions = build_tree_from_lines(pages, len(pages))
    article = root.children[0].children[0].children[0].children[0].children[0]
    sentence = article.children[0]
    assert sentence.content == (
        "Fire protection shall conform to the formula where Is is the importance factor."
    )


def test_a_plain_font_caption_centred_on_the_page_is_captured_with_its_plain_title():
    # Real case: page 746's "Table 9.8.4.2." and its title "Run for
    # Rectangular Treads" are set in plain ArialMT, not the bold caption font.
    pages = _document_fixture()
    pages.append(
        [
            PageLine(
                bbox=(278, 400, 334, 410), text="Table 9.8.4.2.", font="ArialMT", centred=True
            ),
            PageLine(
                bbox=(247, 420, 365, 430),
                text="Run for Rectangular Treads",
                font="ArialMT",
                centred=True,
            ),
            line(440, 224, "Forming Part of Sentence 9.8.4.2.(1)", BOLD),
            line(470, 40, "Some unrelated body line.", BODY),
        ]
    )
    _root, captions = build_tree(FakePdfSource(pages))
    caption = captions[-1]
    assert (caption.kind, caption.identifier) == ("Table", "9.8.4.2.")
    assert caption.title == "Run for Rectangular Treads Forming Part of Sentence 9.8.4.2.(1)"


NOTES_FONT = "ArialMT"


def _article_pages(*body_pages):
    """One Article's heading chain followed by the given body lines - the
    first list on the heading's page, any further lists on the pages after."""
    heading = [
        line(10, 40, "Division B", BLACK),
        line(50, 40, "Part 3", BLACK),
        line(70, 40, "Section  3.1.   General", BLACK),
        line(90, 40, "3.1.13. Interior Finish", BLACK),
        line(110, 40, "3.1.13.2. Flame-Spread Rating", BLACK),
    ]
    return [heading + list(body_pages[0]), *[list(page) for page in body_pages[1:]]]


def _articles(pages):
    root, _captions = build_tree_from_lines(pages, len(pages))
    return root.children[1].children[0].children[0].children[0].children


def _sentences(pages, article_index=0):
    return [sentence.content for sentence in _articles(pages)[article_index].children]


def test_a_table_notes_block_is_left_out_of_the_sentence_it_follows():
    # The notes printed under a table ("Notes to Table 3.1.13.2.:" and its
    # "(1) ..." entries) fell through to body text and were appended to the
    # sentence before the table; the site keeps no such text in it.
    pages = _article_pages(
        [
            line(130, 40, "1) Finishes shall conform to Table 3.1.13.2.", BODY),
            line(300, 40, "Notes to Table 3.1.13.2.:", BOLD),
            line(312, 40, "(1) See Articles 3.1.13.8. and 3.1.13.10.", NOTES_FONT),
            line(324, 40, "(2) Other requirements of this Part apply.", "Arial-ItalicMT/ArialMT"),
            line(340, 40, "2) Doors need not conform to Sentence (1).", BODY),
        ]
    )
    assert _sentences(pages) == [
        "Finishes shall conform to Table 3.1.13.2.",
        "Doors need not conform to Sentence (1).",
    ]


def test_a_table_notes_block_running_onto_the_next_page_is_left_out():
    pages = _article_pages(
        [
            line(130, 40, "1) Finishes shall conform to Table 3.1.13.2.", BODY),
            line(690, 40, "Notes to Table 3.1.13.2.:", BOLD),
            line(713, 40, "43", "TimesNewRomanPSMT"),  # running footer
        ],
        [
            line(50, 40, "(1) See Articles 3.1.13.8. and 3.1.13.10.", NOTES_FONT),
            line(70, 40, "2) Doors need not conform to Sentence (1).", BODY),
        ],
    )
    assert _sentences(pages) == [
        "Finishes shall conform to Table 3.1.13.2.",
        "Doors need not conform to Sentence (1).",
    ]


def test_a_sentence_set_in_the_notes_font_ends_a_table_notes_block():
    # Real case: page 910's Sentence 9.23.13.7.(5), a BC amendment, is set in
    # Arial like the notes above it. A note entry starts "(1)"; a Sentence or
    # Clause starts "5)" or "a)".
    pages = _article_pages(
        [
            line(130, 40, "1) Finishes shall conform to Table 3.1.13.2.", BODY),
            line(300, 40, "Notes to Table 3.1.13.2.:", BOLD),
            line(312, 40, "(1) See Articles 3.1.13.8. and 3.1.13.10.", NOTES_FONT),
            line(340, 40, "2)   Doors need not conform", "Arial-ItalicMT/ArialMT"),
            line(352, 40, "to Sentence (1).", NOTES_FONT),
        ]
    )
    assert _sentences(pages) == [
        "Finishes shall conform to Table 3.1.13.2.",
        "Doors need not conform to Sentence (1).",
    ]


def test_notes_set_in_the_body_font_keep_their_lines_as_body_text():
    # Only the heading can be told apart there: the notes share the body's
    # font, so where they end can't be seen.
    pages = _article_pages(
        [
            line(130, 40, "1) Finishes shall conform to Table 3.1.13.2.", BODY),
            line(300, 40, "Notes to Table 3.1.13.2.:", "BookAntiqua-Bold"),
            line(312, 40, "2) Doors need not conform to Sentence (1).", BODY),
        ]
    )
    assert _sentences(pages) == [
        "Finishes shall conform to Table 3.1.13.2.",
        "Doors need not conform to Sentence (1).",
    ]


def test_a_heading_ends_a_table_notes_block():
    pages = _article_pages(
        [
            line(130, 40, "1) Finishes shall conform to Table 3.1.13.2.", BODY),
            line(300, 40, "Notes to Table 3.1.13.2.:", BOLD),
            line(312, 40, "(1) See Articles 3.1.13.8. and 3.1.13.10.", NOTES_FONT),
            line(330, 40, "3.1.13.3. Bathrooms", BLACK),
            line(350, 40, "1) Bathroom finishes set in the notes font.", NOTES_FONT),
        ]
    )
    assert _sentences(pages, article_index=1) == ["Bathroom finishes set in the notes font."]


def test_a_caption_ends_a_table_notes_block():
    pages = _article_pages(
        [
            line(130, 40, "1) Finishes shall conform to Table 3.1.13.2.", BODY),
            line(300, 40, "Notes to Table 3.1.13.2.:", BOLD),
            line(312, 40, "(1) See Articles 3.1.13.8. and 3.1.13.10.", NOTES_FONT),
            line(330, 40, "Figure 3.1.13.2.", BOLD),
            line(345, 40, "A figure title", BOLD),
            line(360, 40, "Figure text set in the notes font.", NOTES_FONT),
        ]
    )
    assert _sentences(pages) == [
        "Finishes shall conform to Table 3.1.13.2. Figure text set in the notes font."
    ]
