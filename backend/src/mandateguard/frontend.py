"""Production frontend serving without affecting the Vite development server."""

from pathlib import Path

from fastapi import FastAPI, HTTPException, Request, status
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles


def install_frontend(application: FastAPI, dist_directory: Path) -> None:
    """Serve a built Vite bundle and browser-route fallback from one origin."""

    dist_directory = dist_directory.resolve()
    index_file = dist_directory / "index.html"
    if not index_file.is_file():
        raise RuntimeError(f"frontend build is missing index.html in {dist_directory}")

    assets_directory = dist_directory / "assets"
    if assets_directory.is_dir():
        application.mount(
            "/assets", StaticFiles(directory=assets_directory), name="frontend-assets"
        )

    @application.api_route("/", methods=["GET", "HEAD"], include_in_schema=False)
    async def frontend_root() -> Response:
        return FileResponse(index_file)

    @application.api_route("/{path:path}", methods=["GET", "HEAD"], include_in_schema=False)
    async def frontend_route(path: str, request: Request) -> Response:
        if path == "api" or path.startswith("api/"):
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)

        requested_file = (dist_directory / path).resolve()
        if requested_file.is_relative_to(dist_directory) and requested_file.is_file():
            return FileResponse(requested_file)

        accepts = request.headers.get("accept", "")
        is_browser_navigation = "text/html" in accepts
        if Path(path).suffix or not is_browser_navigation:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
        return FileResponse(index_file)
