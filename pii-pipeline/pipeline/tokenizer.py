"""HMAC tokens in Vault's native format, "vault:v<key version>:<base64>"."""

import base64
import hashlib
import hmac
import json
import os
import ssl
import urllib.error
import urllib.request
from pathlib import Path


class TokenizerError(RuntimeError):
    pass


class LocalTokenizer:
    """HMAC with a local key, in the same format Vault returns. CI and tests only."""

    def __init__(self, key: bytes):
        self.key = key

    def tokens(self, values: list[str], key_name: str, key_version: int) -> list[str]:
        # one sub-key per key name and version, like separate keys in Vault
        sub = hmac.new(self.key, f"{key_name}:{key_version}".encode(), hashlib.sha256).digest()
        return [
            f"vault:v{key_version}:" + base64.b64encode(hmac.new(sub, v.encode(), hashlib.sha256).digest()).decode()
            for v in values
        ]


class VaultTokenizer:
    """HMAC through Vault Transit, so the key never leaves Vault."""

    BATCH = 500

    def __init__(self, addr: str, *, token: str | None = None, role: str | None = None,
                 transit_mount: str = "transit", auth_mount: str = "kubernetes",
                 sa_token_path: str = "/var/run/secrets/kubernetes.io/serviceaccount/token",
                 ca_cert: str | None = None, verify_tls: bool = True, timeout: float = 10):
        self.addr = addr.rstrip("/")
        self.transit_mount = transit_mount
        self.timeout = timeout
        if not verify_tls:
            # verify_tls: false is only for a self-signed Vault in test setups
            self.ssl = ssl._create_unverified_context()  # nosemgrep: python.lang.security.unverified-ssl-context.unverified-ssl-context
        else:
            self.ssl = ssl.create_default_context(cafile=ca_cert or None)
        self.token = token or self._login(role, auth_mount, sa_token_path)

    def _call(self, path: str, body: dict, token: str | None = None) -> dict:
        req = urllib.request.Request(
            f"{self.addr}/v1/{path}",
            data=json.dumps(body).encode(),
            headers={"Content-Type": "application/json", **({"X-Vault-Token": token} if token else {})},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout, context=self.ssl) as resp:
                return json.loads(resp.read())
        except urllib.error.HTTPError as e:
            # Vault's error body names the path and reason, never the input values
            raise TokenizerError(f"vault {path}: HTTP {e.code} {e.read()[:300].decode(errors='replace')}") from None
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            raise TokenizerError(f"vault {path}: {e}") from None

    def _login(self, role: str | None, auth_mount: str, sa_token_path: str) -> str:
        if not role:
            raise TokenizerError("VAULT_TOKEN or a Vault role is required")
        jwt = Path(sa_token_path).read_text().strip()
        return self._call(f"auth/{auth_mount}/login", {"role": role, "jwt": jwt})["auth"]["client_token"]

    def tokens(self, values: list[str], key_name: str, key_version: int) -> list[str]:
        out = []
        for i in range(0, len(values), self.BATCH):
            batch = [{"input": base64.b64encode(v.encode()).decode()} for v in values[i:i + self.BATCH]]
            data = self._call(f"{self.transit_mount}/hmac/{key_name}/sha2-256",
                              {"batch_input": batch, "key_version": key_version}, self.token)
            results = data["data"]["batch_results"]
            if len(results) != len(batch) or any("error" in r for r in results):
                raise TokenizerError(f"vault hmac {key_name}: batch failed")
            out += [r["hmac"] for r in results]
        return out


def from_profile(profile: dict):
    """Vault when the profile's address variable is set, otherwise PII_HMAC_KEY for local runs."""
    addr = os.environ.get(profile.get("address_env", "VAULT_ADDR"))
    if addr:
        auth = profile.get("auth", {})
        ca_env = profile.get("ca_cert_path_env", "VAULT_CACERT")
        return VaultTokenizer(
            addr,
            token=os.environ.get("VAULT_TOKEN"),
            role=os.environ.get(auth.get("role_env", "VAULT_ROLE")),
            transit_mount=profile.get("transit_mount", "transit"),
            auth_mount=auth.get("mount", "kubernetes"),
            sa_token_path=auth.get("service_account_token_path",
                                   "/var/run/secrets/kubernetes.io/serviceaccount/token"),
            ca_cert=os.environ.get(ca_env),
            verify_tls=profile.get("verify_tls", True),
            timeout=profile.get("timeout_seconds", 10),
        )
    key = os.environ.get("PII_HMAC_KEY")
    if not key:
        raise TokenizerError("set VAULT_ADDR, or PII_HMAC_KEY for local runs")
    return LocalTokenizer(key.encode())
