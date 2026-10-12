from llm_compare.domain.models import PairRecord, PdfLocation, Verdict, WebLocation
from llm_compare.output.links import RowLinks, page_ids, resolve_links


def _page(*ids, quote='"'):
    body = "".join(f"<p id={quote}{one}{quote}>x</p>" for one in ids)
    return f"<main class='x'>{body}</main>"


def _reader(pages, reads=None):
    def read(path):
        if reads is not None:
            reads.append(path)
        return pages.get(path)

    return read


# ---- page_ids -----------------------------------------------------------------------------


def test_every_id_attribute_on_the_page_is_extracted():
    ids = page_ids(_reader({"p.html": _page("a.b", "c")}), "p.html")
    assert ids == {"a.b", "c"}


def test_single_quoted_ids_and_data_attributes_are_told_apart():
    html = '<p id=\'single\'>1</p><p data-id="nope" aria-labelledby="no">2</p><p id="dbl">3</p>'
    assert page_ids(_reader({"p.html": html}), "p.html") == {"single", "dbl"}


def test_duplicate_ids_collapse_and_entities_are_decoded():
    html = '<p id="a">1</p><p id="a">2</p><p id="x&amp;y">3</p>'
    assert page_ids(_reader({"p.html": html}), "p.html") == {"a", "x&y"}


def test_a_page_without_ids_has_an_empty_set_but_a_missing_page_has_none():
    assert page_ids(_reader({"p.html": "<p>hi</p>"}), "p.html") == set()
    assert page_ids(_reader({}), "gone.html") is None


def test_a_page_that_cannot_be_read_has_none():
    def broken(_path):
        raise OSError("denied")

    assert page_ids(broken, "p.html") is None


# ---- resolve_links ------------------------------------------------------------------------


def _record(row_id="r", pdf=None, web=None, **extra):
    return PairRecord(
        row_id=row_id,
        key=row_id,
        verdict=Verdict.IDENTICAL,
        pdf_path="images/a.png",
        web_path="web_images/a.png",
        pdf_location=pdf,
        web_location=web,
        **extra,
    )


def _pdf(page=40):
    return PdfLocation(page, 91.0, 72.0, 481.0, 252.0)


def _web(element_id="nbc.a.table1", page_file="web_pages/nbc.html"):
    return WebLocation(
        page_file, "/html/body/main/div/main/img[1]", 488, 1530, 988, 1817, element_id
    )


def _links(records, pages, pdf_href="../data/MO%20Package.pdf", prefix="../out/", reads=None):
    return resolve_links(
        records, read_page=_reader(pages, reads), pdf_href=pdf_href, asset_prefix=prefix
    )


def test_an_exact_id_links_the_saved_page_at_that_element():
    pages = {"web_pages/nbc.html": _page("nbc.a.table1")}
    links = _links([_record(web=_web())], pages)["r"]
    assert links.web_href == "../out/web_pages/nbc.html#nbc.a.table1"
    assert (links.web_anchor, links.web_anchor_exact) == ("nbc.a.table1", True)


def test_a_missing_id_links_the_nearest_enclosing_one():
    pages = {"web_pages/nbc.html": _page("nbc.a")}
    links = _links([_record(web=_web("nbc.a.table1.row2"))], pages)["r"]
    assert links.web_href == "../out/web_pages/nbc.html#nbc.a"
    assert (links.web_anchor, links.web_anchor_exact) == ("nbc.a", False)


def test_no_enclosing_id_falls_back_to_the_page_without_a_fragment():
    pages = {"web_pages/nbc.html": _page("zzz")}
    links = _links([_record(web=_web())], pages)["r"]
    assert links.web_href == "../out/web_pages/nbc.html"
    assert links.web_anchor is None and links.web_anchor_exact is None


def test_a_page_that_does_not_exist_gives_no_web_link():
    links = _links([_record(web=_web())], {})["r"]
    assert links.web_href is None and links.web_anchor is None


def test_the_pdf_link_is_the_pdf_at_the_page_and_absent_without_a_pdf():
    assert _links([_record(pdf=_pdf(40))], {})["r"].pdf_href == "../data/MO%20Package.pdf#page=40"
    assert _links([_record(pdf=_pdf(40))], {}, pdf_href=None)["r"].pdf_href is None


def test_a_row_without_locations_has_no_links():
    assert _links([_record()], {})["r"] == RowLinks()


def test_each_distinct_saved_page_is_read_once():
    pages = {"web_pages/nbc.html": _page("nbc.a.table1")}
    reads = []
    records = [_record(f"r{n}", web=_web()) for n in range(5)]
    assert len(_links(records, pages, reads=reads)) == 5
    assert reads == ["web_pages/nbc.html"]


def test_a_missing_page_is_not_read_again_for_every_row():
    reads = []
    _links([_record(f"r{n}", web=_web()) for n in range(3)], {}, reads=reads)
    assert reads == ["web_pages/nbc.html"]


def test_spaces_and_odd_characters_are_url_quoted_in_the_web_link():
    web = _web("a.b c", page_file="web_pages/my page.html")
    pages = {"web_pages/my page.html": _page("a.b c")}
    assert _links([_record(web=web)], pages)["r"].web_href == (
        "../out/web_pages/my%20page.html#a.b%20c"
    )


def test_an_empty_prefix_keeps_the_path_relative_to_the_report():
    pages = {"web_pages/nbc.html": _page("nbc.a.table1")}
    links = _links([_record(web=_web())], pages, prefix="")["r"]
    assert links.web_href == "web_pages/nbc.html#nbc.a.table1"
