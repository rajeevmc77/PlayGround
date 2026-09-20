from web_toc.domain.models import WebNode


def build_tree(nav_data: dict) -> WebNode:
    return WebNode(
        type="root",
        identifier="",
        citation="root",
        title="BC Building Code",
        path="/",
        children=[_convert(raw) for raw in nav_data["tree"]],
    )


def _convert(raw: dict) -> WebNode:
    return WebNode(
        type=raw["type"],
        identifier=str(raw.get("number", "")),
        citation=raw["id"],
        title=raw.get("title", ""),
        path=raw.get("path", ""),
        children=[_convert(child) for child in raw.get("children", [])],
    )


def collect_citations(node: WebNode) -> set[str]:
    citations = {node.citation}
    for child in node.children:
        citations |= collect_citations(child)
    return citations
