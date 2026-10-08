"""Stdlib CLI; run with -I -S -B to exclude installed runtime packages."""

import argparse
import json
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))
from hermes_model_catalog import inspect_model  # noqa: E402


def main():
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--model", required=True)
    args = parser.parse_args()
    report = inspect_model(args.root, args.model)
    print(json.dumps(report.as_dict(), ensure_ascii=True, allow_nan=False))
    return 0 if report.status == "metadata_inspected" else 2


if __name__ == "__main__":
    raise SystemExit(main())
