import argparse
import json
import logging
import os
import re
import sys
from pathlib import Path

from pipeline import export, leakcheck, pseudonymize, review, tokenizer
from pipeline.rules import InvalidRules, load_rules

RUN_ID = re.compile(r"^\d{8}-\d{2}$")


def main(argv=None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    p = argparse.ArgumentParser(prog="pipeline")
    p.add_argument("--rules", type=Path, default=Path(os.environ.get("RULES_PATH", "/rules/pii-rules.yaml")))
    p.add_argument("--schema", type=Path, default=Path(os.environ.get("RULES_SCHEMA", "/rules/pii-rules.schema.json")))
    p.add_argument("--work", type=Path, default=Path(os.environ.get("WORK_DIR", "/work")))
    sub = p.add_subparsers(dest="command", required=True)

    sub.add_parser("validate-rules")
    s = sub.add_parser("pseudonymize")
    s.add_argument("--source-dir", type=Path, help="read CSV files instead of MySQL")
    s = sub.add_parser("review")
    s.add_argument("--run-id", required=True)
    s = sub.add_parser("export")
    s.add_argument("--bucket", default=os.environ.get("LANDING_BUCKET"))
    s = sub.add_parser("leakcheck")
    s.add_argument("--raw-dir", type=Path, required=True)
    args = p.parse_args(argv)

    try:
        rules = load_rules(args.rules, args.schema)
    except InvalidRules as e:
        print(f"invalid rules: {args.rules}\n{e}", file=sys.stderr)
        return 1
    out_dir = args.work / "out"
    review_path = args.work / "adequacy_review.json"

    if args.command == "validate-rules":
        print(f"{rules.version}: {len(rules.tables)} table(s) ok")
        return 0

    if args.command == "pseudonymize":
        pseudonymize.run(rules, out_dir, tokenizer.from_env(), args.source_dir)
        return 0

    if args.command == "review":
        if not RUN_ID.match(args.run_id):
            print("run id must look like 20261117-01", file=sys.stderr)
            return 1
        result = review.run(rules, out_dir, args.run_id)
        review_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        for c in result["checks"]:
            print(f"{'PASS' if c['passed'] else 'FAIL'} {c['item']}: {c['value']} {c['reason'] or ''}".rstrip())
        return 0

    if args.command == "export":
        import boto3

        if not args.bucket:
            print("LANDING_BUCKET is not set", file=sys.stderr)
            return 1
        result = json.loads(review_path.read_text(encoding="utf-8"))
        # on-prem reaches S3 through the interface endpoint over WireGuard
        s3 = boto3.client("s3", endpoint_url=os.environ.get("S3_ENDPOINT_URL") or None)
        record = export.run(rules, out_dir, result, args.bucket, s3)
        if record["status"] != "exported":
            print("export blocked: adequacy review did not pass", file=sys.stderr)
            return 2
        print(f"exported {len(record['files'])} file(s) for run {record['run_id']}")
        return 0

    if args.command == "leakcheck":
        pseudonymize.run(rules, out_dir, tokenizer.LocalTokenizer(b"ci-only"), args.raw_dir)
        problems = leakcheck.run(rules, args.raw_dir, out_dir)
        for line in problems:
            print(f"LEAK {line}", file=sys.stderr)
        print(f"leak check: {len(problems)} problem(s)")
        return 1 if problems else 0

    return 1


if __name__ == "__main__":
    sys.exit(main())
