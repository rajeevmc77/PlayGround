from mo_toc.domain.models import BBox, Caption, Node
from mo_toc.output.markdown_writer import write_markdown


def _sample_tree():
    article = Node(
        type="Article",
        identifier="1.1.1.1.",
        citation="A-1.1.1.1.",
        title="Scope",
        page=7,
        end_page=7,
        bbox=BBox(0, 0, 0, 0),
    )
    division = Node(
        type="Division",
        identifier="A",
        citation="A",
        title="",
        page=6,
        end_page=7,
        bbox=BBox(0, 0, 0, 0),
        children=[article],
    )
    return Node(
        type="Volume",
        identifier="Volume",
        citation="Volume",
        title="",
        page=1,
        end_page=100,
        bbox=BBox(0, 0, 0, 0),
        children=[division],
    )


def test_write_markdown_includes_summary_and_hierarchy(tmp_path):
    caption = Caption(
        kind="Figure",
        identifier="1.1.1.1.-A",
        title="Sample",
        page=7,
        bbox=BBox(0, 0, 0, 0),
        owner_citation="A-1.1.1.1.",
        forming_part_of=None,
        continuation=False,
    )
    out_path = tmp_path / "out.md"
    write_markdown(_sample_tree(), [caption], str(out_path))
    text = out_path.read_text()
    assert "## Summary" in text
    assert "Division" in text
    assert "A-1.1.1.1." in text
    assert "## Figure Index" in text
    assert "1.1.1.1.-A" in text


def test_write_markdown_handles_no_captions(tmp_path):
    out_path = tmp_path / "out.md"
    write_markdown(_sample_tree(), [], str(out_path))
    assert "## Figure Index" in out_path.read_text()
