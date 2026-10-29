import copy
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tools.generate import InvalidSource, build_resources, build_tile_maps, generate, json_bytes, manifest_for, validate_resources
from tools.validate import validate_bundle

SHA = "a" * 40
TILE_SHA = "b" * 40


def fixture():
    characters = {
        "char_002_amiya": {"name": "阿米娅", "profession": "CASTER"},
        "trap_001_a": {"name": "障碍物", "profession": "TOKEN"},
        "trap_002_b": {"name": "障碍物", "profession": "TOKEN"},
        "token_001_a": {"name": "召唤物", "profession": "TOKEN"},
    }
    patches = {"infos": {"char_002_amiya": {"tmplIds": ["char_002_amiya", "char_1001_amiya2"]}}, "patchChars": {
        "char_1001_amiya2": {"name": "阿米娅", "profession": "WARRIOR"}
    }}
    base = {"levelId": "obt/main/level_main_01-07", "zoneId": "main_1", "code": "1-7", "name": "暴君", "difficulty": "NORMAL", "diffGroup": "NONE"}
    normal = {**base, "stageId": "main_01-07"}
    hard = {**base, "stageId": "hard_01-07", "difficulty": "FOUR_STAR"}
    stages = {"stages": {normal["stageId"]: normal, hard["stageId"]: hard}}
    return characters, patches, stages


def tile_fixture():
    return {
        "stageId": "main_01-07", "levelId": "obt/main/level_main_01-07", "width": 2, "height": 2,
        "view": [[0.0, -6.6, -10.63], [1.0958801285994695, -7.1, -11.468506414519773]],
        "heightTypes": [1, 0, 0, 1],
    }


def write_tile_source(root, maps=None):
    root.mkdir(parents=True, exist_ok=True)
    overview = {}
    for index, tile_map in enumerate(maps or [tile_fixture()]):
        tile_map = copy.deepcopy(tile_map)
        filename = f"map-{index}.json"
        heights = tile_map.pop("heightTypes")
        tile_map["tiles"] = [[{"heightType": value} for value in heights[offset:offset + tile_map["width"]]]
                             for offset in range(0, len(heights), tile_map["width"])]
        overview[str(index)] = {key: tile_map[key] for key in ("stageId", "levelId", "width", "height")}
        overview[str(index)]["filename"] = filename
        (root / filename).write_bytes(json_bytes(tile_map))
    (root / "overview.json").write_bytes(json_bytes(overview))


class GeneratorTests(unittest.TestCase):
    def test_preserves_duplicate_names_and_difficulty(self):
        result = build_resources(*fixture(), SHA)
        obstacles = {row["id"] for row in result["cards"] if row["name"] == "障碍物"}
        self.assertEqual(obstacles, {"trap_001_a", "trap_002_b"})
        self.assertEqual(len(result["stages"]), 2)
        self.assertEqual({row["difficulty"] for row in result["stages"]}, {"NORMAL", "FOUR_STAR"})

    def test_variant_ownership_comes_from_infos(self):
        result = build_resources(*fixture(), SHA)
        variant = next(row for row in result["cards"] if row["id"] == "char_1001_amiya2")
        self.assertEqual(variant["charId"], "char_002_amiya")
        self.assertEqual(variant["tmplId"], "char_1001_amiya2")
        self.assertEqual(variant["profession"], "WARRIOR")

    def test_unowned_patch_and_missing_template_fail(self):
        chars, patches, stages = fixture()
        del patches["infos"]
        with self.assertRaises(InvalidSource):
            build_resources(chars, patches, stages, SHA)
        chars, patches, stages = fixture()
        patches["infos"]["char_002_amiya"]["tmplIds"].append("char_missing")
        with self.assertRaises(InvalidSource):
            build_resources(chars, patches, stages, SHA)

    def test_missing_required_field_fails(self):
        chars, patches, stages = fixture()
        del chars["trap_001_a"]["profession"]
        with self.assertRaises(InvalidSource):
            build_resources(chars, patches, stages, SHA)
        chars, patches, stages = fixture()
        del stages["stages"]["main_01-07"]["difficulty"]
        with self.assertRaises(InvalidSource):
            build_resources(chars, patches, stages, SHA)

    def test_nullable_stage_metadata_becomes_empty_string(self):
        chars, patches, stages = fixture()
        for field in ("levelId", "code", "name", "diffGroup"):
            stages["stages"]["main_01-07"][field] = None
        result = build_resources(chars, patches, stages, SHA)
        stage = next(row for row in result["stages"] if row["stageId"] == "main_01-07")
        for field in ("levelId", "code", "name", "diffGroup"):
            self.assertEqual(stage[field], "")

    def test_source_order_does_not_affect_output(self):
        chars, patches, stages = fixture()
        first = json_bytes(build_resources(chars, patches, stages, SHA))
        reordered = dict(reversed(list(chars.items())))
        second = json_bytes(build_resources(reordered, copy.deepcopy(patches), stages, SHA))
        self.assertEqual(first, second)

    def test_manifest_binds_exact_bytes_and_immutable_tag(self):
        data = json_bytes(build_resources(*fixture(), SHA))
        manifest = manifest_for(data, SHA)
        self.assertEqual(manifest["sha256"], hashlib.sha256(data).hexdigest())
        self.assertEqual(manifest["resourceVersion"], manifest["sha256"])
        self.assertIn(f"/releases/download/maa-{manifest['sha256']}/resources.json", manifest["resourcesUrl"])

    def test_generation_and_corrupt_asset_detection(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            for name, data in zip(("character_table", "char_patch_table", "stage_table"), fixture()):
                (root / f"{name}.json").write_bytes(json_bytes(data))
            generate(root, root / "dist", SHA)
            validate_bundle(root / "dist", "SakuraFox-GC/Suzuran.Resources")
            asset = root / "dist/resources.json"
            value = json.loads(asset.read_bytes())
            value["cards"][0]["name"] += "tampered"
            asset.write_bytes(json_bytes(value))
            with self.assertRaises(InvalidSource):
                validate_bundle(root / "dist", "SakuraFox-GC/Suzuran.Resources")

    def test_legacy_resource_has_no_optional_projection_fields(self):
        resources = build_resources(*fixture(), SHA)
        validate_resources(resources)
        self.assertNotIn("tileMaps", resources)
        self.assertNotIn("tileSourceCommit", resources)
        self.assertNotIn("tileSourceCommit", manifest_for(json_bytes(resources), SHA))

    def test_projection_fields_require_each_other(self):
        for fields in ({"tileMaps": [tile_fixture()]}, {"tileSourceCommit": TILE_SHA},
                       {"tileMaps": [], "tileSourceCommit": TILE_SHA},
                       {"tileMaps": [tile_fixture()], "tileSourceCommit": "main"}):
            with self.subTest(fields=fields):
                resources = build_resources(*fixture(), SHA)
                resources.update(fields)
                with self.assertRaises(InvalidSource):
                    validate_resources(resources)

    def test_invalid_map_geometry_is_rejected(self):
        invalid_fields = [
            ("width", 0), ("height", -1), ("width", True), ("height", 2.0),
            ("width", 4097), ("width", 4096), ("heightTypes", [0]),
            ("heightTypes", [0, 0, 0, 2]), ("heightTypes", [0, 0, 0, True]),
            ("heightTypes", [0, 0, 0, 1.0]), ("view", [[0, 0, 0]]),
            ("view", [[0, 0], [0, 0, 0]]), ("view", [[0, 0, float("nan")], [0, 0, 0]]),
            ("view", [[0, 0, float("inf")], [0, 0, 0]]), ("view", [[True, 0, 0], [0, 0, 0]]),
            ("view", [[0, 0, 10 ** 400], [0, 0, 0]]),
            ("levelId", ""), ("stageId", ""), ("levelId", "Uppercase"),
        ]
        for field, value in invalid_fields:
            with self.subTest(field=field, value=value):
                tile_map = tile_fixture()
                tile_map[field] = value
                with self.assertRaises(InvalidSource):
                    build_resources(*fixture(), SHA, tile_maps=[tile_map], tile_source_commit=TILE_SHA)
        tile_map = tile_fixture()
        tile_map.update(width=4096, height=4096)
        with self.assertRaisesRegex(InvalidSource, "too many tiles"):
            build_resources(*fixture(), SHA, tile_maps=[tile_map], tile_source_commit=TILE_SHA)

    def test_distinct_stage_maps_may_share_level_id_but_not_stage_id(self):
        normal = tile_fixture()
        hard = {**tile_fixture(), "stageId": "main_01-07#f#"}
        resources = build_resources(*fixture(), SHA, tile_maps=[normal, hard], tile_source_commit=TILE_SHA)
        self.assertEqual(len(resources["tileMaps"]), 2)
        for maps in ([normal, normal], [hard, normal]):
            with self.assertRaises(InvalidSource):
                build_resources(*fixture(), SHA, tile_maps=maps, tile_source_commit=TILE_SHA)

    def test_tile_source_preserves_row_order_and_normalises_level_id(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            tile_map = {**tile_fixture(), "levelId": "Obt/Main/Level_Main_01-07"}
            write_tile_source(root, [tile_map])
            self.assertEqual(build_tile_maps(root), [tile_fixture()])

    def test_tile_source_order_is_deterministic(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            normal = tile_fixture()
            hard = {**tile_fixture(), "stageId": "main_01-07#f#"}
            write_tile_source(root / "one", [normal, hard])
            write_tile_source(root / "two", [hard, normal])
            self.assertEqual(json_bytes(build_tile_maps(root / "one")), json_bytes(build_tile_maps(root / "two")))

    def test_tile_source_rejects_overview_mismatch_and_unsafe_filename(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            for change in ({"stageId": "wrong"}, {"levelId": "wrong"}, {"width": 3},
                           {"filename": "../outside.json"}):
                with self.subTest(change=change):
                    write_tile_source(root)
                    overview = json.loads((root / "overview.json").read_text())
                    overview["0"].update(change)
                    (root / "overview.json").write_bytes(json_bytes(overview))
                    with self.assertRaises(InvalidSource):
                        build_tile_maps(root)
            write_tile_source(root, [tile_fixture(), tile_fixture()])
            with self.assertRaisesRegex(InvalidSource, "duplicate"):
                build_tile_maps(root)

    def test_tile_source_rejects_missing_or_ragged_rows(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            for tiles in ([], [[{"heightType": 0}], [{"heightType": 0}]], [[{}, {}], [{}, {}]]):
                with self.subTest(tiles=tiles):
                    write_tile_source(root)
                    data = json.loads((root / "map-0.json").read_text())
                    data["tiles"] = tiles
                    (root / "map-0.json").write_bytes(json_bytes(data))
                    with self.assertRaises(InvalidSource):
                        build_tile_maps(root)

    def test_projection_generation_and_manifest_provenance(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            for name, data in zip(("character_table", "char_patch_table", "stage_table"), fixture()):
                (root / f"{name}.json").write_bytes(json_bytes(data))
            tile_root = root / "tiles"
            write_tile_source(tile_root)
            manifest = generate(root, root / "dist", SHA, tile_source_root=tile_root, tile_source_commit=TILE_SHA)
            validate_bundle(root / "dist", "SakuraFox-GC/Suzuran.Resources")
            self.assertEqual(manifest["tileSourceCommit"], TILE_SHA)
            self.assertEqual(manifest["sourceCommit"], SHA)
            self.assertEqual(json.loads((root / "dist/resources.json").read_text())["tileMaps"], [tile_fixture()])
            manifest["tileSourceCommit"] = "c" * 40
            (root / "dist/manifest.json").write_bytes(json_bytes(manifest))
            with self.assertRaises(InvalidSource):
                validate_bundle(root / "dist", "SakuraFox-GC/Suzuran.Resources")

    def test_previously_published_mapping_bundle_still_validates(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            data = json_bytes(build_resources(*fixture(), SHA))
            manifest = manifest_for(data, SHA)
            manifest.update(resourceVersion=SHA,
                            resourcesUrl=f"https://github.com/SakuraFox-GC/Suzuran.Resources/releases/download/maa-{SHA}/resources.json")
            (root / "resources.json").write_bytes(data)
            (root / "manifest.json").write_bytes(json_bytes(manifest))
            validate_bundle(root, "SakuraFox-GC/Suzuran.Resources")

    def test_projection_bundle_rejects_invalid_manifest(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            data = json_bytes(build_resources(*fixture(), SHA, tile_maps=[tile_fixture()], tile_source_commit=TILE_SHA))
            (root / "resources.json").write_bytes(data)
            manifest = manifest_for(data, SHA, tile_source_commit=TILE_SHA)
            for invalid in (None, {}, {**manifest, "schemaVersion": True}, {**manifest, "schemaVersion": 1.0}):
                with self.subTest(manifest=invalid):
                    (root / "manifest.json").write_bytes(json_bytes(invalid))
                    with self.assertRaises(InvalidSource):
                        validate_bundle(root, "SakuraFox-GC/Suzuran.Resources")

    def test_either_source_or_payload_change_changes_release_identity(self):
        versions = set()
        for game_sha, tile_sha, camera_x in ((SHA, TILE_SHA, 0), ("c" * 40, TILE_SHA, 0),
                                            (SHA, "c" * 40, 0), (SHA, TILE_SHA, 1)):
            tile_map = tile_fixture()
            tile_map["view"][0][0] = camera_x
            resources = build_resources(*fixture(), game_sha, tile_maps=[tile_map], tile_source_commit=tile_sha)
            versions.add(manifest_for(json_bytes(resources), game_sha, tile_source_commit=tile_sha)["resourceVersion"])
        self.assertEqual(len(versions), 4)

    def test_resource_size_limit_prevents_writes(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            for name, data in zip(("character_table", "char_patch_table", "stage_table"), fixture()):
                (root / f"{name}.json").write_bytes(json_bytes(data))
            with patch("tools.generate.MAX_RESOURCE_BYTES", 1):
                with self.assertRaisesRegex(InvalidSource, "32 MiB"):
                    generate(root, root / "dist", SHA)
            self.assertFalse((root / "dist").exists())


if __name__ == "__main__":
    unittest.main()
