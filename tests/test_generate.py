import copy
import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from tools.generate import InvalidSource, build_resources, generate, json_bytes, manifest_for
from tools.validate import validate_bundle

SHA = "a" * 40


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
        self.assertIn(f"/releases/download/maa-{SHA}/resources.json", manifest["resourcesUrl"])

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


if __name__ == "__main__":
    unittest.main()
