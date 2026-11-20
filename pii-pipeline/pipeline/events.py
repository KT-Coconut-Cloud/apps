"""One JSON line per finished stage on stdout, for Loki.

Fields: event, run_id, stage, status (success|failed), count. No row values.
"""

import json
import os
import sys

STAGES = ("pseudonymize", "review", "export")


def emit(stage: str, status: str, count: int, run_id: str | None = None, **extra) -> dict:
    line = {
        "event": "pipeline_stage",
        "run_id": run_id if run_id is not None else os.environ.get("RUN_ID", ""),
        "stage": stage,
        "status": status,
        "count": count,
        **extra,
    }
    print(json.dumps(line, ensure_ascii=False), file=sys.stdout, flush=True)
    return line
