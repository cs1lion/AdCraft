/**
 * SyncComparePanel — 同步对比播放（画布工具条 → 对比播放）。
 *
 * 两条视频（默认白模预演 vs 最终成片）双播放器同步 Transport：
 * 共同播放/暂停/seek/倍速，漂移超阈值自动校正；支持并排、滑动分割、差异混合三种视图。
 * B 侧偏移支持 ±0.1s 微调，补偿两侧成片节奏的固定时间差；音源三档（A/B/静）默认 A，
 * 避免两路音频打架（对标 Premiere 参考监视器的单路参考音）。
 * 只读展示，不参与生成链路。
 */

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";

import { agentCanvasApi } from "../../../api/agentCanvasApi.ts";
import { CloseIcon } from "../../../icons.tsx";
import type { AgentCanvasWorkflowV2, V2AssetVersionListResponse } from "../../../types-v2.ts";
import {
  aspectMismatch,
  assetVersionContentPath,
  bestOffsetByNcc,
  clampOffsetSeconds,
  collectSyncCompareCandidates,
  expectedRightTime,
  FRAME_RATE,
  loopBoundaryTime,
  pickPreviousVersion,
  pickSyncCompareDefaults,
  SYNC_DRIFT_TOLERANCE,
  SYNC_HARD_SEEK_SECONDS,
  SYNC_OFFSET_LIMIT,
  type SyncCompareCandidate,
} from "./syncCompareModel.ts";
import "./SyncComparePanel.css";

export interface SyncComparePanelProps {
  workflow: AgentCanvasWorkflowV2;
  open: boolean;
  onClose: () => void;
  /** 测试注入点：亮度轨迹采样（默认 canvas 实现，逐 seek 读像素均值） */
  sampleTracks?: (video: HTMLVideoElement, times: number[]) => Promise<number[]>;
  /** 测试注入点：版本链获取（默认走 agentCanvasApi） */
  listVersions?: (assetId: string) => Promise<V2AssetVersionListResponse>;
}

type CompareMode = "split" | "wipe" | "diff";
type AudioSide = "A" | "B" | "mute";

const SYNC_POLL_MS = 220;
const RATES = [0.5, 1, 1.5, 2] as const;
const MODES: Array<{ value: CompareMode; label: string }> = [
  { value: "split", label: "并排" },
  { value: "wipe", label: "滑动分割" },
  { value: "diff", label: "差异" },
];
const AUDIO_SIDES: Array<{ value: AudioSide; label: string }> = [
  { value: "A", label: "A" },
  { value: "B", label: "B" },
  { value: "mute", label: "静音" },
];

function formatTime(seconds: number): string {
  if (!Number.isFinite(seconds) || seconds < 0) return "0:00.0";
  const m = Math.floor(seconds / 60);
  const s = seconds - m * 60;
  return `${m}:${s.toFixed(1).padStart(4, "0")}`;
}

/** 默认亮度轨迹采样：逐 seek 后把当前帧缩到 32×18 读 luma 均值（同源视频不污染 canvas） */
async function sampleLumaTrack(video: HTMLVideoElement, times: number[]): Promise<number[]> {
  const canvas = document.createElement("canvas");
  canvas.width = 32;
  canvas.height = 18;
  const context = canvas.getContext("2d", { willReadFrequently: true });
  if (!context) throw new Error("canvas_2d_unavailable");
  const track: number[] = [];
  for (const t of times) {
    await new Promise<void>((resolve) => {
      const onSeeked = () => {
        video.removeEventListener("seeked", onSeeked);
        resolve();
      };
      video.addEventListener("seeked", onSeeked);
      video.currentTime = t;
    });
    context.drawImage(video, 0, 0, canvas.width, canvas.height);
    const { data } = context.getImageData(0, 0, canvas.width, canvas.height);
    let sum = 0;
    for (let i = 0; i < data.length; i += 4) {
      sum += 0.299 * data[i] + 0.587 * data[i + 1] + 0.114 * data[i + 2];
    }
    track.push(sum / (data.length / 4));
  }
  return track;
}

export function SyncComparePanel({ workflow, open, onClose, sampleTracks, listVersions }: SyncComparePanelProps) {
  const candidates = useMemo(() => collectSyncCompareCandidates(workflow), [workflow]);
  const defaults = useMemo(() => pickSyncCompareDefaults(candidates), [candidates]);
  const [leftId, setLeftId] = useState<string | null>(defaults.leftId);
  const [rightId, setRightId] = useState<string | null>(defaults.rightId);
  const [mode, setMode] = useState<CompareMode>("split");
  const [divider, setDivider] = useState(50);
  const [audioSide, setAudioSide] = useState<AudioSide>("A");
  const [playing, setPlaying] = useState(false);
  const [time, setTime] = useState(0);
  const [duration, setDuration] = useState(0);
  const [rate, setRate] = useState<number>(1);
  const [driftFixed, setDriftFixed] = useState(0);
  // B 侧偏移（秒）：B 的媒体时间 = A 的主时钟时间 + 偏移。左侧内容领先时取正值。
  const [offsetB, setOffsetB] = useState(0);
  // NLE I/O 区间（秒）：主时钟越过出点回入点；入/出都未设时自然播放
  const [inPoint, setInPoint] = useState<number | null>(null);
  const [outPoint, setOutPoint] = useState<number | null>(null);
  // 视频加载失败反馈（404/资产清理）；换源或重试时清除
  const [loadError, setLoadError] = useState<{ side: "left" | "right"; url: string } | null>(null);
  // 两侧画框尺寸：wipe/diff 叠加对比的错位提示
  const [dims, setDims] = useState<{ left: { w: number; h: number } | null; right: { w: number; h: number } | null }>({ left: null, right: null });
  // 自动对齐（亮度轨迹 NCC）：运行中标记与结果提示
  const [aligning, setAligning] = useState(false);
  const [alignNote, setAlignNote] = useState<string | null>(null);
  // 版本栈（Frame.io Version Stack）：右侧切到左侧节点输出的历史版本
  const [versionOverride, setVersionOverride] = useState<{ assetId: string; versionId: string; versionNo: number; label: string } | null>(null);
  const [versionBusy, setVersionBusy] = useState(false);
  const [versionNote, setVersionNote] = useState<string | null>(null);
  const leftRef = useRef<HTMLVideoElement>(null);
  const rightRef = useRef<HTMLVideoElement>(null);
  const stageRef = useRef<HTMLDivElement>(null);
  const panelRef = useRef<HTMLDivElement>(null);

  const left = candidates.find((c) => c.node.node_id === leftId) ?? null;
  const right = candidates.find((c) => c.node.node_id === rightId) ?? null;
  const leftUrl = left?.url ?? null;
  const rightUrl = right?.url ?? null;
  // 右侧实际展示源：版本栈覆盖优先，否则取节点当前输出
  const rightSource = versionOverride
    ? {
        url: assetVersionContentPath(versionOverride.assetId, versionOverride.versionId),
        title: versionOverride.label,
      }
    : right
      ? { url: right.url, title: right.node.title || right.node.node_id }
      : null;

  // 打开时重置 Transport；候选或产物版本变化（url 变）也重置（偏移/区间/版本栈按对记忆，换对归零）
  useEffect(() => {
    setPlaying(false);
    setTime(0);
    setDriftFixed(0);
    setOffsetB(0);
    setInPoint(null);
    setOutPoint(null);
    setLoadError(null);
    setDims({ left: null, right: null });
    setVersionOverride(null);
    setVersionNote(null);
    for (const ref of [leftRef, rightRef]) {
      const el = ref.current;
      if (el) {
        el.pause();
        el.currentTime = 0;
      }
    }
  }, [leftId, rightId, open, leftUrl, rightUrl]);

  // 倍速同步
  useEffect(() => {
    for (const ref of [leftRef, rightRef]) {
      if (ref.current) ref.current.playbackRate = rate;
    }
  }, [rate, leftId, rightId]);

  // 主时钟：左侧 video 的 timeupdate 驱动显示；双播放器漂移校正（含 B 侧偏移）
  useEffect(() => {
    if (!open) return;
    const id = window.setInterval(() => {
      const a = leftRef.current;
      const b = rightRef.current;
      if (!a) return;
      setTime(a.currentTime);
      if (Number.isFinite(a.duration) && a.duration > 0) setDuration(a.duration);
      // A 已到结尾时由 onEnded 统一收尾；继续校正会把更长的 B 钉在 A 结尾反复抖动
      if (!b || !playing || a.ended) return;
      // NLE I/O 区间循环：越过出点即回入点（轮询粒度内允许小幅越线，回跳即校正）
      const boundary = loopBoundaryTime(a.currentTime, inPoint, outPoint);
      if (boundary !== null) {
        a.currentTime = boundary;
        b.currentTime = expectedRightTime(boundary, offsetB, b.duration);
        setTime(boundary);
        return;
      }
      // B 在 seek 中或缓冲不足时跳过本轮校正，避免弱网下 seek 风暴互相拉扯
      if (b.seeking || b.readyState < 3) return;
      const expected = expectedRightTime(a.currentTime, offsetB, b.duration);
      const drift = b.currentTime - expected;
      const absDrift = Math.abs(drift);
      if (absDrift > SYNC_HARD_SEEK_SECONDS) {
        // 大漂移：硬 seek 回位并复位速率
        b.currentTime = expected;
        b.playbackRate = rate;
        setDriftFixed((n) => n + 1);
      } else if (absDrift > SYNC_DRIFT_TOLERANCE) {
        // 小漂移：±12% playbackRate 微调平滑追平
        b.playbackRate = drift > 0 ? rate * 0.88 : rate * 1.12;
      } else if (b.playbackRate !== rate) {
        // 回到阈值内：复位到基准倍速
        b.playbackRate = rate;
      }
    }, SYNC_POLL_MS);
    return () => window.clearInterval(id);
  }, [open, playing, offsetB, inPoint, outPoint, rate]);

  // 偏移改变立即对齐 B 侧，反馈不等待下一轮轮询
  useEffect(() => {
    const a = leftRef.current;
    const b = rightRef.current;
    if (!a || !b || !Number.isFinite(b.duration)) return;
    b.currentTime = expectedRightTime(a.currentTime, offsetB, b.duration);
  }, [offsetB]);

  // A（主时钟）播完：B 一并停下，Transport 回到暂停态
  const handleLeftEnded = useCallback(() => {
    rightRef.current?.pause();
    setPlaying(false);
  }, []);

  const togglePlay = useCallback(() => {
    const a = leftRef.current;
    const b = rightRef.current;
    if (!a) return;
    if (playing) {
      a.pause();
      b?.pause();
      setPlaying(false);
      return;
    }
    if (b) {
      const expected = expectedRightTime(a.currentTime, offsetB, b.duration);
      if (Math.abs(b.currentTime - expected) > SYNC_DRIFT_TOLERANCE) {
        b.currentTime = expected;
      }
    }
    void a.play().catch(() => setPlaying(false));
    if (b) void b.play().catch(() => undefined);
    setPlaying(true);
  }, [playing, offsetB]);

  const seek = useCallback((next: number) => {
    const a = leftRef.current;
    if (!a) return;
    const clamped = Math.max(0, Math.min(next, Number.isFinite(a.duration) ? a.duration : next));
    a.currentTime = clamped;
    if (rightRef.current) {
      rightRef.current.currentTime = expectedRightTime(clamped, offsetB, rightRef.current.duration);
    }
    setTime(clamped);
  }, [offsetB]);

  // 微调 B 侧偏移（±0.1s 步进）；对齐由 offsetB 的 effect 立即执行
  const nudgeOffset = useCallback((delta: number) => {
    setOffsetB((previous) => clampOffsetSeconds(previous + delta));
  }, []);

  const step = useCallback((deltaSeconds: number) => {
    seek((leftRef.current?.currentTime ?? 0) + deltaSeconds);
  }, [seek]);

  // NLE I/O：以主时钟当前位置设入/出点；新点越过旧点时交换，保持 in ≤ out
  const markIn = useCallback(() => {
    const current = leftRef.current?.currentTime;
    if (typeof current !== "number") return;
    const at = Math.max(0, current);
    if (outPoint !== null && at > outPoint) {
      setInPoint(outPoint);
      setOutPoint(at);
    } else {
      setInPoint(at);
    }
  }, [outPoint]);

  const markOut = useCallback(() => {
    const current = leftRef.current?.currentTime;
    if (typeof current !== "number") return;
    const at = Math.max(0, current);
    if (inPoint !== null && at < inPoint) {
      setOutPoint(inPoint);
      setInPoint(at);
    } else {
      setOutPoint(at);
    }
  }, [inPoint]);

  const clearRegion = useCallback(() => {
    setInPoint(null);
    setOutPoint(null);
  }, []);

  // 版本栈：把右侧切到左侧节点输出的上一版；连点沿链继续往回走
  const loadPreviousVersion = useCallback(async () => {
    if (!left || versionBusy) return;
    setVersionBusy(true);
    setVersionNote(null);
    try {
      const response = await (listVersions ?? ((assetId: string) => agentCanvasApi.listAgentCanvasAssetVersions(assetId)))(left.asset.asset_id);
      const currentVersionId = versionOverride?.versionId ?? left.node.output_asset_version_id ?? null;
      const previous = pickPreviousVersion(response.versions, currentVersionId);
      if (!previous) {
        setVersionNote(currentVersionId ? "已是链上最早版本" : "版本链不足两版");
        return;
      }
      setVersionOverride({
        assetId: left.asset.asset_id,
        versionId: previous.versionId,
        versionNo: previous.versionNo,
        label: `${left.node.title || left.node.node_id} · 上一版 v${previous.versionNo}`,
      });
    } catch {
      setVersionNote("版本链获取失败");
    } finally {
      setVersionBusy(false);
    }
  }, [left, versionBusy, versionOverride, listVersions]);

  // 自动对齐：采样两条视频的亮度轨迹做互相关，把峰值偏移写进 offsetB（通览标定 NCC 的浏览器版）
  const runAutoAlign = useCallback(async () => {
    const a = leftRef.current;
    const b = rightRef.current;
    if (!a || !b || aligning) return;
    const durationA = Number.isFinite(a.duration) ? a.duration : 0;
    const durationB = Number.isFinite(b.duration) ? b.duration : 0;
    const total = Math.min(durationA, durationB);
    if (total <= 1) {
      setAlignNote("元数据未就绪，稍后再试");
      return;
    }
    const resumeA = a.currentTime;
    const wasPlaying = playing;
    setAligning(true);
    setAlignNote(null);
    setPlaying(false);
    a.pause();
    b.pause();
    try {
      const grid = 0.5;
      const times: number[] = [];
      for (let t = 0.25; t < total; t += grid) times.push(t);
      const sample = sampleTracks ?? sampleLumaTrack;
      const [trackA, trackB] = await Promise.all([sample(a, times), sample(b, times)]);
      const result = bestOffsetByNcc(trackA, trackB, grid, SYNC_OFFSET_LIMIT);
      if (!result) {
        setAlignNote("亮度轨迹过平，无法对齐");
        return;
      }
      const clamped = clampOffsetSeconds(result.offset);
      setOffsetB(clamped);
      setAlignNote(`自动对齐 ${clamped >= 0 ? "+" : ""}${clamped.toFixed(1)}s（相关 ${result.score.toFixed(2)}）`);
      a.currentTime = resumeA;
      b.currentTime = expectedRightTime(resumeA, clamped, b.duration);
    } catch {
      setAlignNote("对齐失败（采样不可用）");
    } finally {
      setAligning(false);
      if (wasPlaying) {
        void a.play().catch(() => undefined);
        void b.play().catch(() => undefined);
        setPlaying(true);
      }
    }
  }, [aligning, playing, sampleTracks]);

  // 键盘：空格播放/暂停，左右 ±1s，逗号/句号逐帧，I/O 设区间（NLE 惯例）
  useEffect(() => {
    if (!open) return;
    const onKey = (event: KeyboardEvent) => {
      const target = event.target as HTMLElement | null;
      if (target && (target.tagName === "INPUT" || target.tagName === "SELECT" || target.tagName === "TEXTAREA")) return;
      if (event.code === "Space") {
        event.preventDefault();
        togglePlay();
      } else if (event.code === "ArrowLeft") {
        event.preventDefault();
        step(-1);
      } else if (event.code === "ArrowRight") {
        event.preventDefault();
        step(1);
      } else if (event.key === "," || event.key === "，") {
        step(-1 / FRAME_RATE);
      } else if (event.key === "." || event.key === "。") {
        step(1 / FRAME_RATE);
      } else if (event.key === "i" || event.key === "I") {
        event.preventDefault();
        markIn();
      } else if (event.key === "o" || event.key === "O") {
        event.preventDefault();
        markOut();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, togglePlay, step, markIn, markOut]);

  // 进度条上的 I/O 区间色带
  const regionStyle = useMemo(() => {
    if (inPoint === null && outPoint === null) return undefined;
    const total = duration > 0 ? duration : 1;
    const lo = ((inPoint ?? 0) / total) * 100;
    const hi = ((outPoint ?? total) / total) * 100;
    return {
      background: `linear-gradient(to right, transparent ${lo}%, rgb(157 175 230 / 30%) ${lo}%, rgb(157 175 230 / 30%) ${hi}%, transparent ${hi}%)`,
    };
  }, [inPoint, outPoint, duration]);

  // 滑动分割： divider 拖动
  const onDividerDrag = useCallback((event: React.PointerEvent<HTMLDivElement>) => {
    const stage = stageRef.current;
    if (!stage) return;
    const rect = stage.getBoundingClientRect();
    const move = (clientX: number) => {
      const pct = ((clientX - rect.left) / rect.width) * 100;
      setDivider(Math.max(0, Math.min(100, pct)));
    };
    move(event.clientX);
    const onMove = (e: PointerEvent) => move(e.clientX);
    const onUp = () => {
      window.removeEventListener("pointermove", onMove);
      window.removeEventListener("pointerup", onUp);
    };
    window.addEventListener("pointermove", onMove);
    window.addEventListener("pointerup", onUp);
  }, []);

  // 分割线键盘：方向键 ±2%（stopPropagation 防止触发全局 ±1s/逐帧步进）
  const onDividerKeyDown = useCallback((event: React.KeyboardEvent<HTMLDivElement>) => {
    if (event.key !== "ArrowLeft" && event.key !== "ArrowRight") return;
    event.stopPropagation();
    event.preventDefault();
    setDivider((current) => Math.max(0, Math.min(100, current + (event.key === "ArrowRight" ? 2 : -2))));
  }, []);

  // Esc 关闭（modal 惯例）
  useEffect(() => {
    if (!open) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose]);

  // 焦点陷阱：打开时聚焦面板，Tab 循环限制在面板内，卸载时归还焦点
  useEffect(() => {
    if (!open) return;
    const panel = panelRef.current;
    if (!panel) return;
    const previous = document.activeElement as HTMLElement | null;
    panel.focus();
    const onTab = (event: KeyboardEvent) => {
      if (event.key !== "Tab") return;
      const focusables = panel.querySelectorAll<HTMLElement>(
        'button:not(:disabled), [href], input:not(:disabled), select:not(:disabled), textarea:not(:disabled), [tabindex]:not([tabindex="-1"])',
      );
      if (!focusables.length) return;
      const first = focusables[0];
      const last = focusables[focusables.length - 1];
      if (event.shiftKey && (document.activeElement === first || document.activeElement === panel)) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    };
    window.addEventListener("keydown", onTab);
    return () => {
      window.removeEventListener("keydown", onTab);
      previous?.focus();
    };
  }, [open]);

  if (!open) return null;

  const picker = (side: "left" | "right") => (
    <label className="sync-compare__source">
      <span className="sync-compare__source-label">{side === "left" ? "A · 参考" : "B · 对比"}</span>
      <select
        value={side === "left" ? leftId ?? "" : rightId ?? ""}
        onChange={(event) => (side === "left" ? setLeftId(event.target.value || null) : setRightId(event.target.value || null))}
      >
        <option value="">未选择</option>
        {candidates.map((c) => (
          <option key={c.node.node_id} value={c.node.node_id}>
            {c.node.title || c.node.node_id}
          </option>
        ))}
      </select>
    </label>
  );

  return createPortal(
    <div className="sync-compare" role="dialog" aria-modal="true" aria-label="同步对比播放" data-testid="sync-compare">
      <div className="sync-compare__panel" ref={panelRef} tabIndex={-1} data-testid="sync-compare-panel">
        <header className="sync-compare__header">
          <div className="sync-compare__title-group">
            <h2 className="sync-compare__title">同步对比播放</h2>
            <p className="sync-compare__subtitle">两条视频共享一套 Transport；漂移自动校正</p>
          </div>
          <div className="sync-compare__modes" role="group" aria-label="对比视图">
            {MODES.map(({ value, label }) => (
              <button
                key={value}
                type="button"
                className={mode === value ? "is-active" : ""}
                aria-pressed={mode === value}
                onClick={() => setMode(value)}
              >
                {label}
              </button>
            ))}
          </div>
          <button type="button" className="sync-compare__close" aria-label="关闭对比播放" onClick={onClose}>
            <CloseIcon />
          </button>
        </header>

        {/* 双 pane 常驻：并排=双列网格，分割/差异=同格叠加。切视图不重建 video，播放进度不丢 */}
        <div className={`sync-compare__stage is-${mode}`} ref={stageRef} data-testid="sync-compare-stage">
          <figure className="sync-compare__pane is-left">
            <div className="sync-compare__pane-head">{picker("left")}</div>
            {left ? (
              <video
                ref={leftRef}
                src={left.url}
                playsInline
                preload="metadata"
                muted={audioSide !== "A"}
                onEnded={handleLeftEnded}
                onError={() => setLoadError({ side: "left", url: left.url })}
                onLoadedMetadata={(event) => {
                  if (Number.isFinite(event.currentTarget.duration)) setDuration(event.currentTarget.duration);
                  // currentTarget 只在派发期有效，先取值再进 updater
                  const w = event.currentTarget.videoWidth;
                  const h = event.currentTarget.videoHeight;
                  setDims((previous) => ({ ...previous, left: { w, h } }));
                }}
                data-testid="sync-compare-video-left"
              />
            ) : (
              <div className="sync-compare__empty">选择左侧视频</div>
            )}
            {loadError?.side === "left" ? (
              <div className="sync-compare__pane-error" data-testid="sync-compare-error-left">
                加载失败
                <button type="button" onClick={() => { setLoadError(null); leftRef.current?.load(); }}>重试</button>
              </div>
            ) : null}
            <figcaption>{left?.node.title ?? "—"}</figcaption>
          </figure>
          <figure className="sync-compare__pane is-right">
            <div className="sync-compare__pane-head">
              {picker("right")}
              {left ? (
                <button
                  type="button"
                  className="sync-compare__prev-version"
                  onClick={() => void loadPreviousVersion()}
                  disabled={versionBusy}
                  title="版本栈：把右侧切到左侧节点输出的上一版，连点沿链回溯（Frame.io Version Stack）"
                  data-testid="sync-compare-prev-version"
                >
                  {versionBusy ? "取版本…" : "上一版"}
                </button>
              ) : null}
              {versionNote ? <span className="sync-compare__version-note" data-testid="sync-compare-version-note">{versionNote}</span> : null}
            </div>
            {rightSource ? (
              <video
                ref={rightRef}
                src={rightSource.url}
                playsInline
                preload="metadata"
                muted={audioSide !== "B"}
                style={mode === "wipe" ? { clipPath: `inset(0 0 0 ${divider}%)` } : undefined}
                onError={() => setLoadError({ side: "right", url: rightSource.url })}
                onLoadedMetadata={(event) => {
                  const w = event.currentTarget.videoWidth;
                  const h = event.currentTarget.videoHeight;
                  setDims((previous) => ({ ...previous, right: { w, h } }));
                }}
                data-testid="sync-compare-video-right"
              />
            ) : (
              <div className="sync-compare__empty">选择右侧视频</div>
            )}
            {loadError?.side === "right" ? (
              <div className="sync-compare__pane-error" data-testid="sync-compare-error-right">
                加载失败
                <button type="button" onClick={() => { setLoadError(null); rightRef.current?.load(); }}>重试</button>
              </div>
            ) : null}
            <figcaption>{rightSource?.title ?? "—"}</figcaption>
          </figure>
          {mode === "wipe" ? (
            <>
              <div
                className="sync-compare__divider"
                style={{ left: `${divider}%` }}
                onPointerDown={onDividerDrag}
                onKeyDown={onDividerKeyDown}
                role="slider"
                aria-label="分割位置"
                aria-valuenow={Math.round(divider)}
                aria-valuemin={0}
                aria-valuemax={100}
                tabIndex={0}
              />
              <span className="sync-compare__wipe-tag is-left">{left?.node.title ?? "A"}</span>
              <span className="sync-compare__wipe-tag is-right">{rightSource?.title ?? "B"}</span>
              <div className="sync-compare__wipe-pickers">
                {picker("left")}
                {picker("right")}
              </div>
            </>
          ) : null}
          {mode !== "split" && aspectMismatch(dims.left, dims.right) ? (
            <span className="sync-compare__diff-hint is-warn" data-testid="sync-compare-aspect-warn">两侧宽高比不同，叠加对比会错位</span>
          ) : mode === "diff" ? (
            <span className="sync-compare__diff-hint">黑 = 一致 · 亮 = 差异</span>
          ) : null}
        </div>

        <footer className="sync-compare__transport">
          <button type="button" className="sync-compare__play" onClick={togglePlay} aria-label={playing ? "暂停" : "播放"} data-testid="sync-compare-play">
            {playing ? "⏸" : "▶"}
          </button>
          <button type="button" onClick={() => step(-1 / FRAME_RATE)} aria-label="上一帧">⟨</button>
          <button type="button" onClick={() => step(1 / FRAME_RATE)} aria-label="下一帧">⟩</button>
          <span className="sync-compare__time" data-testid="sync-compare-time">
            {formatTime(time)} / {formatTime(duration)}
          </span>
          <input
            className="sync-compare__seek"
            type="range"
            min={0}
            max={Math.max(duration, 0.1)}
            step={0.04}
            value={Math.min(time, duration || 0)}
            onChange={(event) => seek(Number(event.target.value))}
            style={regionStyle}
            aria-label="播放进度"
            data-testid="sync-compare-seek"
          />
          <label className="sync-compare__rate">
            倍速
            <select value={rate} onChange={(event) => setRate(Number(event.target.value))}>
              {RATES.map((r) => (
                <option key={r} value={r}>{r}×</option>
              ))}
            </select>
          </label>
          <div
            className="sync-compare__offset"
            title="微调 B 侧：右侧内容落后（左侧领先）时取正值，让 B 取更靠后的画面；负值相反"
          >
            <span>微调B</span>
            <button type="button" onClick={() => nudgeOffset(-0.1)} aria-label="B 侧提前 0.1 秒">−</button>
            <span className="sync-compare__offset-value" data-testid="sync-compare-offset">
              {offsetB >= 0 ? `+${offsetB.toFixed(1)}` : `${offsetB.toFixed(1)}`}s
            </span>
            <button type="button" onClick={() => nudgeOffset(0.1)} aria-label="B 侧延后 0.1 秒">＋</button>
            <button
              type="button"
              className="sync-compare__offset-reset"
              onClick={() => setOffsetB(0)}
              aria-label="偏移归零"
              disabled={offsetB === 0}
            >
              0
            </button>
          </div>
          <button
            type="button"
            className="sync-compare__auto-align"
            onClick={() => void runAutoAlign()}
            disabled={aligning || !left || !right}
            title="亮度轨迹互相关自动对齐（采样 0.5s 网格，NCC 取峰）"
            data-testid="sync-compare-auto-align"
          >
            {aligning ? "对齐中…" : "自动对齐"}
          </button>
          {alignNote ? (
            <span className="sync-compare__align-note" data-testid="sync-compare-align-note">{alignNote}</span>
          ) : null}
          <div className="sync-compare__region" title="NLE 式 I/O：I 设入点、O 设出点，播放到出点回入点循环">
            <button type="button" onClick={markIn} aria-label="设置入点">入</button>
            <span className="sync-compare__region-value" data-testid="sync-compare-region">
              {inPoint === null && outPoint === null ? "区间" : `${formatTime(inPoint ?? 0)}–${formatTime(outPoint ?? duration)}`}
            </span>
            <button type="button" onClick={markOut} aria-label="设置出点">出</button>
            <button
              type="button"
              onClick={clearRegion}
              aria-label="清除区间"
              disabled={inPoint === null && outPoint === null}
            >
              ✕
            </button>
          </div>
          <div className="sync-compare__audio" role="group" aria-label="音源">
            {AUDIO_SIDES.map(({ value, label }) => (
              <button
                key={value}
                type="button"
                className={audioSide === value ? "is-active" : ""}
                aria-pressed={audioSide === value}
                onClick={() => setAudioSide(value)}
              >
                {label}
              </button>
            ))}
          </div>
          <span className="sync-compare__drift" title="漂移校正累计次数">
            {driftFixed > 0 ? `已校正 ${driftFixed} 次` : "同步中"}
          </span>
        </footer>
      </div>
    </div>,
    document.body,
  );
}
