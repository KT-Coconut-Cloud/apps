import json
import shutil
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.auth import hash_password
from app.config import Settings
from app.main import create_app

DATA = Path(__file__).resolve().parent.parent / "sample-data"


@pytest.fixture
def data_dir(tmp_path):
    # the fake Lambda writes into data_dir, so each test gets its own copy
    path = tmp_path / "data"
    # leave out requests made while running the app locally
    shutil.copytree(DATA, path, ignore=shutil.ignore_patterns("requests", "analysis_requests"))
    return path


@pytest.fixture
def settings(tmp_path, data_dir):
    accounts = tmp_path / "accounts.json"
    accounts.write_text(json.dumps({"accounts": [
        {"username": "policy01", "name": "정책", "role": "policy", "password_hash": hash_password("pw-policy", 1000)},
        {"username": "policy02", "name": "정책2", "role": "policy", "password_hash": hash_password("pw-policy", 1000)},
        {"username": "security01", "name": "보안", "role": "security", "password_hash": hash_password("pw-security", 1000)},
    ]}), encoding="utf-8")
    return Settings(
        git_sha="abc1234",
        data_dir=data_dir,
        accounts_file=accounts,
        session_secret="test",
        max_login_failures=3,
        local_analysis_delay=0,
    )


@pytest.fixture
def client(settings):
    return TestClient(create_app(settings))


def login(client, username, password):
    return client.post("/login", data={"username": username, "password": password}, follow_redirects=False)


@pytest.fixture
def policy(client):
    assert login(client, "policy01", "pw-policy").status_code == 303
    return client


@pytest.fixture
def security(client):
    assert login(client, "security01", "pw-security").status_code == 303
    return client
