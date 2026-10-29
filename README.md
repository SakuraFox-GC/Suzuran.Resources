# Suzuran resources

Deterministic name, ID and stage mappings for Suzuran and Hikari, with optional
MAA tile projection data. Releases are published only by manual workflow dispatch.

Generate from fixed upstream checkouts:

```sh
python tools/generate.py --source-root /path/to/ArknightsGameData --tile-source-root /path/to/MaaResource --output-dir dist
python tools/validate.py dist
python -m unittest discover -s tests -v
```

The source commits default to each checkout's `HEAD`. Exported source directories
require explicit full `--source-commit` and `--tile-source-commit` values. Omitting
the tile source produces a bundle containing only the original mappings.

## Resource format

`resources.json` retains `schemaVersion: 1`, `sourceCommit`, `cards` and `stages`.
The optional `tileSourceCommit` and `tileMaps` fields must appear together.
`sourceCommit` identifies ArknightsGameData; `tileSourceCommit` identifies
MaaResource. Both are complete lowercase Git commit hashes.

Each tile map contains `stageId`, lowercase `levelId`, positive integer `width`
and `height`, `view`, and `heightTypes`. `view` contains the normal and side camera
positions, in that order; each is a vector of three finite numbers. `heightTypes`
contains `width * height` integers in top-row-first order, indexed by
`y * width + x` in MAA coordinates. Ground is `0`, highland is `1`. Dimensions are
limited to 4,096 and a map to 1,048,576 tiles. Maps are sorted by unique `stageId`;
different stages may share a `levelId` and must not be merged on that basis.
Buildability and current game state are deliberately absent from projection data.

Map records come from `resource/Arknights-Tile-Pos/overview.json` and its named
files. Identities and dimensions must agree. Invalid input aborts generation;
the generator does not substitute camera positions or silently skip bad maps.

Old clients ignore the optional fields. New clients must continue loading old
bundles and report unavailable projection data only when a pixel action needs it.
The complete resource file may not exceed the Android downloader's 32 MiB limit.

## Release identity and provenance

`manifest.json` retains schema version 1 and the existing download fields. It
adds `tileSourceCommit` when tile data is present. Its `sha256` and
`resourceVersion` are the SHA-256 of the exact generated `resources.json` bytes;
`resourceVersion` is not embedded in those bytes. The release tag is
`maa-<resourceVersion>`, so changing either upstream or generated content creates
a new immutable asset identity. The stable discovery URL remains
`releases/latest/download/manifest.json`.

The workflow resolves both requested upstream refs to commits, generates twice,
compares bytes and validates the manifest before publication. Existing releases
are reused only when all published assets match; assets are never replaced.
Previously published `maa-<game-data-commit>` releases remain untouched. Release
notes link both upstream commits and the generator commit. Source attribution and
the MaaResource licence are included as release assets; see
[THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).
