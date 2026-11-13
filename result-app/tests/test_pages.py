def test_policy_lists_ready_runs(policy):
    text = policy.get("/policy/datasets").text
    assert "20261112-01" in text and "20261109-01" in text
    assert "20261111-01" not in text


def test_policy_home_is_request_list(client):
    from tests.conftest import login

    assert login(client, "policy01", "pw-policy").headers["location"] == "/policy/analyses"


def test_new_analysis_form_lists_runs_and_templates(policy):
    text = policy.get("/policy/analyses/new?run_id=20261109-01").text
    assert '<option value="20261109-01" selected>' in text and "분석 목적" in text
    assert "2026-11-12 (최신)" in text
    assert "위기가구 지원 연계율" in text and "기초생활보장 수급 현황" in text


def test_params_fragment_follows_template(policy):
    res = policy.get("/policy/analyses/new/params?scenario=basic_living_status", headers={"HX-Request": "true"})
    assert "<html" not in res.text
    assert "가구 유형" in res.text and "위기정보 유형" not in res.text
    assert 'value="2023"' in res.text and 'value="2025"' in res.text


def test_security_run_status(security):
    text = security.get("/security/runs").text
    assert text.count("반출 완료") >= 2
    assert "적정성 검토에서 중단" in text and "Macie 검사에서 탐지되어 격리" in text
    assert "rules-v1.2" in text


def test_aborted_run_has_no_export(security):
    text = security.get("/security/runs/20261111-01").text
    assert "k-익명성" in text
    assert "반출하지 않았습니다" in text


def test_failures_counts_reasons(security):
    text = security.get("/security/failures").text
    assert "k-익명성" in text and "직접식별자 잔존" in text and "휴대전화 번호" in text


def test_failures_filters_by_date(security):
    text = security.get("/security/failures?start=2026-11-12&end=2026-11-12").text
    assert "rules-v1.2" in text and "rules-v1.0" not in text
    everything = security.get("/security/failures?start=&end=").text
    assert "rules-v1.0" in everything and "rules-v1.1" in everything


def test_failures_partial_for_htmx(security):
    res = security.get("/security/failures?start=2026-11-09&end=2026-11-12", headers={"HX-Request": "true"})
    assert "<html" not in res.text and "규칙 버전별 결과" in res.text
