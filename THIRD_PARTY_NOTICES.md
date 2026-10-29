# Third-party data and attribution

The MIT licence in this repository applies to its original generator and tooling.
It does not replace the licences or rights attached to upstream resource data.

## Arknights game data

Character, template and stage mappings are extracted from
[Kengxxiao/ArknightsGameData](https://github.com/Kengxxiao/ArknightsGameData).
The exact source revision is recorded in the resource and manifest
`sourceCommit` fields. Arknights names and game data originate from Hypergryph
and their respective rights holders.

## MAA tile projection data

Camera positions and tile height data are extracted from
[MaaAssistantArknights/MaaResource](https://github.com/MaaAssistantArknights/MaaResource),
under `resource/Arknights-Tile-Pos`. The exact revision is recorded in
`tileSourceCommit`. MaaResource supplies the GNU Affero General Public License,
version 3; the complete upstream text is included in
[LICENSES/MaaResource-AGPL-3.0.txt](LICENSES/MaaResource-AGPL-3.0.txt).

The map projection work originates from
[yuanyan3060/Arknights-Tile-Pos](https://github.com/yuanyan3060/Arknights-Tile-Pos).
This resource generator extracts the supplied map data and does not copy its
projection implementation. The generated fields retain MAA's camera-vector order,
grid row order and numeric height convention.

Releases include these notices, the upstream licence text and links to both
source commits and the generator commit. The referenced upstream repositories
provide the source data; this repository provides the extraction tooling.
