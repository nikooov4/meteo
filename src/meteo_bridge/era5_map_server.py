"""Loopback frame service used by Streamlit's real ERA5 map iframe."""

import socket
import threading
import time
from collections import OrderedDict

import uvicorn
from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse

from .era5_map_archive import READ_LOCK
from .precipitation_map import map_html


def create_era5_map_app(archives, viewers):
    app = FastAPI(title="MeteoBridge ERA5 map")
    # A downloaded HTML has a null origin; the in-app iframe uses same-origin requests.
    app.add_middleware(CORSMiddleware, allow_origins=["null"], allow_methods=["GET"],
                       expose_headers=["X-Data-Available", "X-Cycle-UTC"])

    def current(key):
        if key not in archives:
            raise HTTPException(404, "Карта устарела. Повторно постройте её в приложении.")
        return archives[key]

    @app.get("/viewer/{key}", response_class=HTMLResponse)
    def viewer(key: str):
        if key not in viewers:
            raise HTTPException(404, "Карта устарела. Повторно постройте её в приложении.")
        return viewers[key]

    @app.get("/archive/{key}/catalog")
    def catalog(key: str):
        return current(key).catalog()

    @app.get("/archive/{key}/range")
    def selection(key: str, start: str, end: str, member: int = 0):
        try:
            return current(key).selection(member, start, end)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc

    @app.get("/archive/{key}/frame")
    def frame(key: str, hour: int, member: int = 0, manifest_sha256: str = ""):
        with READ_LOCK:
            archive = current(key)
            if manifest_sha256 != archive.sha:
                raise HTTPException(409, "Архив изменился. Повторно постройте карту.")
            try:
                payload, headers = archive.frame(member, hour)
                return Response(payload, media_type="application/octet-stream", headers=headers)
            except (ValueError, OSError) as exc:
                raise HTTPException(422, str(exc)) from exc

    @app.get("/health")
    def health(request: Request):
        return {"status": "ok", "archives": len(archives)}

    return app


class Era5MapServer:
    def __init__(self):
        self.archives, self.viewers = OrderedDict(), OrderedDict()
        self.socket = socket.socket()
        self.socket.bind(("127.0.0.1", 0))
        self.socket.listen(32)
        self.url = f"http://127.0.0.1:{self.socket.getsockname()[1]}"
        self.app = create_era5_map_app(self.archives, self.viewers)
        self.server = uvicorn.Server(uvicorn.Config(self.app, log_level="error", access_log=False))
        self.thread = threading.Thread(target=self.server.run, kwargs={"sockets": [self.socket]}, daemon=True)
        self.thread.start()
        deadline = time.monotonic() + 10
        while not self.server.started:
            if not self.thread.is_alive() or time.monotonic() > deadline:
                self.server.should_exit = True
                self.socket.close()
                raise OSError("Не удалось запустить локальный сервер кадров ERA5.")
            time.sleep(.02)

    def add(self, archive, selection):
        key = f"{archive.sha}-{selection['first_hour']}-{selection['hours']}"
        data = archive.initial_map(selection)
        html = map_html(data, f"{self.url}/archive/{key}")
        with READ_LOCK:
            self.archives[key], self.viewers[key] = archive, html
            self.archives.move_to_end(key)
            self.viewers.move_to_end(key)
            while len(self.archives) > 4:
                old, _ = self.archives.popitem(last=False)
                self.viewers.pop(old, None)
        return f"{self.url}/viewer/{key}", html, data["metadata"]
