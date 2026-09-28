"""拉片复刻 · ``.adrecipe`` 配方层（hypit recipes 的 AdCraft 落地，G5）。

hypit 的风格不是整包 skill，而是**语义维度 token 集**（字幕族：font/color/
position/lead/tail/handoff；components 按名引用）。本模块把这一思想落地为：
配方（recipe）= 一组字幕渲染维度 + 文档层（``.adrecipe`` 标记文本）+
内置配方库（可扩展的文件化 catalog）。

**词汇表只收渲染链真实消费的字段**——``WorkflowV2TimelineSubtitleStyle``
在 G3 之后恰好有这六个维度，配方到样式是 1:1 映射。每个新维度都必须有
编译目标（调研档 §3.4 封顶原则）：收一个渲染器不消费的字段，就是让文档
说谎。未覆盖的维度（motion 预设、镜头语言）等渲染链支持后再进词汇表，
本版刻意不收。

- ``<adrecipe version="1" kind="subtitle-style">`` → ``<subtitle>`` 六维；
- normalize 兜底（数字容忍、范围钳制由样式 schema 负责），**未知属性/
  根元素显式报错**（静默降级禁止，同 ``.adreplica`` 纪律）；
- 内置库：``agent/recipes/catalog.json``（条目损坏跳过、目录缺失才报错，
  同风格库的宽容纪律）。

纯函数 + 文件读取；无 LLM、无 HTTP。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import xml.etree.ElementTree as ET
from pydantic import BaseModel, Field

from app.schemas.workflow_v2 import WorkflowV2TimelineSubtitleStyle

#: 文档语法版本（区别于配方条目自己的 version）
ADRECIPE_VERSION = "1"

_ROOT_TAG = "adrecipe"
_KIND = "subtitle-style"

#: 词汇表：配方属性 → (样式字段, 文档属性名)。**这就是配音方的全部真相**——
#: 渲染器（drawtext enable 窗/字号/颜色/位置）真实消费的六个维度。
_VOCABULARY: tuple[tuple[str, str], ...] = (
    ("font_size", "font-size"),
    ("color", "color"),
    ("position", "position"),
    ("lead_seconds", "lead"),
    ("tail_seconds", "tail"),
    ("handoff", "handoff"),
)

_VOCABULARY_BY_ATTR = {doc_name: field for field, doc_name in _VOCABULARY}

_POSITIONS = ("top_center", "center", "bottom_center")
_HANDOFFS = ("cut", "overlap")

_DEFAULT_RECIPES_DIR = Path(__file__).resolve().parents[3] / "agent" / "recipes"

#: 内置配方 id（编译层缺省 = 当前复刻直出的默认形态，显式化而非隐式）
DEFAULT_RECIPE_ID = "bottom-bold"


class AdRecipeParseError(Exception):
    """``.adrecipe`` 文本无法解析/校验为配方。"""


class RecipeError(ValueError):
    """配方库不可用或条目非法。"""


class ReplicaSubtitleRecipeV2(BaseModel):
    """字幕族配方维度（全部可选：未设置的维度保持样式原值）。

    范围与 ``WorkflowV2TimelineSubtitleStyle`` 同口径——配方到样式是
    1:1 映射，不引入渲染器不消费的字段。
    """

    font_size: int | None = Field(default=None, ge=12, le=96)
    color: str | None = Field(default=None, pattern=r"^#[0-9A-Fa-f]{6}$")
    position: str | None = Field(default=None)
    lead_seconds: float | None = Field(default=None, ge=0, le=5)
    tail_seconds: float | None = Field(default=None, ge=0, le=5)
    handoff: str | None = Field(default=None)

    def applied_fields(self) -> dict[str, Any]:
        """实际设置的维度（None = 未设置，不进文档也不覆盖样式）。"""
        return {field: value for field, value in self.model_dump().items() if value is not None}


class ReplicaRecipeV2(BaseModel):
    """一个配方：字幕族维度 + 可读元数据（id/name/description）。"""

    recipe_id: str = Field(min_length=1, max_length=64)
    name: str = Field(default="", max_length=64)
    description: str = Field(default="", max_length=512)
    version: str = Field(default="1", max_length=16)
    subtitle: ReplicaSubtitleRecipeV2 = Field(default_factory=ReplicaSubtitleRecipeV2)

    def to_style_patch(self) -> dict[str, Any]:
        """配方 → 字幕样式增量（只含设置的维度）。"""
        return self.subtitle.applied_fields()


# ---------------------------------------------------------------------------
# 配方 → 样式（编译层消费）
# ---------------------------------------------------------------------------


def apply_recipe(
    style: WorkflowV2TimelineSubtitleStyle, recipe: ReplicaRecipeV2 | None
) -> WorkflowV2TimelineSubtitleStyle:
    """把配方合并进字幕样式（未设置的维度保持原值）。

    无配方（None）时原样返回——默认形态由调用方的样式默认值决定（复刻
    编译层 = G3 的 0.1/0.2/cut 显式默认）。
    """
    if recipe is None:
        return style
    patch = recipe.to_style_patch()
    if not patch:
        return style
    return style.model_copy(update=patch)


# ---------------------------------------------------------------------------
# .adrecipe 文档层（parse / serialize，往返锁定）
# ---------------------------------------------------------------------------


def adrecipe_from_recipe(recipe: ReplicaRecipeV2) -> str:
    """配方 → ``.adrecipe`` 标记文本（确定性输出；未设置的维度不写）。"""
    root = ET.Element(
        _ROOT_TAG,
        {"version": ADRECIPE_VERSION, "kind": _KIND, "id": recipe.recipe_id},
    )
    meta = ET.SubElement(
        root,
        "meta",
        {"version": recipe.version},
    )
    if recipe.name:
        _sub_text(meta, "name", recipe.name)
    if recipe.description:
        _sub_text(meta, "description", recipe.description)
    subtitle = ET.SubElement(root, "subtitle")
    for field, doc_name in _VOCABULARY:
        value = getattr(recipe.subtitle, field)
        if value is None:
            continue
        subtitle.set(doc_name, _fmt(value))
    ET.indent(root, space="  ")
    return ET.tostring(root, encoding="unicode") + "\n"


def recipe_from_adrecipe(text: str) -> ReplicaRecipeV2:
    """``.adrecipe`` 文本 → 配方（normalize 兜底 + 结构错误显式报错）。"""
    try:
        root = ET.fromstring(text)
    except ET.ParseError as exc:
        raise AdRecipeParseError(f"Invalid .adrecipe XML: {exc}") from exc
    if root.tag != _ROOT_TAG:
        raise AdRecipeParseError(f"Unexpected root element: {root.tag}")
    if (root.get("version") or "") != ADRECIPE_VERSION:
        raise AdRecipeParseError(
            f"Unsupported .adrecipe version: {root.get('version')!r}"
        )
    if (root.get("kind") or "") != _KIND:
        raise AdRecipeParseError(f"Unexpected document kind: {root.get('kind')!r}")
    recipe_id = (root.get("id") or "").strip()
    if not recipe_id:
        raise AdRecipeParseError("Missing recipe id on <adrecipe>")

    meta = root.find("meta")
    version = (meta.get("version") if meta is not None else None) or "1"
    name = _text_of(meta.find("name")) if meta is not None else ""
    description = _text_of(meta.find("description")) if meta is not None else ""

    subtitle_el = root.find("subtitle")
    if subtitle_el is None:
        raise AdRecipeParseError("Missing <subtitle> block")
    known = {doc_name for _, doc_name in _VOCABULARY}
    unknown = set(subtitle_el.attrib) - known
    if unknown:
        raise AdRecipeParseError(
            f"Unknown subtitle recipe property: {sorted(unknown)}"
        )
    patch: dict[str, Any] = {}
    for doc_name, field in _VOCABULARY_BY_ATTR.items():
        raw = subtitle_el.get(doc_name)
        if raw is None or raw.strip() == "":
            continue
        patch[field] = _coerce(field, raw.strip())
    try:
        subtitle = ReplicaSubtitleRecipeV2(**patch)
    except Exception as exc:
        raise AdRecipeParseError(f"Invalid subtitle recipe values: {exc}") from exc

    return ReplicaRecipeV2(
        recipe_id=recipe_id,
        name=name,
        description=description,
        version=str(version),
        subtitle=subtitle,
    )


# ---------------------------------------------------------------------------
# 内置配方库（catalog.json，宽容扫描）
# ---------------------------------------------------------------------------


def load_recipes(recipes_dir: Path | None = None) -> list[ReplicaRecipeV2]:
    """加载内置配方库；目录缺失/文件损坏报错，单条损坏跳过（同风格库纪律）。"""
    base = recipes_dir or _DEFAULT_RECIPES_DIR
    catalog_path = base / "catalog.json"
    if not catalog_path.exists():
        raise RecipeError(f"Recipe catalog not found: {catalog_path}")
    try:
        catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
    except (ValueError, OSError) as exc:
        raise RecipeError(f"Recipe catalog unreadable: {exc}") from exc
    recipes: list[ReplicaRecipeV2] = []
    for entry in catalog.get("recipes", []):
        if not isinstance(entry, dict):
            continue
        try:
            recipe = ReplicaRecipeV2(
                recipe_id=str(entry.get("recipe_id") or ""),
                name=str(entry.get("name") or ""),
                description=str(entry.get("description") or ""),
                version=str(entry.get("version") or "1"),
                subtitle=ReplicaSubtitleRecipeV2(
                    **{
                        key: entry[key]
                        for key in (
                            "font_size", "color", "position",
                            "lead_seconds", "tail_seconds", "handoff",
                        )
                        if key in entry
                    }
                ),
            )
        except Exception:
            continue
        if not recipe.recipe_id:
            continue
        recipes.append(recipe)
    return recipes


def default_recipe(recipes_dir: Path | None = None) -> ReplicaRecipeV2:
    """内置默认配方（ catalog 缺失该条目时退化为代码内同形定义）。"""
    fallback = ReplicaRecipeV2(
        recipe_id=DEFAULT_RECIPE_ID,
        name="底部大字",
        description="经典短视频字幕形态：底部居中白字，可见窗比口播各宽 0.1/0.2s，同轨 cut 交接。",
        version="1",
        subtitle=ReplicaSubtitleRecipeV2(
            font_size=42, color="#FFFFFF", position="bottom_center",
            lead_seconds=0.1, tail_seconds=0.2, handoff="cut",
        ),
    )
    for recipe in load_recipes(recipes_dir):
        if recipe.recipe_id == DEFAULT_RECIPE_ID:
            return recipe
    return fallback


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _fmt(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, float):
        return f"{value:g}"
    return str(value)


def _coerce(field: str, raw: str) -> Any:
    if field in {"font_size"}:
        return int(float(raw))
    if field in {"lead_seconds", "tail_seconds"}:
        return float(raw)
    if field == "color":
        return raw.upper() if raw.startswith("#") else raw
    return raw


def _sub_text(parent: ET.Element, tag: str, text: str) -> None:
    element = ET.SubElement(parent, tag)
    element.text = text


def _text_of(element: ET.Element | None) -> str:
    return (element.text or "").strip() if element is not None else ""
