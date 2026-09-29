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
import {
  clearReplicaRender,
  readReplicaRender,
  writeReplicaRender,
} from "./replicaRenderStore.ts";

import { useApp } from "../../../AppContextValue.ts";
import { agentCanvasApi } from "../../../api/agentCanvasApi.ts";
import { finalRenderCancelPath, finalRenderStatePath } from "../../../api/finalRenderPaths.ts";
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

/**
 * E5: 后端错误 → 可行动的逐条说明（替代本文件 7 处内联提取）。
 *
 * 覆盖三种载荷：
 * - FastAPI 422 校验数组 `[{loc,msg,type}]`——逐条展开（"loc: msg"）；
 * - 对象 detail `{code,message,drifts|rejected,…}`——message + 每条 drift/
 *   rejected + 具名 code（结构漂移这类错误因此逐条可行动）；
 * - 字符串 detail——原样返回（后端已写好的可读文案）。
 */
export function describeReplicaError(status: number, detail: unknown): string[] {
  const fallback = `请求失败 (HTTP ${status})`;
  if (Array.isArray(detail)) {
    const items = detail.map((entry) => {
      if (entry && typeof entry === "object") {
        const record = entry as Record<string, unknown>;
        const loc = Array.isArray(record.loc) ? record.loc.join(".") : "";
        const message = String(record.msg ?? record.message ?? JSON.stringify(record));
        return loc ? `${loc}: ${message}` : message;
      }
      return String(entry);
    });
    return items.length > 0 ? items : [fallback];
  }
  if (detail && typeof detail === "object") {
    const record = detail as Record<string, unknown>;
    const lines: string[] = [];
    const message =
      typeof record.message === "string"
        ? record.message
        : typeof record.error === "string"
          ? record.error
          : "";
    if (message) lines.push(message);
    for (const key of ["drifts", "rejected"] as const) {
      if (Array.isArray(record[key])) {
        for (const entry of record[key]) {
          lines.push(typeof entry === "string" ? entry : JSON.stringify(entry));
        }
      }
    }
    const code =
      typeof record.code === "string"
        ? record.code
        : typeof record.error_type === "string"
          ? record.error_type
          : "";
    if (code && !lines.some((line) => line.includes(code))) lines.push(`（${code}）`);
    return lines.length > 0 ? lines : [fallback];
  }
  if (typeof detail === "string" && detail.trim()) return [detail];
  return [fallback];
}

export function ReplicaBlueprintPanel({ node, height = 380 }: ReplicaBlueprintPanelProps) {
  const blueprint = useMemo(() => parseBlueprint(node), [node]);
  const { setAgentCanvasWorkflow } = useApp();

  const [tab, setTab] = useState<TabKey>("slots");
  // 一键复刻成片（2026-09-29 简约好用分支）：选好槽位 → 一个按钮 → 每镜一个
  // video 节点 + 一次 run。script 节点 / 蓝图词汇 / instantiate 都是内部实现。
  const [filmBusy, setFilmBusy] = useState(false);
  const [filmError, setFilmError] = useState<string | null>(null);
  const [filmShots, setFilmShots] = useState<Array<{ node_id: string; title: string }>>([]);
  const [shotStatus, setShotStatus] = useState<Record<string, string>>({});
  // 概念断奶（2026-09-29）：锚点/镜头表/源码是高级入口，默认收起——
  // 作者默认只见"导演台 + 槽位替换（含一键成片）"。
  const [showAdvanced, setShowAdvanced] = useState(false);

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
        // E5: 逐条展开（422 数组 / {code,message,drifts} / 字符串）——每条都能指向下一步
        throw new Error(describeReplicaError(response.status, body?.detail).join("；"));
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
  // D7: seconds elapsed in the in-flight render (starting→polling), for the "正在渲染 N 秒" line.
  const [renderElapsed, setRenderElapsed] = useState(0);
  // 门拒绝的缺失清单（这片子有什么必须生成，不能零模型费直出）
  const [renderBlockers, setRenderBlockers] = useState<string[]>([]);
  // E5: 其余失败的逐条说明（422 校验数组 / 结构漂移 drifts / 具名错误）
  const [renderErrorItems, setRenderErrorItems] = useState<string[]>([]);
  // 直出的诚实备注（替换了哪版时间线 / 哪些库素材未计入）
  const [renderNotes, setRenderNotes] = useState<string[]>([]);
  // P4 pace 预检告警（台词预估时长超窗：删词 or 加窗，合成前说）
  const [renderPaceWarnings, setRenderPaceWarnings] = useState<
    Array<{
      beat_id: string;
      text: string;
      estimated_seconds: number;
      window_seconds: number;
      ratio: number | null;
    }>
  >([]);
  // D2: 未解析库素材的**可行动清单**（后端直出响应已带 unresolved_assets——
  // clip/intent/时长；此前只拼成一句 note，用户无法补齐，BGM 被静默剥掉）
  const [renderUnresolved, setRenderUnresolved] = useState<
    Array<{
      clip_id: string;
      track_id: string;
      intent: string;
      library_hint: string | string[];
      duration_seconds: number;
    }>
  >([]);
  // D2: 人工补齐（resolve-library 的产物）：clip → 真实 asset/version，随下一次直出提交
  const [libraryResolutions, setLibraryResolutions] = useState<
    Array<{ clip_id: string; asset_id: string; version_id: string }>
  >([]);
  // D2: 哪条未解析素材正在选素材（行内补选器）
  const [fillingClipId, setFillingClipId] = useState<string | null>(null);
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
  // E8: 配方库拉取失败的可见降级（§4）——此前空 catch 静默吞掉：用户以为
  // 选中了配方，实际成片是默认字幕形态。意图保留（可选增强不绊倒直出），
  // 但失败必须看得见、可重试。
  const [recipeCatalogError, setRecipeCatalogError] = useState<string | null>(null);
  const [recipeCatalogAttempt, setRecipeCatalogAttempt] = useState(0);
  useEffect(() => {
    // 配方库在**源码 tab 打开时**才拉（直出 UI 所在处）：挂载即拉会在无关
    // 流程的 fetch 调用序列里插队，把"第一次 POST 是这个端点"的观测变浑浊。
    if (tab !== "source" || recipes.length > 0) return;
    let cancelled = false;
    void (async () => {
      try {
        const response = await fetch("/api/v1/replica/blueprint/recipes");
        const body = await response.json().catch(() => null);
        if (cancelled) return;
        if (response.status !== 200 || !body?.success) {
          setRecipeCatalogError(
            `配方库不可用 (HTTP ${response.status})，已用默认字幕形态直出`,
          );
          return;
        }
        const list = Array.isArray(body.recipes) ? (body.recipes as RecipeEntry[]) : [];
        setRecipes(list);
        setRecipeCatalogError(null);
        if (list.length > 0) setSelectedRecipe(list[0] as unknown as Record<string, unknown>);
      } catch (err) {
        if (cancelled) return;
        setRecipeCatalogError(
          `配方库不可用（${err instanceof Error ? err.message : "网络错误"}），已用默认字幕形态直出`,
        );
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [tab, recipes.length, recipeCatalogAttempt]);

  // E2: .adrecipe 配方文档的导出/导入（配方家族的"文件即真相源"）——
  // 与蓝图 .adreplica 同纪律：改写用例可存 before/after，粘贴回来即换样式。
  const [recipeText, setRecipeText] = useState("");
  const [recipeBusy, setRecipeBusy] = useState(false);

  const exportRecipe = useCallback(async () => {
    if (!selectedRecipe) {
      setError("先选一个字幕配方（或导入一个）再导出");
      return;
    }
    setRecipeBusy(true);
    setError(null);
    setNotice(null);
    try {
      const response = await fetch("/api/v1/replica/blueprint/recipe/export", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ recipe: selectedRecipe }),
      });
      const body = await response.json().catch(() => null);
      if (response.status !== 200 || !body) {
        // E5: 逐条展开（422 数组 / {code,message,drifts} / 字符串）——每条都能指向下一步
        throw new Error(describeReplicaError(response.status, body?.detail).join("；"));
      }
      setRecipeText(body.adrecipe ?? "");
      setNotice(
        `已导出配方 .adrecipe（${String(selectedRecipe.name ?? selectedRecipe.recipe_id ?? "")}）`,
      );
    } catch (err) {
      setError(err instanceof Error ? err.message : "配方导出失败");
    } finally {
      setRecipeBusy(false);
    }
  }, [selectedRecipe]);

  const importRecipe = useCallback(async () => {
    if (!recipeText.trim()) {
      setError("请先把 .adrecipe 配方文本粘贴到文本框（或先导出一个再改）");
      return;
    }
    setRecipeBusy(true);
    setError(null);
    setNotice(null);
    try {
      const response = await fetch("/api/v1/replica/blueprint/recipe/import", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ adrecipe: recipeText }),
      });
      const body = await response.json().catch(() => null);
      if (response.status !== 200 || !body) {
        // E5: 逐条展开（422 数组 / {code,message,drifts} / 字符串）——每条都能指向下一步
        throw new Error(describeReplicaError(response.status, body?.detail).join("；"));
      }
      // 导入即选为直出配方——改完的样式下一次直出生效
      setSelectedRecipe(body.recipe as Record<string, unknown>);
      setNotice("配方已导入并选为本次直出的字幕配方");
    } catch (err) {
      setError(err instanceof Error ? err.message : "配方导入失败");
    } finally {
      setRecipeBusy(false);
    }
  }, [recipeText]);

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
        // E5: 逐条展开（422 数组 / {code,message,drifts} / 字符串）——每条都能指向下一步
        throw new Error(describeReplicaError(response.status, body?.detail).join("；"));
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
        // E5: 逐条展开（422 数组 / {code,message,drifts} / 字符串）——每条都能指向下一步
        throw new Error(describeReplicaError(response.status, body?.detail).join("；"));
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
  // 一键复刻成片：当前槽位 → 后端编排（每镜一个 video 节点 + 一次 run）→
  // 逐镜轮询直到终态。作者只按一个按钮，其余都是内部实现。
  const generateFilm = useCallback(async () => {
    setFilmBusy(true);
    setFilmError(null);
    try {
      const slotUpdates: Record<string, string> = {};
      for (const slot of slots) slotUpdates[slot.kind] = slot.replace_with;
      const response = await fetch("/api/v1/replica/generate-film", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          workflow_id: node.workflow_id,
          replica_node_id: node.node_id,
          slot_updates: slotUpdates,
        }),
      });
      const body = (await response.json().catch(() => null)) as {
        success?: boolean;
        shots?: Array<{ node_id: string; title: string }>;
        detail?: { error?: string } | string;
      } | null;
      if (!response.ok || !body?.success) {
        const detail = body?.detail;
        const message = typeof detail === "string" ? detail : detail?.error;
        throw new Error(message || `生成失败 (HTTP ${response.status})`);
      }
      const shots = body.shots ?? [];
      setFilmShots(shots);
      setShotStatus(Object.fromEntries(shots.map((shot) => [shot.node_id, "排队中"])));
      // 逐镜轮询直到终态（4s 一拍；video 生成通常 1–3 分钟/镜）
      const deadline = Date.now() + 30 * 60 * 1000;
      while (Date.now() < deadline) {
        await new Promise((resolve) => setTimeout(resolve, 4000));
        const statuses = await Promise.all(
          shots.map(async (shot) => {
            try {
              const res = await fetch(
                `/api/v2/workflows/${node.workflow_id}/nodes/${shot.node_id}`,
              );
              const data = (await res.json()) as { status?: string };
              return [shot.node_id, data.status ?? "unknown"] as const;
            } catch {
              return [shot.node_id, "查询失败"] as const;
            }
          }),
        );
        setShotStatus(Object.fromEntries(statuses));
        if (statuses.every(([, status]) => status === "ready" || status === "failed")) break;
      }
      // S8：镜头齐了 → 铺到时间线（合成）；v2 渲染栈对 canvas 工作流不可达
      // （2026-09-29 实证的架构缺口），失败如实带码上屏，不假装成片。
      const readyIds = shots
        .filter((shot) => (shotStatus[shot.node_id] ?? "") === "ready")
        .map((shot) => shot.node_id);
      if (readyIds.length > 0) {
        const asm = await fetch("/api/v1/creation/assemble-film", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ workflow_id: node.workflow_id, node_ids: readyIds }),
        });
        const asmBody = (await asm.json().catch(() => null)) as {
          clip_count?: number;
          render_id?: string;
          error?: string;
        } | null;
        if (asmBody?.render_id) {
          setShotStatus((prev) => ({ ...prev, __film: `render:${asmBody.render_id}` }));
        } else if (asmBody?.clip_count) {
          setShotStatus((prev) => ({
            ...prev,
            __film: `timeline:${asmBody.clip_count}`,
          }));
        }
        if (asmBody?.error) setFilmError(asmBody.error);
      }
    } catch (err) {
      setFilmError(err instanceof Error ? err.message : "生成失败");
    } finally {
      setFilmBusy(false);
    }
  }, [node.workflow_id, node.node_id, slots]);

  const startDirectRender = useCallback(async () => {
    // D7 idempotency guard: never fire a second direct-execute while one is in flight.
    if (renderPhase === "starting" || renderPhase === "polling") return;
    setRenderPhase("starting");
    setRenderFailure(null);
    setRenderBlockers([]);
    setRenderErrorItems([]);
    setRenderNotes([]);
    setRenderPaceWarnings([]);
    setRenderUnresolved([]);
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
          // D2: 人工补齐的库素材（clip → 真实 asset/version）随车提交
          ...(libraryResolutions.length > 0
            ? {
                library_resolutions: libraryResolutions.map((resolution) => ({
                  clip_id: resolution.clip_id,
                  asset_id: resolution.asset_id,
                  version_id: resolution.version_id,
                })),
              }
            : {}),
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
        // E5: 结构漂移 / 422 校验 / 具名错误都逐条落状态（失败块按条目渲染）
        setRenderErrorItems(describeReplicaError(response.status, detail));
        setRenderPhase("failed");
        return;
      }

      const notes: string[] = [];
      // D7 幂等事实：同一蓝图复用了既有渲染（在途或已完成发布）——不是又一次
      // 出片。如实说出口，别让用户以为又烧了一次渲染。
      if (body.reused === true) {
        const kind =
          body.reuse_kind === "completed_asset"
            ? "已完成的同一成片"
            : "当前在途的同一渲染";
        notes.push(
          `同一蓝图复用${kind}，未重复出片（final 时间线重存为版本 ${body.timeline_version ?? "?"}，内容未变）`,
        );
      } else if (
        typeof body.previous_timeline_version === "number" &&
        body.previous_timeline_version > 0
      ) {
        notes.push(
          `已替换工作流此前的 final-composition 时间线（版本 ${body.previous_timeline_version} → ${body.timeline_version}）`,
        );
      }
      // D2: 未解析库素材逐条可行动——supersedes 此前那句"未计入"一笔带过的 note。
      // 空数组也要如实落状态：清零清单与已被消费的补齐态。
      const unresolved = Array.isArray(body.unresolved_assets)
        ? body.unresolved_assets.map((item: Record<string, unknown>) => ({
            clip_id: String(item.clip_id ?? ""),
            track_id: String(item.track_id ?? ""),
            intent: String(item.intent ?? ""),
            library_hint: (item.library_hint ?? "") as string | string[],
            duration_seconds: Number(item.duration_seconds ?? 0),
          }))
        : [];
      setRenderUnresolved(unresolved);
      // 已随本次直出解析掉的 clip，补齐态同步失效（后端只接受哨兵 clip 回填）
      const stillUnresolved = new Set(
        unresolved.map((item: { clip_id: string }) => item.clip_id),
      );
      setLibraryResolutions((current) =>
        current.filter((resolution) => stillUnresolved.has(resolution.clip_id)),
      );
      // P4 pace 预检：台词预估时长超窗——在花钱合成前说出来（删词 or 加窗）
      if (Array.isArray(body.pace_warnings) && body.pace_warnings.length > 0) {
        setRenderPaceWarnings(
          body.pace_warnings.map((item: Record<string, unknown>) => ({
            beat_id: String(item.beat_id ?? ""),
            text: String(item.text ?? ""),
            estimated_seconds: Number(item.estimated_seconds ?? 0),
            window_seconds: Number(item.window_seconds ?? 0),
            ratio: typeof item.ratio === "number" ? item.ratio : null,
          })),
        );
      }
      setRenderNotes(notes);
      const nextRenderId = String(body.render_id ?? "");
      setRenderId(nextRenderId);
      setRenderPhase("polling");
      // D7: persist so a refresh mid-render can re-attach to this detached render.
      writeReplicaRender(node.workflow_id, node.node_id, {
        renderId: nextRenderId,
        renderPhase: "polling",
      });
    } catch (err) {
      setRenderFailure(err instanceof Error ? err.message : "直出失败");
      setRenderPhase("failed");
    }
  }, [buildContent, node, setAgentCanvasWorkflow, selectedRecipe, renderPhase, libraryResolutions]);
  // 轮询渲染状态（组件卸载自动停；超过 ~5 分钟未终态则明确失败，不无限轮）
  useEffect(() => {
    if (renderPhase !== "polling" || !renderId) return;
    let cancelled = false;
    let attempts = 0;
    const tick = async () => {
      attempts += 1;
      try {
        const response = await fetch(finalRenderStatePath(node.workflow_id, renderId));
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

  // D7: re-attach to an in-flight render after a refresh (render_id survived in storage).
  useEffect(() => {
    const snapshot = readReplicaRender(node.workflow_id, node.node_id);
    if (snapshot) {
      setRenderId(snapshot.renderId);
      setRenderPhase("polling");
    }
  }, [node.workflow_id, node.node_id]);

  // D7: once the render reaches a terminal state, drop the resumable snapshot.
  useEffect(() => {
    if (renderPhase === "completed" || renderPhase === "failed") {
      clearReplicaRender(node.workflow_id, node.node_id);
    }
  }, [renderPhase, node.workflow_id, node.node_id]);

  // D7: count elapsed seconds while a render is starting/polling.
  useEffect(() => {
    if (renderPhase !== "starting" && renderPhase !== "polling") return;
    setRenderElapsed(0);
    const timer = window.setInterval(() => setRenderElapsed((seconds) => seconds + 1), 1000);
    return () => window.clearInterval(timer);
  }, [renderPhase]);

  // D7: stop tracking an in-flight render — and E6: ask the backend to really
  // cancel it (v2 final-composition has a cancel endpoint that transitions the
  // job and stops the process; pretending to cancel by clearing UI state is
  // what made the old "取消" dishonest).
  const cancelDirectRender = useCallback(async () => {
    const currentRenderId = renderId;
    clearReplicaRender(node.workflow_id, node.node_id);
    setRenderId(null);
    setRenderProgress(null);
    setRenderElapsed(0);
    setRenderPhase("idle");
    if (!currentRenderId) {
      setNotice("已停止跟踪本次直出渲染。");
      return;
    }
    try {
      const response = await fetch(finalRenderCancelPath(node.workflow_id, currentRenderId), {
        method: "POST",
      });
      const body = await response.json().catch(() => null);
      if (response.status !== 200) {
        setNotice(
          `已停止跟踪；取消请求未被接受 (HTTP ${response.status})——渲染可能仍在后台进行，可到工作流的 final-composition 面板查看。`,
        );
        return;
      }
      const status = typeof body?.status === "string" ? body.status : "";
      setNotice(
        status === "cancelled"
          ? "✓ 已取消该直出渲染（后端已停止任务）。"
          : `已请求取消（后端状态：${status || "处理中"}）——渲染可能仍在收尾，可到 final-composition 面板查看。`,
      );
    } catch {
      setNotice(
        "已停止跟踪；取消请求发送失败——渲染可能仍在后台进行，可到 final-composition 面板查看。",
      );
    }
  }, [node.workflow_id, node.node_id, renderId]);

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
          {/* 一键复刻成片：作者唯一需要按的按钮 */}
          <div
            style={{
              background: "#141428",
              border: "1px solid #2a2a4a",
              borderRadius: 4,
              padding: "6px 8px",
              marginBottom: 8,
            }}
          >
            <button
              onClick={() => void generateFilm()}
              disabled={filmBusy}
              title="按当前槽位生成全部镜头（重复点击会复用已生成的镜头）"
              style={{
                background: filmBusy ? "#2a2a4a" : "#2a6a3a",
                border: "none",
                color: filmBusy ? "#666" : "#fff",
                padding: "4px 12px",
                borderRadius: 3,
                cursor: filmBusy ? "default" : "pointer",
                fontSize: 10,
                fontFamily: "monospace",
              }}
            >
              {filmBusy ? "⏳ 生成中…" : "🎬 生成复刻成片"}
            </button>
            {filmError && (
              <div style={{ color: "#f88", fontSize: 9, marginTop: 4 }}>
                生成失败：{filmError}
              </div>
            )}
            {filmShots.map((shot) => {
              const status = shotStatus[shot.node_id] ?? "排队中";
              return (
                <div
                  key={shot.node_id}
                  style={{
                    fontSize: 9,
                    marginTop: 2,
                    color: status === "ready" ? "#8f8" : status === "failed" ? "#f88" : "#9ab",
                  }}
                >
                  {shot.title}：
                  {status === "ready" ? "✓ 已生成" : status === "failed" ? "✗ 失败" : status}
                </div>
              );
            })}
            {shotStatus.__film?.startsWith("timeline:") && (
              <div style={{ fontSize: 9, marginTop: 2, color: "#8cf" }}>
                ✓ 已铺上时间线（{shotStatus.__film.slice("timeline:".length)} 镜）——在时间线编辑器里可见
              </div>
            )}
            {shotStatus.__film?.startsWith("render:") && (
              <div style={{ fontSize: 9, marginTop: 2, color: "#8f8" }}>
                ✓ 成片渲染中（{shotStatus.__film.slice("render:".length)}）
              </div>
            )}
          </div>
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
                  onApply={(skillId, recipe) => {
                    const next = [...slots];
                    next[styleSlotIndex] = {
                      ...slot,
                      replace_with: skillId,
                    };
                    setSlots(next);
                    // E1: 变体自带字幕配方——应用即选为该直出的配方，
                    // "看得见的差异"由此真正进入成片（此前只写 skill 槽位）
                    if (recipe) setSelectedRecipe(recipe);
                  }}
                />
              )}
              {slot.kind === "style" && index === styleSlotIndex && (
                <VariantRenderPlans blueprint={buildContent()} />
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
            {recipes.length === 0 && recipeCatalogError && (
              <div
                style={{
                  marginBottom: 6,
                  padding: "4px 8px",
                  background: "#3a2a1a",
                  border: "1px solid #5a4a2a",
                  borderRadius: 3,
                  fontSize: 9,
                  color: "#fc8",
                  lineHeight: 1.6,
                }}
              >
                ⚠ {recipeCatalogError}
                <button
                  type="button"
                  onClick={() => {
                    setRecipeCatalogError(null);
                    setRecipeCatalogAttempt((n) => n + 1);
                  }}
                  style={{
                    marginLeft: 6,
                    background: "transparent",
                    border: "1px solid #678",
                    color: "#9bd",
                    borderRadius: 3,
                    fontSize: 9,
                    padding: "0 6px",
                    cursor: "pointer",
                  }}
                >
                  重试
                </button>
              </div>
            )}
            {/* E2: 配方文档层——导出改完再导入（.adrecipe，与蓝图 .adreplica 同纪律） */}
            <div style={{ display: "flex", gap: 6, marginBottom: 6, flexWrap: "wrap" }}>
              <button
                onClick={() => void exportRecipe()}
                disabled={recipeBusy || !selectedRecipe}
                title={selectedRecipe ? "把当前配方导出成 .adrecipe 文本" : "先选一个配方"}
                style={{
                  background: recipeBusy || !selectedRecipe ? "#2a2a4a" : "#3a3a6a",
                  border: "none",
                  color: recipeBusy || !selectedRecipe ? "#666" : "#fff",
                  padding: "2px 10px",
                  borderRadius: 3,
                  cursor: recipeBusy || !selectedRecipe ? "default" : "pointer",
                  fontSize: 9,
                }}
              >
                {recipeBusy ? "⏳ 处理中…" : "🎨 导出配方 .adrecipe"}
              </button>
              <button
                onClick={() => void importRecipe()}
                disabled={recipeBusy || !recipeText.trim()}
                title="把文本框里的 .adrecipe 配方导入并选为直出配方"
                style={{
                  background: recipeBusy || !recipeText.trim() ? "#2a2a4a" : "#3a5a8a",
                  border: "none",
                  color: recipeBusy || !recipeText.trim() ? "#666" : "#fff",
                  padding: "2px 10px",
                  borderRadius: 3,
                  cursor: recipeBusy || !recipeText.trim() ? "default" : "pointer",
                  fontSize: 9,
                }}
              >
                📥 导入配方
              </button>
            </div>
            {/* E2 订正：textarea 常驻。原条件渲染（recipeText 非空才出现）让
                "请先把 .adrecipe 配方文本粘贴到文本框"无从下手——recipeText 只有
                导出/输入后才非空，首次导入是鸡生蛋。常驻后粘贴即用。 */}
            <textarea
              value={recipeText}
              onChange={(event) => setRecipeText(event.target.value)}
              placeholder={'<adrecipe version="1" kind="subtitle-style">…'}
              spellCheck={false}
              style={{
                width: "100%",
                minHeight: 64,
                marginBottom: 6,
                background: "#101018",
                border: "1px solid #2a2a4a",
                borderRadius: 3,
                color: "#8f8",
                fontSize: 10,
                fontFamily: "monospace",
                padding: "4px 6px",
                resize: "vertical",
              }}
            />
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
                {renderProgress !== null ? `${Math.round(renderProgress)}%` : "已进入渲染队列"} · 正在渲染 {renderElapsed} 秒{" "}
                <button
                  type="button"
                  onClick={() => void cancelDirectRender()}
                  style={{
                    marginLeft: 6,
                    background: "transparent",
                    border: "1px solid #678",
                    color: "#9bd",
                    borderRadius: 3,
                    fontSize: 10,
                    padding: "0 8px",
                    cursor: "pointer",
                  }}
                >
                  取消渲染
                </button>
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
                ) : renderErrorItems.length > 0 ? (
                  <>
                    {/* E5: 逐条可行动——结构漂移每条点名维度+期望/实际，
                        422 校验每条 loc: msg，而不是"HTTP 422"一句 */}
                    <div>直出失败，逐条说明：</div>
                    <ul style={{ margin: "2px 0", paddingLeft: 16 }}>
                      {renderErrorItems.map((item, index) => (
                        <li key={`${index}_${item}`}>{item}</li>
                      ))}
                    </ul>
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
            {renderPaceWarnings.length > 0 && (
              <div
                style={{
                  marginTop: 6,
                  padding: "4px 8px",
                  background: "#3a2a1a",
                  border: "1px solid #5a4a2a",
                  borderRadius: 3,
                  fontSize: 9,
                  color: "#fc8",
                  lineHeight: 1.6,
                }}
              >
                <div>⏱ 语速预检：{renderPaceWarnings.length} 段台词预估念不完（合成前处理更便宜）：</div>
                {renderPaceWarnings.map((warning) => (
                  <div key={warning.beat_id}>
                    · [{warning.beat_id}]「{warning.text}」预估 {warning.estimated_seconds}s vs 段落窗{" "}
                    {warning.window_seconds}s
                    {warning.ratio !== null ? `（${warning.ratio.toFixed(1)}×）` : ""}——删词或加窗
                  </div>
                ))}
              </div>
            )}
            {renderUnresolved.length > 0 && (
              <div
                style={{
                  marginTop: 6,
                  padding: "4px 8px",
                  background: "#3a2a1a",
                  border: "1px solid #5a4a2a",
                  borderRadius: 3,
                  fontSize: 9,
                  color: "#fc8",
                  lineHeight: 1.7,
                }}
              >
                <div>
                  🔇 有 {renderUnresolved.length} 个库素材未解析，已跳过、未计入本次直出
                  （补上即可入片，不必整片重做）：
                </div>
                {renderUnresolved.map((item) => {
                  const resolution = libraryResolutions.find((r) => r.clip_id === item.clip_id);
                  const hint = Array.isArray(item.library_hint)
                    ? item.library_hint.join("、")
                    : String(item.library_hint ?? "");
                  return (
                    <div key={item.clip_id} style={{ marginTop: 3 }}>
                      · [{item.clip_id}] 意图「{item.intent || "—"}」
                      {hint ? ` · 提示：${hint}` : ""} · {item.duration_seconds.toFixed(1)}s{" "}
                      {resolution ? (
                        <>
                          <span style={{ color: "#8f8" }}>
                            ✓ 已选素材 {resolution.asset_id}（{resolution.version_id}）
                          </span>{" "}
                          <button
                            type="button"
                            onClick={() =>
                              setLibraryResolutions((current) =>
                                current.filter((r) => r.clip_id !== item.clip_id),
                              )
                            }
                            style={{
                              background: "transparent",
                              border: "1px solid #678",
                              color: "#9bd",
                              borderRadius: 3,
                              fontSize: 9,
                              padding: "0 6px",
                              cursor: "pointer",
                            }}
                          >
                            撤销补齐
                          </button>
                        </>
                      ) : (
                        <button
                          type="button"
                          onClick={() =>
                            setFillingClipId((current) =>
                              current === item.clip_id ? null : item.clip_id,
                            )
                          }
                          style={{
                            background: "transparent",
                            border: "1px solid #678",
                            color: "#9bd",
                            borderRadius: 3,
                            fontSize: 9,
                            padding: "0 6px",
                            cursor: "pointer",
                          }}
                        >
                          选素材补齐
                        </button>
                      )}
                      {fillingClipId === item.clip_id && !resolution && (
                        <LibraryAssetPicker
                          query={item.intent || hint}
                          onResolve={(picked) => {
                            setLibraryResolutions((current) => [
                              ...current.filter((r) => r.clip_id !== item.clip_id),
                              {
                                clip_id: item.clip_id,
                                asset_id: picked.asset_id,
                                version_id: picked.version_id,
                              },
                            ]);
                            setFillingClipId(null);
                          }}
                          onCancel={() => setFillingClipId(null)}
                        />
                      )}
                    </div>
                  );
                })}
                {libraryResolutions.length > 0 && (
                  <button
                    type="button"
                    onClick={() => void startDirectRender()}
                    disabled={renderPhase === "starting" || renderPhase === "polling"}
                    style={{
                      marginTop: 5,
                      background:
                        renderPhase === "starting" || renderPhase === "polling" ? "#2a2a4a" : "#3a5a8a",
                      border: "none",
                      color:
                        renderPhase === "starting" || renderPhase === "polling" ? "#666" : "#fff",
                      borderRadius: 3,
                      fontSize: 9,
                      padding: "2px 10px",
                      cursor:
                        renderPhase === "starting" || renderPhase === "polling" ? "default" : "pointer",
                    }}
                  >
                    ↻ 带 {libraryResolutions.length} 个补齐重新直出
                  </button>
                )}
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
// VariantRenderPlans — E1/E5 收口：变体渲染计划审片（/variant-render-plans）
// 后端对 Top-N 变体各编译一份 direct-execute 渲染计划（只出计划不渲染），
// 并在结构漂移时 500 + 逐条 drifts。此前面向前端无调用方——漂移错误永远
// 看不到。本面板同时闭合两件事：低成本审片有入口；E5 的逐条错误有实机路径。
// ---------------------------------------------------------------------------

interface VariantRenderPlanEntry {
  variant_id: string;
  skill_ids: string[];
  names: string[];
  score: number;
  mixable_applied: boolean;
  recipe_id: string;
  recipe_name: string;
  feasible: boolean;
  subtitle_cue_count: number;
  needs_placeholder_video: boolean;
  unresolved_assets: unknown[];
}

function VariantRenderPlans({ blueprint }: { blueprint: ReplicaBlueprintContentV2 }) {
  const [loading, setLoading] = useState(false);
  const [plans, setPlans] = useState<VariantRenderPlanEntry[]>([]);
  const [errorItems, setErrorItems] = useState<string[]>([]);
  const [open, setOpen] = useState(false);

  const loadPlans = useCallback(async () => {
    setLoading(true);
    setErrorItems([]);
    try {
      const response = await fetch("/api/v1/replica/blueprint/variant-render-plans", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ blueprint, n: 5, render_representatives: 2 }),
      });
      const body = await response.json().catch(() => null);
      if (response.status !== 200 || !body) {
        // E5: 结构漂移（replica_structure_drift + drifts）逐条可读
        setErrorItems(describeReplicaError(response.status, body?.detail));
        setPlans([]);
        setOpen(true);
        return;
      }
      setPlans(Array.isArray(body.variants) ? (body.variants as VariantRenderPlanEntry[]) : []);
      setOpen(true);
    } catch (err) {
      setErrorItems([err instanceof Error ? err.message : "变体渲染计划获取失败"]);
      setPlans([]);
      setOpen(true);
    } finally {
      setLoading(false);
    }
  }, [blueprint]);

  return (
    <div style={{ marginTop: 4 }}>
      <button
        onClick={() => (open ? setOpen(false) : void loadPlans())}
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
        {loading ? "⏳ 编译中…" : open ? "📋 收起变体渲染计划" : "📋 变体渲染计划"}
      </button>
      {open && errorItems.length > 0 && (
        <div style={{ marginTop: 4, fontSize: 9, color: "#f88", lineHeight: 1.7 }}>
          <div>变体渲染计划获取失败，逐条说明：</div>
          <ul style={{ margin: "2px 0", paddingLeft: 16 }}>
            {errorItems.map((item, index) => (
              <li key={`${index}_${item}`}>{item}</li>
            ))}
          </ul>
        </div>
      )}
      {open && errorItems.length === 0 && plans.length > 0 && (
        <div style={{ marginTop: 4, fontSize: 9, lineHeight: 1.8 }}>
          <div style={{ color: "#888", marginBottom: 2 }}>
            低成本审片：各变体的 direct-execute 编译计划（只出计划，不渲染）。
          </div>
          {plans.map((plan) => (
            <div key={plan.variant_id} style={{ color: plan.feasible ? "#ccc" : "#f88" }}>
              · {plan.names.join(" × ")}
              {plan.recipe_name ? <span style={{ color: "#ca8" }}> · 🎨 {plan.recipe_name}</span> : null}
              {" · "}
              {plan.feasible ? "可直出" : "不可直出（有必须生成的环节）"}
              {` · 字幕 ${plan.subtitle_cue_count} 条`}
              {plan.unresolved_assets.length > 0
                ? ` · 未解析素材 ${plan.unresolved_assets.length} 个`
                : ""}
              {plan.needs_placeholder_video ? " · 需占位视频" : ""}
            </div>
          ))}
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
  // E1: 后端已返回的配方身份（G5 兑付点——变体之间"看得见的差异"由它提供）
  recipe_id: string;
  recipe_name: string;
}

/** E1：把配方的字幕参数画成一张迷你预览卡——变体差异必须肉眼可辨，
 *  而不是只给一行 skill 名字（RW-3：各变体字幕样式可见地不同）。 */
function RecipeCaptionPreview({ recipe }: { recipe: Record<string, unknown> | null }) {
  const subtitle = (recipe?.subtitle ?? {}) as Record<string, unknown>;
  const fontSize = typeof subtitle.font_size === "number" ? subtitle.font_size : null;
  const color = typeof subtitle.color === "string" ? subtitle.color : "#eee";
  const position = typeof subtitle.position === "string" ? subtitle.position : "bottom_center";
  const lead = typeof subtitle.lead_seconds === "number" ? subtitle.lead_seconds : null;
  const tail = typeof subtitle.tail_seconds === "number" ? subtitle.tail_seconds : null;
  const justify =
    position.startsWith("top") ? "flex-start" : position === "center" ? "center" : "flex-end";
  return (
    <div
      style={{
        width: 72,
        height: 40,
        background: "#0a0a14",
        border: "1px solid #2a2a4a",
        borderRadius: 3,
        display: "flex",
        flexDirection: "column",
        justifyContent: justify,
        padding: 3,
        flexShrink: 0,
      }}
      title={`position=${position} · font_size=${fontSize ?? "默认"} · lead=${lead ?? "默认"}s · tail=${tail ?? "默认"}s`}
    >
      <span
        style={{
          color,
          fontSize: fontSize ? Math.max(7, Math.round(fontSize / 3)) : 8,
          lineHeight: 1.2,
          textAlign: "center",
          overflow: "hidden",
        }}
      >
        别再这样洗脸
      </span>
      {lead !== null || tail !== null ? (
        <span style={{ fontSize: 6, color: "#556", textAlign: "center" }}>
          +{lead ?? 0}s / -{tail ?? 0}s
        </span>
      ) : null}
    </div>
  );
}

function StyleVariantPicker({
  blueprint,
  onApply,
}: {
  blueprint: ReplicaBlueprintContentV2;
  onApply: (skillId: string, recipe: Record<string, unknown> | null) => void;
}) {
  const [open, setOpen] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [variants, setVariants] = useState<StyleVariantCandidate[]>([]);
  // E1: 配方库（预览卡 + 应用时随车提交都靠它）。打开选择器才拉——
  // 与源码 tab 的配方拉取同一纪律：不挂载即拉，不污染首屏 fetch 序列。
  const [recipes, setRecipes] = useState<Record<string, unknown>[]>([]);

  const loadVariants = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [variantsResponse, recipesResponse] = await Promise.all([
        fetch("/api/v1/replica/blueprint/style-variants", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ blueprint, n: 5 }),
        }),
        fetch("/api/v1/replica/blueprint/recipes"),
      ]);
      const body = await variantsResponse.json().catch(() => null);
      if (variantsResponse.status !== 200 || !body) {
        throw new Error(
          describeReplicaError(variantsResponse.status, body?.detail).join("；"),
        );
      }
      setVariants(body.variants ?? []);
      // 配方库拉取失败不阻断推荐（无预览卡而已），但名字仍从变体响应里来
      const recipesBody = await recipesResponse.json().catch(() => null);
      if (recipesResponse.status === 200 && Array.isArray(recipesBody?.recipes)) {
        setRecipes(recipesBody.recipes as Record<string, unknown>[]);
      }
      setOpen(true);
    } catch (err) {
      setError(err instanceof Error ? err.message : "风格推荐失败");
    } finally {
      setLoading(false);
    }
  }, [blueprint]);

  const recipeOf = (variant: StyleVariantCandidate) =>
    variant.recipe_id
      ? recipes.find((entry) => String(entry.recipe_id ?? "") === variant.recipe_id) ?? null
      : null;

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
          {variants.map((variant) => {
            const recipe = recipeOf(variant);
            return (
              <div
                key={variant.variant_id}
                style={{
                  display: "flex",
                  gap: 6,
                  alignItems: "center",
                  marginBottom: 4,
                  fontSize: 9,
                }}
              >
                <span style={{ color: "#8af", minWidth: 34 }}>
                  {variant.score.toFixed(2)}
                </span>
                {/* E1: 并排预览卡——同一句话在各配方下的可见形态 */}
                <RecipeCaptionPreview recipe={recipe} />
                <span style={{ flex: 1, color: "#ccc" }}>
                  {variant.names.join(" × ")}
                  {variant.recipe_name ? (
                    <span style={{ color: "#ca8" }}> · 🎨 {variant.recipe_name}</span>
                  ) : null}
                  <span style={{ color: "#666" }}> · {variant.rationale}</span>
                </span>
                <button
                  onClick={() =>
                    variant.mixable_applied && onApply(variant.skill_ids[0], recipe)
                  }
                  disabled={!variant.mixable_applied}
                  title={
                    variant.mixable_applied
                      ? recipe
                        ? "应用该风格 + 字幕配方（直出时生效）"
                        : "应用该风格"
                      : "多风格并行激活暂未支持"
                  }
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
            );
          })}
          <div style={{ color: "#555", fontSize: 8, marginTop: 2 }}>
            预览卡显示各变体配方下的字幕样式（颜色/字号/位置/可见窗）；应用后配方随直出提交。
          </div>
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// LibraryAssetPicker — D2 未解析库素材的行内补选器（B v1：人解析）
// 两步：候选实体（按意图关键词搜）→ 实体的 version-pinned 资产。
// 选中即给出确定的 asset/version 交给直出提交（library_resolutions）；
// 自动匹配语义（搜索/标签/置信度）是 v2，这里不猜、失败必须可见。
// ---------------------------------------------------------------------------

function LibraryAssetPicker({
  query,
  onResolve,
  onCancel,
}: {
  query: string;
  onResolve: (picked: { asset_id: string; version_id: string }) => void;
  onCancel: () => void;
}) {
  const [entities, setEntities] = useState<Array<{ entity_id: string; display_name: string }>>([]);
  const [assets, setAssets] = useState<Array<Record<string, unknown>> | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // 重试计数：load 受它驱动——失败后的"重试"必须真的再拉一次，而不是清空列表装死
  const [loadAttempt, setLoadAttempt] = useState(0);

  useEffect(() => {
    let cancelled = false;
    void (async () => {
      setLoading(true);
      setError(null);
      try {
        const params = new URLSearchParams();
        if (query.trim()) params.set("q", query.trim());
        const suffix = params.toString() ? `?${params.toString()}` : "";
        const response = await fetch(`/api/v1/asset-library/entities${suffix}`);
        const body = await response.json().catch(() => null);
        if (cancelled) return;
        if (response.status !== 200 || !body) {
          setError(`素材库不可用 (HTTP ${response.status})——可到资产库页手动确认后重试`);
          return;
        }
        const list = Array.isArray(body.entities) ? (body.entities as unknown[]) : [];
        setEntities(
          list
            .map((raw: unknown) => {
              const item = raw as Record<string, unknown>;
              return {
                entity_id: String(item.entity_id ?? ""),
                display_name: String(item.display_name ?? item.entity_id ?? ""),
              };
            })
            .filter((item) => item.entity_id),
        );
      } catch (err) {
        if (!cancelled) setError(err instanceof Error ? err.message : "素材库不可用");
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [query, loadAttempt]);

  const openEntity = useCallback(async (entityId: string) => {
    setLoading(true);
    setError(null);
    try {
      const response = await fetch(`/api/v1/asset-library/entities/${encodeURIComponent(entityId)}`);
      const body = await response.json().catch(() => null);
      if (response.status !== 200 || !body) {
        setError(`素材详情拉取失败 (HTTP ${response.status})`);
        return;
      }
      setAssets(Array.isArray(body.assets) ? body.assets : []);
    } catch (err) {
      setError(err instanceof Error ? err.message : "素材详情拉取失败");
    } finally {
      setLoading(false);
    }
  }, []);

  return (
    <div
      style={{
        marginTop: 4,
        padding: "5px 8px",
        background: "#16162a",
        border: "1px solid #2a2a4a",
        borderRadius: 3,
        fontSize: 9,
      }}
    >
      {loading && <div style={{ color: "#888" }}>⏳ 拉取素材库…</div>}
      {error && (
        <div style={{ color: "#f88" }}>
          ⚠ {error}{" "}
          <button
            type="button"
            onClick={() => {
              setAssets(null);
              setLoadAttempt((n) => n + 1);
            }}
            style={{
              background: "transparent",
              border: "1px solid #678",
              color: "#9bd",
              borderRadius: 3,
              fontSize: 9,
              padding: "0 6px",
              cursor: "pointer",
            }}
          >
            重试
          </button>
        </div>
      )}
      {assets === null ? (
        <>
          <div style={{ color: "#888", marginBottom: 3 }}>
            按意图「{query || "—"}」搜到 {entities.length} 个候选实体，选一个看资产：
          </div>
          {entities.map((entity) => (
            <button
              key={entity.entity_id}
              type="button"
              onClick={() => void openEntity(entity.entity_id)}
              style={{
                display: "block",
                marginBottom: 2,
                background: "#1a1a30",
                border: "1px solid #2a2a4a",
                color: "#9bd",
                borderRadius: 3,
                fontSize: 9,
                padding: "2px 8px",
                cursor: "pointer",
                width: "100%",
                textAlign: "left",
              }}
            >
              📁 {entity.display_name || entity.entity_id}
            </button>
          ))}
          {!loading && !error && entities.length === 0 && (
            <div style={{ color: "#888" }}>没有候选素材——可到资产库上传后重试。</div>
          )}
        </>
      ) : (
        <>
          <div style={{ color: "#888", marginBottom: 3 }}>选一个资产版本回填：</div>
          {assets.map((asset, index) => {
            const source = (asset.source ?? {}) as Record<string, unknown>;
            const realAssetId =
              typeof source.asset_id === "string" && source.asset_id
                ? source.asset_id
                : String(asset.asset_id ?? "");
            const versionId =
              typeof source.version_id === "string" && source.version_id
                ? source.version_id
                : `version_${realAssetId}`;
            return (
              <button
                key={`${realAssetId}_${index}`}
                type="button"
                onClick={() => onResolve({ asset_id: realAssetId, version_id: versionId })}
                style={{
                  display: "block",
                  marginBottom: 2,
                  background: "#1a2a1a",
                  border: "1px solid #2a4a2a",
                  color: "#8f8",
                  borderRadius: 3,
                  fontSize: 9,
                  padding: "2px 8px",
                  cursor: "pointer",
                  width: "100%",
                  textAlign: "left",
                }}
              >
                🎵 {String(asset.semantic_type || asset.asset_type || "素材")} — {realAssetId} ·{" "}
                {versionId}
              </button>
            );
          })}
          {assets.length === 0 && <div style={{ color: "#888" }}>该实体下没有可用资产。</div>}
          <button
            type="button"
            onClick={() => setAssets(null)}
            style={{
              marginTop: 2,
              background: "transparent",
              border: "1px solid #2a2a4a",
              color: "#889",
              borderRadius: 3,
              fontSize: 9,
              padding: "0 6px",
              cursor: "pointer",
            }}
          >
            ← 返回实体列表
          </button>
        </>
      )}
      <button
        type="button"
        onClick={onCancel}
        style={{
          marginLeft: 6,
          background: "transparent",
          border: "1px solid #2a2a4a",
          color: "#889",
          borderRadius: 3,
          fontSize: 9,
          padding: "0 6px",
          cursor: "pointer",
        }}
      >
        收起
      </button>
    </div>
  );
}
