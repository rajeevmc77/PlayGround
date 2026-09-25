"""Assigns every node a cross-source unified_number built from the building
code's own numbering, so the same clause/table/note gets the same key in
bcbc_pdf.json and bcbc_web.json (design:
ai_docs/2026-09-25-cross-source-unified-numbering-design.md).

Each pipeline supplies a {node type: Rule} table. Sibling position is used only
by the "ordinal" rule, for things with no official number. Duck-types on any
object exposing `.type`, `.identifier`, `.citation`, `.children` and a settable
`.unified_number` - no dependency on either domain model.
"""

from collections.abc import Callable
from dataclasses import dataclass, field

# Kinds whose key restarts the chain: nothing above them (e.g. the volume)
# leaks into descendants' keys, and they are never ~n-suffixed - the web
# splits Division B across two volumes and both must stay "B".
_RESTART_KINDS = frozenset({"fixed", "root"})
_IDENTIFIER_KINDS = frozenset({"root", "absolute", "child", "suffix"})


@dataclass(frozen=True)
class Rule:
    """kind:
    fixed    -> `prefix` verbatim ("V1", "FM")
    root     -> prefix + identifier ("B", "AppD", "V2")
    absolute -> nearest restart key + "." + identifier ("B.9.10.18.2")
    child    -> parent key + "." + identifier ("B.9.10.18.2.(2)")
    suffix   -> parent key + identifier, no dot ("B.9.10.18.2.(2)(a)")
    literal  -> parent key + "." + prefix ("B.9.Notes")
    ordinal  -> base + "." + prefix + n, counting same-type nodes under base;
                base is the enclosing scope node when `scoped`, else the parent.
    `fallback` (identifier kinds only) is a fixed key used when the
    identifier is empty (the web's unnumbered "Preface" division -> "FM").
    """

    kind: str
    prefix: str = ""
    scoped: bool = False
    fallback: str = ""


@dataclass(frozen=True)
class _Context:
    parent_key: str = ""
    root_key: str = ""
    scope_key: str = ""


@dataclass
class _Walk:
    rules: dict[str, Rule]
    scope_types: frozenset[str]
    counters: dict[tuple[str, str], int] = field(default_factory=dict)
    seen: dict[str, int] = field(default_factory=dict)
    scope_by_citation: dict[str, str] = field(default_factory=dict)


def normalize_identifier(identifier: str) -> str:
    return " ".join(identifier.split()).rstrip(".")


def _join(base: str, segment: str) -> str:
    return f"{base}.{segment}" if base else segment


_BUILDERS: dict[str, Callable[[str, Rule, _Context], str]] = {
    "fixed": lambda ident, rule, ctx: rule.prefix,
    "root": lambda ident, rule, ctx: f"{rule.prefix}{ident}",
    "absolute": lambda ident, rule, ctx: _join(ctx.root_key, ident),
    "child": lambda ident, rule, ctx: _join(ctx.parent_key, ident),
    "suffix": lambda ident, rule, ctx: f"{ctx.parent_key}{ident}",
    "literal": lambda ident, rule, ctx: _join(ctx.parent_key, rule.prefix),
}


def _rule_for(node, walk: _Walk) -> Rule:
    rule = walk.rules.get(node.type, Rule("ordinal", node.type))
    if rule.kind not in _IDENTIFIER_KINDS or normalize_identifier(node.identifier):
        return rule
    if rule.fallback:
        return Rule("fixed", rule.fallback)
    return Rule("ordinal", node.type)


def _ordinal(node, rule: Rule, ctx: _Context, walk: _Walk) -> str:
    base = ctx.scope_key if rule.scoped else ctx.parent_key
    counter = (base, node.type)
    walk.counters[counter] = walk.counters.get(counter, 0) + 1
    return _join(base, f"{rule.prefix}{walk.counters[counter]}")


def _key_for(node, rule: Rule, ctx: _Context, walk: _Walk) -> str:
    if rule.kind == "ordinal":
        return _ordinal(node, rule, ctx, walk)
    return _BUILDERS[rule.kind](normalize_identifier(node.identifier), rule, ctx)


def _unique(key: str, rule: Rule, walk: _Walk) -> str:
    if rule.kind in _RESTART_KINDS:
        return key
    count = walk.seen.get(key, 0) + 1
    walk.seen[key] = count
    return key if count == 1 else f"{key}~{count}"


def _child_context(node, key: str, rule: Rule, ctx: _Context, walk: _Walk) -> _Context:
    restarts = rule.kind in _RESTART_KINDS
    root_key = key if restarts else ctx.root_key
    scope_key = key if restarts or node.type in walk.scope_types else ctx.scope_key
    return _Context(parent_key=key, root_key=root_key, scope_key=scope_key)


def _number(nodes: list, ctx: _Context, walk: _Walk) -> None:
    for node in nodes:
        rule = _rule_for(node, walk)
        node.unified_number = _unique(_key_for(node, rule, ctx, walk), rule, walk)
        child_ctx = _child_context(node, node.unified_number, rule, ctx, walk)
        # First wins: a later node reusing a citation must not re-key its images.
        walk.scope_by_citation.setdefault(node.citation, child_ctx.scope_key or node.unified_number)
        _number(node.children, child_ctx, walk)


def assign_unified_numbers(
    nodes: list, rules: dict[str, Rule], scope_types: frozenset[str] = frozenset()
) -> dict[str, str]:
    """Numbers `nodes` and all descendants in place. Returns citation -> key of
    that node's nearest enclosing scope node (itself included), which
    number_images uses to key an image by its owner."""
    walk = _Walk(rules=rules, scope_types=scope_types)
    _number(nodes, _Context(), walk)
    return walk.scope_by_citation


def number_images(
    images: list,
    scope_by_citation: dict[str, str],
    skip: Callable[[object], bool] | None = None,
) -> None:
    counters: dict[str, int] = {}
    for image in images:
        base = scope_by_citation.get(image.owner_citation)
        if base is None or (skip is not None and skip(image)):
            continue
        counters[base] = counters.get(base, 0) + 1
        image.unified_number = f"{base}.Fig{counters[base]}"
