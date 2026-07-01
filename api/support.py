from __future__ import annotations

from pathlib import Path
from threading import Event, Thread
from urllib.parse import urlparse

from fastapi import HTTPException, Request

from services.auth_service import auth_service
from services.config import config

BASE_DIR = Path(__file__).resolve().parents[1]
WEB_DIST_DIR = BASE_DIR / "web_dist"


def extract_bearer_token(authorization: str | None) -> str:
    scheme, _, value = str(authorization or "").partition(" ")
    if scheme.lower() != "bearer" or not value.strip():
        return ""
    return value.strip()


def _legacy_admin_identity(token: str) -> dict[str, object] | None:
    auth_key = str(config.auth_key or "").strip()
    if auth_key and token == auth_key:
        return {"id": "admin", "name": "管理员", "role": "admin"}
    return None


def require_identity(authorization: str | None) -> dict[str, object]:
    token = extract_bearer_token(authorization)
    identity = _legacy_admin_identity(token) or auth_service.authenticate(token)
    if identity is None:
        raise HTTPException(status_code=401, detail={"error": "authorization is invalid"})
    return identity


def require_auth_key(authorization: str | None) -> None:
    require_identity(authorization)


def require_admin(authorization: str | None) -> dict[str, object]:
    identity = require_identity(authorization)
    if identity.get("role") != "admin":
        raise HTTPException(status_code=403, detail={"error": "admin permission required"})
    return identity


def _base_url_from_absolute_url(value: object) -> str:
    parsed = urlparse(str(value or "").strip())
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return ""
    return f"{parsed.scheme}://{parsed.netloc}".rstrip("/")


def _first_header_value(value: object) -> str:
    return str(value or "").split(",", 1)[0].strip()


def resolve_image_base_url(request: Request) -> str:
    configured = config.base_url
    if configured:
        return configured

    origin = _base_url_from_absolute_url(request.headers.get("origin"))
    if origin:
        return origin

    referer = _base_url_from_absolute_url(request.headers.get("referer"))
    if referer:
        return referer

    forwarded_host = _first_header_value(request.headers.get("x-forwarded-host"))
    if forwarded_host:
        forwarded_proto = _first_header_value(request.headers.get("x-forwarded-proto")) or str(request.url.scheme)
        if forwarded_proto in {"http", "https"}:
            return f"{forwarded_proto}://{forwarded_host}".rstrip("/")

    return f"{request.url.scheme}://{request.headers.get('host', request.url.netloc)}".rstrip("/")


def raise_image_quota_error(exc: Exception) -> None:
    message = str(exc)
    if "no available image quota" in message.lower():
        raise HTTPException(status_code=429, detail={"error": "no available image quota"}) from exc
    raise HTTPException(status_code=502, detail={"error": message}) from exc


def start_quota_reservation_watcher(stop_event: Event) -> Thread:
    def worker() -> None:
        while not stop_event.is_set():
            try:
                expired = auth_service.expire_quota_reservations()
                if expired:
                    print(f"[quota-reservation-watcher] expired {expired} reservations")
            except Exception as exc:
                print(f"[quota-reservation-watcher] fail {exc}")
            stop_event.wait(60)

    thread = Thread(target=worker, name="quota-reservation-watcher", daemon=True)
    thread.start()
    return thread


def resolve_web_asset(requested_path: str) -> Path | None:
    if not WEB_DIST_DIR.exists():
        return None
    clean_path = requested_path.strip("/")
    base_dir = WEB_DIST_DIR.resolve()
    if clean_path == "favicon.ico":
        site_icon = str(config.site_icon or "").strip()
        if site_icon.startswith("/") and "://" not in site_icon:
            icon_path = site_icon.split("?", 1)[0].lstrip("/")
            candidate = base_dir / Path(icon_path)
            try:
                candidate.resolve().relative_to(base_dir)
            except ValueError:
                candidate = None
            if candidate is not None and candidate.is_file():
                return candidate
    candidates = [base_dir / "index.html"] if not clean_path else [
        base_dir / Path(clean_path),
        base_dir / clean_path / "index.html",
        base_dir / f"{clean_path}.html",
    ]
    for candidate in candidates:
        try:
            candidate.resolve().relative_to(base_dir)
        except ValueError:
            continue
        if candidate.is_file():
            return candidate
    return None
