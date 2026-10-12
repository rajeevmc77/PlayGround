# ruff: noqa: E501  (the prompt is the user's text, verbatim; its lines are long)
"""The agreed Gemini comparison prompt, verbatim, plus the paragraph that makes it work on
a batch of numbered pairs. Editing the text changes PROMPT_VERSION and so invalidates the
cache."""

import hashlib

INSTRUCTIONS = """\
System / Instruction Prompt:
You are an expert visual analysis AI. Your task is to compare two provided images to determine if their visible content, information, and structural layout are functionally identical.
Guidelines for Comparison:

1. Focus on Content: Compare all text, labels, diagrams, shapes, illustrations, annotations, structural elements, and data points present in both images.
2. Ignore Quality & Formatting Differences: Do NOT flag differences in image resolution, pixelation, compression artifacts, aspect ratio, image file format, scaling, or minor brightness/contrast variations.
3. Determine Match: The images should be considered identical in content if a reader receives the exact same information, wording, diagrams, and layout from both.

Output Structure:

* Verdict: State clearly whether the content is IDENTICAL or DIFFERENT
* Differences (if any):
* If DIFFERENT, list the specific missing, modified, visible information, wording, annotations, and structural diagrams  between the two.

Batch handling: this call holds several numbered pairs. Judge each pair independently of the others, comparing only image A (PDF) with image B (web) of the same pair. Return one verdict per pair, with pair_id equal to the PAIR number, verdict exactly IDENTICAL or DIFFERENT, and differences empty when IDENTICAL.
"""

PROMPT_VERSION = hashlib.sha256(INSTRUCTIONS.encode()).hexdigest()[:12]
