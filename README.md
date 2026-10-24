# Suzuran.Resources

Suzuran 的 MAA 作业系统使用的轻量中文名称/ID映射。数据提取自 [Kengxxiao/ArknightsGameData](https://github.com/Kengxxiao/ArknightsGameData)，只包含角色名称、角色与职业模板标识和关卡导航字段；账号、属性、技能、模组与解锁状态由模组读取游戏数据库。

## 更新与发布

**只手动更新。** 在 Actions 中选择 **Update mapping resources → Run workflow**，输入上游分支、标签或完整 commit SHA（默认 `master`）。工作流将该引用解析为固定提交，使用浅克隆，仅检出中文服三张表；运行验证后发布 `maa-<完整上游SHA>`。没有 `schedule`、`push` 或 `pull_request` 触发器。

- 模组更新入口：<https://github.com/SakuraFox-GC/Suzuran.Resources/releases/latest/download/manifest.json>
- 每个 manifest 指向同次发布标签下的 `resources.json`，并携带对应文件字节的 SHA-256。
- 相同上游提交的已有发布只能复核，不能覆盖；内容不同会直接失败。修正生成规则且需要替换既有产物时，必须先升级资源格式或发布版本设计，不应偷偷重写已发布资产。
- 新发布完成后才更新 latest；若下载、校验、生成或发布失败，旧发布继续可用。

## 数据契约（schemaVersion = 1）

`resources.json`：

```json
{
  "schemaVersion": 1,
  "sourceCommit": "<40-character upstream SHA>",
  "cards": [
    {"id": "char_1001_amiya2", "charId": "char_002_amiya", "tmplId": "char_1001_amiya2", "name": "阿米娅", "profession": "WARRIOR"}
  ],
  "stages": [
    {"stageId": "main_01-07", "levelId": "obt/main/level_main_01-07", "zoneId": "main_1", "code": "1-7", "name": "暴君", "difficulty": "NORMAL", "diffGroup": "NONE"}
  ]
}
```

卡牌包含 `character_table` 的 `char_`、`token_`、`trap_` 及 `char_patch_table.patchChars`；职业模板所属角色只通过 `char_patch_table.infos` 反查，不通过命名猜测。普通角色的 `charId`、`tmplId` 均等于 `id`。资源按 ID 保存每条记录，**重名不能合并**；消费者应建立 `name → unordered_set<ID>` 索引，再结合职业、编队、场景卡组或实例坐标消歧。关卡同样不能按名称、code 或 levelId 去重，不同难度各自保留。

`levelId`、`code`、`name`、`diffGroup` 若上游明确为 `null`，统一转换为空字符串以保持模组的字符串契约；消费者需将无关卡资源/代码等记录展示为不可用或只用于匹配，不能凭空补齐路线。其余字段缺失或归属不完整会让生成明确失败。

`manifest.json`：

```json
{
  "schemaVersion": 1,
  "resourceVersion": "<40-character upstream SHA>",
  "sourceCommit": "<40-character upstream SHA>",
  "resourcesUrl": "https://github.com/SakuraFox-GC/Suzuran.Resources/releases/download/maa-<SHA>/resources.json",
  "sha256": "<resources.json byte SHA-256>"
}
```

所有 JSON 使用 UTF-8、排序键、两空格缩进和文件末尾单个换行；卡牌按 `id`、关卡按 `stageId` 排序。同一输入提交与生成器产生完全一致的字节。

## 本地生成

Python 3.10+，只使用标准库，没有额外依赖。

```sh
git clone --depth 1 --filter=blob:none --sparse https://github.com/Kengxxiao/ArknightsGameData.git upstream
git -C upstream sparse-checkout set --no-cone /zh_CN/gamedata/excel/character_table.json /zh_CN/gamedata/excel/char_patch_table.json /zh_CN/gamedata/excel/stage_table.json
python3 -m unittest discover -s tests -v
python3 tools/generate.py --source-root upstream --output-dir dist
python3 tools/validate.py dist
```

如从归档或 GitHub API取得三张表，可通过 `--source-commit <完整SHA>` 明确提供来源提交；调用者必须保证三表来自该提交。生产工作流始终直接读取检出仓库的 HEAD。

## 数据来源与权利

本仓库仅维护生成工具与最小映射产物；上游游戏数据和名称的权利归各自权利人所有，不为上游数据新增授权。生成工具以 MIT 许可发布。
