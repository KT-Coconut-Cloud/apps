import json
import re
from io import StringIO
from pathlib import Path

import pandas as pd

RUN_ID = re.compile(r"^\d{8}-\d{2}$")
REQUEST_ID = re.compile(r"^req-\d{8}-\d{4}$")


class InvalidId(ValueError):
    pass


def check_run_id(run_id: str) -> str:
    if not RUN_ID.match(run_id):
        raise InvalidId(run_id)
    return run_id


def check_request_id(request_id: str) -> str:
    if not REQUEST_ID.match(request_id):
        raise InvalidId(request_id)
    return request_id


class Store:
    """Read-only view of one prefix in the clean bucket.

    Keys are relative to the prefix and use "/" like S3 keys.
    """

    def read_text(self, key: str) -> str | None:
        raise NotImplementedError

    def list_dirs(self, prefix: str = "") -> list[str]:
        raise NotImplementedError

    def list_files(self, prefix: str = "") -> list[str]:
        raise NotImplementedError

    def read_json(self, key: str) -> dict | None:
        text = self.read_text(key)
        return json.loads(text) if text is not None else None

    def read_csv(self, key: str) -> pd.DataFrame | None:
        text = self.read_text(key)
        return pd.read_csv(StringIO(text)) if text is not None else None

    def run_ids(self) -> list[str]:
        ids = [d.removeprefix("run_id=") for d in self.list_dirs() if d.startswith("run_id=")]
        return sorted((i for i in ids if RUN_ID.match(i)), reverse=True)


class LocalStore(Store):
    """Same key layout as the bucket, under a local folder."""

    def __init__(self, root: Path, prefix: str):
        self.base = (Path(root) / prefix.strip("/")).resolve()

    def _path(self, key: str) -> Path:
        path = (self.base / key).resolve()
        if path != self.base and self.base not in path.parents:
            raise InvalidId(key)
        return path

    def read_text(self, key: str) -> str | None:
        path = self._path(key)
        return path.read_text(encoding="utf-8") if path.is_file() else None

    def list_dirs(self, prefix: str = "") -> list[str]:
        path = self._path(prefix)
        return sorted(p.name for p in path.iterdir() if p.is_dir()) if path.is_dir() else []

    def list_files(self, prefix: str = "") -> list[str]:
        path = self._path(prefix)
        return sorted(p.name for p in path.iterdir() if p.is_file()) if path.is_dir() else []


class S3Store(Store):
    def __init__(self, client, bucket: str, prefix: str):
        self.client = client
        self.bucket = bucket
        self.prefix = prefix.strip("/") + "/"

    def read_text(self, key: str) -> str | None:
        try:
            obj = self.client.get_object(Bucket=self.bucket, Key=self.prefix + key)
        except self.client.exceptions.NoSuchKey:
            return None
        return obj["Body"].read().decode("utf-8")

    def _list(self, prefix: str) -> tuple[list[str], list[str]]:
        full = self.prefix + (prefix.strip("/") + "/" if prefix else "")
        dirs, files = [], []
        pages = self.client.get_paginator("list_objects_v2").paginate(Bucket=self.bucket, Prefix=full, Delimiter="/")
        for page in pages:
            dirs += [p["Prefix"][len(full):].rstrip("/") for p in page.get("CommonPrefixes", [])]
            files += [o["Key"][len(full):] for o in page.get("Contents", []) if o["Key"] != full]
        return sorted(dirs), sorted(files)

    def list_dirs(self, prefix: str = "") -> list[str]:
        return self._list(prefix)[0]

    def list_files(self, prefix: str = "") -> list[str]:
        return self._list(prefix)[1]
