"""Node patch scope report — ADR 0009 决策 2 的执行件.

The author's real question after an edit is not "did it save" but "what did
I just affect?". This module answers it exactly, for the node-patch path:

* AUTHORING fields (prompt / structured_content / parameters / model /
  title) change what the node WILL produce. Nothing structurally consumes
  them — bindings read a node's OUTPUT (ADR 0009 决策 1), so the honest
  answer for a content edit is "no neighbours affected".
* The answer must be COMPUTED, not assumed: the report diffs the patch
  against the node's prior state and names the touched keys. A future patch
  field that IS dependency-bearing is classified through the registry below
  rather than silently inheriting "local".

Never silent: an empty neighbour list is reported as an explicit note the UI
can show ("未动：其余镜头与时间线") — an empty list left unspoken reads as
"the system didn't check".
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

# Patch-schema fields classified by what they can affect. AUTHORING_* fields
# are local by construction (nothing reads them structurally). The registry
# exists so a NEW patch field must be classified here before it can inherit
# "local" — the failure mode is a silent cascade, and this makes it loud.
AUTHORING_PATCH_FIELDS: frozenset[str] = frozenset(
    {
        "generation_prompt",
        "summary_prompt",
        "structured_content",
        "parameters",
        "model_selection_mode",
        "model_ref",
        "title",
    }
)

# Human labels for the content areas a dirty node reports (Chinese: the
# workbench UI speaks it).
_DIRTY_REASON_LABELS: dict[str, str] = {
    "title": "标题",
    "summary_prompt": "摘要",
    "generation_prompt": "生成提示词",
    "parameters": "参数",
    "model_selection_mode": "模型选择",
    "model_ref": "模型选择",
    "structured_content": "结构化内容",
}

# structured_content keys whose meaning the author recognises, for the
# dirty reasons. Unknown keys fall back to the generic label.
_CONTENT_KEY_LABELS: dict[str, str] = {
    "scene_script": "场景脚本",
    "audio_bed": "音频床",
    "dialogue_lines": "台词行",
    "white_model": "白模模式",
    "white_model_report": "白模操作日志",
    "narration": "旁白",
    "script_text": "剧本文本",
}

MAX_EDITED_KEYS = 40


@dataclass(frozen=True, slots=True)
class ScopeReport:
    """What a node patch touched, and what it did NOT."""

    edited_keys: tuple[str, ...] = ()
    content_areas: tuple[str, ...] = ()
    affected_neighbours: tuple[dict[str, str], ...] = ()
    dirty_reasons: tuple[str, ...] = ()
    notes: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "edited_keys": list(self.edited_keys),
            "content_areas": list(self.content_areas),
            "affected_neighbours": [dict(entry) for entry in self.affected_neighbours],
            "dirty_reasons": list(self.dirty_reasons),
            "notes": list(self.notes),
        }


def _diff_values(before: Any, after: Any, prefix: str, out: list[str], depth: int) -> None:
    """Collect the paths that differ between two JSON-ish values."""

    if len(out) >= MAX_EDITED_KEYS:
        return
    if depth > 6:
        # Deeper than this the exact path stops being informative to the
        # author; report the subtree root instead of exploding the list.
        if before != after and prefix not in out:
            out.append(prefix)
        return
    if isinstance(before, dict) and isinstance(after, dict):
        for key in sorted(set(before) | set(after)):
            path = f"{prefix}.{key}" if prefix else str(key)
            if key not in before:
                out.append(f"{path} (新增)")
            elif key not in after:
                out.append(f"{path} (移除)")
            else:
                _diff_values(before[key], after[key], path, out, depth + 1)
        return
    if isinstance(before, list) and isinstance(after, list):
        if before != after:
            out.append(f"{prefix}[] ({len(before)} → {len(after)} 项)")
        return
    if before != after:
        out.append(prefix)


def build_patch_scope_report(
    *,
    node_type: str,
    before_structured: dict[str, Any],
    patch_fields: dict[str, Any],
) -> ScopeReport:
    """Classify a node patch (ADR 0009 决策 1 + 2).

    `patch_fields` is the patch's SET fields only (omitted fields are not
    edits). Returns the exact scope: which keys changed, which content areas
    are now dirty, whether any neighbour is affected, and the note to show.
    """

    unknown_fields = sorted(set(patch_fields) - AUTHORING_PATCH_FIELDS)
    if unknown_fields:
        # A patch field outside the registry cannot silently be "local".
        notes = tuple(
            f"字段 {name} 未在 ADR 0009 范围登记表中分类，需先声明其作用域。"
            for name in unknown_fields
        )
        return ScopeReport(
            edited_keys=(),
            content_areas=(),
            affected_neighbours=(),
            dirty_reasons=(),
            notes=notes,
        )

    edited_keys: list[str] = []
    content_areas: list[str] = []

    if "structured_content" in patch_fields:
        incoming = patch_fields["structured_content"]
        merged: dict[str, Any] = {**before_structured, **(incoming or {})}
        _diff_values(before_structured, merged, "", edited_keys, 0)
        for key in sorted(incoming or {}):
            if (incoming or {}).get(key) != before_structured.get(key):
                content_areas.append(_CONTENT_KEY_LABELS.get(key, key))

    for name in ("generation_prompt", "summary_prompt", "parameters", "title"):
        if name in patch_fields:
            edited_keys.append(name)
            content_areas.append(_DIRTY_REASON_LABELS[name])
    for name in ("model_selection_mode", "model_ref"):
        if name in patch_fields:
            edited_keys.append(name)
            if "模型选择" not in content_areas:
                content_areas.append("模型选择")

    if not edited_keys:
        return ScopeReport(notes=("补丁没有改变任何字段。",))

    reasons = tuple(
        f"{area}有未提交的作者修改" for area in dict.fromkeys(content_areas)
    )
    notes = (
        "本次编辑不影响任何已绑定节点（下游只消费本节点的产物，不读取作者态）。",
        "修改将在下次执行本节点时生效；未执行的作者修改不会波及前后关联节点。",
    )
    return ScopeReport(
        edited_keys=tuple(edited_keys),
        content_areas=tuple(dict.fromkeys(content_areas)),
        affected_neighbours=(),
        dirty_reasons=reasons,
        notes=notes,
    )
