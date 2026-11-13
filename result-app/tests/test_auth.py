from tests.conftest import login


def test_pages_need_login(client):
    res = client.get("/policy/datasets", follow_redirects=False)
    assert res.status_code == 303
    assert res.headers["location"].startswith("/login")


def test_login_redirects_to_team_home(client):
    res = login(client, "security01", "pw-security")
    assert res.headers["location"] == "/security/runs"


def test_wrong_password_shows_remaining_tries(client):
    res = login(client, "policy01", "nope")
    assert res.status_code == 401
    assert "2회 남음" in res.text


def test_account_locks_after_max_failures(client):
    for _ in range(3):
        login(client, "policy01", "nope")
    res = login(client, "policy01", "pw-policy")
    assert res.status_code == 401
    assert "다시 시도하세요" in res.text


def test_header_shows_team(policy):
    assert "정책기획팀" in policy.get("/policy/datasets").text


def test_logout_clears_session(policy):
    policy.post("/logout")
    assert policy.get("/policy/datasets", follow_redirects=False).status_code == 303
