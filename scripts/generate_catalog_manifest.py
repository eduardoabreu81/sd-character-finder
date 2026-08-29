"""Generate the validation manifest for the packaged character catalogue."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from wildcard_creator.catalog_health import build_catalog_manifest


DEFAULT_DATABASE = ROOT / "data" / "catalog" / "characters-v2.db"
DEFAULT_OUTPUT = ROOT / "data" / "characters.manifest.json"
# Pin recovery to the release asset that publishes this exact database.
# Release assets do not depend on a commit staying reachable, and they are the
# right channel for an artifact this size. Update this value only when
# publishing a rebuilt catalogue and manifest; see docs/CATALOG_REBUILD.md.
DEFAULT_DOWNLOAD_URL = (
    "https://github.com/eduardoabreu81/sd-character-finder/"
    "releases/download/v0.7.0/characters-v2-20260724.db"
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, default=DEFAULT_DATABASE)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--download-url", default=DEFAULT_DOWNLOAD_URL)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    manifest = build_catalog_manifest(
        args.database,
        download_url=str(args.download_url),
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    temp_path = args.output.with_suffix(args.output.suffix + ".tmp")
    temp_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    os.replace(temp_path, args.output)
    print(f"Manifest: {args.output}")
    print(f"SHA-256: {manifest['catalog_sha256']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
