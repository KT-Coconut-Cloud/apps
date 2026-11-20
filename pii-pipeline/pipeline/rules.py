"""Load rules/pii-rules.yaml. The schema checks the shape, this module checks what the schema can't."""

import json
import re
from dataclasses import dataclass
from pathlib import Path

import yaml
from jsonschema import Draft202012Validator


class InvalidRules(ValueError):
    pass


@dataclass(frozen=True)
class Column:
    source: str
    action: str
    name: str  # output name; same as source unless "as" is set
    spec: dict

    def get(self, key, default=None):
        return self.spec.get(key, default)


@dataclass(frozen=True)
class Derived:
    name: str
    spec: dict

    def get(self, key, default=None):
        return self.spec.get(key, default)


@dataclass(frozen=True)
class Table:
    name: str
    source_sql: Path | None
    row_key: str
    unknown_input_column: str
    missing_input_column: str
    processing_order: tuple[str, ...]
    columns: tuple[Column, ...]
    derived: tuple[Derived, ...]
    output: dict
    validation: dict

    @property
    def output_columns(self) -> tuple[str, ...]:
        return tuple(self.output["columns"])

    @property
    def filename(self) -> str:
        return self.output["filename"]

    @property
    def token_columns(self) -> tuple[Column, ...]:
        return tuple(c for c in self.columns if c.action == "tokenize")

    def column(self, source: str) -> Column:
        return next(c for c in self.columns if c.source == source)


@dataclass(frozen=True)
class Rules:
    version: str
    scenario: str
    vault_profile: dict
    tables: dict[str, Table]


def _read_yaml(path: Path) -> dict:
    try:
        return yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    except OSError as e:
        raise InvalidRules(f"cannot read {path}: {e.strerror}") from e
    except yaml.YAMLError as e:
        raise InvalidRules(f"yaml: {e}") from e


def _resolve(rules_path: Path, ref: str) -> Path:
    # paths in the rules are written from the repo root ("rules/..."), and the image keeps rules/ at /rules
    return Path(rules_path).resolve().parent.parent / ref


def _check_table(tname: str, t: dict) -> None:
    where = f"table/{tname}"
    produced = {}
    for src, c in t["columns"].items():
        if c["action"] != "drop":
            produced.setdefault(c.get("as", src), []).append(src)
    for name in t.get("derived", {}):
        produced.setdefault(name, []).append(f"derived.{name}")
    dup = sorted(n for n, srcs in produced.items() if len(srcs) > 1)
    if dup:
        raise InvalidRules(f"{where}: more than one rule writes {dup}")

    out = t["output"]["columns"]
    if len(set(out)) != len(out):
        raise InvalidRules(f"{where}/output/columns: duplicate column")
    unknown = [c for c in out if c not in produced]
    if unknown:
        raise InvalidRules(f"{where}/output/columns: no rule produces {unknown}")
    unused = sorted(set(produced) - set(out))
    if unused:
        raise InvalidRules(f"{where}/output/columns: {unused} is produced but not exported")

    if t["row_key"] not in t["columns"]:
        raise InvalidRules(f"{where}/row_key: {t['row_key']} is not an input column")
    for name, d in t.get("derived", {}).items():
        for ref in (d["numerator"], d["denominator"]):
            if ref not in t["columns"]:
                raise InvalidRules(f"{where}/derived/{name}: {ref} is not an input column")

    v = t.get("validation", {})
    forbidden = set(v.get("forbidden_columns", [])) & set(out)
    if forbidden:
        raise InvalidRules(f"{where}/output/columns: forbidden column {sorted(forbidden)}")
    for col in v.get("unique_columns", []):
        if col not in out:
            raise InvalidRules(f"{where}/validation/unique_columns: {col} is not an output column")
    src = v.get("consistent_token_source")
    if src and t["columns"].get(src, {}).get("action") != "tokenize":
        raise InvalidRules(f"{where}/validation/consistent_token_source: {src} is not tokenized")
    for key in v:
        if key.endswith("_pattern") and key not in ("token_pattern",):
            col = key.removesuffix("_pattern")
            if col not in out:
                raise InvalidRules(f"{where}/validation/{key}: {col} is not an output column")
    for p in [v.get("token_pattern"), *(v.get(k) for k in v if k.endswith("_pattern")),
              *v.get("pii_patterns", {}).values()]:
        if p:
            try:
                re.compile(p)
            except re.error as e:
                raise InvalidRules(f"{where}/validation: bad pattern: {e}") from None


def load_rules(path: Path, schema_path: Path) -> Rules:
    raw = _read_yaml(path)
    schema = json.loads(Path(schema_path).read_text(encoding="utf-8"))
    errors = sorted(Draft202012Validator(schema).iter_errors(raw), key=lambda e: list(e.path))
    if errors:
        lines = [f"{'/'.join(map(str, e.path)) or '(root)'}: {e.message}" for e in errors]
        raise InvalidRules("\n".join(lines))

    profile = {}
    if raw.get("vault_profile"):
        profile_path = _resolve(path, raw["vault_profile"])
        if not profile_path.is_file():
            raise InvalidRules(f"vault_profile: {raw['vault_profile']} not found")
        profile = _read_yaml(profile_path) or {}

    tables = {}
    for tname, t in raw["table"].items():
        _check_table(tname, t)
        sql = None
        if t.get("source_sql"):
            sql = _resolve(path, t["source_sql"])
            if not sql.is_file():
                raise InvalidRules(f"table/{tname}/source_sql: {t['source_sql']} not found")
        tables[tname] = Table(
            name=tname,
            source_sql=sql,
            row_key=t["row_key"],
            unknown_input_column=t.get("unknown_input_column", "error"),
            missing_input_column=t.get("missing_input_column", "error"),
            processing_order=tuple(t["processing_order"]),
            columns=tuple(Column(src, c["action"], c.get("as", src), c) for src, c in t["columns"].items()),
            derived=tuple(Derived(name, d) for name, d in t.get("derived", {}).items()),
            output=t["output"],
            validation=t.get("validation", {}),
        )
    return Rules(raw["version"], raw["scenario"], profile, tables)
