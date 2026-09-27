"""Cross-node character drift — the 服装 dimension's computable half (V0.2 §5).

Within ONE SceneScript the appearance dimension is structurally safe: a
character has exactly one ``appearance``, so "Scene 02 把她换成黑风衣" cannot be
authored. Across NODES it can: the workflow's scene-3d nodes each hold their own
script, and the same character can be red-jacketed in the corridor scene and
blue-coated in the street scene while BOTH claim the same character asset.

The asset binding is the identity lock (the Dramagic lock: "同一个角色" is what
a reviewer and a downstream video model rely on). When two nodes bind the same
asset but render different appearances, the lock is lying — and the failure
lands exactly where V0.2 §5 warns: "上一镜人物向右运动，下一镜突然向左" has a
sibling failure "同一个角色在两场里换了装".

What is checkable here, honestly:

* ``character_appearance_drift`` — one asset, two low-poly appearances. The
  bindings say "same person"; the renders say otherwise.
* ``character_binding_conflict`` — one character ID, two different assets.
  The name says "same person"; the bindings say otherwise.
* ``character_palette_vs_asset_drift`` — a bound character whose previs
  colour/palette is disjoint from what the CHARACTER ASSET declares. ADR 0011:
  the asset is the source of truth for how this person looks and the previs is
  a proxy, so a proxy wearing colours nobody declared is inventing the one
  fact the asset binding exists to pin. Characters whose asset declares nothing
  are skipped (an asset that never declared is not a disagreement).
* ``character_palette_drift`` — one asset, two declared wardrobe palettes.
  V0.2 §5's 服装 is about what the NEXT scene inherits; when two scenes
  bind the same character but declare different palettes, the inheritance
  is silently broken in the one place it can be: each node holds its own
  script, and nobody can see the other node's declaration while painting.
  Characters that declare nothing are skipped — an empty palette is an
  author who has not decided yet, not a drift.

Unbound characters are deliberately out of scope: the per-script gate already
flags those (``character_unbound``), and a character nobody bound has no
cross-node identity claim to violate.

Advisory only, published per node so a reviewer can ask for it.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.schemas.scene_script import SceneScriptRoot


@dataclass(frozen=True)
class CharacterDriftFinding:
    """One way two nodes disagree about who a character is."""

    code: str
    subject: str
    message: str
    remedy: str

    def to_dict(self) -> dict[str, str]:
        return {
            "code": self.code,
            "subject": self.subject,
            "message": self.message,
            "remedy": self.remedy,
        }


def _normalized_color(color: str | None) -> str:
    return (color or "").strip().lower()


#: Two colours closer than this (RGB euclidean) are the same colour: the
#: previs body and the asset declaration are picked by different tools at
#: different times, and a hex-exact match would flag every legitimate reuse.
PALETTE_MATCH_TOLERANCE = 60.0


def _near_declared(color: str, declared: list[str]) -> bool:
    """Whether ``color`` is (near) one of the asset's declared palette."""

    mine = _channels(color)
    for entry in declared:
        theirs = _channels(entry)
        if mine is None or theirs is None:
            continue
        if (
            (mine[0] - theirs[0]) ** 2
            + (mine[1] - theirs[1]) ** 2
            + (mine[2] - theirs[2]) ** 2
        ) ** 0.5 <= PALETTE_MATCH_TOLERANCE:
            return True
    return False


def _channels(color: str) -> tuple[int, int, int] | None:
    try:
        return (
            int(color[1:3], 16),
            int(color[3:5], 16),
            int(color[5:7], 16),
        )
    except (ValueError, IndexError):
        return None


def check_cross_node_character_drift(
    scripts_by_node: dict[str, SceneScriptRoot],
    *,
    asset_palettes: dict[str, list[str]] | None = None,
) -> list[CharacterDriftFinding]:
    """Notice where two scene-3d nodes disagree about a character's identity.

    ``scripts_by_node`` maps node id → that node's SceneScript. The node the
    check runs for is included like any other; a single-node workflow yields
    nothing to compare and therefore no findings.

    ``asset_palettes`` (optional) maps character asset id → the palette that
    asset DECLARES, so a previs wearing colours nobody declared can be
    noticed. Without it the asset-side check is skipped rather than guessed.
    """

    findings: list[CharacterDriftFinding] = []
    # 1. The previs must not invent the wardrobe the asset declares
    #    (ADR 0011). ``asset_palettes`` maps asset id -> declared palette.
    declared_palettes = asset_palettes or {}
    for node_id, script in scripts_by_node.items():
        for character in script.characters:
            asset_id = character.character_asset_id
            if not asset_id:
                continue
            declared = declared_palettes.get(asset_id)
            if not declared:
                continue  # the asset says nothing: nothing to compare against.
            # What the previs says THIS character wears: the declared palette
            # when the author wrote one, otherwise the body colour (the one
            # number every script has).
            worn = [
                entry.upper()
                for entry in (character.appearance.palette or [character.appearance.color])
            ]
            if any(_near_declared(entry, declared) for entry in worn):
                continue
            findings.append(
                CharacterDriftFinding(
                    code="character_palette_vs_asset_drift",
                    subject=asset_id,
                    message=(
                        f"角色资产 {asset_id} 声明穿 {'、'.join(declared)}，"
                        f"但 {node_id}/{character.id} 的预演穿 {'、'.join(worn)}："
                        "预演在替角色发明颜色，而资产绑定本来要钉住的正是这一点。"
                    ),
                    remedy=(
                        "在 3D 编辑器里选中该角色 → 服装色板，改成资产色板里的颜色；"
                        "或更新角色资产的色板声明（换装要让叙事说明，而不是静默漂移）。"
                    ),
                )
            )


    if len(scripts_by_node) < 2:
        return findings

    # 2. One asset, many appearances: the binding claims one person.
    by_asset: dict[str, list[tuple[str, str, str]]] = {}
    for node_id, script in scripts_by_node.items():
        for character in script.characters:
            if not character.character_asset_id:
                continue
            by_asset.setdefault(character.character_asset_id, []).append(
                (node_id, character.id, _normalized_color(character.appearance.color))
            )
    for asset_id, entries in sorted(by_asset.items()):
        colors = {color for _, _, color in entries if color}
        if len(colors) > 1:
            described = "、".join(
                f"{node_id}/{character_id} 用 {color}" for node_id, character_id, color in entries
            )
            findings.append(
                CharacterDriftFinding(
                    code="character_appearance_drift",
                    subject=asset_id,
                    message=(
                        f"角色资产 {asset_id} 被多个场景节点绑定，但外观不一致：{described}。"
                        "身份绑定说这是同一个人，预览却说不是。"
                    ),
                    remedy=(
                        "把各场景节点里该角色的外观色统一（检查器 → 角色资产绑定下方）；"
                        "确需换装时，让叙事说明这次变化，而不是静默漂移。"
                    ),
                )
            )

    # 3. One character id, two assets: the name claims one person.
    by_character_id: dict[str, set[str]] = {}
    for script in scripts_by_node.values():
        for character in script.characters:
            if character.character_asset_id:
                by_character_id.setdefault(character.id, set()).add(
                    character.character_asset_id
                )
    for character_id, asset_ids in sorted(by_character_id.items()):
        if len(asset_ids) > 1:
            findings.append(
                CharacterDriftFinding(
                    code="character_binding_conflict",
                    subject=character_id,
                    message=(
                        f"角色 id「{character_id}」在不同场景节点绑定了不同资产："
                        f"{'、'.join(sorted(asset_ids))}。名字说这是同一个人，绑定说不是。"
                    ),
                    remedy=(
                        "统一该角色在各场景节点绑定的角色资产；或改用一个不带歧义的 id。"
                    ),
                )
            )

    # 4. One asset, two declared palettes: the wardrobe the next scene must
    #    inherit disagrees with the one it was authored from.
    by_asset_palette: dict[str, list[tuple[str, str, tuple[str, ...]]]] = {}
    for node_id, script in scripts_by_node.items():
        for character in script.characters:
            palette = character.appearance.palette
            if not character.character_asset_id or not palette:
                continue
            by_asset_palette.setdefault(character.character_asset_id, []).append(
                (node_id, character.id, tuple(entry.upper() for entry in palette))
            )
    for asset_id, entries in sorted(by_asset_palette.items()):
        distinct = {palette for _, _, palette in entries}
        if len(distinct) <= 1:
            continue
        described = "；".join(
            f"{node_id}/{character_id} 声明 {'、'.join(palette)}"
            for node_id, character_id, palette in entries
        )
        findings.append(
            CharacterDriftFinding(
                code="character_palette_drift",
                subject=asset_id,
                message=(
                    f"角色资产 {asset_id} 在多场里声明了不同服装色板：{described}。"
                    "同一个角色被下一镜继承时，两边对『她穿什么』的说法不一致。"
                ),
                remedy=(
                    "在 3D 编辑器里选中该角色 → 服装色板，把各场景节点统一到同一组颜色；"
                    "确需换装时，让叙事说明这次变化，而不是静默漂移。"
                ),
            )
        )

    return findings
