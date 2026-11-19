import csv
import io
import json

import pandas as pd
import pytest

from app.catalog import CATALOG, InvalidParams, Scenario, clean_params
from app.local_lambda import suppress
from tests.conftest import login

MAIN = {"run_id": "20261112-01", "scenario": "livelihood_recheck", "pay_month": "2025-12", "purpose": "생계급여 지급 건 점검"}


def submit(client, **form):
    return client.post("/policy/analyses", data=form, follow_redirects=False)


def request_id_of(res) -> str:
    return res.headers["location"].rsplit("/", 1)[1]


def test_request_runs_and_shows_result(policy):
    res = submit(policy, **MAIN)
    assert res.status_code == 303
    url = res.headers["location"]
    assert url.startswith("/policy/analyses/req-")

    text = policy.get(url).text
    assert "완료" in text and "시도별 점검 결과" in text and "재확인 필요 비율" in text
    assert url.rsplit("/", 1)[1] in policy.get("/policy/analyses").text


@pytest.mark.parametrize("scenario, heading", [
    ("livelihood_recheck", "시도별 재확인 필요 비율"),
    ("recheck_by_household", "가구원 수별 재확인 필요 비율"),
    ("recheck_by_age", "연령대별 재확인 필요 비율"),
    ("recheck_excess", "시도별 120% 초과 비율"),
])
def test_every_template_runs(policy, data_dir, scenario, heading):
    request_id = request_id_of(submit(policy, **{**MAIN, "scenario": scenario}))
    manifest = json.loads((data_dir / "results" / "requests" / request_id / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["status"] == "succeeded" and manifest["rows"] > 0
    assert heading in policy.get(f"/policy/analyses/{request_id}").text


def test_grouping_values_get_readable_names(policy):
    text = policy.get(f"/policy/analyses/{request_id_of(submit(policy, **{**MAIN, 'scenario': 'recheck_by_household'}))}").text
    assert "1인" in text and "4인" in text and "자료 없음" in text


def test_result_files_follow_contract(policy, data_dir):
    request_id = request_id_of(submit(policy, **MAIN))
    base = data_dir / "results" / "requests" / request_id

    manifest = json.loads((base / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["status"] == "succeeded"
    assert manifest["params"]["pay_month"] == "2025-12"

    rows = list(csv.DictReader((base / "result.csv").open(encoding="utf-8")))
    assert list(rows[0]) == list(CATALOG["livelihood_recheck"].columns)
    assert len(rows) == manifest["rows"]

    record = json.loads((data_dir / "reports" / "analysis_requests" / f"{request_id}.json").read_text(encoding="utf-8"))
    assert record["requested_by"] == "policy01"
    assert record["suppressed_cells"] == manifest["suppressed_cells"]


def test_flag_counts_add_up(policy, data_dir):
    request_id = request_id_of(submit(policy, **MAIN))
    df = pd.read_csv(data_dir / "results" / "requests" / request_id / "result.csv").dropna()
    assert (df["within"] + df["recheck"] + df["no_data"] == df["payments"]).all()


def test_small_cells_are_blank(policy, data_dir):
    scenario = CATALOG["livelihood_recheck"]
    request_id = request_id_of(submit(policy, **{**MAIN, "scenario": scenario.key}))
    base = data_dir / "results" / "requests" / request_id
    manifest = json.loads((base / "manifest.json").read_text(encoding="utf-8"))
    rows = list(csv.DictReader((base / "result.csv").open(encoding="utf-8")))

    blanks = 0
    for r in rows:
        for col in scenario.counts:
            if r[col] == "":
                blanks += 1
            else:
                assert int(r[col]) == 0 or int(r[col]) >= 5
    assert blanks == manifest["suppressed_cells"] > 0
    assert 'class="rv-masked"' in policy.get(f"/policy/analyses/{request_id}").text


def test_derived_column_hidden_with_its_count():
    scenario = Scenario(key="t", title="", description="", params=(), columns=("k", "n", "avg"), counts=("n",), derived=("avg",))
    df, hidden = suppress(pd.DataFrame({"k": ["a", "b"], "n": [3, 9], "avg": [100, 200]}), scenario, 5)
    assert df["n"].isna().tolist() == [True, False]
    assert df["avg"].isna().tolist() == [True, False]
    assert hidden == 2


def test_download_csv(policy):
    url = submit(policy, **MAIN).headers["location"]
    res = policy.get(url + "/result.csv")
    assert res.status_code == 200
    assert "attachment" in res.headers["content-disposition"]
    assert next(csv.reader(io.StringIO(res.text.lstrip("﻿")))) == list(CATALOG["livelihood_recheck"].columns)


@pytest.mark.parametrize("form, message", [
    ({**MAIN, "pay_month": "2025-13"}, "YYYY-MM"),
    ({**MAIN, "pay_month": ""}, "지급월을(를) 입력하세요"),
    ({**MAIN, "household_size": "5+"}, "목록에 없습니다"),
    ({**MAIN, "scenario": "free_sql"}, "지원하지 않는"),
    ({**MAIN, "run_id": "20261111-01"}, "분석에 쓸 수 없습니다"),
    ({**MAIN, "run_id": "20261113-01"}, "분석에 쓸 수 없습니다"),
    ({**MAIN, "purpose": " "}, "분석 목적을"),
    ({**MAIN, "purpose": "x" * 201}, "분석 목적을"),
])
def test_bad_request_is_rejected(policy, data_dir, form, message):
    res = submit(policy, **form)
    assert res.status_code == 422
    assert message in res.text
    assert not (data_dir / "results" / "requests").exists()


def test_requester_comes_from_session(policy, data_dir):
    request_id = request_id_of(submit(policy, **MAIN, requested_by="someone"))
    request = json.loads((data_dir / "results" / "requests" / request_id / "request.json").read_text(encoding="utf-8"))
    assert request["requested_by"] == "policy01"
    assert request["purpose"] == "생계급여 지급 건 점검"


def test_other_users_cannot_open_request(client):
    login(client, "policy01", "pw-policy")
    url = submit(client, **MAIN).headers["location"]
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
    url = submit(policy, **MAIN).headers["location"]

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
    submit(policy, **{**MAIN, "scenario": "recheck_by_age"})
    client.post("/logout")
    login(client, "security01", "pw-security")
    text = client.get("/security/analyses").text
    assert "policy01" in text and "연령대별 재확인 필요 지급 건" in text and "지급월 2025-12" in text
    assert "생계급여 지급 건 점검" in text
    assert "비공개 값" in text


def test_clean_params_fills_optional_with_none():
    params = clean_params(CATALOG["livelihood_recheck"], {"pay_month": "2025-12"})
    assert params == {"pay_month": "2025-12", "household_size": None, "age_group": None}
    with pytest.raises(InvalidParams):
        clean_params(CATALOG["livelihood_recheck"], {"pay_month": "2025-1"})


def test_results_menu_lists_only_finished(policy, client):
    done = request_id_of(submit(policy, **MAIN))
    client.app.state.analysis.delay = 60
    running = request_id_of(submit(policy, **MAIN))
    text = policy.get("/policy/results").text
    assert f"/policy/analyses/{done}" in text and f"/policy/analyses/{running}" not in text


def test_retry_link_keeps_conditions(policy):
    url = submit(policy, **{**MAIN, "household_size": "2"}).headers["location"]
    text = policy.get(url).text
    assert "run_id=20261112-01" in text and "household_size=2" in text
    form = policy.get("/policy/analyses/new?run_id=20261112-01&scenario=livelihood_recheck&household_size=2&pay_month=2025-11").text
    assert "<option selected>2</option>" in form and 'value="2025-11"' in form
