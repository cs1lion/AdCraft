"""拉片复刻 · 风格混搭变体引擎（Jev 式结构化决策的确定性实现）。

调研档 §4.4（Jev+Hypit 方案）的落地切片：**风格导演**接口——给定蓝图
（复刻目标/整片解读/视觉系统），对风格库做 Score/Choice 式判断并产出
Top-K 候选与 N 个变体。内部实现为确定性关键词打分（不依赖 Jev API）——
与调研档建议一致："落地不依赖接入 Jev 本体……用结构化输出的小模型/GLM
模仿 Choice/Score/Noul 三问式即可，接口保持一致"；后续可换小模型实现。

    蓝图 ──score_skills──▶ Top-K 兼容风格集（含理由）
         ──plan_style_variants──▶ N 个变体（seed 派生自蓝图，可复现）

风格库来源：``agent/video-skills/``（catalog.json + 各 Skill 的
SKILL.md frontmatter：name/description 中文元数据）。

诚实边界：多风格并行激活尚未支持（调研档 §5 风险 4）——``mix_size=2``
的组合候选可生成（前端展示），但应用侧当前只能落单风格槽位。
"""

from __future__ import annotations

import hashlib
import json
import random
import re
from dataclasses import dataclass
from pathlib import Path

from app.schemas.agent_canvas_ad_media import ReplicaBlueprintContentV2

#: 风格库默认位置（apps/api/agent/video-skills）
_DEFAULT_SKILLS_DIR = Path(__file__).resolve().parents[3] / "agent" / "video-skills"

#: 中性兜底风格不参与推荐/混搭（它是"未选择"，不是候选）
_NEUTRAL_SKILL_ID = "platform-default"

_HAN = re.compile(r"[\u4e00-\u9fff]")
_LATIN = re.compile(r"[a-z][a-z0-9_-]{2,}")


class StyleVariantError(ValueError):
    """风格库不可用或参数非法。"""


@dataclass(frozen=True)
class StyleSkillInfo:
    """一个风格 Skill 的可打分元数据。"""

    skill_id: str
    name: str
    description: str
    category_id: str
    version: str


@dataclass(frozen=True)
class StyleVariant:
    """一个风格变体候选（Jev Choice 语义：选项 + 依据 + 分数）。

    G5：变体 = **skill × recipe**——skill 是整包风格技能，recipe 是字幕族
    配方（.adrecipe）。没有 recipe 的变体在渲染计划里只有 style 槽位差异，
    字幕样式逐字节相同（老问题）；配方让"看得见的差异"成立。
    """

    variant_id: str
    skill_ids: tuple[str, ...]
    names: tuple[str, ...]
    score: float
    rationale: str
    mixable_applied: bool = True  # 多风格激活支持后组合才可一键应用
    recipe_id: str = ""  # 字幕族配方 id（空 = 编译层默认形态）
    recipe_name: str = ""


# ---------------------------------------------------------------------------
# 风格库扫描
# ---------------------------------------------------------------------------


def _parse_frontmatter(skill_md: str) -> dict[str, str]:
    """SKILL.md 头部 frontmatter（name/description）；缺失返回空。"""
    if not skill_md.startswith("---"):
        return {}
    end = skill_md.find("\n---", 3)
    if end < 0:
        return {}
    block = skill_md[3:end]
    fields: dict[str, str] = {}
    for line in block.splitlines():
        if ":" not in line:
            continue
        key, _, value = line.partition(":")
        fields[key.strip()] = value.strip()
    return fields


def load_style_skills(skills_dir: Path | None = None) -> list[StyleSkillInfo]:
    """扫描风格库：catalog.json 的 skills × 各自 SKILL.md 元数据。

    目录缺失/条目损坏时跳过该条（库扫描是宽容的）；整个目录缺失才报错。
    """
    base = skills_dir or _DEFAULT_SKILLS_DIR
    catalog_path = base / "catalog.json"
    if not catalog_path.exists():
        raise StyleVariantError(f"Style catalog not found: {catalog_path}")
    catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
    categories = {
        c.get("category_id", ""): c.get("category_id", "")
        for c in catalog.get("categories", [])
        if isinstance(c, dict)
    }
    skills: list[StyleSkillInfo] = []
    for entry in catalog.get("skills", []):
        if not isinstance(entry, dict):
            continue
        skill_id = str(entry.get("skill_id") or "")
        version = str(entry.get("version") or "")
        if not skill_id or not version:
            continue
        skill_md_path = base / skill_id / version / "SKILL.md"
        meta = (
            _parse_frontmatter(skill_md_path.read_text(encoding="utf-8"))
            if skill_md_path.exists()
            else {}
        )
        skills.append(
            StyleSkillInfo(
                skill_id=skill_id,
                name=meta.get("name", ""),
                description=meta.get("description", ""),
                category_id=categories.get(str(entry.get("category_id") or ""), ""),
                version=version,
            )
        )
    return skills


# ---------------------------------------------------------------------------
# 确定性打分（Choice/Score 语义）
# ---------------------------------------------------------------------------


def _tokens(text: str) -> set[str]:
    """CJK 二元组 + 拉丁词（≥3 字符小写）——无分词依赖的确定性词元。"""
    tokens: set[str] = set()
    han_runs = _HAN.findall(text)
    # findall 返回单字符序列，按原文顺序取连续段做 bigram
    run: list[str] = []
    runs: list[list[str]] = []
    for ch in text:
        if _HAN.match(ch):
            run.append(ch)
        elif run:
            runs.append(run)
            run = []
    if run:
        runs.append(run)
    _ = han_runs
    for segment in runs:
        for i in range(len(segment) - 1):
            tokens.add(segment[i] + segment[i + 1])
    for word in _LATIN.findall(text.lower()):
        tokens.add(word)
    return tokens


def blueprint_query_text(blueprint: ReplicaBlueprintContentV2) -> str:
    """蓝图 → 打分查询文本（复刻目标/解读/格式/系统）。"""
    parts = [
        blueprint.replica_goal,
        blueprint.whole_piece_reading,
        blueprint.format_name,
        blueprint.systems_captions,
        blueprint.systems_music,
        *blueprint.systems_graphics,
        *blueprint.systems_sfx,
        *blueprint.constraints,
    ]
    return "\n".join(part for part in parts if part)


def score_skills(
    blueprint: ReplicaBlueprintContentV2,
    skills: list[StyleSkillInfo],
) -> list[tuple[StyleSkillInfo, float]]:
    """对每个风格 Skill 打分：查询词元与 Skill 词元的重叠度（确定性）。

    score = |query ∩ skill| / sqrt(|skill 词元|)——偏向具体、词元更少的
    Skill（小模型"判官"的确定性替身）。返回按分数降序的列表。
    """
    query_tokens = _tokens(blueprint_query_text(blueprint))
    scored: list[tuple[StyleSkillInfo, float]] = []
    for skill in skills:
        if skill.skill_id == _NEUTRAL_SKILL_ID:
            continue
        skill_tokens = _tokens(f"{skill.name} {skill.description}")
        if not skill_tokens or not query_tokens:
            scored.append((skill, 0.0))
            continue
        overlap = len(query_tokens & skill_tokens)
        scored.append((skill, round(overlap / (len(skill_tokens) ** 0.5), 4)))
    scored.sort(key=lambda pair: (-pair[1], pair[0].skill_id))
    return scored


# ---------------------------------------------------------------------------
# 变体规划（Hypit 式混搭，seed 可复现）
# ---------------------------------------------------------------------------


def plan_style_variants(
    blueprint: ReplicaBlueprintContentV2,
    *,
    n: int = 5,
    mix_size: int = 1,
    top_k: int = 8,
    skills: list[StyleSkillInfo] | None = None,
    seed: str | None = None,
) -> list[StyleVariant]:
    """蓝图 → N 个风格变体（确定性：相同输入 + 相同 seed 得相同序列）。

    - 候选：score_skills 的 Top-K；
    - 混搭：``mix_size`` 个候选一组（``mix_size=1`` 即排名推荐）；
    - 组合去重、不足 N 时返回全部可行组合；
    - ``seed`` 缺省取蓝图内容摘要——同一蓝图重开得到同一批候选。
    """
    if n < 1 or n > 12:
        raise StyleVariantError(f"n out of range [1, 12]: {n}")
    if mix_size < 1 or mix_size > 3:
        raise StyleVariantError(f"mix_size out of range [1, 3]: {mix_size}")
    skill_list = skills if skills is not None else load_style_skills()
    ranked = score_skills(blueprint, skill_list)[: max(top_k, mix_size)]
    if not ranked:
        return []

    seed_material = seed or hashlib.sha256(
        blueprint.model_dump_json(exclude={"instantiated_script_node_id"}).encode("utf-8")
    ).hexdigest()
    rng = random.Random(seed_material)

    candidates = [skill for skill, _ in ranked]
    scores = dict(ranked)

    if mix_size == 1:
        # 单风格 = 排名推荐（Jev Score 语义：分高者先）
        chosen: list[tuple[StyleSkillInfo, ...]] = [(skill,) for skill in candidates[:n]]
    else:
        # 混搭 = 加权随机不放回（Hypit 式多样性；权重来自分数，rng 可复现）
        chosen = []
        pool = {skill: max(scores[skill], 0.01) for skill in candidates}
        for _ in range(min(n, max(1, len(candidates) // mix_size))):
            if len(pool) < mix_size:
                break
            pick: list[StyleSkillInfo] = []
            local_pool = dict(pool)
            for _ in range(mix_size):
                total = sum(local_pool.values())
                point = rng.random() * total
                acc = 0.0
                for skill, weight in local_pool.items():
                    acc += weight
                    if acc >= point:
                        pick.append(skill)
                        del local_pool[skill]
                        break
            chosen.append(tuple(sorted(pick, key=lambda s: -scores[s])))
            for skill in pick:
                pool.pop(skill, None)
            if not pool:
                break

    variants: list[StyleVariant] = []
    for combo in chosen:
        ids = tuple(s.skill_id for s in combo)
        names = tuple(s.name or s.skill_id for s in combo)
        score = round(sum(scores[s] for s in combo) / len(combo), 4)
        matched = _top_overlap_terms(blueprint, list(combo))
        variants.append(
            StyleVariant(
                variant_id="variant_"
                + hashlib.sha256(
                    ("|".join(ids) + f"|{seed_material}").encode("utf-8")
                ).hexdigest()[:12],
                skill_ids=ids,
                names=names,
                score=score,
                rationale="匹配关键词："
                + ("、".join(matched) if matched else "（无明显命中，按库序推荐）"),
                mixable_applied=len(combo) == 1,
            )
        )
    # G5：挂字幕族配方（变体 = skill × recipe；库不可用时保持无配方）
    return attach_recipes(variants, seed_material=seed_material)


def _top_overlap_terms(
    blueprint: ReplicaBlueprintContentV2, combo: list[StyleSkillInfo]
) -> list[str]:
    """给出候选命中的查询词元（最多 4 个，理由可读）。"""
    query_tokens = _tokens(blueprint_query_text(blueprint))
    skill_tokens: set[str] = set()
    for skill in combo:
        skill_tokens |= _tokens(f"{skill.name} {skill.description}")
    return sorted(query_tokens & skill_tokens)[:4]


# ---------------------------------------------------------------------------
# G5：变体 = skill × recipe（字幕族配方轮换）
# ---------------------------------------------------------------------------


def attach_recipes(
    variants: list[StyleVariant],
    recipes: list | None = None,
    *,
    seed_material: str = "",
) -> list[StyleVariant]:
    """给变体挂字幕族配方（.adrecipe）——没有它，变体只有 skill 槽位差异。

    确定性轮换：第 i 个变体取 ``recipes[i % len(recipes)]``——同一 seed
    下同一变体永远拿到同一配方，且相邻变体配方不同（差异可感知；审片时
    "看得见的不同"正是 recipe 带来的）。

    配方库不可用（目录缺失/损坏）时变体保持无 recipe——库是增强不是依赖，
    不为一个可选增强炸掉主流程。
    """
    if recipes is None:
        try:
            from app.services.replica.recipe import RecipeError, load_recipes

            recipes = load_recipes()
        except RecipeError:
            recipes = []
    if not recipes:
        return variants
    attached: list[StyleVariant] = []
    for index, variant in enumerate(variants):
        recipe = recipes[index % len(recipes)]
        attached.append(
            StyleVariant(
                variant_id="variant_"
                + hashlib.sha256(
                    (
                        "|".join(variant.skill_ids)
                        + f"|{recipe.recipe_id}"
                        + f"|{seed_material}"
                    ).encode("utf-8")
                ).hexdigest()[:12],
                skill_ids=variant.skill_ids,
                names=variant.names,
                score=variant.score,
                rationale=(
                    variant.rationale + "；样式配方：" + (recipe.name or recipe.recipe_id)
                ),
                mixable_applied=variant.mixable_applied,
                recipe_id=recipe.recipe_id,
                recipe_name=recipe.name or recipe.recipe_id,
            )
        )
    return attached
