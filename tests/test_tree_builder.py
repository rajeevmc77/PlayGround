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
