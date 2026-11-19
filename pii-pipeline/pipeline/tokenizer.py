import base64
import hashlib
import hmac
import json
import os
import urllib.request
from pathlib import Path

TOKEN_PREFIX = "t_"
TOKEN_HEX = 16


def _token(digest: bytes) -> str:
    return TOKEN_PREFIX + digest.hex()[:TOKEN_HEX]


class LocalTokenizer:
    """HMAC with a key from the environment. CI and tests only."""

    def __init__(self, key: bytes):
        self.key = key

    def tokens(self, values: list[str], key_name: str) -> list[str]:
        # one sub-key per transit key name, same as having separate keys in Vault
        sub = hmac.new(self.key, key_name.encode(), hashlib.sha256).digest()
        return [_token(hmac.new(sub, v.encode(), hashlib.sha256).digest()) for v in values]


class VaultTokenizer:
    """HMAC through Vault Transit, so the key never leaves Vault."""

    BATCH = 500
    SA_TOKEN = Path("/var/run/secrets/kubernetes.io/serviceaccount/token")

    def __init__(self, addr: str, token: str | None = None, role: str | None = None, mount: str = "transit"):
        self.addr = addr.rstrip("/")
        self.mount = mount
        self.token = token or self._login(role)

    def _call(self, path: str, body: dict, token: str | None = None) -> dict:
        req = urllib.request.Request(
            f"{self.addr}/v1/{path}",
            data=json.dumps(body).encode(),
            headers={"Content-Type": "application/json", **({"X-Vault-Token": token} if token else {})},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read())

    def _login(self, role: str | None) -> str:
        if not role:
            raise RuntimeError("VAULT_TOKEN or VAULT_ROLE is required")
        jwt = self.SA_TOKEN.read_text().strip()
        return self._call("auth/kubernetes/login", {"role": role, "jwt": jwt})["auth"]["client_token"]

    def tokens(self, values: list[str], key_name: str) -> list[str]:
        out = []
        for i in range(0, len(values), self.BATCH):
            batch = [{"input": base64.b64encode(v.encode()).decode()} for v in values[i:i + self.BATCH]]
            data = self._call(f"{self.mount}/hmac/{key_name}/sha2-256", {"batch_input": batch}, self.token)
            for item in data["data"]["batch_results"]:
                # "vault:v1:<base64>"
                out.append(_token(base64.b64decode(item["hmac"].split(":", 2)[2])))
        return out


def from_env():
    if os.environ.get("VAULT_ADDR"):
        return VaultTokenizer(
            os.environ["VAULT_ADDR"],
            token=os.environ.get("VAULT_TOKEN"),
            role=os.environ.get("VAULT_ROLE"),
            mount=os.environ.get("VAULT_TRANSIT_MOUNT", "transit"),
        )
    key = os.environ.get("PII_HMAC_KEY")
    if not key:
        raise RuntimeError("set VAULT_ADDR, or PII_HMAC_KEY for local runs")
    return LocalTokenizer(key.encode())
