from mo_toc.domain.models import BBox, Node
from mo_toc.parsing.numbering_config import MO_TOC_RULES, MO_TOC_SCOPE_TYPES
from shared.numbering import assign_unified_numbers
from web_toc.domain.models import WebNode
from web_toc.parsing.numbering_config import WEB_TOC_RULES, WEB_TOC_SCOPE_TYPES


def _pdf(node_type, identifier, children=()):
    return Node(
        type=node_type,
        identifier=identifier,
        citation=f"pdf-{node_type}-{identifier}",
        title="",
        page=1,
        end_page=1,
        bbox=BBox(0, 0, 0, 0),
        children=list(children),
    )


def _web(node_type, identifier, children=()):
    return WebNode(
        type=node_type,
        identifier=identifier,
        citation=f"web-{node_type}-{identifier}",
        title="",
        path="",
        children=list(children),
    )


def _keys(node):
    yield node.type.lower(), node.unified_number
    for child in node.children:
        yield from _keys(child)


def test_part_9_gets_identical_keys_although_the_web_puts_it_in_volume_2():
    pdf_table = _pdf("Table", "9.10.18.2.", [_pdf("Row", "Row1", [_pdf("Cell", "Col1")])])
    pdf_article = _pdf(
        "Article",
        "9.10.18.2.",
        [
            _pdf("Sentence", "(2)", [_pdf("Clause", "(a)"), pdf_table]),
        ],
    )
    pdf_notes = _pdf("NotesContainer", "9", [_pdf("Note", "A-9.10.18.2.(2)")])
    pdf_part = _pdf(
        "Part",
        "9",
        [
            _pdf("Section", "9.10.", [_pdf("Subsection", "9.10.18.", [pdf_article])]),
            pdf_notes,
        ],
    )
    pdf_volume = _pdf("Volume", "Volume", [_pdf("Division", "B", [pdf_part])])

    web_table = _web("Table", "table1", [_web("Row", "row1", [_web("Cell", "col1")])])
    web_article = _web(
        "article",
        "9.10.18.2",
        [
            _web("Sentence", "(2)", [_web("Clause", "(a)")]),
            web_table,
        ],
    )
    web_notes = _web("part_appendix", "", [_web("Note", "A-9.10.18.2.(2)")])
    web_part = _web(
        "part",
        "9",
        [
            _web("section", "9.10", [_web("subsection", "9.10.18", [web_article])]),
            web_notes,
        ],
    )
    web_volume2 = _web("volume", "2", [_web("division", "B", [web_part])])

    assign_unified_numbers([pdf_volume], MO_TOC_RULES, MO_TOC_SCOPE_TYPES)
    assign_unified_numbers([web_volume2], WEB_TOC_RULES, WEB_TOC_SCOPE_TYPES)

    pdf_keys = {key for _, key in _keys(pdf_volume.children[0])}
    web_keys = {key for _, key in _keys(web_volume2.children[0])}
    assert pdf_keys == web_keys
    assert "B.9.10.18.2.Tbl1.Row1.Col1" in web_keys
    assert "B.9.Notes" in web_keys
    assert "B.A-9.10.18.2.(2)" in web_keys
