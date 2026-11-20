import pytest

from pipeline.tokenizer import LocalTokenizer, TokenizerError, VaultTokenizer, from_profile


def test_each_key_gives_different_tokens():
    tok = LocalTokenizer(b"k")
    assert tok.tokens(["100"], "payment-id", 1) != tok.tokens(["100"], "household-id", 1)
    assert tok.tokens(["100"], "payment-id", 1) == tok.tokens(["100"], "payment-id", 1)
    assert tok.tokens(["100"], "payment-id", 2)[0].startswith("vault:v2:")


def fake_vault(monkeypatch, response):
    calls = []

    def call(self, path, body, token=None):
        calls.append((path, body, token))
        return response(body)

    monkeypatch.setattr(VaultTokenizer, "_call", call)
    return calls


def test_vault_request_and_native_output(monkeypatch):
    calls = fake_vault(monkeypatch, lambda body: {"data": {"batch_results": [
        {"hmac": f"vault:v1:{'A' * 43}="} for _ in body["batch_input"]]}})
    tok = VaultTokenizer("https://vault:8200", token="t")
    assert tok.tokens(["payment:v1:1", "payment:v1:2"], "payment-id", 1) == [f"vault:v1:{'A' * 43}="] * 2
    path, body, token = calls[0]
    assert path == "transit/hmac/payment-id/sha2-256" and body["key_version"] == 1 and token == "t"
    assert body["batch_input"][0] == {"input": "cGF5bWVudDp2MTox"}


def test_vault_batch_error_fails(monkeypatch):
    fake_vault(monkeypatch, lambda body: {"data": {"batch_results": [{"error": "key not found"}]}})
    with pytest.raises(TokenizerError):
        VaultTokenizer("https://vault:8200", token="t").tokens(["x"], "payment-id", 1)


def test_profile_picks_kubernetes_login(monkeypatch, tmp_path, rules):
    sa = tmp_path / "token"
    sa.write_text("jwt")
    profile = {**rules.vault_profile, "auth": {**rules.vault_profile["auth"], "service_account_token_path": str(sa)}}
    calls = fake_vault(monkeypatch, lambda body: {"auth": {"client_token": "s.abc"}})
    monkeypatch.setenv("VAULT_ADDR", "https://vault:8200")
    monkeypatch.setenv("VAULT_ROLE", "pii-pipeline")
    monkeypatch.delenv("VAULT_TOKEN", raising=False)
    tok = from_profile(profile)
    assert tok.token == "s.abc" and calls == [("auth/kubernetes/login", {"role": "pii-pipeline", "jwt": "jwt"}, None)]


def test_profile_without_vault_needs_a_local_key(monkeypatch, rules):
    monkeypatch.delenv("VAULT_ADDR", raising=False)
    monkeypatch.delenv("PII_HMAC_KEY", raising=False)
    with pytest.raises(TokenizerError):
        from_profile(rules.vault_profile)
    monkeypatch.setenv("PII_HMAC_KEY", "local")
    assert isinstance(from_profile(rules.vault_profile), LocalTokenizer)
