from web_toc.parsing.page_html import ASSET_PREFIX
from web_toc.parsing.site_css import build_nav_css, css_url_paths, rebase_css_urls

_CSS_PATH = "/_next/static/chunks/0_2w1old0g5~5.css"
_FONT_FACE = (
    '@font-face{font-family:BC Sans;src:url(../media/BCSans-Regular.0zj.woff2)format("woff2"),'
    "url('../media/BCSans-Regular.09j.woff')format(\"woff\")}"
)


def test_css_url_paths_resolves_relative_urls_against_the_stylesheet():
    assert css_url_paths(_FONT_FACE, _CSS_PATH) == [
        "/_next/static/media/BCSans-Regular.0zj.woff2",
        "/_next/static/media/BCSans-Regular.09j.woff",
    ]


def test_css_url_paths_keeps_root_relative_urls():
    assert css_url_paths('a{background:url("/bc-logo.png")}', _CSS_PATH) == ["/bc-logo.png"]


def test_css_url_paths_skips_data_uris_and_other_hosts():
    css = (
        'a{background:url("data:image/svg+xml,%3Csvg%3E")}'
        "b{src:url(https://cdn.example/f.woff)}c{src:url(//cdn.example/g.woff)}"
    )
    assert css_url_paths(css, _CSS_PATH) == []


def test_css_url_paths_deduplicates_in_first_seen_order():
    css = "a{src:url(x.woff)}b{src:url(y.woff)}c{src:url(x.woff)}"
    assert css_url_paths(css, "/s/a.css") == ["/s/x.woff", "/s/y.woff"]


def test_css_url_paths_is_empty_without_urls():
    assert css_url_paths(".nav-tree{display:block}", _CSS_PATH) == []


def test_rebase_css_urls_points_resolved_urls_at_the_asset_mirror():
    assert rebase_css_urls("a{src:url('../media/f.woff2')}", _CSS_PATH) == (
        f'a{{src:url("{ASSET_PREFIX}/_next/static/media/f.woff2")}}'
    )


def test_rebase_css_urls_leaves_data_uris_and_other_hosts_alone():
    css = 'a{background:url("data:image/svg+xml,x")}b{src:url(https://cdn.example/f.woff)}'
    assert rebase_css_urls(css, _CSS_PATH) == css


def test_build_nav_css_rebases_each_rule_against_its_own_stylesheet():
    rules = [
        {"href": "/_next/static/chunks/a.css", "css": "@font-face { src: url(../media/f.woff2); }"},
        {"href": "/", "css": ".nav-tree-link { color: red; }"},
    ]
    assert build_nav_css(rules) == (
        f'@font-face {{ src: url("{ASSET_PREFIX}/_next/static/media/f.woff2"); }}\n'
        ".nav-tree-link { color: red; }\n"
    )


def test_build_nav_css_drops_exact_duplicate_rules():
    # Every stylesheet re-declares its own :root block; identical copies add nothing.
    rule = {"href": "/", "css": ":root { --x: 1; }"}
    assert build_nav_css([rule, dict(rule)]) == ":root { --x: 1; }\n"


def test_build_nav_css_of_no_rules_is_empty():
    assert build_nav_css([]) == ""
