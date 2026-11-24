import json

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
    assert "시도별 생계급여 재확인 필요 지급 건" in text and "재확인 필요 건의 기준 초과 정도" in text


def test_params_fragment_follows_template(policy):
    res = policy.get("/policy/analyses/new/params?scenario=recheck_by_household", headers={"HX-Request": "true"})
    assert "<html" not in res.text
    assert 'id="p-region"' in res.text and 'id="p-household_size"' not in res.text
    assert 'value="2025-12"' in res.text


def test_security_run_status(security):
    text = security.get("/security/runs").text
    assert text.count("반출 완료") >= 2
    assert "적정성 검토에서 중단" in text and "Macie 검사에서 탐지되어 격리" in text
    assert "benefit_review v3.1" in text


def test_macie_error_is_not_quarantine(security):
    text = security.get("/security/runs").text
    assert "Macie 검사를 마치지 못해 격리 버킷에 보관" in text
    detail = security.get("/security/runs/20261113-01").text
    assert "검증 오류" in detail and "sha256 mismatch" in detail


def test_aborted_run_has_no_export(security):
    text = security.get("/security/runs/20261111-01").text
    assert "준식별자 일반화" in text
    assert "반출하지 않았습니다" in text


def test_failures_counts_reasons(security):
    text = security.get("/security/failures").text
    assert "준식별자 일반화" in text and "직접식별자 잔존" in text and "휴대전화 번호" in text


def test_failures_filters_by_date(security):
    text = security.get("/security/failures?start=2026-11-12&end=2026-11-12").text
    assert "benefit_review v3.1" in text and "benefit_review v2.9" not in text
    everything = security.get("/security/failures?start=&end=").text
    assert "benefit_review v2.9" in everything and "benefit_review v3.0" in everything


def test_failures_partial_for_htmx(security):
    res = security.get("/security/failures?start=2026-11-09&end=2026-11-12", headers={"HX-Request": "true"})
    assert "<html" not in res.text and "규칙 버전별 결과" in res.text


def add_pseudonymize_failure(data_dir, run_id="20261114-01"):
    base = data_dir / "reports" / f"run_id={run_id}"
    base.mkdir(parents=True)
    (base / "export_record.json").write_text(json.dumps({
        "run_id": run_id,
        "executed_at": "2026-11-14T10:00:00+09:00",
        "status": "aborted",
        "failed_stage": "pseudonymize",
        "rules_version": "benefit_review v3.1",
        "reasons": ["benefit_review_joined: input column not in the rules ['memo']"],
        "files": [],
    }, ensure_ascii=False), encoding="utf-8")


def test_pseudonymize_failure_is_listed(security, data_dir):
    add_pseudonymize_failure(data_dir)
    text = security.get("/security/runs").text
    assert "가명처리에서 중단" in text and "가명처리 중단" in text
    detail = security.get("/security/runs/20261114-01").text
    assert "가명처리 실패" in detail and "memo" in detail
    assert "가명처리에서 중단되어 적정성 검토를 하지 않았습니다" in detail
    assert "가명처리에서 중단되어 반출하지 않았습니다" in detail
    assert "반출하지 않아 검사 대상이 없습니다" in detail


def test_pseudonymize_failure_counts_as_reason(security, data_dir):
    add_pseudonymize_failure(data_dir)
    text = security.get("/security/failures?start=&end=").text
    assert "가명처리 실패" in text
