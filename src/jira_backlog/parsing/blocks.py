"""Splits a Markdown document into the blocks that start at a matching line."""

import re
from collections.abc import Callable


def split_blocks(
    lines: list[str], start: re.Pattern, ends: Callable[[str], bool]
) -> list[list[str]]:
    """Each block runs from a line matching ``start`` up to the next start or
    the next line for which ``ends`` is true (which belongs to no block)."""
    blocks: list[list[str]] = []
    open_block: list[str] | None = None
    for line in lines:
        if start.match(line):
            open_block = [line]
            blocks.append(open_block)
        elif ends(line):
            open_block = None
        elif open_block is not None:
            open_block.append(line)
    return blocks
