/**
 * ReplicaBlueprintPanel — 拉片复刻工作台（replica 节点的画布面板）。
 *
 * "复刻"半场的操作台：蓝图槽位编辑（人/货/词/风格/声音）→ 锚点事件保留/移除
 * → 一键生成复刻工作流（蓝图 → script 节点，执行走既有工作流引擎）。
 *
 * 与 hypit 的对应：槽位=组件化替换的"槽"；锚点事件=@{词} 锚定的 MVP 形态；
 * 实例化=编译落地。蓝图是本节点的 structured_content（单一真相源），
 * 画布状态经 useApp 的 setAgentCanvasWorkflow 同步。
 */

import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { useApp } from "../../../AppContextValue.ts";
import { agentCanvasApi } from "../../../api/agentCanvasApi.ts";
import type {
  CanvasNodeV2,
  ReplicaAnchorEventV2,
  ReplicaBlueprintContentV2,
  ReplicaSlotV2,
} from "../../../types-v2.ts";
import { ReplicaSourceEditor } from "./ReplicaSourceEditor.tsx";

export interface ReplicaBlueprintPanelProps {
  node: CanvasNodeV2;
  height?: number;
}

type TabKey = "slots" | "anchors" | "shots" | "source";

/** 零模型费直出的前端阶段机（ADR 0010 R3）：idle → starting → polling → 终态。 */
type RenderPhase = "idle" | "starting" | "polling" | "completed" | "failed";

/** 从节点内容解析蓝图；容忍空/半成品内容（新建节点的默认态）。 */
function parseBlueprint(node: CanvasNodeV2): ReplicaBlueprintContentV2 {
  const content = (node.structured_content ?? {}) as Partial<ReplicaBlueprintContentV2>;
  return {
    blueprint_version: "replica-blueprint-v1",
    source_video_asset_id: content.source_video_asset_id ?? "",
    duration_seconds: content.duration_seconds ?? 0,
    aspect: content.aspect ?? "",
    replica_goal: content.replica_goal ?? "",
    whole_piece_reading: content.whole_piece_reading ?? "",
    format_name: content.format_name ?? "short-video",
    slots: content.slots ?? [],
    beats: content.beats ?? [],
    anchor_events: content.anchor_events ?? [],
    shots: content.shots ?? [],
    rhythm_avg_shot_seconds: content.rhythm_avg_shot_seconds ?? 0,
    rhythm_cut_points_seconds: content.rhythm_cut_points_seconds ?? [],
    rhythm_energy_curve: content.rhythm_energy_curve ?? "",
    systems_captions: content.systems_captions ?? "",
    systems_music: content.systems_music ?? "",
    systems_graphics: content.systems_graphics ?? [],
    systems_sfx: content.systems_sfx ?? [],
    constraints: content.constraints ?? [],
    instantiated_script_node_id: content.instantiated_script_node_id ?? null,
  };
}

export function ReplicaBlueprintPanel({ node, height = 380 }: ReplicaBlueprintPanelProps) {
  const blueprint = useMemo(() => parseBlueprint(node), [node]);
  const { setAgentCanvasWorkflow } = useApp();

  const [tab, setTab] = useState<TabKey>("slots");
  const [slots, setSlots] = useState<ReplicaSlotV2[]>(blueprint.slots);
  const [removedAnchors, setRemovedAnchors] = useState<string[]>(
    blueprint.anchor_events.filter((a) => !a.keep).map((a) => a.event_id),
  );
  const [saving, setSaving] = useState(false);
  const [instantiating, setInstantiating] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [scriptText, setScriptText] = useState<string | null>(null);
  const [scriptNodeId, setScriptNodeId] = useState<string | null>(null);

  const hasBlueprint = blueprint.shots.length > 0 || blueprint.beats.length > 0;

  // --- 本地编辑状态与节点内容的同步 -------------------------------------
  // slots/removedAnchors 是本地编辑态；节点内容被外部更新（导入重编译、
  // 协同 patch、刷新）时必须跟上，否则面板显示过期蓝图。用内容签名判断：
  // 内容没变（仅对象引用变了）不重置，避免打字途中被无关渲染清掉编辑。
  const contentSignature = useMemo(
    () => JSON.stringify([blueprint.slots, blueprint.anchor_events]),
    [blueprint.slots, blueprint.anchor_events],
  );
  const syncedSignature = useRef(contentSignature);
  useEffect(() => {
    if (contentSignature === syncedSignature.current) return;
    syncedSignature.current = contentSignature;
    setSlots(blueprint.slots);
    setRemovedAnchors(
      blueprint.anchor_events.filter((a) => !a.keep).map((a) => a.event_id),
    );
  }, [contentSignature, blueprint]);

  // 把当前编辑（槽位替换 + 锚点保留/移除）合并进蓝图——保存/实例化/导出
  // 共用同一个"生效内容"视图。
  const buildContent = useCallback((): ReplicaBlueprintContentV2 => {
    const nextSlots = slots.map((slot) => ({
      ...slot,
      applied: Boolean(slot.replace_with.trim()),
    }));
    return {
      ...blueprint,
      slots: nextSlots,
      anchor_events: blueprint.anchor_events.map((anchor) => ({
        ...anchor,
        keep: !removedAnchors.includes(anchor.event_id),
      })),
      beats: blueprint.beats.map((beat) => ({
        ...beat,
        anchor_event_ids: beat.anchor_event_ids.filter(
          (id) => !removedAnchors.includes(id),
        ),
      })),
    };
  }, [blueprint, removedAnchors, slots]);

  const dirty = useMemo(() => {
    const edited = buildContent();
    return (
      JSON.stringify(edited.slots) !== JSON.stringify(blueprint.slots) ||
      JSON.stringify(edited.anchor_events) !== JSON.stringify(blueprint.anchor_events)
    );
  }, [blueprint, buildContent]);

  const saveBlueprint = useCallback(async () => {
    setSaving(true);
    setError(null);
    setNotice(null);
    try {
      const content = buildContent();
      const response = await agentCanvasApi.patchAgentCanvasNode(
        node.workflow_id,
        node.node_id,
        { structured_content: content as unknown as Record<string, unknown> },
      );
      setAgentCanvasWorkflow(response.value.workflow);
      setNotice("蓝图已保存");
    } catch (err) {
      setError(err instanceof Error ? err.message : "蓝图保存失败");
    } finally {
      setSaving(false);
    }
  }, [buildContent, node, setAgentCanvasWorkflow]);

  const instantiate = useCallback(async () => {
    setInstantiating(true);
    setError(null);
    setNotice(null);
    setScriptText(null);
    setScriptNodeId(null);
    try {
      // 1) 先落盘当前编辑（槽位/锚点），再实例化——单一真相源不含未保存编辑
      const content = buildContent();
      const slotUpdates: Record<string, string> = {};
      for (const slot of content.slots) {
        slotUpdates[slot.kind] = slot.replace_with.trim();
      }
      await agentCanvasApi.patchAgentCanvasNode(
        node.workflow_id,
        node.node_id,
        { structured_content: content as unknown as Record<string, unknown> },
      );

      // 2) 实例化：蓝图 → script 节点（后端经画布节点服务创建）
      const response = await fetch("/api/v1/replica/instantiate", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          workflow_id: node.workflow_id,
          replica_node_id: node.node_id,
          slot_updates: slotUpdates,
        }),
      });
      const body = await response.json().catch(() => null);
      if (response.status !== 200 || !body) {
        const detail = body?.detail;
        throw new Error(
          (typeof detail === "object" && detail?.error) ||
            (typeof detail === "string" && detail) ||
            `实例化失败 (HTTP ${response.status})`,
        );
      }
      setScriptText(body.script_text ?? "");
      setScriptNodeId(body.script_node_id ?? "");
      setNotice(
        `已生成复刻工作流：script 节点 ${body.script_node_id ?? ""}` +
          (body.binding_id ? "（已自动连接到复刻蓝图）" : ""),
      );

      // 3) 画布同步：用服务端权威工作流刷新
      const workflow = await agentCanvasApi.agentCanvasWorkflowWithEtag(node.workflow_id);
      setAgentCanvasWorkflow(workflow.value);
    } catch (err) {
      setError(err instanceof Error ? err.message : "实例化失败");
    } finally {
      setInstantiating(false);
    }
  }, [buildContent, node, setAgentCanvasWorkflow]);

  // --- .adreplica 源码 tab：文档即真相源的前端入口 -----------------------
  const [sourceText, setSourceText] = useState<string>("");
  const [sourceBusy, setSourceBusy] = useState(false);
  const [sourceCopied, setSourceCopied] = useState(false);
  // 双向锚点跳转：源码行内锚 ↔ 锚点列表行
  const [highlightedEventId, setHighlightedEventId] = useState<string | null>(null);
  const [sourceJumpEventId, setSourceJumpEventId] = useState<string | null>(null);

  // --- 零模型费直出（ADR 0010 R3：渲染桥 → 耐久渲染 → 轮询 → 成片预览）----
  // 桥端点把编译时间线写进工作流 final 时间线并复用剪辑域 start_render；
  // 渲染是 detached 的，这里只轮询状态、不持有渲染进程。
  const [renderPhase, setRenderPhase] = useState<RenderPhase>("idle");
  const [renderId, setRenderId] = useState<string | null>(null);
  const [renderProgress, setRenderProgress] = useState<number | null>(null);
  const [renderVideoUrl, setRenderVideoUrl] = useState<string | null>(null);
  const [renderFailure, setRenderFailure] = useState<string | null>(null);
  // 门拒绝的缺失清单（这片子有什么必须生成，不能零模型费直出）
  const [renderBlockers, setRenderBlockers] = useState<string[]>([]);
  // 直出的诚实备注（替换了哪版时间线 / 哪些库素材未计入）
  const [renderNotes, setRenderNotes] = useState<string[]>([]);
  // G5 字幕族配方（.adrecipe 库）：直出时连同配方一起提交——变体之间
  // "看得见的差异"由它提供（否则只有 skill 槽位值不同，字幕样式逐字节相同）
  type RecipeEntry = {
    recipe_id: string;
    name: string;
    description: string;
    subtitle: Record<string, unknown>;
  };
  const [recipes, setRecipes] = useState<RecipeEntry[]>([]);
  const [selectedRecipe, setSelectedRecipe] = useState<Record<string, unknown> | null>(null);
  useEffect(() => {
    // 配方库在**源码 tab 打开时**才拉（直出 UI 所在处）：挂载即拉会在无关
    // 流程的 fetch 调用序列里插队，把"第一次 POST 是这个端点"的观测变浑浊。
    if (tab !== "source" || recipes.length > 0) return;
    let cancelled = false;
    void (async () => {
      try {
        const response = await fetch("/api/v1/replica/blueprint/recipes");
        const body = await response.json().catch(() => null);
        if (cancelled || response.status !== 200 || !body?.success) return;
        const list = Array.isArray(body.recipes) ? (body.recipes as RecipeEntry[]) : [];
        setRecipes(list);
        if (list.length > 0) setSelectedRecipe(list[0] as unknown as Record<string, unknown>);
      } catch {
        // 配方库不可用不影响直出（编译层默认形态）；对可选增强静默是可接受的
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [tab, recipes.length]);

  // 高亮行滚动到可见（jsdom 无 scrollIntoView，需守卫）
  useEffect(() => {
    if (!highlightedEventId || tab !== "anchors") return;
    const row = document.getElementById(`anchor-row-${highlightedEventId}`);
    if (row && typeof row.scrollIntoView === "function") {
      row.scrollIntoView({ block: "center" });
    }
  }, [highlightedEventId, tab]);

  const exportSource = useCallback(async () => {
    setSourceBusy(true);
    setError(null);
    setNotice(null);
    try {
      const response = await fetch("/api/v1/replica/blueprint/export", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ blueprint: buildContent() }),
      });
      const body = await response.json().catch(() => null);
      if (response.status !== 200 || !body) {
        const detail = body?.detail;
        throw new Error(
          (typeof detail === "object" && detail?.error) ||
            (typeof detail === "string" && detail) ||
            `导出失败 (HTTP ${response.status})`,
        );
      }
      setSourceText(body.adreplica ?? "");
      setSourceCopied(false);
      setNotice(body.filename ? `已导出为 .adreplica（建议文件名：${body.filename}）` : "已导出为 .adreplica");
    } catch (err) {
      setError(err instanceof Error ? err.message : "导出失败");
    } finally {
      setSourceBusy(false);
    }
  }, [buildContent]);

  const copySource = useCallback(async () => {
    if (!sourceText) return;
    try {
      await navigator.clipboard.writeText(sourceText);
      setSourceCopied(true);
    } catch {
      setError("复制失败，请在文本框中手动选择复制");
    }
  }, [sourceText]);

  const importSource = useCallback(async () => {
    if (!sourceText.trim()) {
      setError("请先把 .adreplica 文本粘贴到文本框（或先导出）");
      return;
    }
    setSourceBusy(true);
    setError(null);
    setNotice(null);
    try {
      // 1) 文本 → 蓝图（后端 normalize 兜底 + 结构校验）
      const response = await fetch("/api/v1/replica/blueprint/import", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ adreplica: sourceText }),
      });
      const body = await response.json().catch(() => null);
      if (response.status !== 200 || !body) {
        const detail = body?.detail;
        throw new Error(
          (typeof detail === "object" && detail?.error) ||
            (typeof detail === "string" && detail) ||
            `导入失败 (HTTP ${response.status})`,
        );
      }
      const imported = body.blueprint as ReplicaBlueprintContentV2;
      // 2) 本地编辑态切换为导入蓝图
      setSlots(imported.slots);
      setRemovedAnchors(imported.anchor_events.filter((a) => !a.keep).map((a) => a.event_id));
      // 3) 落盘回节点（回写闭环：文档是真相源，节点是投影）
      const patchResponse = await agentCanvasApi.patchAgentCanvasNode(
        node.workflow_id,
        node.node_id,
        { structured_content: imported as unknown as Record<string, unknown> },
      );
      setAgentCanvasWorkflow(patchResponse.value.workflow);
      setNotice("已从 .adreplica 导入并写回蓝图节点");
    } catch (err) {
      setError(err instanceof Error ? err.message : "导入失败");
    } finally {
      setSourceBusy(false);
    }
  }, [node, setAgentCanvasWorkflow, sourceText]);

  // --- 零模型费直出（R3 渲染桥）------------------------------------------
  // 1) 先落盘当前编辑（与"一键生成"同纪律：节点是真相源，不含未保存编辑）；
  // 2) 桥端点内部跑可行性门——非可行即 422 + rejected 缺失清单，不渲染；
  // 3) 渲染是 detached 的：拿到 render_id 后轮询 v2 渲染状态端点。
  const startDirectRender = useCallback(async () => {    setRenderPhase("starting");
    setRenderFailure(null);
    setRenderBlockers([]);
    setRenderNotes([]);
    setRenderVideoUrl(null);
    setRenderProgress(null);
    setError(null);
    setNotice(null);
    try {
      const content = buildContent();
      const patchResponse = await agentCanvasApi.patchAgentCanvasNode(
        node.workflow_id,
        node.node_id,
        { structured_content: content as unknown as Record<string, unknown> },
      );
      setAgentCanvasWorkflow(patchResponse.value.workflow);

      const response = await fetch("/api/v1/replica/blueprint/direct-execute/render", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          workflow_id: node.workflow_id,
          blueprint: content,
          ...(selectedRecipe ? { recipe: selectedRecipe } : {}),
        }),
      });
      const body = await response.json().catch(() => null);
      if (response.status !== 200 || !body) {
        const detail = body?.detail;
        const errorType =
          typeof detail === "object" && detail?.error_type ? String(detail.error_type) : "";
        if (errorType === "direct_execute_not_feasible") {
          setRenderBlockers(
            Array.isArray(detail?.rejected) ? detail.rejected.map((item: unknown) => String(item)) : [],
          );
          setRenderPhase("failed");
          return;
        }
        throw new Error(
          (typeof detail === "object" && detail?.error) ||
            (typeof detail === "string" && detail) ||
            `直出失败 (HTTP ${response.status})`,
        );
      }

      const notes: string[] = [];
      if (typeof body.previous_timeline_version === "number" && body.previous_timeline_version > 0) {
        notes.push(
          `已替换工作流此前的 final-composition 时间线（版本 ${body.previous_timeline_version} → ${body.timeline_version}）`,
        );
      }
      if (Array.isArray(body.dropped_unresolved_clip_ids) && body.dropped_unresolved_clip_ids.length > 0) {
        notes.push(
          `库素材未解析，未计入本次直出：${body.dropped_unresolved_clip_ids.join("、")}`,
        );
      }
      setRenderNotes(notes);
      setRenderId(String(body.render_id ?? ""));
      setRenderPhase("polling");
    } catch (err) {
      setRenderFailure(err instanceof Error ? err.message : "直出失败");
      setRenderPhase("failed");
    }
  }, [buildContent, node, setAgentCanvasWorkflow, selectedRecipe]);
  // 轮询渲染状态（组件卸载自动停；超过 ~5 分钟未终态则明确失败，不无限轮）
  useEffect(() => {
    if (renderPhase !== "polling" || !renderId) return;
    let cancelled = false;
    let attempts = 0;
    const tick = async () => {
      attempts += 1;
      try {
        const response = await fetch(
          `/api/v2/workflows/${node.workflow_id}/final-composition/renders/${renderId}`,
        );
        const body = await response.json().catch(() => null);
        if (cancelled) return;
        if (response.status !== 200 || !body) {
          setRenderFailure(`渲染状态查询失败 (HTTP ${response.status})`);
          setRenderPhase("failed");
          return;
        }
        if (typeof body.progress_percent === "number") {
          setRenderProgress(body.progress_percent);
        }
        if (body.status === "completed") {
          setRenderVideoUrl(typeof body.output_url === "string" ? body.output_url : null);
          setRenderPhase("completed");
        } else if (body.status === "failed") {
          setRenderFailure(body.error_message || body.error_code || "渲染失败");
          setRenderPhase("failed");
        } else if (body.status === "cancelled") {
          setRenderFailure("渲染已取消");
          setRenderPhase("failed");
        } else if (attempts >= 150) {
          setRenderFailure("渲染轮询超时——请到工作流的 final-composition 面板查看渲染状态");
          setRenderPhase("failed");
        }
      } catch (err) {
        if (cancelled) return;
        setRenderFailure(err instanceof Error ? err.message : "渲染状态查询失败");
        setRenderPhase("failed");
      }
    };
    void tick();
    const timer = window.setInterval(() => void tick(), 2000);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [renderPhase, renderId, node.workflow_id]);

  if (!hasBlueprint) {
    return (
      <div style={{ padding: 10, color: "#888", fontSize: 11, fontFamily: "monospace" }}>
        <div style={{ marginBottom: 8 }}>空复刻蓝图。</div>
        <div style={{ color: "#555", fontSize: 10, lineHeight: 1.6 }}>
          在 3D Previs 节点的 Reference 页上传参考视频，点击「🎬 拉片复刻」，
          拆解完成后选择「创建复刻蓝图」，即可在此编辑槽位并生成复刻工作流。
        </div>
      </div>
    );
  }

  const tabs: { key: TabKey; label: string }[] = [
    { key: "slots", label: "槽位替换" },
    { key: "anchors", label: `锚点事件(${blueprint.anchor_events.length})` },
    { key: "shots", label: `镜头表(${blueprint.shots.length})` },
    { key: "source", label: "源码 .adreplica" },
  ];

  const styleSlotIndex = slots.findIndex((slot) => slot.kind === "style");

  return (
    <div
      style={{
        padding: 10,
        overflow: "auto",
        height: "100%",
        color: "#ccc",
        fontSize: 11,
        fontFamily: "monospace",
      }}
    >
      <div style={{ display: "flex", gap: 2, marginBottom: 8 }}>
        {tabs.map((entry) => (
          <button
            key={entry.key}
            onClick={() => setTab(entry.key)}
            style={{
              padding: "3px 10px",
              border: "none",
              borderRadius: 3,
              background: tab === entry.key ? "#3a3a6a" : "transparent",
              color: tab === entry.key ? "#fff" : "#888",
              cursor: "pointer",
              fontSize: 11,
              fontFamily: "monospace",
            }}
          >
            {entry.label}
          </button>
        ))}
      </div>

      {error && (
        <div
          style={{
            background: "#3a1a1a",
            border: "1px solid #5a2a2a",
            borderRadius: 4,
            padding: "6px 10px",
            color: "#f88",
            marginBottom: 8,
            fontSize: 10,
          }}
        >
          ⚠ {error}
        </div>
      )}
      {notice && (
        <div
          style={{
            background: "#1a2a1a",
            border: "1px solid #2a4a2a",
            borderRadius: 4,
            padding: "6px 10px",
            color: "#4f4",
            marginBottom: 8,
            fontSize: 10,
          }}
        >
          ✓ {notice}
        </div>
      )}

      {tab === "slots" && (
        <div>
          <div style={{ color: "#888", fontSize: 10, marginBottom: 6 }}>
            槽位 = 复刻时要替换的成分（留空 = 保留原片值）
          </div>
          {slots.map((slot, index) => (
            <div key={slot.kind} style={{ marginBottom: 8 }}>
              <div style={{ color: "#fc8", marginBottom: 3 }}>
                【{slot.label}】
                {slot.source_value ? (
                  <span style={{ color: "#666" }}> 原片值：{slot.source_value}</span>
                ) : null}
              </div>
              <input
                value={slot.replace_with}
                onChange={(event) => {
                  const next = [...slots];
                  next[index] = { ...slot, replace_with: event.target.value };
                  setSlots(next);
                }}
                placeholder={
                  slot.kind === "style"
                    ? "风格 skill_id（如 gentle-everyday-vlog）"
                    : slot.kind === "character"
                      ? "角色资产 ID 或描述"
                      : slot.kind === "product"
                        ? "商品资产 ID 或描述"
                        : "替换值（留空保留原片）"
                }
                style={{
                  width: "100%",
                  background: "#16162a",
                  border: "1px solid #2a2a4a",
                  borderRadius: 3,
                  color: "#ccc",
                  fontSize: 10,
                  fontFamily: "monospace",
                  padding: "4px 6px",
                }}
              />
              {slot.kind === "style" && index === styleSlotIndex && (
                <StyleVariantPicker
                  blueprint={buildContent()}
                  onApply={(skillId) => {
                    const next = [...slots];
                    next[styleSlotIndex] = {
                      ...slot,
                      replace_with: skillId,
                    };
                    setSlots(next);
                  }}
                />
              )}
            </div>
          ))}
        </div>
      )}

      {tab === "anchors" && (
        <div>
          <div style={{ color: "#888", fontSize: 10, marginBottom: 6 }}>
            锚点事件 = 挂在结构段落上的 B-roll/字幕/音效（取消勾选 = 复刻时移除）
          </div>
          {blueprint.beats.map((beat) => (
            <div key={beat.beat_id} style={{ marginBottom: 8 }}>
              <div style={{ color: "#8f8", marginBottom: 3 }}>
                [{beat.start_seconds.toFixed(1)}–{beat.end_seconds.toFixed(1)}s] {beat.role}
              </div>
              {beat.words && beat.words.length > 0 && (
                <div
                  style={{
                    marginBottom: 4,
                    padding: "3px 6px",
                    background: "#141428",
                    border: "1px solid #2a2a4a",
                    borderRadius: 3,
                    fontSize: 9,
                    lineHeight: 1.8,
                  }}
                  title="词级转录词流（hypit 时间脊柱）：词锚解析与词级字幕的时间基准"
                >
                  <span style={{ color: "#666" }}>词流 {beat.words.length} 词：</span>{" "}
                  {beat.words.map((word, wordIndex) => (
                    <span
                      key={`${beat.beat_id}_w${wordIndex}`}
                      style={{ color: "#9c9", marginRight: 6, whiteSpace: "nowrap" }}
                    >
                      {word.text}
                      <span style={{ color: "#556" }}>
                        （{word.start_seconds.toFixed(1)}–{word.end_seconds.toFixed(1)}s）
                      </span>
                    </span>
                  ))}
                </div>
              )}
              {beat.anchor_event_ids.map((eventId) => {
                const anchor = blueprint.anchor_events.find((a) => a.event_id === eventId);
                if (!anchor) return null;
                const highlighted = highlightedEventId === eventId;
                return (
                  <label
                    key={eventId}
                    id={`anchor-row-${eventId}`}
                    style={{
                      display: "flex",
                      gap: 6,
                      alignItems: "flex-start",
                      marginBottom: 3,
                      background: highlighted ? "#2a3a2a" : "transparent",
                      borderRadius: 3,
                      padding: highlighted ? "2px 4px" : 0,
                    }}
                  >
                    <input
                      type="checkbox"
                      checked={!removedAnchors.includes(eventId)}
                      onChange={(event) => {
                        setRemovedAnchors((current) =>
                          event.target.checked
                            ? current.filter((id) => id !== eventId)
                            : [...current, eventId],
                        );
                      }}
                    />
                    <span>
                      <span style={{ color: "#8af" }}>@{eventId}</span>{" "}
                      <span style={{ color: "#ca8" }}>[{anchor.kind}]</span>{" "}
                      触发「{anchor.trigger || "—"}」：{anchor.hint || "—"}
                      {anchor.word && (
                        <span style={{ color: "#8f8" }}>
                          {" "}
                          · 词锚「{anchor.word}」
                          {anchor.word_start_seconds
                            ? `（${anchor.word_start_seconds.toFixed(1)}–${(anchor.word_end_seconds ?? 0).toFixed(1)}s）`
                            : "（时间待转录解析）"}
                        </span>
                      )}
                      <button
                        onClick={() => {
                          setSourceJumpEventId(eventId);
                          setTab("source");
                        }}
                        title="跳到源码里的行内锚"
                        style={{
                          marginLeft: 6,
                          background: "transparent",
                          border: "1px solid #2a2a4a",
                          color: "#889",
                          padding: "0 6px",
                          borderRadius: 3,
                          cursor: "pointer",
                          fontSize: 9,
                        }}
                      >
                        📍 源码定位
                      </button>
                    </span>
                  </label>
                );
              })}
            </div>
          ))}
        </div>
      )}

      {tab === "shots" && (
        <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 10 }}>
          <thead>
            <tr style={{ color: "#666", textAlign: "left" }}>
              <th style={{ padding: "2px 4px" }}>#</th>
              <th style={{ padding: "2px 4px" }}>时间</th>
              <th style={{ padding: "2px 4px" }}>景别/运镜</th>
              <th style={{ padding: "2px 4px" }}>内容</th>
              <th style={{ padding: "2px 4px" }}>屏上文字</th>
              <th style={{ padding: "2px 4px" }}>复刻提示</th>
            </tr>
          </thead>
          <tbody>
            {blueprint.shots.map((shot) => (
              <tr key={shot.index} style={{ borderTop: "1px solid #2a2a4a" }}>
                <td style={{ padding: "2px 4px", color: "#8af" }}>{shot.index}</td>
                <td style={{ padding: "2px 4px", whiteSpace: "nowrap" }}>
                  {shot.start_seconds.toFixed(1)}–{shot.end_seconds.toFixed(1)}s
                </td>
                <td style={{ padding: "2px 4px" }}>
                  {shot.shot_size}/{shot.camera_motion}
                </td>
                <td style={{ padding: "2px 4px" }}>{shot.subject_action || "—"}</td>
                <td style={{ padding: "2px 4px", color: "#fc8" }}>
                  {shot.on_screen_text || "—"}
                </td>
                <td style={{ padding: "2px 4px" }}>{shot.recreate_hint || "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      {tab === "source" && (
        <div>
          <div
            style={{
              border: "1px solid #3a3a5a",
              borderRadius: 4,
              padding: 8,
              marginBottom: 10,
            }}
          >
            <div style={{ color: "#9df", fontSize: 10, marginBottom: 6, lineHeight: 1.6 }}>
              ⚡ 零模型费直出（ADR 0010 R3）：纯字幕/音效/配乐/剪辑环节直接出片，
              不调生成模型。有动作镜头、台词或已应用主体替换的片子会被可行性门
              拒绝（缺什么会列出来）。直出会替换该工作流当前的 final-composition
              时间线——面板关闭后渲染仍在工作流内继续。
            </div>
            {recipes.length > 0 && (
              <label style={{ display: "flex", alignItems: "center", gap: 6, marginBottom: 6, fontSize: 10 }}>
                <span style={{ color: "#8af" }}>🎨 字幕配方</span>
                <select
                  value={selectedRecipe ? String(selectedRecipe.recipe_id ?? "") : ""}
                  onChange={(event) => {
                    const picked = recipes.find((r) => r.recipe_id === event.target.value);
                    setSelectedRecipe(picked ? (picked as unknown as Record<string, unknown>) : null);
                  }}
                  title={
                    selectedRecipe
                      ? String(selectedRecipe.description ?? "")
                      : "字幕族配方（.adrecipe）：字体/颜色/位置/可见窗/交接"
                  }
                  style={{
                    background: "#16162a",
                    border: "1px solid #2a2a4a",
                    borderRadius: 3,
                    color: "#ccc",
                    fontSize: 10,
                    fontFamily: "monospace",
                    padding: "3px 6px",
                  }}
                >
                  {recipes.map((recipe) => (
                    <option key={recipe.recipe_id} value={recipe.recipe_id}>
                      {recipe.name || recipe.recipe_id}
                    </option>
                  ))}
                </select>
              </label>
            )}
            <button
              onClick={() => void startDirectRender()}
              disabled={renderPhase === "starting" || renderPhase === "polling"}
              style={{
                background:
                  renderPhase === "starting" || renderPhase === "polling" ? "#2a2a4a" : "#3a5a8a",
                border: "none",
                color: renderPhase === "starting" || renderPhase === "polling" ? "#666" : "#fff",
                padding: "4px 12px",
                borderRadius: 3,
                cursor:
                  renderPhase === "starting" || renderPhase === "polling" ? "default" : "pointer",
                fontSize: 10,
              }}
            >
              {renderPhase === "starting"
                ? "⏳ 发起中…"
                : renderPhase === "polling"
                  ? "⏳ 渲染中…"
                  : "⚡ 零模型费直出"}
            </button>
            {renderPhase === "polling" && (
              <div style={{ marginTop: 6, fontSize: 10, color: "#8cf" }}>
                渲染中…{" "}
                {renderProgress !== null ? `${Math.round(renderProgress)}%` : "已进入渲染队列"}
              </div>
            )}
            {renderPhase === "completed" && (
              <div style={{ marginTop: 6 }}>
                <div style={{ fontSize: 10, color: "#4f4", marginBottom: 4 }}>
                  ✓ 成片已产出（工作流 final-composition 候选）
                </div>
                {renderVideoUrl ? (
                  <video
                    src={renderVideoUrl}
                    controls
                    style={{
                      width: "100%",
                      maxWidth: 240,
                      borderRadius: 3,
                      background: "#000",
                    }}
                  />
                ) : (
                  <div style={{ fontSize: 10, color: "#888" }}>
                    （预览地址未返回——到工作流的 final-composition 面板查看候选）
                  </div>
                )}
              </div>
            )}
            {renderPhase === "failed" && (
              <div style={{ marginTop: 6, fontSize: 10, color: "#f88", lineHeight: 1.6 }}>
                {renderBlockers.length > 0 ? (
                  <>
                    <div>这片子有必须生成的环节，不能零模型费直出：</div>
                    <ul style={{ margin: "2px 0", paddingLeft: 16 }}>
                      {renderBlockers.map((item) => (
                        <li key={item}>{item}</li>
                      ))}
                    </ul>
                    <div style={{ color: "#888" }}>
                      可改用「⚡ 一键生成复刻工作流」走完整生成流。
                    </div>
                  </>
                ) : (
                  <div>直出失败：{renderFailure ?? "未知错误"}</div>
                )}
              </div>
            )}
            {renderNotes.length > 0 && (
              <div style={{ marginTop: 6, fontSize: 9, color: "#888", lineHeight: 1.6 }}>
                {renderNotes.map((note) => (
                  <div key={note}>· {note}</div>
                ))}
              </div>
            )}
          </div>
          <div style={{ color: "#888", fontSize: 10, marginBottom: 6, lineHeight: 1.6 }}>
            .adreplica = 蓝图的标记语言形态（hypit "文件即真相源"）：导出后可交给
            Agent 或自己手改，再粘贴回来重编译——改几行 = 换槽位/增删锚点。
          </div>
          <div style={{ display: "flex", gap: 6, marginBottom: 6 }}>
            <button
              onClick={() => void exportSource()}
              disabled={sourceBusy}
              style={{
                background: sourceBusy ? "#2a2a4a" : "#3a3a6a",
                border: "none",
                color: sourceBusy ? "#666" : "#fff",
                padding: "3px 10px",
                borderRadius: 3,
                cursor: sourceBusy ? "default" : "pointer",
                fontSize: 10,
              }}
            >
              {sourceBusy ? "⏳ 处理中…" : "📄 导出当前蓝图"}
            </button>
            <button
              onClick={() => void copySource()}
              disabled={!sourceText}
              style={{
                background: sourceCopied ? "#2a4a2a" : "#3a3a6a",
                border: "none",
                color: sourceText ? (sourceCopied ? "#4f4" : "#fff") : "#666",
                padding: "3px 10px",
                borderRadius: 3,
                cursor: sourceText ? "pointer" : "default",
                fontSize: 10,
              }}
            >
              {sourceCopied ? "✓ 已复制" : "📋 复制"}
            </button>
            <button
              onClick={() => void importSource()}
              disabled={sourceBusy}
              style={{
                background: sourceBusy ? "#2a2a4a" : "#3a5a8a",
                border: "none",
                color: sourceBusy ? "#666" : "#fff",
                padding: "3px 10px",
                borderRadius: 3,
                cursor: sourceBusy ? "default" : "pointer",
                fontSize: 10,
              }}
            >
              📥 导入重编译
            </button>
          </div>
          <ReplicaSourceEditor
            value={sourceText}
            onChange={setSourceText}
            onAnchorClick={(eventId) => {
              setHighlightedEventId(eventId);
              setTab("anchors");
            }}
            jumpToEventId={sourceJumpEventId}
            onJumpHandled={() => setSourceJumpEventId(null)}
          />
        </div>
      )}

      <div style={{ display: "flex", gap: 6, margin: "10px 0" }}>
        <button
          onClick={() => void saveBlueprint()}
          disabled={saving || instantiating}
          title={dirty ? "有未保存的槽位/锚点修改" : ""}
          style={{
            background: saving ? "#2a2a4a" : dirty ? "#4a4a2a" : "#3a3a6a",
            border: dirty && !saving ? "1px solid #8a8a3a" : "none",
            color: saving ? "#666" : "#fff",
            padding: "5px 12px",
            borderRadius: 3,
            cursor: saving ? "default" : "pointer",
            fontSize: 10,
          }}
        >
          {saving ? "⏳ 保存中…" : dirty ? "💾 保存蓝图 ●" : "💾 保存蓝图"}
        </button>
        <button
          onClick={() => void instantiate()}
          disabled={instantiating || saving}
          style={{
            background: instantiating ? "#2a2a4a" : "#3a5a8a",
            border: "none",
            color: instantiating ? "#666" : "#fff",
            padding: "5px 12px",
            borderRadius: 3,
            cursor: instantiating ? "default" : "pointer",
            fontSize: 10,
          }}
        >
          {instantiating ? "⏳ 生成中…" : "⚡ 一键生成复刻工作流"}
        </button>
      </div>

      <div style={{ color: "#555", fontSize: 9, lineHeight: 1.6 }}>
        生成 = 蓝图编译为 script 节点（复刻脚本）+ 画布自动刷新；执行仍走既有
        工作流引擎。原片结构不变，替换只影响槽位与锚点。
      </div>

      {scriptText && (
        <div style={{ marginTop: 10 }}>
          <div style={{ color: "#888", fontSize: 10, marginBottom: 4 }}>
            复刻脚本 {scriptNodeId ? `· 节点 ${scriptNodeId}` : ""}
          </div>
          <pre
            style={{
              margin: 0,
              padding: 8,
              background: "#101018",
              borderRadius: 3,
              maxHeight: Math.max(120, height - 220),
              overflow: "auto",
              color: "#8f8",
              fontSize: 10,
              whiteSpace: "pre-wrap",
              wordBreak: "break-word",
            }}
          >
            {scriptText}
          </pre>
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// StyleVariantPicker — Jev 式风格导演的前端入口（确定性打分，可复现）
// ---------------------------------------------------------------------------

interface StyleVariantCandidate {
  variant_id: string;
  skill_ids: string[];
  names: string[];
  score: number;
  rationale: string;
  mixable_applied: boolean;
}

function StyleVariantPicker({
  blueprint,
  onApply,
}: {
  blueprint: ReplicaBlueprintContentV2;
  onApply: (skillId: string) => void;
}) {
  const [open, setOpen] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [variants, setVariants] = useState<StyleVariantCandidate[]>([]);

  const loadVariants = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const response = await fetch("/api/v1/replica/blueprint/style-variants", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ blueprint, n: 5 }),
      });
      const body = await response.json().catch(() => null);
      if (response.status !== 200 || !body) {
        const detail = body?.detail;
        throw new Error(
          (typeof detail === "object" && detail?.error) ||
            (typeof detail === "string" && detail) ||
            `风格推荐失败 (HTTP ${response.status})`,
        );
      }
      setVariants(body.variants ?? []);
      setOpen(true);
    } catch (err) {
      setError(err instanceof Error ? err.message : "风格推荐失败");
    } finally {
      setLoading(false);
    }
  }, [blueprint]);

  return (
    <div style={{ marginTop: 4 }}>
      <button
        onClick={() => (open ? setOpen(false) : void loadVariants())}
        disabled={loading}
        style={{
          background: loading ? "#2a2a4a" : "#3a3a6a",
          border: "none",
          color: loading ? "#666" : "#fff",
          padding: "2px 8px",
          borderRadius: 3,
          cursor: loading ? "default" : "pointer",
          fontSize: 9,
        }}
      >
        {loading ? "⏳ 打分中…" : open ? "🎲 收起风格推荐" : "🎲 风格推荐"}
      </button>
      {error && (
        <div style={{ color: "#f88", fontSize: 9, marginTop: 3 }}>⚠ {error}</div>
      )}
      {open && variants.length > 0 && (
        <div style={{ marginTop: 4 }}>
          {variants.map((variant) => (
            <div
              key={variant.variant_id}
              style={{
                display: "flex",
                gap: 6,
                alignItems: "center",
                marginBottom: 3,
                fontSize: 9,
              }}
            >
              <span style={{ color: "#8af", minWidth: 34 }}>
                {variant.score.toFixed(2)}
              </span>
              <span style={{ flex: 1, color: "#ccc" }}>
                {variant.names.join(" × ")}
                <span style={{ color: "#666" }}> · {variant.rationale}</span>
              </span>
              <button
                onClick={() => variant.mixable_applied && onApply(variant.skill_ids[0])}
                disabled={!variant.mixable_applied}
                title={variant.mixable_applied ? "" : "多风格并行激活暂未支持"}
                style={{
                  background: variant.mixable_applied ? "#3a5a3a" : "#2a2a4a",
                  border: "none",
                  color: variant.mixable_applied ? "#fff" : "#666",
                  padding: "1px 8px",
                  borderRadius: 3,
                  cursor: variant.mixable_applied ? "pointer" : "default",
                  fontSize: 9,
                }}
              >
                应用
              </button>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
