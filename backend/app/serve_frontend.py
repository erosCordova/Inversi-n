import base64
import binascii
import os
import secrets
from pathlib import Path

from fastapi import Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from .main import app


FRONTEND_DIST = (
    Path(__file__).resolve().parents[2]
    / "frontend"
    / "dist"
)

AUTH_USER = os.getenv("REPLIKERS_USER", "")
AUTH_PASSWORD = os.getenv("REPLIKERS_PASSWORD", "")

if not AUTH_USER or not AUTH_PASSWORD:
    raise RuntimeError(
        "Configura REPLIKERS_USER y REPLIKERS_PASSWORD "
        "antes de iniciar el servidor de despliegue."
    )

if not FRONTEND_DIST.is_dir():
    raise RuntimeError(
        f"No se encontró el frontend compilado: {FRONTEND_DIST}"
    )


def valid_credentials(authorization: str | None) -> bool:
    if not authorization or not authorization.startswith("Basic "):
        return False

    try:
        encoded = authorization.removeprefix("Basic ").strip()
        decoded = base64.b64decode(
            encoded,
            validate=True,
        ).decode("utf-8")
    except (binascii.Error, UnicodeDecodeError, ValueError):
        return False

    supplied_user, separator, supplied_password = decoded.partition(":")

    return (
        bool(separator)
        and secrets.compare_digest(supplied_user, AUTH_USER)
        and secrets.compare_digest(supplied_password, AUTH_PASSWORD)
    )


@app.middleware("http")
async def protect_application(request: Request, call_next):
    if request.url.path == "/api/health":
        return await call_next(request)

    if not valid_credentials(
        request.headers.get("authorization")
    ):
        return JSONResponse(
            status_code=401,
            content={"detail": "Se requiere iniciar sesión."},
            headers={
                "WWW-Authenticate": 'Basic realm="Replikers"',
                "Cache-Control": "no-store",
            },
        )

    return await call_next(request)


app.mount(
    "/",
    StaticFiles(directory=FRONTEND_DIST, html=True),
    name="frontend",
)