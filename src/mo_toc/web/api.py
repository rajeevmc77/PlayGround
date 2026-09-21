import json
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles


def create_app(
    toc_json_path: str,
    pdf_path: str,
    thumbnails_dir: str,
    web_toc_json_path: str | None = None,
) -> FastAPI:
    app = FastAPI(title="MO Package TOC Viewer")
    payload = json.loads(Path(toc_json_path).read_text())
    web_payload = None
    if web_toc_json_path and Path(web_toc_json_path).exists():
        web_payload = json.loads(Path(web_toc_json_path).read_text())

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

    @app.get("/pdf")
    def get_pdf():
        return FileResponse(pdf_path, media_type="application/pdf")

    @app.get("/api/image/{index}/thumbnail")
    def get_thumbnail(index: int):
        if index < 0 or index >= len(payload["images"]):
            raise HTTPException(status_code=404, detail="No such image")
        rel_path = payload["images"][index]["thumbnail_path"]
        file_path = Path(thumbnails_dir).parent / rel_path
        if not file_path.exists():
            raise HTTPException(status_code=404, detail="Thumbnail file missing")
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

    static_dir = Path(__file__).resolve().parent / "static"
    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

    @app.get("/")
    def index():
        return FileResponse(str(static_dir / "index.html"))

    return app
