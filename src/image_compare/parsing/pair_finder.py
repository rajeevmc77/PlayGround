from pathlib import Path

from image_compare.domain.models import MatchedStem, PairingResult


def find_pairs(pdf_filenames: list[str], web_filenames: list[str]) -> PairingResult:
    """Pairs filenames by stem (filename without its final extension), since
    the same figure carries a different extension in each source: a PNG
    rendered from the PDF vs. a JPEG downloaded from the website."""
    pdf_by_stem = {Path(name).stem: name for name in pdf_filenames}
    web_by_stem = {Path(name).stem: name for name in web_filenames}
    shared_stems = pdf_by_stem.keys() & web_by_stem.keys()

    matched = [
        MatchedStem(stem=stem, pdf_filename=pdf_by_stem[stem], web_filename=web_by_stem[stem])
        for stem in sorted(shared_stems)
    ]
    pdf_only = sorted(pdf_by_stem[stem] for stem in pdf_by_stem.keys() - web_by_stem.keys())
    web_only = sorted(web_by_stem[stem] for stem in web_by_stem.keys() - pdf_by_stem.keys())
    return PairingResult(matched=matched, pdf_only=pdf_only, web_only=web_only)
