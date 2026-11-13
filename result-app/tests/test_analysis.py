import csv
import io
import json

import pytest

from app.catalog import CATALOG, InvalidParams, clean_params
from tests.conftest import login

CRISIS = {"run_id": "20261112-01", "scenario": "crisis_link_rate", "from": "2026-05", "to": "2026-10", "purpose": "연계율 점검"}


def submit(client, **form):
    return client.post("/policy/analyses", data=form, follow_redirects=False)


def test_request_runs_and_shows_result(policy):
    res = submit(policy, **CRISIS)
    assert res.status_code == 303
    url = res.headers["location"]
    assert url.startswith("/policy/analyses/req-")

    text = policy.get(url).text
    assert "완료" in text and "시군구, 위기정보 유형별 연계 현황" in text
    assert url.rsplit("/", 1)[1] in policy.get("/policy/analyses").text


def test_result_files_follow_contract(policy, data_dir):
    request_id = submit(policy, **CRISIS).headers["location"].rsplit("/", 1)[1]
    base = data_dir / "results" / "requests" / request_id

    manifest = json.loads((base / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["status"] == "succeeded"
    assert manifest["params"]["from"] == "2026-05"

    rows = list(csv.DictReader((base / "result.csv").open(encoding="utf-8")))
    assert list(rows[0]) == list(CATALOG["crisis_link_rate"].columns)
    assert len(rows) == manifest["rows"]

    record = json.loads((data_dir / "reports" / "analysis_requests" / f"{request_id}.json").read_text(encoding="utf-8"))
    assert record["requested_by"] == "policy01"
    assert record["suppressed_cells"] == manifest["suppressed_cells"]


def test_small_cells_are_blank(policy, data_dir):
    request_id = submit(policy, **{**CRISIS, "from": "2026-08", "to": "2026-08"}).headers["location"].rsplit("/", 1)[1]
    base = data_dir / "results" / "requests" / request_id
    manifest = json.loads((base / "manifest.json").read_text(encoding="utf-8"))
    rows = list(csv.DictReader((base / "result.csv").open(encoding="utf-8")))

    blanks = 0
    for r in rows:
        for col in ("households", "linked"):
            if r[col] == "":
                blanks += 1
            else:
                assert int(r[col]) == 0 or int(r[col]) >= 5
    assert blanks == manifest["suppressed_cells"] > 0
    assert 'class="rv-masked"' in policy.get(f"/policy/analyses/{request_id}").text


def test_derived_column_hidden_with_its_count(policy, data_dir):
    form = {"run_id": "20261112-01", "scenario": "basic_living_status", "from": "2026", "to": "2026", "benefit_type": "교육급여", "purpose": "점검"}
    request_id = submit(policy, **form).headers["location"].rsplit("/", 1)[1]
    rows = list(csv.DictReader((data_dir / "results" / "requests" / request_id / "result.csv").open(encoding="utf-8")))
    assert rows
    for r in rows:
        assert (r["recipients"] == "") == (r["avg_payment"] == "")


def test_download_csv(policy):
    url = submit(policy, **CRISIS).headers["location"]
    res = policy.get(url + "/result.csv")
    assert res.status_code == 200
    assert "attachment" in res.headers["content-disposition"]
    assert next(csv.reader(io.StringIO(res.text.lstrip("﻿")))) == list(CATALOG["crisis_link_rate"].columns)


@pytest.mark.parametrize("form, message", [
    ({**CRISIS, "from": "2026-13"}, "YYYY-MM"),
    ({**CRISIS, "from": "2026-10", "to": "2026-05"}, "시작이 종료보다"),
    ({**CRISIS, "sigungu": "서울 종로구"}, "목록에 없습니다"),
    ({**CRISIS, "scenario": "free_sql"}, "지원하지 않는"),
    ({**CRISIS, "run_id": "20261111-01"}, "분석에 쓸 수 없습니다"),
    ({**CRISIS, "purpose": " "}, "분석 목적을"),
    ({**CRISIS, "purpose": "x" * 201}, "분석 목적을"),
])
def test_bad_request_is_rejected(policy, data_dir, form, message):
    res = submit(policy, **form)
    assert res.status_code == 422
    assert message in res.text
    assert not (data_dir / "results" / "requests").exists()


def test_requester_comes_from_session(policy, data_dir):
    request_id = submit(policy, **CRISIS, requested_by="someone").headers["location"].rsplit("/", 1)[1]
    request = json.loads((data_dir / "results" / "requests" / request_id / "request.json").read_text(encoding="utf-8"))
    assert request["requested_by"] == "policy01"
    assert request["purpose"] == "연계율 점검"


def test_other_users_cannot_open_request(client):
    login(client, "policy01", "pw-policy")
    url = submit(client, **CRISIS).headers["location"]
    client.post("/logout")
    login(client, "policy02", "pw-policy")
    assert client.get(url).status_code == 404
    assert client.get(url + "/result.csv").status_code == 404
    assert url.rsplit("/", 1)[1] not in client.get("/policy/analyses").text


@pytest.mark.parametrize("request_id", ["req-1", "req-20261112-00011", "..", "req-20261112-abcd"])
def test_bad_request_id_is_404(policy, request_id):
    assert policy.get(f"/policy/analyses/{request_id}").status_code == 404


def test_running_request_polls_until_done(policy, client, data_dir):
    lam = client.app.state.analysis
    lam.delay = 60
    url = submit(policy, **CRISIS).headers["location"]

    page = policy.get(url).text
    assert "분석 중" in page and 'hx-trigger="every 5s"' in page
    assert "hx-trigger" in policy.get("/policy/analyses").text

    poll = policy.get(url, headers={"HX-Request": "true"})
    assert 'id="pending"' in poll.text and "<html" not in poll.text

    request_id = url.rsplit("/", 1)[1]
    request = json.loads((data_dir / "results" / "requests" / request_id / "request.json").read_text(encoding="utf-8"))
    lam.finalize(request)
    done = policy.get(url, headers={"HX-Request": "true"})
    assert done.headers.get("hx-refresh") == "true"


def test_security_sees_request_log_without_results(policy, client):
    submit(policy, **{**CRISIS, "from": "2026-08", "to": "2026-08"})
    client.post("/logout")
    login(client, "security01", "pw-security")
    text = client.get("/security/analyses").text
    assert "policy01" in text and "위기가구 지원 연계율" in text and "2026-08 ~ 2026-08" in text
    assert "연계율 점검" in text
    assert "비공개 값" in text


def test_clean_params_fills_optional_with_none():
    params = clean_params(CATALOG["basic_living_status"], {"from": "2024", "to": "2026"})
    assert params == {"from": "2024", "to": "2026", "household_type": None, "benefit_type": None}
    with pytest.raises(InvalidParams):
        clean_params(CATALOG["basic_living_status"], {"from": "24", "to": "2026"})


def test_results_menu_lists_only_finished(policy, client):
    done = submit(policy, **CRISIS).headers["location"].rsplit("/", 1)[1]
    client.app.state.analysis.delay = 60
    running = submit(policy, **CRISIS).headers["location"].rsplit("/", 1)[1]
    text = policy.get("/policy/results").text
    assert f"/policy/analyses/{done}" in text and f"/policy/analyses/{running}" not in text


def test_retry_link_keeps_conditions(policy):
    url = submit(policy, **{**CRISIS, "sigungu": "서울 노원구"}).headers["location"]
    text = policy.get(url).text
    assert "run_id=20261112-01" in text and "sigungu=%EC%84%9C%EC%9A%B8" in text
    form = policy.get("/policy/analyses/new?run_id=20261112-01&scenario=crisis_link_rate&sigungu=서울 노원구&from=2026-05").text
    assert "<option selected>서울 노원구</option>" in form and 'value="2026-05"' in form
