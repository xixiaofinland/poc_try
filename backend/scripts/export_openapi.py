#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def _default_output_path() -> Path:
    backend_dir = Path(__file__).resolve().parents[1]
    return backend_dir / "openapi.json"


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Export the FastAPI-generated OpenAPI schema to a JSON file."
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=_default_output_path(),
        help="Output path (default: backend/openapi.json).",
    )
    args = parser.parse_args()

    backend_dir = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(backend_dir))

    from app.main import app

    schema = app.openapi()
    output_path: Path = args.out
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(schema, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(f"Wrote {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
