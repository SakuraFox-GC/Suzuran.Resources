#!/usr/bin/env python3
"""Generate deterministic Suzuran mappings and optional MAA tile projections."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import subprocess
from pathlib import Path
from typing import Any

SCHEMA_VERSION = 1
REPOSITORY = "SakuraFox-GC/Suzuran.Resources"
CARD_FIELDS = ("id", "charId", "tmplId", "name", "profession")
STAGE_FIELDS = ("stageId", "levelId", "zoneId", "code", "name", "difficulty", "diffGroup")
TILE_MAP_FIELDS = ("stageId", "levelId", "width", "height", "view", "heightTypes")
MAX_RESOURCE_BYTES = 32 * 1024 * 1024
MAX_MAP_DIMENSION = 4096
MAX_MAP_TILES = 1_048_576


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


def commit_value(value: Any, context: str) -> str:
    if not isinstance(value, str) or re.fullmatch(r"[0-9a-f]{40}", value) is None:
        raise InvalidSource(f"{context}: expected a full lowercase Git SHA-1")
    return value


def json_bytes(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n").encode("utf-8")


def build_resources(characters: dict, patches: dict, stage_table: dict, source_commit: str,
                    *, tile_maps: list[dict] | None = None, tile_source_commit: str | None = None) -> dict:
    commit_value(source_commit, "source commit")
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
    if tile_maps is not None or tile_source_commit is not None:
        result["tileSourceCommit"] = tile_source_commit
        result["tileMaps"] = tile_maps
    validate_resources(result)
    return result


def validate_tile_map(value: Any) -> dict:
    row = object_value(value, "tile map")
    if set(row) != set(TILE_MAP_FIELDS):
        raise InvalidSource("tile map: unexpected fields")
    context = string_value(row["stageId"], "tile map.stageId")
    level_id = string_value(row["levelId"], f"{context}.levelId")
    if level_id != level_id.lower():
        raise InvalidSource(f"{context}.levelId: expected lowercase identifier")
    for key in ("width", "height"):
        if type(row[key]) is not int or not 0 < row[key] <= MAX_MAP_DIMENSION:
            raise InvalidSource(f"{context}.{key}: expected integer in [1, {MAX_MAP_DIMENSION}]")
    if row["width"] * row["height"] > MAX_MAP_TILES:
        raise InvalidSource(f"{context}: too many tiles")
    view = row["view"]
    if not isinstance(view, list) or len(view) != 2:
        raise InvalidSource(f"{context}.view: expected normal and side camera vectors")
    for vector in view:
        if not isinstance(vector, list) or len(vector) != 3:
            raise InvalidSource(f"{context}.view: expected three-dimensional vectors")
        try:
            finite = all(type(value) in (int, float) and math.isfinite(value) for value in vector)
        except OverflowError:
            finite = False
        if not finite:
            raise InvalidSource(f"{context}.view: expected finite numbers")
    heights = row["heightTypes"]
    if not isinstance(heights, list) or len(heights) != row["width"] * row["height"]:
        raise InvalidSource(f"{context}.heightTypes: dimensions do not match")
    if any(type(value) is not int or value not in (0, 1) for value in heights):
        raise InvalidSource(f"{context}.heightTypes: expected ground (0) or highland (1)")
    return row


def build_tile_maps(source_root: Path) -> list[dict]:
    candidates = (source_root / "resource/Arknights-Tile-Pos", source_root / "Arknights-Tile-Pos", source_root)
    directory = next((path for path in candidates if (path / "overview.json").is_file()), None)
    if directory is None:
        raise InvalidSource("cannot find Arknights-Tile-Pos/overview.json under tile source root")
    overview = object_value(json.loads((directory / "overview.json").read_text(encoding="utf-8")), "tile overview")
    if not overview:
        raise InvalidSource("tile overview must not be empty")
    output = []
    identities = set()
    for key, summary in sorted(overview.items()):
        summary = object_value(summary, f"overview.{key}")
        filename = string_value(required(summary, "filename", key), f"{key}.filename")
        path = directory / filename
        if path.resolve().parent != directory.resolve() or path.suffix != ".json":
            raise InvalidSource(f"{key}.filename: expected a JSON file in the tile source directory")
        data = object_value(json.loads(path.read_text(encoding="utf-8")), filename)
        stage_id = string_value(required(data, "stageId", filename), f"{filename}.stageId")
        level_id = string_value(required(data, "levelId", filename), f"{filename}.levelId").lower()
        if stage_id in identities:
            raise InvalidSource(f"{stage_id}: duplicate tile map identity")
        identities.add(stage_id)
        for field in ("stageId", "levelId", "width", "height"):
            expected = required(summary, field, key)
            actual = required(data, field, filename)
            if field == "levelId":
                expected = string_value(expected, f"{key}.levelId").lower()
                actual = level_id
            if type(expected) is not type(actual) or expected != actual:
                raise InvalidSource(f"{filename}.{field}: differs from overview")
        width, height = data["width"], data["height"]
        if (type(width) is not int or type(height) is not int or
                not 0 < width <= MAX_MAP_DIMENSION or not 0 < height <= MAX_MAP_DIMENSION or
                width * height > MAX_MAP_TILES):
            raise InvalidSource(f"{filename}: invalid or oversized map dimensions")
        tiles = required(data, "tiles", filename)
        if not isinstance(tiles, list) or len(tiles) != height:
            raise InvalidSource(f"{filename}.tiles: row count does not match height")
        heights = []
        for row in tiles:
            if not isinstance(row, list) or len(row) != width:
                raise InvalidSource(f"{filename}.tiles: column count does not match width")
            for tile in row:
                heights.append(required(object_value(tile, filename), "heightType", filename))
        item = {"stageId": stage_id, "levelId": level_id, "width": width, "height": height,
                "view": required(data, "view", filename), "heightTypes": heights}
        validate_tile_map(item)
        output.append(item)
    return sorted(output, key=lambda row: row["stageId"])


def validate_resources(value: dict) -> None:
    value = object_value(value, "resources")
    if type(value.get("schemaVersion")) is not int or value["schemaVersion"] != SCHEMA_VERSION:
        raise InvalidSource("invalid schema version")
    commit_value(value.get("sourceCommit"), "source commit")
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
    if "tileMaps" in value or "tileSourceCommit" in value:
        commit_value(value.get("tileSourceCommit"), "tile source commit")
        maps = value.get("tileMaps")
        if not isinstance(maps, list) or not maps:
            raise InvalidSource("tileMaps: expected nonempty list")
        ids = [validate_tile_map(row)["stageId"] for row in maps]
        if ids != sorted(set(ids)):
            raise InvalidSource("tileMaps: stage IDs must be unique and sorted")


def manifest_for(resources_data: bytes, source_commit: str, repository: str = REPOSITORY,
                 *, tile_source_commit: str | None = None) -> dict:
    commit_value(source_commit, "source commit")
    if re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository) is None:
        raise InvalidSource("repository must have owner/name form")
    if len(resources_data) > MAX_RESOURCE_BYTES:
        raise InvalidSource("resources.json exceeds the 32 MiB download limit")
    digest = hashlib.sha256(resources_data).hexdigest()
    manifest = {
        "schemaVersion": SCHEMA_VERSION,
        "resourceVersion": digest,
        "sourceCommit": source_commit,
        "resourcesUrl": f"https://github.com/{repository}/releases/download/maa-{digest}/resources.json",
        "sha256": digest,
    }
    if tile_source_commit is not None:
        manifest["tileSourceCommit"] = commit_value(tile_source_commit, "tile source commit")
    return manifest


def generate(source_root: Path, output_dir: Path, source_commit: str | None = None, repository: str = REPOSITORY,
             *, tile_source_root: Path | None = None, tile_source_commit: str | None = None) -> dict:
    if source_commit is None:
        source_commit = subprocess.check_output(["git", "-C", str(source_root), "rev-parse", "HEAD"], text=True).strip()
    # Accept repository root, the zh_CN root, or a directory with the three tables.
    candidates = (source_root / "zh_CN/gamedata/excel", source_root / "gamedata/excel", source_root)
    tables = next((path for path in candidates if (path / "character_table.json").is_file()), None)
    if tables is None:
        raise InvalidSource("cannot find character_table.json under source root")
    inputs = [json.loads((tables / f"{name}.json").read_text(encoding="utf-8")) for name in ("character_table", "char_patch_table", "stage_table")]
    tile_maps = None
    if tile_source_root is not None:
        if tile_source_commit is None:
            tile_source_commit = subprocess.check_output(["git", "-C", str(tile_source_root), "rev-parse", "HEAD"], text=True).strip()
        tile_maps = build_tile_maps(tile_source_root)
    elif tile_source_commit is not None:
        raise InvalidSource("tile source commit requires a tile source root")
    resources = build_resources(*inputs, source_commit, tile_maps=tile_maps, tile_source_commit=tile_source_commit)
    resources_data = json_bytes(resources)
    manifest = manifest_for(resources_data, source_commit, repository, tile_source_commit=tile_source_commit)
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "resources.json").write_bytes(resources_data)
    (output_dir / "manifest.json").write_bytes(json_bytes(manifest))
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", required=True, type=Path)
    parser.add_argument("--output-dir", default=Path("dist"), type=Path)
    parser.add_argument("--source-commit", help="full upstream SHA; by default read from source checkout HEAD")
    parser.add_argument("--tile-source-root", type=Path, help="optional pinned MaaResource checkout or tile resource directory")
    parser.add_argument("--tile-source-commit", help="full MaaResource SHA; by default read from tile checkout HEAD")
    parser.add_argument("--repository", default=REPOSITORY)
    args = parser.parse_args()
    try:
        manifest = generate(args.source_root, args.output_dir, args.source_commit, args.repository,
                            tile_source_root=args.tile_source_root, tile_source_commit=args.tile_source_commit)
    except (InvalidSource, OSError, ValueError, subprocess.CalledProcessError) as exc:
        parser.exit(1, f"generation failed: {exc}\n")
    print(f"Generated {args.output_dir} from {manifest['sourceCommit']} (SHA-256 {manifest['sha256']})")


if __name__ == "__main__":
    main()
