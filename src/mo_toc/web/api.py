import json
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse


def create_app(toc_json_path: str, pdf_path: str, thumbnails_dir: str) -> FastAPI:
    app = FastAPI(title="MO Package TOC Viewer")
    payload = json.loads(Path(toc_json_path).read_text())

    @app.get("/api/toc")
    def get_toc():
        return JSONResponse(payload["volume"])

    @app.get("/api/images")
    def get_images():
        return JSONResponse(payload["images"])

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

    return app
