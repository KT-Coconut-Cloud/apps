import time

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse

from app.auth import HOME, User, current_user, load_accounts, verify_password
from app.config import Settings, get_settings
from app.templating import templates

router = APIRouter()


@router.get("/")
def index(user: User = Depends(current_user)):
    return RedirectResponse(HOME[user.role], status_code=303)


@router.get("/login")
def login_page(request: Request):
    if request.session.get("user"):
        return RedirectResponse("/", status_code=303)
    return templates.TemplateResponse(request, "login.html", {"expired": request.query_params.get("expired")})


@router.post("/login")
def login(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    settings: Settings = Depends(get_settings),
):
    guard = request.app.state.login_guard
    username = username.strip()

    def fail(message: str):
        return templates.TemplateResponse(
            request, "login.html", {"error": message, "username": username}, status_code=401
        )

    wait = guard.locked_for(username)
    if wait:
        return fail(f"로그인 시도 횟수를 초과했습니다. {wait // 60 + 1}분 후 다시 시도하세요.")

    account = load_accounts(settings.accounts_file).get(username)
    if account is None or not verify_password(password, account["password_hash"]):
        count = guard.fail(username)
        if guard.locked_for(username):
            return fail(f"비밀번호를 {settings.max_login_failures}회 잘못 입력해 계정이 잠겼습니다. {settings.lockout_minutes}분 후 다시 시도하세요.")
        left = settings.max_login_failures - count
        return fail(f"아이디 또는 비밀번호가 맞지 않습니다. ({left}회 남음)")

    guard.reset(username)
    request.session.clear()
    request.session["user"] = {"username": username, "name": account["name"], "role": account["role"]}
    request.session["last_seen"] = int(time.time())
    return RedirectResponse(HOME[account["role"]], status_code=303)


@router.post("/logout")
def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/login", status_code=303)
