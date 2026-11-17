import json
from dataclasses import dataclass, field
from pathlib import Path

import yaml
from jsonschema import Draft202012Validator


class InvalidRules(ValueError):
    pass


@dataclass(frozen=True)
class Column:
    source: str
    action: str
    name: str  # column name in the output; same as source unless "as" is set
    method: str | None = None
    values: dict = field(default_factory=dict)
    default: str | int | None = None


@dataclass(frozen=True)
class Table:
    name: str
    columns: tuple[Column, ...]
    quasi_identifiers: tuple[str, ...]

    @property
    def output(self) -> tuple[Column, ...]:
        return tuple(c for c in self.columns if c.action != "drop")

    @property
    def token_column(self) -> str | None:
        return next((c.name for c in self.columns if c.action == "tokenize"), None)


@dataclass(frozen=True)
class Rules:
    version: str
    k_threshold: int
    tables: dict[str, Table]


def load_rules(path: Path, schema_path: Path) -> Rules:
    try:
        raw = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    except OSError as e:
        raise InvalidRules(f"cannot read {path}: {e.strerror}") from e
    except yaml.YAMLError as e:
        raise InvalidRules(f"yaml: {e}") from e
    schema = json.loads(Path(schema_path).read_text(encoding="utf-8"))
    errors = sorted(Draft202012Validator(schema).iter_errors(raw), key=lambda e: list(e.path))
    if errors:
        lines = [f"{'/'.join(map(str, e.path)) or '(root)'}: {e.message}" for e in errors]
        raise InvalidRules("\n".join(lines))

    tables = {}
    for tname, t in raw["tables"].items():
        cols = tuple(
            Column(
                source=src,
                action=c["action"],
                name=c.get("as", src),
                method=c.get("method"),
                values={str(k): v for k, v in c.get("values", {}).items()},
                default=c.get("default"),
            )
            for src, c in t["columns"].items()
        )
        out_names = [c.name for c in cols if c.action != "drop"]
        dup = {n for n in out_names if out_names.count(n) > 1}
        if dup:
            raise InvalidRules(f"tables/{tname}: duplicate output column {sorted(dup)}")
        qi = tuple(t.get("quasi_identifiers", ()))
        missing = [q for q in qi if q not in out_names]
        if missing:
            raise InvalidRules(f"tables/{tname}/quasi_identifiers: not an output column {missing}")
        tables[tname] = Table(tname, cols, qi)
    return Rules(raw["version"], raw["k_anonymity"]["threshold"], tables)
