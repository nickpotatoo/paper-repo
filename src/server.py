"""Bind the listening socket and run Uvicorn for the viewer application."""

import asyncio
import socket
import sys
import webbrowser

import uvicorn

from src import routes
from src import config as repo_config


def launch(
    open_browser: bool = repo_config.OPEN_BROWSER,
    auto_shutdown: bool = repo_config.AUTO_SHUTDOWN,
    *,
    validate: bool = repo_config.VALIDATE_REQUEST_DATA,
    port: int | None = None,
    host: str = repo_config.SERVER_HOST,
) -> None:
    """Run Uvicorn using repo paths from src.config."""
    app = routes.create_app(
        papers_path=repo_config.PAPERS_PATH,
        taxonomy_path=repo_config.TAXONOMY_PATH,
        state_path=repo_config.REPO_STATE_PATH,
        viewer_dir=repo_config.VIEWER_DIR,
        validate=validate, auto_shutdown=auto_shutdown,
        on_idle=lambda: setattr(server, "should_exit", True),
    )

    class ViewerServer(uvicorn.Server):
        async def startup(self, sockets=None) -> None:
            await super().startup(sockets=sockets)
            if self.started:
                print(url, flush=True)
                if open_browser:
                    await asyncio.to_thread(webbrowser.open, url)

    config = uvicorn.Config(
        app, host=host, port=port or 0,
        access_log=repo_config.UVICORN_ACCESS_LOG, log_level=repo_config.UVICORN_LOG_LEVEL,
    )
    server = ViewerServer(config)
    # Hold the socket throughout startup, including when the OS picks port 0.
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        if sys.platform == "win32":
            listener.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        else:
            listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        listener.bind((host, port or 0))
        listener.setblocking(False)
        browser_host = repo_config.BROWSER_HOST if host == "0.0.0.0" else host
        url = f"http://{browser_host}:{listener.getsockname()[1]}/"
        server.run(sockets=[listener])


if __name__ == "__main__":
    launch()
