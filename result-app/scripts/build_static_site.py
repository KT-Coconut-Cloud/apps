"""Render every screen with sample data into site/ for GitHub Pages.

Pages can't run the app, so this logs in with the test client, makes a few
analysis requests, saves the HTML of each screen and rewrites links so the
pages click through to each other. Forms and filters do not send anything.
"""

import argparse
import json
import re
import shutil
import sys
import tempfile
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from fastapi.testclient import TestClient  # noqa: E402

from app.auth import hash_password  # noqa: E402
from app.config import Settings  # noqa: E402
from app.main import create_app  # noqa: E402

DEMO_REQUESTS = [
    {"run_id": "20261112-01", "scenario": "crisis_link_rate", "from": "2026-05", "to": "2026-10",
     "purpose": "2026년 하반기 위기가구 발굴 사업 연계율 점검"},
    {"run_id": "20261112-01", "scenario": "crisis_link_rate", "from": "2026-08", "to": "2026-08",
     "purpose": "8월 단전, 단수 가구 연계 현황 확인"},
    {"run_id": "20261112-01", "scenario": "basic_living_status", "from": "2023", "to": "2025",
     "purpose": "최근 3년 기초생활보장 급여별 수급 추이 확인"},
]

NOTICE = "정적 미리보기: 샘플 데이터로 미리 만든 화면입니다. 신청이나 기간 조회 같은 입력은 저장되지 않습니다."


def page_path(path: str, query: str = "") -> str:
    """URL path in the app -> URL path on the static site."""
    if path.startswith("/static/") or path.endswith(".csv"):
        return path.lstrip("/") + (f"?{query}" if query and path.startswith("/static/") else "")
    if path == "/policy/analyses/new" and parse_qs(query).get("scenario") == ["basic_living_status"]:
        return "policy/analyses/new/basic_living_status/"
    path = path.strip("/")
    return f"{path}/" if path else ""


def file_for(url_path: str) -> str:
    return url_path if not url_path or not url_path.endswith("/") and "." in url_path.rsplit("/", 1)[-1] else url_path + "index.html"


def rewrite(html: str, base: str, demo_request: str) -> str:
    html = html.replace("http://testserver/", "/")
    html = re.sub(r'<div class="rv-govbar">\s*<div class="rv-inner">.*?</div>',
                  f'<div class="rv-govbar"><div class="rv-inner">{NOTICE}</div>', html, count=1, flags=re.S)
    html = re.sub(r'<form method="post" action="/login".*?</form>',
                  '<div class="rv-actions">'
                  '<a href="/policy/analyses" class="krds-btn primary large">정책기획팀 화면 보기</a>'
                  '<a href="/security/runs" class="krds-btn secondary large">정보보호팀 화면 보기</a></div>',
                  html, flags=re.S)
    html = html.replace('<form method="post" action="/logout">', '<form method="get" action="/login">')
    html = html.replace('<form method="post" action="/policy/analyses" class="rv-form">',
                        f'<form method="get" action="/policy/analyses/{demo_request}" class="rv-form">')
    html = html.replace(
        'hx-get="/policy/analyses/new/params" hx-target="#params" hx-trigger="change"',
        f"onchange=\"location.href='{base}policy/analyses/new/'+(this.value==='crisis_link_rate'?'':this.value+'/')\"")
    html = re.sub(r'\s+hx-[a-z-]+="[^"]*"', "", html)

    def link(m):
        parts = urlsplit(m.group(2))
        return f'{m.group(1)}="{base}{page_path(parts.path, parts.query)}"'

    return re.sub(r'(href|src|action)="(/[^"]*)"', link, html)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="/", help="URL prefix, e.g. /hybrid-privacy-viewer/ for a project page")
    ap.add_argument("--out", default=str(ROOT / "site"))
    args = ap.parse_args()
    base = "/" + args.base.strip("/") + "/" if args.base.strip("/") else "/"
    out = Path(args.out)

    tmp = Path(tempfile.mkdtemp())
    data = tmp / "data"
    shutil.copytree(ROOT / "sample-data", data, ignore=shutil.ignore_patterns("requests", "analysis_requests"))
    accounts = tmp / "accounts.json"
    accounts.write_text(json.dumps({"accounts": [
        {"username": "policy01", "name": "양희연", "role": "policy", "password_hash": hash_password("demo", 1000)},
        {"username": "security01", "name": "윤민혁", "role": "security", "password_hash": hash_password("demo", 1000)},
    ]}), encoding="utf-8")
    settings = Settings(data_dir=data, accounts_file=accounts, session_secret="static-build", local_analysis_delay=0)
    app = create_app(settings)

    pages: dict[str, str | bytes] = {}

    anon = TestClient(app)
    pages["login/"] = anon.get("/login").text

    policy = TestClient(app)
    policy.post("/login", data={"username": "policy01", "password": "demo"})
    ids = []
    for form in DEMO_REQUESTS:
        res = policy.post("/policy/analyses", data=form, follow_redirects=False)
        ids.append(res.headers["location"].rsplit("/", 1)[1])
    for path in ["/policy/analyses/new", "/policy/analyses", "/policy/results", "/policy/datasets"]:
        pages[page_path(path)] = policy.get(path).text
    pages["policy/analyses/new/basic_living_status/"] = policy.get("/policy/analyses/new?scenario=basic_living_status").text
    for request_id in ids:
        pages[f"policy/analyses/{request_id}/"] = policy.get(f"/policy/analyses/{request_id}").text
        pages[f"policy/analyses/{request_id}/result.csv"] = policy.get(f"/policy/analyses/{request_id}/result.csv").content

    security = TestClient(app)
    security.post("/login", data={"username": "security01", "password": "demo"})
    pages["security/runs/"] = security.get("/security/runs").text
    for run_id in app.state.reports.run_ids():
        pages[f"security/runs/{run_id}/"] = security.get(f"/security/runs/{run_id}").text
    pages["security/failures/"] = security.get("/security/failures?start=&end=").text
    pages["security/analyses/"] = security.get("/security/analyses").text
    pages["404.html"] = policy.get("/policy/analyses/req-00000000-0000").text

    if out.exists():
        shutil.rmtree(out)
    shutil.copytree(ROOT / "app" / "static", out / "static")
    js = out / "static" / "js" / "app.js"
    js.write_text(js.read_text(encoding="utf-8").replace('"/login?expired=1"', f'"{base}login/"'), encoding="utf-8")

    for url_path, body in pages.items():
        target = out / file_for(url_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(body, bytes):
            target.write_bytes(body)
        else:
            target.write_text(rewrite(body, base, ids[0]), encoding="utf-8")
    (out / "index.html").write_text(
        f'<!doctype html><meta charset="utf-8"><meta http-equiv="refresh" content="0; url={base}login/">'
        f'<a href="{base}login/">미리보기로 이동</a>', encoding="utf-8")
    (out / ".nojekyll").write_text("", encoding="utf-8")
    print(f"{len(pages)} pages -> {out}")


if __name__ == "__main__":
    main()
