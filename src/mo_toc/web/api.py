import json
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from web_toc.output.page_writer import asset_file, page_file

_NOT_BUILT = "Run src/build_web_pages.py first"
_LLM_NOT_BUILT = "Run src/build_llm_comparison.py first"


def _add_web_page_routes(app: FastAPI, web_pages_dir: str | None) -> None:
    """Serves the live site's own scraped reading pages (build_web_pages.py)
    and the site stylesheets/fonts/images they reference, mirrored under
    the same paths the site uses."""
    pages_dir = Path(web_pages_dir) if web_pages_dir else None

    def built_dir() -> Path:
        if pages_dir is None or not (pages_dir / "pages.json").exists():
            raise HTTPException(status_code=503, detail=_NOT_BUILT)
        return pages_dir

    def existing(path: Path | None) -> Path:
        if path is None or not path.is_file():
            raise HTTPException(status_code=404, detail="Not found")
        return path

    @app.get("/web-page/{citation}")
    def get_web_page(citation: str):
        return FileResponse(str(existing(page_file(built_dir(), citation))))

    @app.get("/web-assets/{site_path:path}")
    def get_web_asset(site_path: str):
        return FileResponse(str(existing(asset_file(built_dir() / "assets", f"/{site_path}"))))


def _read_llm_report(report_path: str | None):
    """The LLM image report, read fresh so a run made while the server is up shows
    after a browser refresh; 503 (never a traceback) when it is absent or unreadable."""
    if not report_path or not Path(report_path).is_file():
        raise HTTPException(status_code=503, detail=_LLM_NOT_BUILT)
    try:
        return json.loads(Path(report_path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        detail = f"{Path(report_path).name} is not valid JSON ({error}). {_LLM_NOT_BUILT}"
        raise HTTPException(status_code=503, detail=detail) from error


def _image_under(root: Path, relative: str) -> Path:
    """`relative` resolved inside `root`; 404 for anything that lands outside it
    (`..`, an absolute path, a symlink out) or is not a file."""
    resolved_root = root.resolve()
    try:
        target = (resolved_root / relative).resolve()
        inside = target.is_relative_to(resolved_root) and target.is_file()
    except (OSError, ValueError):  # e.g. a NUL byte in the path
        inside = False
    if not inside:
        raise HTTPException(status_code=404, detail="Not found")
    return target


def _add_llm_routes(app: FastAPI, llm_report_path: str | None, output_dir: str | None) -> None:
    """The viewer's "Image Comparison" tab: build_llm_comparison.py's report and the
    PDF/web image files it points at (paths relative to the output dir)."""

    @app.get("/api/llm-comparison")
    def get_llm_comparison():
        return JSONResponse(_read_llm_report(llm_report_path))

    @app.get("/api/llm-image/{path:path}")
    def get_llm_image(path: str):
        if not output_dir:
            raise HTTPException(status_code=503, detail=_LLM_NOT_BUILT)
        return FileResponse(str(_image_under(Path(output_dir), path)))


def create_app(
    toc_json_path: str,
    pdf_path: str,
    images_dir: str,
    web_toc_json_path: str | None = None,
    web_pages_dir: str | None = None,
    comparison_json_path: str | None = None,
    llm_report_path: str | None = None,
    output_dir: str | None = None,
) -> FastAPI:
    app = FastAPI(title="MO Package TOC Viewer")
    payload = json.loads(Path(toc_json_path).read_text())
    web_payload = None
    if web_toc_json_path and Path(web_toc_json_path).exists():
        web_payload = json.loads(Path(web_toc_json_path).read_text())
    comparison_payload = None
    if comparison_json_path and Path(comparison_json_path).exists():
        comparison_payload = json.loads(Path(comparison_json_path).read_text())

    @app.get("/api/toc")
    def get_toc():
        return JSONResponse(payload["volume"])

    @app.get("/api/images")
    def get_images():
        return JSONResponse(payload["images"])

    @app.get("/api/web-toc")
    def get_web_toc():
        if web_payload is None:
            raise HTTPException(status_code=503, detail="Run src/build_web_toc.py first")
        return JSONResponse(web_payload)

    @app.get("/api/comparison")
    def get_comparison():
        if comparison_payload is None:
            raise HTTPException(status_code=503, detail="Run src/build_comparison.py first")
        return JSONResponse(comparison_payload)

    @app.get("/pdf")
    def get_pdf():
        return FileResponse(pdf_path, media_type="application/pdf")

    @app.get("/api/image/{index}")
    def get_image(index: int):
        if index < 0 or index >= len(payload["images"]):
            raise HTTPException(status_code=404, detail="No such image")
        rel_path = payload["images"][index]["image_path"]
        file_path = Path(images_dir).parent / rel_path
        if not file_path.exists():
            raise HTTPException(status_code=404, detail="Image file missing")
        return FileResponse(str(file_path))

    @app.get("/api/web-image/{image_id}/thumbnail")
    def get_web_image(image_id: str):
        if web_payload is None:
            raise HTTPException(status_code=503, detail="Run src/build_web_toc.py first")
        match = next((i for i in web_payload["images"] if i["id"] == image_id), None)
        if match is None or not match["local_path"]:
            raise HTTPException(status_code=404, detail="No cached image")
        file_path = Path(web_toc_json_path).parent / match["local_path"]
        if not file_path.exists():
            raise HTTPException(status_code=404, detail="Cached image file missing")
        return FileResponse(str(file_path))

    _add_web_page_routes(app, web_pages_dir)
    _add_llm_routes(app, llm_report_path, output_dir)

    static_dir = Path(__file__).resolve().parent / "static"
    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

    @app.get("/")
    def index():
        return FileResponse(str(static_dir / "index.html"))

    return app
