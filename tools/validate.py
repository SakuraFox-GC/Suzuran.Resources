#!/usr/bin/env python3
"""Validate a generated release, including the immutable URL and byte hash."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

try:
    from .generate import MAX_RESOURCE_BYTES, InvalidSource, json_bytes, manifest_for, validate_resources
except ImportError:
    from generate import MAX_RESOURCE_BYTES, InvalidSource, json_bytes, manifest_for, validate_resources


def validate_bundle(directory: Path, repository: str) -> None:
    if (directory / "resources.json").stat().st_size > MAX_RESOURCE_BYTES:
        raise InvalidSource("resources.json exceeds the 32 MiB download limit")
    data = (directory / "resources.json").read_bytes()
    resources = json.loads(data)
    validate_resources(resources)
    if json_bytes(resources) != data:
        raise InvalidSource("resources.json is not in canonical format")
    manifest = json.loads((directory / "manifest.json").read_bytes())
    expected = manifest_for(data, resources["sourceCommit"], repository,
                            tile_source_commit=resources.get("tileSourceCommit"))
    legacy = None
    if "tileMaps" not in resources:
        legacy = {**expected, "resourceVersion": resources["sourceCommit"],
                  "resourcesUrl": f"https://github.com/{repository}/releases/download/maa-{resources['sourceCommit']}/resources.json"}
    if (not isinstance(manifest, dict) or type(manifest.get("schemaVersion")) is not int or
            manifest != expected and (legacy is None or manifest != legacy)):
        raise InvalidSource("manifest schema, SHA-256, commit or immutable URL mismatch")
    print(f"Validated {len(resources['cards'])} cards, {len(resources['stages'])} stages, "
          f"{len(resources.get('tileMaps', []))} tile maps, source {resources['sourceCommit']}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    parser.add_argument("--repository", default="SakuraFox-GC/Suzuran.Resources")
    args = parser.parse_args()
    try:
        validate_bundle(args.directory, args.repository)
    except (InvalidSource, ValueError, OSError) as exc:
        parser.exit(1, f"validation failed: {exc}\n")


if __name__ == "__main__":
    main()
