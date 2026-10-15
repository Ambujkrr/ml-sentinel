"""Native HTML sign-in keeps administrator credentials out of dashboard JS."""
import hmac
from pathlib import Path
from urllib.parse import parse_qs

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.admin import (COOKIE_NAME, SESSION_SECONDS, admin_enabled, admin_sessions,
                            require_admin, require_admin_action, require_enabled, require_origin)
from app.core.config import get_settings
from app.db.session import get_db
from app.models.domain import PendingDatasetDeletion

router = APIRouter(prefix="/admin", tags=["dataset administration"])


def login_page(error: str = "", status_code: int = 200):
    page = (Path(__file__).resolve().parents[2] / "web" / "admin-login.html").read_text(encoding="utf-8")
    # no-referrer turns the Origin of native form POSTs into null in browsers,
    # conflicting with the strict CSRF check. same-origin keeps it for this form
    # while suppressing referrers to other sites.
    return HTMLResponse(page.replace("<!--ADMIN_ERROR-->", error), status_code=status_code,
                        headers={"Cache-Control": "no-store", "Referrer-Policy": "same-origin",
                                 "X-Frame-Options": "DENY", "Content-Security-Policy":
                                 "default-src 'none'; style-src 'self'; form-action 'self'; base-uri 'none'; frame-ancestors 'none'"})


@router.get("/session")
def session_status(request: Request):
    return JSONResponse({"enabled": admin_enabled(), "authenticated":
                         admin_sessions.valid(request.cookies.get(COOKIE_NAME, ""))},
                        headers={"Cache-Control": "no-store"})


@router.get("/login", response_class=HTMLResponse, dependencies=[Depends(require_enabled)])
def login_form():
    return login_page()


@router.post("/login", dependencies=[Depends(require_origin)])
async def login(request: Request):
    admin_sessions.allow_login()
    if request.query_params or request.headers.get("content-type", "").split(";")[0] != "application/x-www-form-urlencoded":
        raise HTTPException(400, "Use the administrator sign-in form")
    body = bytearray()
    async for chunk in request.stream():
        if len(body) + len(chunk) > 2048:
            raise HTTPException(413, "Sign-in request is too large")
        body.extend(chunk)
    try:
        fields = parse_qs(body.decode("utf-8"), keep_blank_values=True, strict_parsing=True,
                          max_num_fields=2, errors="strict")
        if set(fields) != {"username", "password"} or any(len(values) != 1 for values in fields.values()):
            raise ValueError
        settings = get_settings()
        username_matches = hmac.compare_digest(fields["username"][0].encode(),
                                                settings.ADMIN_USERNAME.get_secret_value().encode())
        password_matches = hmac.compare_digest(fields["password"][0].encode(),
                                                settings.ADMIN_PASSWORD.get_secret_value().encode())
    except (UnicodeError, ValueError):
        username_matches = password_matches = False
    if not (username_matches and password_matches):
        return login_page('<p role="alert">Sign-in failed. Check your administrator credentials.</p>', 401)
    response = RedirectResponse("/dashboard", status_code=303, headers={"Cache-Control": "no-store"})
    response.set_cookie(COOKIE_NAME, admin_sessions.create(), max_age=SESSION_SECONDS,
                        httponly=True, secure=get_settings().ADMIN_ALLOWED_ORIGIN.startswith("https://"),
                        samesite="strict", path="/")
    return response


@router.post("/logout", dependencies=[Depends(require_admin_action)])
def logout(request: Request):
    admin_sessions.revoke(request.cookies.get(COOKIE_NAME, ""))
    response = Response(status_code=204, headers={"Cache-Control": "no-store"})
    response.delete_cookie(COOKIE_NAME, path="/", httponly=True, samesite="strict",
                           secure=get_settings().ADMIN_ALLOWED_ORIGIN.startswith("https://"))
    return response


@router.get("/deletions", dependencies=[Depends(require_admin)])
def pending_deletions(db: Session = Depends(get_db)):
    jobs = db.scalars(select(PendingDatasetDeletion).order_by(PendingDatasetDeletion.id).limit(100)).all()
    return JSONResponse([{"dataset_id": job.id, "name": job.dataset_name} for job in jobs],
                        headers={"Cache-Control": "no-store"})
