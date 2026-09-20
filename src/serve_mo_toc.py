#!/usr/bin/env python3
"""Launches the interactive MO Package TOC/Image viewer.

Usage:
    python3 src/serve_mo_toc.py            # serves on http://127.0.0.1:8001
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from mo_toc.web.api import create_app

PROJECT_ROOT = Path(__file__).resolve().parent.parent
TOC_JSON = str(PROJECT_ROOT / "output" / "mo_toc.json")
PDF_PATH = str(PROJECT_ROOT / "data" / "MO Package BCBC MRK signed.pdf")
THUMBNAILS_DIR = str(PROJECT_ROOT / "output" / "thumbnails")

app = create_app(toc_json_path=TOC_JSON, pdf_path=PDF_PATH, thumbnails_dir=THUMBNAILS_DIR)


def main() -> None:
    import uvicorn

    if not Path(TOC_JSON).exists():
        sys.exit(f"No such file: {TOC_JSON} (run src/build_mo_toc.py first)")
    uvicorn.run(app, host="127.0.0.1", port=8001)


if __name__ == "__main__":
    main()
