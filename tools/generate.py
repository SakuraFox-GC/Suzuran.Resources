#!/usr/bin/env python3
"""Generate the small, deterministic Suzuran name-to-ID resource bundle."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
from pathlib import Path
from typing import Any

SCHEMA_VERSION = 1
REPOSITORY = "SakuraFox-GC/Suzuran.Resources"
CARD_FIELDS = ("id", "charId", "tmplId", "name", "profession")
STAGE_FIELDS = ("stageId", "levelId", "zoneId", "code", "name", "difficulty", "diffGroup")


class InvalidSource(ValueError):
    """An upstream schema changed or a relation is incomplete."""


def object_value(value: Any, context: str) -> dict:
    if not isinstance(value, dict):
        raise InvalidSource(f"{context}: expected object")
    return value


def string_value(value: Any, context: str, *, nullable: bool = False) -> str | None:
    if nullable and value is None:
        return ""
    if not isinstance(value, str) or (not value and not nullable):
        raise InvalidSource(f"{context}: expected nonempty string")
    return value


def required(record: dict, key: str, context: str) -> Any:
    if key not in record:
        raise InvalidSource(f"{context}: missing {key}")
    return record[key]


def json_bytes(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")


def build_resources(characters: dict, patches: dict, stage_table: dict, source_commit: str) -> dict:
    if re.fullmatch(r"[0-9a-f]{40}", source_commit) is None:
        raise InvalidSource("source commit must be a full lowercase Git SHA-1")
    characters = object_value(characters, "character_table")
    patches = object_value(patches, "char_patch_table")
    infos = object_value(required(patches, "infos", "char_patch_table"), "infos")
    patch_chars = object_value(required(patches, "patchChars", "char_patch_table"), "patchChars")
    stages = object_value(required(object_value(stage_table, "stage_table"), "stages", "stage_table"), "stages")
    if not characters or not stages:
        raise InvalidSource("character_table and stages must not be empty")

    owners: dict[str, str] = {}
    for base, info in infos.items():
        if base not in characters:
            raise InvalidSource(f"infos.{base}: base character missing")
        info = object_value(info, f"infos.{base}")
        templates = required(info, "tmplIds", f"infos.{base}")
        if not isinstance(templates, list) or not templates or len(set(templates)) != len(templates):
            raise InvalidSource(f"infos.{base}.tmplIds: expected nonempty unique list")
        if base not in templates:
            raise InvalidSource(f"infos.{base}.tmplIds: does not include base character")
        for template in templates:
            string_value(template, f"infos.{base}.tmplIds[]")
            if template in owners and owners[template] != base:
                raise InvalidSource(f"{template}: conflicting base character")
            if template not in characters and template not in patch_chars:
                raise InvalidSource(f"{template}: template data missing")
            owners[template] = base

    all_cards = dict(characters)
    for card_id, data in patch_chars.items():
        if card_id not in owners:
            raise InvalidSource(f"patchChars.{card_id}: no owner in infos")
        if card_id in all_cards and all_cards[card_id] != data:
            raise InvalidSource(f"patchChars.{card_id}: conflicts with character_table")
        all_cards[card_id] = data
    cards = []
    for card_id, card in sorted(all_cards.items()):
        if not card_id.startswith(("char_", "token_", "trap_")):
            raise InvalidSource(f"{card_id}: unexpected card ID prefix")
        card = object_value(card, card_id)
        cards.append({
            "id": card_id,
            "charId": owners.get(card_id, card_id),
            "tmplId": card_id,
            "name": string_value(required(card, "name", card_id), f"{card_id}.name"),
            "profession": string_value(required(card, "profession", card_id), f"{card_id}.profession"),
        })

    output_stages = []
    for stage_id, stage in sorted(stages.items()):
        stage = object_value(stage, stage_id)
        item = {}
        for field in STAGE_FIELDS:
            value = required(stage, field, stage_id)
            item[field] = string_value(value, f"{stage_id}.{field}", nullable=field in ("levelId", "code", "name", "diffGroup"))
        if item["stageId"] != stage_id:
            raise InvalidSource(f"{stage_id}: stageId differs from table key")
        output_stages.append(item)
    result = {"schemaVersion": SCHEMA_VERSION, "sourceCommit": source_commit, "cards": cards, "stages": output_stages}
    validate_resources(result)
    return result


def validate_resources(value: dict) -> None:
    value = object_value(value, "resources")
    if value.get("schemaVersion") != SCHEMA_VERSION or re.fullmatch(r"[0-9a-f]{40}", value.get("sourceCommit", "")) is None:
        raise InvalidSource("invalid schema version or source commit")
    for kind, key, fields in (("cards", "id", CARD_FIELDS), ("stages", "stageId", STAGE_FIELDS)):
        rows = value.get(kind)
        if not isinstance(rows, list) or not rows:
            raise InvalidSource(f"{kind}: expected nonempty list")
        ids = []
        for row in rows:
            row = object_value(row, kind)
            if set(row) != set(fields):
                raise InvalidSource(f"{kind}: unexpected fields")
            ids.append(string_value(row[key], f"{kind}.{key}"))
        if ids != sorted(set(ids)):
            raise InvalidSource(f"{kind}: IDs must be unique and sorted")
    cards = {row["id"]: row for row in value["cards"]}
    for row in cards.values():
        if row["tmplId"] != row["id"] or row["charId"] not in cards:
            raise InvalidSource(f"{row['id']}: invalid template ownership")


def manifest_for(resources_data: bytes, source_commit: str, repository: str = REPOSITORY) -> dict:
    if re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository) is None:
        raise InvalidSource("repository must have owner/name form")
    return {
        "schemaVersion": SCHEMA_VERSION,
        "resourceVersion": source_commit,
        "sourceCommit": source_commit,
        "resourcesUrl": f"https://github.com/{repository}/releases/download/maa-{source_commit}/resources.json",
        "sha256": hashlib.sha256(resources_data).hexdigest(),
    }


def generate(source_root: Path, output_dir: Path, source_commit: str | None = None, repository: str = REPOSITORY) -> dict:
    if source_commit is None:
        source_commit = subprocess.check_output(["git", "-C", str(source_root), "rev-parse", "HEAD"], text=True).strip()
    # Accept repository root, the zh_CN root, or a directory with the three tables.
    candidates = (source_root / "zh_CN/gamedata/excel", source_root / "gamedata/excel", source_root)
    tables = next((path for path in candidates if (path / "character_table.json").is_file()), None)
    if tables is None:
        raise InvalidSource("cannot find character_table.json under source root")
    inputs = [json.loads((tables / f"{name}.json").read_text(encoding="utf-8")) for name in ("character_table", "char_patch_table", "stage_table")]
    resources = build_resources(*inputs, source_commit)
    resources_data = json_bytes(resources)
    manifest = manifest_for(resources_data, source_commit, repository)
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "resources.json").write_bytes(resources_data)
    (output_dir / "manifest.json").write_bytes(json_bytes(manifest))
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", required=True, type=Path)
    parser.add_argument("--output-dir", default=Path("dist"), type=Path)
    parser.add_argument("--source-commit", help="full upstream SHA; by default read from source checkout HEAD")
    parser.add_argument("--repository", default=REPOSITORY)
    args = parser.parse_args()
    try:
        manifest = generate(args.source_root, args.output_dir, args.source_commit, args.repository)
    except (InvalidSource, OSError, ValueError, subprocess.CalledProcessError) as exc:
        parser.exit(1, f"generation failed: {exc}\n")
    print(f"Generated {args.output_dir} from {manifest['sourceCommit']} (SHA-256 {manifest['sha256']})")


if __name__ == "__main__":
    main()
