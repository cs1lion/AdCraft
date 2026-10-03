/**
 * OutlineStarter — 从一句话开始（Flow B 的入口，2026-09-29 简约好用分支）。
 *
 * 写一条纲领 → 展开成镜（LLM）→ 审一眼 → 开始生成（设定图 + 成片节点 +
 * 一次 run）。作者看不见 script 节点 / 分镜阶段 / provider 词汇。
 */

import { useCallback, useEffect, useId, useRef, useState } from "react";
import { bumpTimelineMutationRefresh } from "./timeline/timelineMutationRefresh.ts";
import { finalRenderStatePath } from "../../api/finalRenderPaths.ts";

interface OutlineShot {
  summary: string;
  visual: string;
  duration_seconds: number;
  on_screen_text: string;
}

type Busy = "idle" | "expand" | "build";
type Stage = "idle" | "shots" | "shots-paused" | "assembling" | "assemble-failed" | "rendering" | "render-paused" | "render-failed" | "complete";
interface RenderState {
  status?: string;
  progress_percent?: number;
  output_url?: string;
  error_message?: string;
  error_code?: string;
}
const POLL_DELAY = 6000;
const RENDER_POLL_DELAY = 2000;
const MAX_STATUS_FAILURES = 3;
const MAX_RENDER_POLLS = 150;

export function OutlineStarter({ workflowId, showEntry = true }: { workflowId: string; showEntry?: boolean }) {
  const [outline, setOutline] = useState("");
  const [shots, setShots] = useState<OutlineShot[]>([]);
  const [busy, setBusy] = useState<Busy>("idle");
  const [error, setError] = useState<string | null>(null);
  const [status, setStatus] = useState<string | null>(null);
  const outlineId = useId();
  const generationRef = useRef(0);
  const busyRef = useRef(false);
  const [expandedOutline, setExpandedOutline] = useState<string | null>(null);
  const [accepted, setAccepted] = useState(false);
  const [stage, setStage] = useState<Stage>("idle");
  const [renderId, setRenderId] = useState<string | null>(null);
  const [videoUrl, setVideoUrl] = useState<string | null>(null);
  const filmIdsRef = useRef<string[]>([]);
  const readyIdsRef = useRef<string[]>([]);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const waitForPoll = useCallback((delay: number) => new Promise<void>((resolve) => {
    timerRef.current = setTimeout(() => { timerRef.current = null; resolve(); }, delay);
  }), []);
  const [editingShot, setEditingShot] = useState<number | null>(null);
  const shotsValid = shots.every((shot) => shot.summary.trim() && shot.visual.trim() && Number.isFinite(shot.duration_seconds) && shot.duration_seconds > 0 && shot.duration_seconds <= 120);
  const patchShot = (index: number, patch: Partial<OutlineShot>) => {
    setShots((current) => current.map((shot, shotIndex) => shotIndex === index ? { ...shot, ...patch } : shot));
  };
  const previewStale = shots.length > 0 && expandedOutline !== outline.trim();
  useEffect(() => {
    generationRef.current += 1;
    busyRef.current = false;
    setBusy("idle");
    setShots([]);
    setEditingShot(null);
    setOutline("");
    setExpandedOutline(null);
    setAccepted(false);
    setStage("idle");
    setRenderId(null);
    setVideoUrl(null);
    filmIdsRef.current = [];
    readyIdsRef.current = [];
    setError(null);
    setStatus(null);
    return () => {
      generationRef.current += 1;
      if (timerRef.current !== null) clearTimeout(timerRef.current);
    };
  }, [workflowId]);

  const expand = useCallback(async () => {
    if (busyRef.current || !outline.trim() || accepted) return;
    busyRef.current = true;
    const generation = ++generationRef.current;
    const submittedOutline = outline.trim();
    setBusy("expand");
    setError(null);
    setStatus(null);
    try {
      const response = await fetch("/api/v1/creation/expand-outline", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ outline: submittedOutline }),
      });
      const body = (await response.json().catch(() => null)) as {
        success?: boolean;
        shots?: OutlineShot[];
        error?: string;
      } | null;
      if (generation !== generationRef.current) return;
      if (!response.ok || !body?.success) throw new Error(body?.error || "展开失败");
      const nextShots = body.shots ?? [];
      if (!nextShots.length) throw new Error("没有得到可用分镜，请补充创意后重试。");
      setShots(nextShots);
      setExpandedOutline(submittedOutline);
      setStatus(`分镜已准备：${nextShots.length} 镜。确认内容后再开始生成。`);
    } catch (err) {
      if (generation === generationRef.current) setError(err instanceof Error ? err.message : "展开失败");
    } finally {
      if (generation === generationRef.current) {
        busyRef.current = false;
        setBusy("idle");
      }
    }
  }, [outline, accepted]);

  const pollRender = useCallback(async (id: string, generation: number) => {
    const isCurrent = () => generation === generationRef.current;
    let failures = 0;
    setStage("rendering");
    setError(null);
    setStatus("成片渲染中…");
    for (let attempt = 0; attempt < MAX_RENDER_POLLS && isCurrent(); attempt += 1) {
      try {
        const response = await fetch(finalRenderStatePath(workflowId, id));
        const body = await response.json().catch(() => null) as RenderState | null;
        if (!isCurrent()) return;
        if (!response.ok || !body?.status) throw new Error("渲染状态查询失败");
        failures = 0;
        if (body.status === "completed") {
          if (!body.output_url || !/^(https?:\/\/|\/(?!\/))/.test(body.output_url)) {
            setStage("render-paused");
            setError("渲染已完成，但尚未返回视频地址。请重新查询原渲染，不必重新合成。");
          } else {
            setVideoUrl(body.output_url);
            setStage("complete");
            setStatus("✓ 成片已完成");
          }
          busyRef.current = false;
          return;
        }
        if (body.status === "failed" || body.status === "cancelled") {
          setStage("render-failed");
          setStatus("成片渲染未完成，镜头已保留");
          setError(body.error_message || body.error_code || (body.status === "cancelled" ? "渲染已取消" : "渲染失败"));
          busyRef.current = false;
          return;
        }
        const progress = typeof body.progress_percent === "number" && Number.isFinite(body.progress_percent)
          ? `（${Math.round(Math.max(0, Math.min(100, body.progress_percent)))}%）` : "";
        setStatus(`成片渲染中${progress}，无需重新生成镜头。`);
      } catch {
        if (!isCurrent()) return;
        failures += 1;
        setStatus("暂时无法查询渲染状态；原渲染仍在后台运行。");
        if (failures >= MAX_STATUS_FAILURES) break;
      }
      if (attempt + 1 < MAX_RENDER_POLLS) await waitForPoll(RENDER_POLL_DELAY);
    }
    if (!isCurrent()) return;
    busyRef.current = false;
    setStage("render-paused");
    setError("渲染状态查询已暂停（连续失败或超时）。请重新查询原渲染，不会创建新渲染。");
  }, [workflowId, waitForPoll]);

  // Only IDs cached after every returned shot is ready may reach assembly.
  const assembleReadyShots = useCallback(async (scopedIds: string[], generation: number) => {
    const isCurrent = () => generation === generationRef.current;
    if (!isCurrent() || !scopedIds.length) return;
    setStage("assembling");
    setStatus("镜头已就绪，正在合成成片…");
    setError(null);
    setVideoUrl(null);
    setRenderId(null);
    try {
      const response = await fetch("/api/v1/creation/assemble-film", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ workflow_id: workflowId, node_ids: scopedIds }),
      });
      const body = await response.json().catch(() => null) as { success?: boolean; render_id?: string; error?: string } | null;
      if (!isCurrent()) return;
      if (!response.ok || body?.success === false || body?.error || !body?.render_id) throw new Error(body?.error || "合成未返回可查询的渲染编号。镜头已保留。");
      setRenderId(body.render_id);
      bumpTimelineMutationRefresh();
      await pollRender(body.render_id, generation);
    } catch (err) {
      if (!isCurrent()) return;
      busyRef.current = false;
      setStage("assemble-failed");
      setStatus("合成失败，已就绪镜头已保留");
      setError(err instanceof Error ? err.message : "合成失败");
    }
  }, [workflowId, pollRender]);

  const pollShots = useCallback(async (generation: number) => {
    const isCurrent = () => generation === generationRef.current;
    let failures = 0;
    setStage("shots");
    setError(null);
    for (let attempt = 0; attempt < 300; attempt += 1) {
      await waitForPoll(POLL_DELAY);
      if (!isCurrent()) return;
      try {
        const response = await fetch(`/api/v2/workflows/${encodeURIComponent(workflowId)}`);
        const body = await response.json() as { nodes?: Array<{ node_id: string; status?: string }> };
        if (!isCurrent()) return;
        if (!response.ok || !Array.isArray(body.nodes)) throw new Error("镜头状态查询失败");
        failures = 0;
        const films = filmIdsRef.current.map((id) => body.nodes?.find((node) => node.node_id === id));
        if (films.some((node) => node?.status === "failed")) {
          setError("部分镜头生成失败。请在画布选中失败节点检查原因并重试，再重新查询镜头；不必重新搭建整个项目。");
          break;
        }
        const ready = films.filter((node) => node?.status === "ready");
        if (ready.length !== films.length) {
          setStatus(`生成中（${ready.length}/${films.length} 镜就绪）`);
          continue;
        }
        readyIdsRef.current = [...filmIdsRef.current];
        await assembleReadyShots(readyIdsRef.current, generation);
        return;
      } catch {
        if (!isCurrent()) return;
        failures += 1;
        setStatus("暂时无法查询生成状态；后台生成不会因此中断。");
        if (failures >= MAX_STATUS_FAILURES) break;
      }
    }
    if (!isCurrent()) return;
    busyRef.current = false;
    setStage("shots-paused");
    setError((current) => current || "镜头状态查询已暂停（连续失败或超时）。请重新查询镜头，勿重复搭建。");
  }, [workflowId, waitForPoll, assembleReadyShots]);

  const retryStage = () => {
    if (busyRef.current) return;
    busyRef.current = true;
    const generation = ++generationRef.current;
    if (stage === "render-paused" && renderId) void pollRender(renderId, generation);
    else if (stage === "shots-paused") void pollShots(generation);
    else if (stage === "assemble-failed" || stage === "render-failed") void assembleReadyShots(readyIdsRef.current, generation);
    else busyRef.current = false;
  };

  const build = useCallback(async () => {
    if (busyRef.current || accepted || !shots.length || previewStale || !shotsValid) return;
    busyRef.current = true;
    const generation = ++generationRef.current;
    const isCurrent = () => generation === generationRef.current;
    setBusy("build");
    setError(null);
    setStatus("搭建中…");
    try {
      const response = await fetch("/api/v1/creation/build-from-outline", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ workflow_id: workflowId, outline, shots }),
      });
      const body = (await response.json().catch(() => null)) as {
        success?: boolean;
        error?: string;
        film_node_ids?: string[];
      } | null;
      if (!isCurrent()) return;
      if (!response.ok || !body?.success) {
        throw new Error(body?.error || `搭建失败 (HTTP ${response.status})`);
      }
      setAccepted(true);
      const ids = body.film_node_ids;
      if (!Array.isArray(ids) || !ids.length || ids.some((id) => typeof id !== "string" || !id.trim())) {
        setError("搭建已接受，但未返回本次成片镜头编号。请在画布检查本次节点或联系支持；不要重复搭建，也不会猜测旧镜头进行合成。");
        setStatus("无法追踪本次镜头");
        return;
      }
      filmIdsRef.current = [...new Set(ids)];
      setStatus("已开画（设定图与成片镜头生成中，节点上可见进度）");
      void pollShots(generation);
    } catch (err) {
      if (isCurrent()) {
        setError(err instanceof Error ? err.message : "搭建失败");
        setStatus(null);
      }
    } finally {
      if (isCurrent()) {
        if (!filmIdsRef.current.length) busyRef.current = false;
        setBusy("idle");
      }
    }
  }, [outline, shots, workflowId, accepted, previewStale, shotsValid, pollShots]);

  const progress = <>
    {status && <div className="agent-canvas-outline-starter__status" role="status" aria-live="polite">{status}</div>}
    {error && <div className="agent-canvas-outline-starter__error" role="alert">{error}</div>}
    {(stage === "assemble-failed" || stage === "render-failed") && <>
      <p>仅使用已就绪镜头重新合成（新 FFmpeg 渲染），不调用模型、不重新生成素材。</p>
      <button type="button" onClick={retryStage}>仅重试合成</button>
    </>}
    {stage === "render-paused" && <button type="button" onClick={retryStage}>重新查询原渲染</button>}
    {stage === "shots-paused" && <button type="button" onClick={retryStage}>重新查询镜头</button>}
    {stage === "complete" && videoUrl && <details open={showEntry}>
      <summary>成片已就绪 · 预览/下载</summary>
      <video controls preload="metadata" src={videoUrl} aria-label="成片预览" />
      <div className="agent-canvas-outline-starter__actions">
        <a href={videoUrl} target="_blank" rel="noopener noreferrer">打开成片</a>
        <a href={videoUrl} download>下载成片</a>
      </div>
    </details>}
  </>;

  // Keep the accepted owner mounted, with stage-local controls even in compact mode.
  if (!showEntry) return accepted ? <div className="agent-canvas-outline-starter" aria-label="从创意到成片的进度">{progress}</div> : null;

  return (
    <div className="agent-canvas-outline-starter">
      <label htmlFor={outlineId}><b>从一句话开始</b></label>
      <p id={`${outlineId}-help`}>先展开并确认分镜，再开始素材生成。生成可能调用已配置模型并产生费用。</p>
      <textarea
        id={outlineId}
        aria-describedby={`${outlineId}-help`}
        disabled={busy !== "idle" || accepted}
        value={outline}
        onChange={(event) => setOutline(event.target.value)}
        placeholder="例如：一条 20 秒的红苹果清晨广告——果园阳光、切开慢动作、家人分享"
        rows={3}
      />
      <div className="agent-canvas-outline-starter__actions">
        <button type="button" onClick={() => void expand()} disabled={busy !== "idle" || !outline.trim() || accepted}>
          {busy === "expand" ? "展开中…" : shots.length ? "重新展开" : "展开分镜"}
        </button>
        {shots.length > 0 && (
          <button
            type="button"
            className="agent-canvas-outline-starter__primary"
            onClick={() => void build()}
            disabled={busy !== "idle" || previewStale || accepted || !shotsValid}
            title={previewStale ? "创意已修改，请重新展开分镜" : undefined}
          >
            {accepted ? "已开始生成" : busy === "build" ? "提交生成中…" : `开始生成（${shots.length} 镜）`}
          </button>
        )}
      </div>
      {previewStale && <div className="agent-canvas-outline-starter__status" role="status">创意已修改，请重新展开分镜，避免按旧分镜生成。</div>}
      {progress}
      {shots.length > 0 && !accepted && <p>可以直接修改某个镜头的画面、文案或时长，不必重新展开整份创意。</p>}
      {shots.length > 0 && !shotsValid && <div role="alert">请补齐镜头标题和画面，并填写 0–120 秒范围内的有效时长（不能为 0）。</div>}
      {shots.length > 0 && (
        <ol className="agent-canvas-outline-starter__shots">
          {shots.map((shot, index) => (
            <li key={index}>
              <b>{shot.summary}</b>
              <span>（{shot.duration_seconds.toFixed(0)}s）</span>
              <p>{shot.visual}</p>
              {shot.on_screen_text && <p>屏上文字：{shot.on_screen_text}</p>}
              {!accepted && <button type="button" disabled={busy !== "idle" || previewStale} aria-expanded={editingShot === index} onClick={() => setEditingShot(editingShot === index ? null : index)}>{editingShot === index ? "收起修改" : `修改镜头 ${index + 1}`}</button>}
              {editingShot === index && !accepted && <fieldset disabled={busy !== "idle" || previewStale}>
                <legend>修改镜头 {index + 1} · 修改会直接用于生成</legend>
                <label>镜头 {index + 1} 标题<input value={shot.summary} onChange={(event) => patchShot(index, { summary: event.target.value })} /></label>
                <label>镜头 {index + 1} 画面<textarea value={shot.visual} onChange={(event) => patchShot(index, { visual: event.target.value })} rows={3} /></label>
                <label>镜头 {index + 1} 屏上文字<input value={shot.on_screen_text} onChange={(event) => patchShot(index, { on_screen_text: event.target.value })} placeholder="留空则不添加文字" /></label>
                <label>镜头 {index + 1} 时长（秒）<input type="number" min="0.1" max="120" step="0.1" value={Number.isFinite(shot.duration_seconds) ? shot.duration_seconds : ""} onChange={(event) => patchShot(index, { duration_seconds: event.target.value === "" ? NaN : Number(event.target.value) })} /></label>
              </fieldset>}
            </li>
          ))}
        </ol>
      )}
    </div>
  );
}
