/**
 * ReplicaTeardown — 拉片复刻入口（MVP 切片）。
 *
 * 设计理念借鉴 hypit（视频是可拆解、可复刻的工程）：
 * 上传的参考视频 → POST /api/v1/replica/teardown → 结构化拉片报告
 * （整片解读 / 结构 Beats / 镜头表 / 节奏 / 视觉系统）+ 复刻分镜草稿。
 *
 * 产出物是"进入正常创作流的桥"：复刻分镜草稿可一键复制，粘贴到 script
 * 节点或 Agent 对话继续创作；报告本身同时诚实声明边界——复刻的是结构与
 * 关系，不是像素（constraints 由后端写入）。
 *
 * 交互契约对齐 ReferenceVideoPanel / SceneImageIntake：同样的深色等宽
 * 面板、加载态、错误面。
 */

import { useCallback, useEffect, useRef, useState } from "react";

import { useApp } from "../../../AppContextValue.ts";
import { agentCanvasApi } from "../../../api/agentCanvasApi.ts";

// ---------------------------------------------------------------------------
// Response types（对齐后端 TeardownResponse）
// ---------------------------------------------------------------------------

export interface TeardownShot {
  index: number;
  start_seconds: number;
  end_seconds: number;
  shot_size: string;
  camera_motion: string;
  subject_action: string;
  on_screen_text: string;
  transition_to_next: string;
  note: string;
}

export interface TeardownBeat {
  role: string;
  description: string;
  /** 段落台词原文（词级转录可用时） */
  line?: string;
  start_seconds: number;
  end_seconds: number;
}

export interface TeardownRhythm {
  avg_shot_seconds: number;
  cut_points_seconds: number[];
  energy_curve: string;
}

export interface TeardownSystems {
  captions: string;
  music: string;
  graphics: string[];
  sfx: string[];
}

export interface TeardownTranscript {
  source: string;
  language: string;
  reason: string;
  lines: Array<{ text: string; start_seconds: number; end_seconds: number }>;
}

export interface TeardownReport {
  whole_piece_reading: string;
  format_name: string;
  shots: TeardownShot[];
  beats: TeardownBeat[];
  rhythm: TeardownRhythm;
  systems: TeardownSystems;
  /** 词级转录（whisperX 可用时）；unavailable 的降级原因写入 constraints */
  transcript?: TeardownTranscript;
  replica_storyboard_draft: string;
  constraints: string[];
}

export interface TeardownVideoMetadata {
  duration_seconds: number;
  width: number;
  height: number;
}

export interface TeardownResponse {
  success: boolean;
  report: TeardownReport;
  num_frames_analyzed: number;
  video_metadata?: TeardownVideoMetadata;
}

export interface ReplicaTeardownProps {
  /** 已上传参考视频的 asset_id（来自 ReferenceVideoPanel 的上传结果）。 */
  assetId: string | null;
  /** 当前工作流（创建复刻蓝图节点用）。 */
  workflowId?: string | null;
  height?: number;
}

/** 从分辨率推导画幅比（蓝图/.adreplica 文档需要 aspect）。 */
export function aspectFromDimensions(width: number, height: number): string {
  if (!width || !height) return "";
  const gcd = (a: number, b: number): number => (b === 0 ? a : gcd(b, a % b));
  const d = gcd(width, height);
  let w = width / d;
  let h = height / d;
  if (w > 32 || h > 32) {
    // 非整比分辨率吸附到常见画幅，避免 "43:57" 这类不可读值
    const ratio = width / height;
    const common: Array<[number, number]> = [
      [1, 1], [4, 3], [3, 4], [16, 9], [9, 16], [4, 5], [3, 2], [2, 3],
    ];
    const best = common.reduce((a, b) =>
      Math.abs(b[0] / b[1] - ratio) < Math.abs(a[0] / a[1] - ratio) ? b : a,
    );
    w = best[0];
    h = best[1];
  }
  return `${Math.round(w)}:${Math.round(h)}`;
}

/** 复刻目标：作为 user_description 引导 LLM 读片侧重。 */
const REPLICA_GOALS = [
  { value: "", label: "整片复刻（保留全部结构）" },
  { value: "换商品，保留人物与台词结构", label: "换商品" },
  { value: "换人物/演员，保留商品与台词", label: "换人物" },
  { value: "只换台词文案，保留画面结构", label: "换台词" },
  { value: "换风格，保留镜头与节奏", label: "换风格" },
] as const;

function sectionLabel(text: string) {
  return (
    <div style={{ color: "#888", marginBottom: 6, fontSize: 10, letterSpacing: 1 }}>
      {text}
    </div>
  );
}

function cardStyle(): React.CSSProperties {
  return {
    background: "#16162a",
    border: "1px solid #2a2a4a",
    borderRadius: 4,
    padding: "8px 10px",
    marginBottom: 10,
  };
}

export function ReplicaTeardown({
  assetId,
  workflowId = null,
  height = 320,
}: ReplicaTeardownProps) {
  const { setAgentCanvasWorkflow } = useApp();
  const [running, setRunning] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [cancelled, setCancelled] = useState(false);
  const [elapsedSeconds, setElapsedSeconds] = useState(0);
  const [videoMeta, setVideoMeta] = useState<TeardownVideoMetadata | null>(null);
  // G6：拆解缓存溯源（命中 = 未调用 LLM 的复用报告）
  const [cacheInfo, setCacheInfo] = useState<{ cached: boolean; cacheKey: string } | null>(null);
  const abortRef = useRef<AbortController | null>(null);
  // D8：拆解任务句柄（提交即得，轮询/取消都用它）
  const jobIdRef = useRef<string | null>(null);
  const [jobStatus, setJobStatus] = useState<string | null>(null);
  // D8：取消后的说明（真取消/无需取消，替代旧那句"后端可能仍在跑"）
  const [cancelNote, setCancelNote] = useState<string | null>(null);
  const [report, setReport] = useState<TeardownReport | null>(null);
  const [goal, setGoal] = useState<string>("");
  const [copied, setCopied] = useState(false);
  const [creating, setCreating] = useState(false);
  const [blueprintNodeId, setBlueprintNodeId] = useState<string | null>(null);
  // 链接入口（hypit media fetch）：无本地上传时粘贴视频链接
  const [linkUrl, setLinkUrl] = useState("");
  const [linking, setLinking] = useState(false);
  const [linkAsset, setLinkAsset] = useState<{ asset_id: string; source_url: string } | null>(null);

  const effectiveAssetId = assetId ?? linkAsset?.asset_id ?? null;

  // 拉片耗时 1-3 分钟：秒级进度反馈，替代"一句静态提示看到底"
  useEffect(() => {
    if (!running) return;
    setElapsedSeconds(0);
    const startedAt = Date.now();
    const timer = window.setInterval(() => {
      setElapsedSeconds(Math.floor((Date.now() - startedAt) / 1000));
    }, 1000);
    return () => window.clearInterval(timer);
  }, [running]);

  // 卸载时断开未完成的等待，避免 setState on unmounted 组件
  useEffect(() => () => abortRef.current?.abort(), []);

  // D8：拆解是任务（后端 TeardownJobManager）。POST 只提交拿 job_id，
  // 状态/结果走轮询；取消调取消端点——协作式取消在下次 LLM 调用前真的停，
  // 不再出现"界面取消、后端照烧额度"。
  // 轮询上限 450 × 2s = 15 分钟，与后端总预算口径一致：超时明确失败。
  const TEARDOWN_POLL_LIMIT = 450;

  const pollTeardownJob = useCallback(async (jobId: string, signal: AbortSignal) => {
    for (let attempt = 0; attempt < TEARDOWN_POLL_LIMIT; attempt += 1) {
      const response = await fetch(`/api/v1/replica/teardown/jobs/${jobId}`, { signal });
      const body = await response.json().catch(() => null);
      if (response.status !== 200 || !body) {
        throw new Error(`任务状态查询失败 (HTTP ${response.status})`);
      }
      setJobStatus(String(body.status ?? ""));
      if (body.status === "completed") {
        setReport(body.report as TeardownReport);
        setVideoMeta((body.video_metadata as TeardownVideoMetadata) ?? null);
        // G6 缓存溯源：命中时如实告知"未消耗新 LLM 额度"（缓存是优化，不是秘密）
        setCacheInfo(
          body.cached
            ? { cached: true, cacheKey: typeof body.cache_key === "string" ? body.cache_key : "" }
            : null,
        );
        return;
      }
      if (body.status === "failed") {
        throw new Error(
          (typeof body.error === "string" && body.error) ||
            (typeof body.error_type === "string" && body.error_type) ||
            "拆解失败",
        );
      }
      if (body.status === "cancelled") {
        setCancelNote("⏹ 已取消：后端在下次调用前已停止，不再消耗额度。可调整后重新拉片。");
        return;
      }
      await new Promise((resolve) => window.setTimeout(resolve, 2000));
    }
    throw new Error(
      "拆解轮询超时（15 分钟）——任务可能仍在后台进行，请稍后重新拉片查看",
    );
  }, []);

  const runTeardown = useCallback(async () => {
    if (!effectiveAssetId) return;
    const controller = new AbortController();
    abortRef.current = controller;
    setRunning(true);
    setError(null);
    setCancelled(false);
    setCancelNote(null);
    setReport(null);
    setCacheInfo(null);
    setCopied(false);
    setBlueprintNodeId(null);
    setJobStatus("pending");
    try {
      const formData = new FormData();
      formData.append("asset_id", effectiveAssetId);
      if (goal) formData.append("user_description", goal);
      const response = await fetch("/api/v1/replica/teardown", {
        method: "POST",
        body: formData,
        signal: controller.signal,
      });
      const body = await response.json().catch(() => null);
      if (response.status !== 200 || !body?.job_id) {
        const detail = body?.detail;
        throw new Error(
          (typeof detail === "object" && detail?.error) ||
            (typeof detail === "string" && detail) ||
            `拉片失败 (HTTP ${response.status})`,
        );
      }
      jobIdRef.current = String(body.job_id);
      await pollTeardownJob(String(body.job_id), controller.signal);
    } catch (err) {
      if (err instanceof DOMException && err.name === "AbortError") {
        setCancelled(true);
      } else {
        setError(err instanceof Error ? err.message : "拉片失败");
      }
    } finally {
      setRunning(false);
    }
  }, [effectiveAssetId, goal, pollTeardownJob]);

  // D8：真取消——告诉后端停（下次 LLM 调用前生效），同时停前端轮询。
  const cancelTeardown = useCallback(async () => {
    const jobId = jobIdRef.current;
    abortRef.current?.abort();
    if (!jobId) {
      setCancelled(true);
      return;
    }
    try {
      const response = await fetch(`/api/v1/replica/teardown/jobs/${jobId}/cancel`, {
        method: "POST",
      });
      const body = await response.json().catch(() => null);
      if (response.status !== 200 || !body) {
        setError(`取消失败 (HTTP ${response.status})——后台任务可能仍在进行，可等待完成`);
        return;
      }
      if (body.cancelled) {
        setCancelNote("⏹ 已取消：后端在下次调用前已停止，不再消耗额度。可调整后重新拉片。");
      } else {
        setCancelNote(`⏹ 无需取消：${body.reason || "任务已结束"}`);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "取消失败");
    }
  }, []);

  const createBlueprintNode = useCallback(async () => {
    if (!report || !workflowId) return;
    setCreating(true);
    setError(null);
    try {
      // 1) report → blueprint（后端纯转换；时长/画幅来自真实视频元数据）
      const blueprintResponse = await fetch("/api/v1/replica/blueprint", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          report,
          source_video_asset_id: effectiveAssetId ?? "",
          duration_seconds: videoMeta?.duration_seconds ?? 0,
          aspect: aspectFromDimensions(videoMeta?.width ?? 0, videoMeta?.height ?? 0),
          replica_goal: goal,
        }),
      });
      const blueprintBody = await blueprintResponse.json().catch(() => null);
      if (blueprintResponse.status !== 200 || !blueprintBody) {
        const detail = blueprintBody?.detail;
        throw new Error(
          (typeof detail === "object" && detail?.error) ||
            (typeof detail === "string" && detail) ||
            `蓝图生成失败 (HTTP ${blueprintResponse.status})`,
        );
      }
      // 2) 创建 replica 节点（蓝图即结构化内容）
      const created = await agentCanvasApi.createAgentCanvasNode(workflowId, {
        node_type: "replica",
        creative_role: "replica_blueprint",
        role_contract_version: "ad-media-role-v2",
        title: `复刻蓝图 · ${blueprintBody.blueprint?.format_name ?? "reference"}`,
        summary_prompt: "拉片复刻蓝图：结构来自参考片拆解，槽位可编辑，可一键生成复刻工作流",
        generation_prompt: null,
        structured_content: blueprintBody.blueprint ?? {},
        model_selection_mode: "default",
        model_ref: null,
        parameters: {},
        position: { x: 320, y: 160 },
        source_asset_id: null,
      });
      setAgentCanvasWorkflow(created.value.workflow);
      setBlueprintNodeId(created.value.node?.node_id ?? null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "蓝图节点创建失败");
    } finally {
      setCreating(false);
    }
  }, [effectiveAssetId, goal, report, setAgentCanvasWorkflow, videoMeta, workflowId]);

  const copyDraft = useCallback(async () => {
    if (!report?.replica_storyboard_draft) return;
    try {
      await navigator.clipboard.writeText(report.replica_storyboard_draft);
      setCopied(true);
    } catch {
      setError("复制失败，请在下方草稿中手动选择复制");
    }
  }, [report]);

  const ingestLink = useCallback(async () => {
    if (!linkUrl.trim() || linking) return;
    setLinking(true);
    setError(null);
    setReport(null);
    setBlueprintNodeId(null);
    try {
      const response = await fetch("/api/v1/replica/ingest-link", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ url: linkUrl.trim() }),
      });
      const body = await response.json().catch(() => null);
      if (response.status !== 200 || !body) {
        const detail = body?.detail;
        throw new Error(
          (typeof detail === "object" && detail?.error) ||
            (typeof detail === "string" && detail) ||
            `链接抓取失败 (HTTP ${response.status})`,
        );
      }
      setLinkAsset({ asset_id: body.asset_id, source_url: body.source_url });
      setLinkUrl("");
    } catch (err) {
      setError(err instanceof Error ? err.message : "链接抓取失败");
    } finally {
      setLinking(false);
    }
  }, [linkUrl, linking]);

  if (!effectiveAssetId) {
    return (
      <div style={{ color: "#ccc", fontSize: 10, fontFamily: "monospace", lineHeight: 1.6 }}>
        <div style={{ color: "#555", fontSize: 9, marginBottom: 6 }}>
          上传参考视频（Reference 页上方）或粘贴视频链接，即可进行拉片复刻。
        </div>
        <div style={{ display: "flex", gap: 4 }}>
          <input
            value={linkUrl}
            onChange={(event) => setLinkUrl(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Enter") void ingestLink();
            }}
            placeholder="https://www.bilibili.com/video/BV…（服务端下载，≤60s）"
            style={{
              flex: 1,
              background: "#16162a",
              border: "1px solid #2a2a4a",
              borderRadius: 3,
              color: "#ccc",
              fontSize: 9,
              fontFamily: "monospace",
              padding: "3px 6px",
            }}
          />
          <button
            onClick={() => void ingestLink()}
            disabled={linking || !linkUrl.trim()}
            style={{
              background: linking || !linkUrl.trim() ? "#2a2a4a" : "#3a5a8a",
              border: "none",
              color: linking || !linkUrl.trim() ? "#666" : "#fff",
              padding: "3px 8px",
              borderRadius: 3,
              cursor: linking || !linkUrl.trim() ? "default" : "pointer",
              fontSize: 9,
            }}
          >
            {linking ? "⏳ 抓取中…" : "🔗 抓取"}
          </button>
        </div>
        {error && (
          <div style={{ color: "#f88", fontSize: 9, marginTop: 4 }}>⚠ {error}</div>
        )}
      </div>
    );
  }

  return (
    <div style={{ color: "#ccc", fontSize: 11, fontFamily: "monospace" }}>
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
          marginBottom: 8,
          gap: 6,
        }}
      >
        <span style={{ color: "#888", fontSize: 10 }}>拉片复刻 · 参考片拆解</span>
        <button
          onClick={() => void runTeardown()}
          disabled={running}
          style={{
            background: running ? "#2a2a4a" : "#3a5a8a",
            border: "none",
            color: running ? "#666" : "#fff",
            padding: "4px 10px",
            borderRadius: 3,
            cursor: running ? "default" : "pointer",
            fontSize: 10,
          }}
        >
          {running ? "⏳ 拉片中…" : "🎬 拉片复刻"}
        </button>
      </div>

      {linkAsset && !assetId && (
        <div style={{ color: "#4f4", fontSize: 9, marginBottom: 6 }}>
          🔗 来源：链接导入（{linkAsset.source_url.slice(0, 48)}…）
        </div>
      )}

      <label
        style={{
          display: "flex",
          alignItems: "center",
          gap: 6,
          marginBottom: 8,
          fontSize: 10,
          color: "#888",
        }}
      >
        复刻目标
        <select
          value={goal}
          onChange={(e) => setGoal(e.target.value)}
          disabled={running}
          style={{
            flex: 1,
            background: "#16162a",
            border: "1px solid #2a2a4a",
            borderRadius: 3,
            color: "#ccc",
            fontSize: 10,
            fontFamily: "monospace",
            padding: "3px 6px",
          }}
        >
          {REPLICA_GOALS.map((option) => (
            <option key={option.value} value={option.value}>
              {option.label}
            </option>
          ))}
        </select>
      </label>

      {running && (
        <div
          style={{
            background: "#141c2e",
            border: "1px solid #2a3a5a",
            borderRadius: 4,
            padding: "6px 10px",
            marginBottom: 8,
            color: "#4a9eff",
            fontSize: 10,
            lineHeight: 1.7,
          }}
        >
          正在读片：抽帧 → 逐帧分析 → 综合拆解 → 生成复刻草稿
          <br />
          已进行 <span style={{ color: "#8cf" }}>{elapsedSeconds}s</span>
          {jobStatus === "running" ? "（分析中）" : jobStatus ? `（${jobStatus}）` : ""}
          （通常 1-3 分钟；期间可以继续其他操作，完成后报告出现在这里）
          <button
            onClick={() => void cancelTeardown()}
            style={{
              marginLeft: 8,
              background: "transparent",
              border: "1px solid #2a3a5a",
              color: "#889",
              padding: "1px 8px",
              borderRadius: 3,
              cursor: "pointer",
              fontSize: 9,
            }}
          >
            ⏹ 取消等待
          </button>
        </div>
      )}

      {cancelNote && (
        <div style={{ color: "#ca8", fontSize: 10, marginBottom: 8 }}>{cancelNote}</div>
      )}

      {cancelled && !cancelNote && (
        <div style={{ color: "#ca8", fontSize: 10, marginBottom: 8 }}>
          ⏹ 已取消等待：前端已停止轮询，后端任务如仍在跑会在下次调用前停止。
        </div>
      )}

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

      {report && (
        <div style={{ maxHeight: height, overflow: "auto" }}>
          <div style={{ display: "flex", gap: 6, marginBottom: 8 }}>
            <button
              onClick={() => void createBlueprintNode()}
              disabled={creating || !workflowId}
              title={workflowId ? "" : "当前画布不可用"}
              style={{
                background: creating || !workflowId ? "#2a2a4a" : "#3a5a8a",
                border: "none",
                color: creating || !workflowId ? "#666" : "#fff",
                padding: "4px 10px",
                borderRadius: 3,
                cursor: creating || !workflowId ? "default" : "pointer",
                fontSize: 10,
              }}
            >
              {creating ? "⏳ 创建中…" : "🧬 创建复刻蓝图"}
            </button>
          </div>

          {blueprintNodeId && (
            <div
              style={{
                background: "#1a2a1a",
                border: "1px solid #2a4a2a",
                borderRadius: 4,
                padding: "8px 10px",
                marginBottom: 10,
                fontSize: 10,
                lineHeight: 1.7,
              }}
            >
              <div style={{ color: "#4f4" }}>✓ 复刻蓝图已创建（节点 {blueprintNodeId}）</div>
              <div style={{ color: "#888", marginTop: 3 }}>
                下一步：在画布上打开该「复刻蓝图」节点 → 工作台里替换槽位（人/货/词/
                风格/声音）→ 点「⚡ 生成复刻工作流」落到 script 节点。
              </div>
            </div>
          )}

          {/* 整片解读 */}
          <div style={cardStyle()}>
            {sectionLabel(
              `整片解读 · ${report.format_name || "short-video"}` +
                (report.transcript?.source === "whisperx"
                  ? ` · 词级转录 ${report.transcript.lines.length} 句`
                  : "") +
                (videoMeta?.duration_seconds ? ` · ${videoMeta.duration_seconds.toFixed(1)}s` : "") +
                (() => {
                  const aspect = aspectFromDimensions(videoMeta?.width ?? 0, videoMeta?.height ?? 0);
                  return aspect ? ` · ${aspect}` : "";
                })(),
            )}
            <div style={{ lineHeight: 1.6 }}>
              {report.whole_piece_reading || "（未生成）"}
            </div>
            {cacheInfo?.cached && (
              <div
                style={{
                  marginTop: 6,
                  padding: "3px 8px",
                  borderRadius: 3,
                  background: "#1e3a1e",
                  color: "#8f8",
                  fontSize: 10,
                }}
                title={cacheInfo.cacheKey ? `缓存键 ${cacheInfo.cacheKey}` : undefined}
              >
                ♻️ 缓存命中：相同视频与参数的既有拆解报告，未调用 LLM（零新增额度消耗）
              </div>
            )}
          </div>

          {/* 结构 Beats */}
          {report.beats.length > 0 && (
            <div style={cardStyle()}>
              {sectionLabel("结构")}
              {report.beats.map((beat, i) => (
                <div key={`${beat.role}-${i}`} style={{ marginBottom: 3 }}>
                  <span style={{ color: "#8f8" }}>
                    [{beat.start_seconds.toFixed(1)}–{beat.end_seconds.toFixed(1)}s]
                  </span>{" "}
                  <span style={{ color: "#fc8" }}>{beat.role}</span>：
                  {beat.description}
                  {beat.line && (
                    <div style={{ color: "#6a6", fontSize: 9, marginLeft: 8 }}>
                      「{beat.line}」
                    </div>
                  )}
                </div>
              ))}
            </div>
          )}

          {/* 镜头表 */}
          <div style={cardStyle()}>
            {sectionLabel(`镜头表（${report.shots.length} 个镜头）`)}
            <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 10 }}>
              <thead>
                <tr style={{ color: "#666", textAlign: "left" }}>
                  <th style={{ padding: "2px 4px" }}>#</th>
                  <th style={{ padding: "2px 4px" }}>时间</th>
                  <th style={{ padding: "2px 4px" }}>景别/运镜</th>
                  <th style={{ padding: "2px 4px" }}>内容</th>
                  <th style={{ padding: "2px 4px" }}>屏上文字</th>
                </tr>
              </thead>
              <tbody>
                {report.shots.map((shot) => (
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
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          {/* 节奏 + 系统 */}
          <div style={cardStyle()}>
            {sectionLabel("节奏")}
            <div style={{ marginBottom: 6 }}>
              平均镜头 {report.rhythm.avg_shot_seconds.toFixed(1)}s · 切点：
              {report.rhythm.cut_points_seconds.map((c) => c.toFixed(1)).join(", ")}
              {report.rhythm.energy_curve ? ` · ${report.rhythm.energy_curve}` : ""}
            </div>
            {sectionLabel("视觉系统")}
            <div style={{ lineHeight: 1.6 }}>
              字幕：{report.systems.captions || "未检测到"}
              <br />
              音乐：{report.systems.music || "未检测到"}
              <br />
              图形/MG：
              {report.systems.graphics.length > 0
                ? report.systems.graphics.join("；")
                : "未检测到"}
              <br />
              音效：
              {report.systems.sfx.length > 0 ? report.systems.sfx.join("；") : "未检测到"}
            </div>
          </div>

          {/* 边界声明 */}
          {report.constraints.length > 0 && (
            <div
              style={{
                ...cardStyle(),
                border: "1px solid #5a4a2a",
                color: "#ca8",
              }}
            >
              {sectionLabel("边界声明")}
              {report.constraints.map((c, i) => (
                <div key={i} style={{ marginBottom: 3 }}>
                  • {c}
                </div>
              ))}
            </div>
          )}

          {/* 复刻分镜草稿：进入正常创作流的桥 */}
          <div style={cardStyle()}>
            <div
              style={{
                display: "flex",
                justifyContent: "space-between",
                alignItems: "center",
                marginBottom: 6,
              }}
            >
              <span style={{ color: "#888", fontSize: 10, letterSpacing: 1 }}>
                复刻分镜草稿
              </span>
              <button
                onClick={() => void copyDraft()}
                style={{
                  background: copied ? "#2a4a2a" : "#3a3a6a",
                  border: "none",
                  color: copied ? "#4f4" : "#fff",
                  padding: "3px 10px",
                  borderRadius: 3,
                  cursor: "pointer",
                  fontSize: 10,
                }}
              >
                {copied ? "✓ 已复制" : "📋 复制草稿"}
              </button>
            </div>
            <div style={{ color: "#888", fontSize: 9, marginBottom: 6 }}>
              复制后粘贴到 Script 节点或 Agent 对话，即可带着原片结构继续创作。
            </div>
            <pre
              style={{
                margin: 0,
                padding: 8,
                background: "#101018",
                borderRadius: 3,
                maxHeight: 200,
                overflow: "auto",
                color: "#8f8",
                fontSize: 10,
                whiteSpace: "pre-wrap",
                wordBreak: "break-word",
              }}
            >
              {report.replica_storyboard_draft}
            </pre>
          </div>
        </div>
      )}

      {!report && !running && !error && (
        <div style={{ color: "#555", fontSize: 9, lineHeight: 1.5 }}>
          对已上传的参考视频进行拉片：输出整片解读、结构 Beats、镜头表（景别/
          运镜/屏上文字）、节奏与视觉系统，并生成复刻分镜草稿。镜头边界为
          推断值——复刻结构，不复刻像素。
        </div>
      )}
    </div>
  );
}
