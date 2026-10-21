"""Cliente HTTP/WS del servidor FoxMsg.

- Failover automático: Tailscale -> Cloudflare -> (reintento).
- Todas las llamadas son síncronas: el caller las ejecuta en un hilo.
"""
from __future__ import annotations

import json
import threading
from typing import Any, Callable

import httpx

from . import config


class ApiError(Exception):
    def __init__(self, status: int, detail: Any):
        super().__init__(f"HTTP {status}: {detail}")
        self.status = status
        self.detail = detail

    @property
    def message(self) -> str:
        if isinstance(self.detail, dict):
            return str(self.detail.get("message") or self.detail)
        return str(self.detail)


class Api:
    def __init__(self) -> None:
        self.base: str | None = None      # servidor activo (tras primer éxito)
        self.access: str | None = None
        self.refresh: str | None = None
        self._lock = threading.Lock()
        # timeout generoso: subidas de media de hasta 50 MB
        self._client = httpx.Client(timeout=60.0)

    # ------------------------------------------------------------ auth

    def set_tokens(self, access: str | None, refresh: str | None) -> None:
        self.access, self.refresh = access, refresh

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.access}"} if self.access else {}

    # ------------------------------------------------------------ request

    def _bases(self) -> list[str]:
        if self.base:
            # activo primero, luego el otro como respaldo
            rest = [u for _, u in config.SERVERS if u != self.base]
            return [self.base, *rest]
        return [u for _, u in config.SERVERS]

    def request(
        self,
        method: str,
        path: str,
        *,
        json_body: Any = None,
        data: Any = None,
        files: Any = None,
        params: dict | None = None,
        auth: bool = True,
    ) -> Any:
        last_exc: Exception | None = None
        for base in self._bases():
            try:
                resp = self._client.request(
                    method,
                    base + path,
                    json=json_body,
                    data=data,
                    files=files,
                    params=params,
                    headers=self._headers() if auth else {},
                )
            except httpx.HTTPError as exc:
                last_exc = exc
                continue  # probar siguiente servidor

            self.base = base  # este servidor respondió
            if resp.status_code >= 400:
                try:
                    detail = resp.json().get("detail", resp.text)
                except Exception:
                    detail = resp.text
                err = ApiError(resp.status_code, detail)
                # 401: intentar refresh una vez
                if resp.status_code == 401 and auth and self.refresh and path != "/api/auth/refresh":
                    if self._try_refresh():
                        return self.request(
                            method, path, json_body=json_body, data=data,
                            files=files, params=params, auth=auth,
                        )
                raise err
            if resp.status_code == 204 or not resp.content:
                return {}
            try:
                return resp.json()
            except Exception:
                return {"raw": resp.text}
        raise ApiError(0, f"Servidor inaccesible: {last_exc}")

    def _try_refresh(self) -> bool:
        try:
            resp = self._client.post(
                self._bases()[0] + "/api/auth/refresh",
                json={"refresh": self.refresh},
                timeout=8.0,
            )
            if resp.status_code >= 400:
                return False
            tokens = resp.json()["tokens"]
            self.access, self.refresh = tokens["access"], tokens["refresh"]
            return True
        except Exception:
            return False

    # ------------------------------------------------------------ atajos

    def get(self, path: str, **kw) -> Any:
        return self.request("GET", path, **kw)

    def post(self, path: str, body: Any = None, **kw) -> Any:
        return self.request("POST", path, json_body=body, **kw)

    def put(self, path: str, body: Any = None, **kw) -> Any:
        return self.request("PUT", path, json_body=body, **kw)

    def delete(self, path: str, **kw) -> Any:
        return self.request("DELETE", path, **kw)

    def upload(self, path: str, filename: str, content: bytes, mime: str) -> Any:
        # Validación local ANTES de enviar: el servidor rechaza por
        # Content-Length y corta la conexión, lo que el cliente vería como
        # error de red en vez de un 413 limpio.
        if len(content) > config.MAX_UPLOAD_BYTES:
            mb = config.MAX_UPLOAD_BYTES // (1024 * 1024)
            raise ApiError(413, f"El archivo supera los {mb} MB")
        return self.request(
            "POST", path, files={"file": (filename, content, mime)}
        )

    def media_url(self, media_path: str) -> str:
        """URL absoluta para QML Image (token por query: QML no manda headers)."""
        base = self.base or config.SERVERS[0][1]
        if not self.access:
            return base + media_path
        sep = "&" if "?" in media_path else "?"
        return f"{base}{media_path}{sep}token={self.access}"

    def ws_url(self) -> str:
        if self.base:
            ws_base = self.base.replace("http://", "ws://").replace("https://", "wss://")
            rest = [u for _, u in config.WS_SERVERS if u != ws_base]
            order = [ws_base, *rest]
        else:
            order = [u for _, u in config.WS_SERVERS]
        return order[0] + f"/api/ws?token={self.access}"

    def server_label(self) -> str:
        if not self.base:
            return "—"
        for name, url in config.SERVERS:
            if url == self.base:
                return name
        return self.base


api = Api()
