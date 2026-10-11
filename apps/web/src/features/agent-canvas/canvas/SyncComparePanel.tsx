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

import { CloseIcon } from "../../../icons.tsx";
import type { AgentCanvasWorkflowV2 } from "../../../types-v2.ts";
import {
  clampOffsetSeconds,
  collectSyncCompareCandidates,
  expectedRightTime,
  pickSyncCompareDefaults,
  SYNC_DRIFT_TOLERANCE,
  type SyncCompareCandidate,
} from "./syncCompareModel.ts";
import "./SyncComparePanel.css";

export interface SyncComparePanelProps {
  workflow: AgentCanvasWorkflowV2;
  open: boolean;
  onClose: () => void;
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

export function SyncComparePanel({ workflow, open, onClose }: SyncComparePanelProps) {
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
  const leftRef = useRef<HTMLVideoElement>(null);
  const rightRef = useRef<HTMLVideoElement>(null);
  const stageRef = useRef<HTMLDivElement>(null);

  const left = candidates.find((c) => c.node.node_id === leftId) ?? null;
  const right = candidates.find((c) => c.node.node_id === rightId) ?? null;

  // 打开时重置 Transport；候选变化（换源）也重置（偏移按对记忆，换对归零）
  useEffect(() => {
    setPlaying(false);
    setTime(0);
    setDriftFixed(0);
    setOffsetB(0);
    for (const ref of [leftRef, rightRef]) {
      const el = ref.current;
      if (el) {
        el.pause();
        el.currentTime = 0;
      }
    }
  }, [leftId, rightId, open]);

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
      const expected = expectedRightTime(a.currentTime, offsetB, b.duration);
      const drift = b.currentTime - expected;
      if (Math.abs(drift) > SYNC_DRIFT_TOLERANCE) {
        b.currentTime = expected;
        setDriftFixed((n) => n + 1);
      }
    }, SYNC_POLL_MS);
    return () => window.clearInterval(id);
  }, [open, playing, offsetB]);

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

  // 键盘：空格播放/暂停，左右 ±1s，逗号/句号逐帧
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
        step(-1 / 24);
      } else if (event.key === "." || event.key === "。") {
        step(1 / 24);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, togglePlay, step]);

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

  // Esc 关闭（modal 惯例）
  useEffect(() => {
    if (!open) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose]);

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
      <div className="sync-compare__panel">
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
            {picker("left")}
            {left ? (
              <video
                ref={leftRef}
                src={left.url}
                playsInline
                preload="metadata"
                muted={audioSide !== "A"}
                onEnded={handleLeftEnded}
                onLoadedMetadata={(event) => {
                  if (Number.isFinite(event.currentTarget.duration)) setDuration(event.currentTarget.duration);
                }}
                data-testid="sync-compare-video-left"
              />
            ) : (
              <div className="sync-compare__empty">选择左侧视频</div>
            )}
            <figcaption>{left?.node.title ?? "—"}</figcaption>
          </figure>
          <figure className="sync-compare__pane is-right">
            {picker("right")}
            {right ? (
              <video
                ref={rightRef}
                src={right.url}
                playsInline
                preload="metadata"
                muted={audioSide !== "B"}
                style={mode === "wipe" ? { clipPath: `inset(0 0 0 ${divider}%)` } : undefined}
                data-testid="sync-compare-video-right"
              />
            ) : (
              <div className="sync-compare__empty">选择右侧视频</div>
            )}
            <figcaption>{right?.node.title ?? "—"}</figcaption>
          </figure>
          {mode === "wipe" ? (
            <>
              <div
                className="sync-compare__divider"
                style={{ left: `${divider}%` }}
                onPointerDown={onDividerDrag}
                role="slider"
                aria-label="分割位置"
                aria-valuenow={Math.round(divider)}
                aria-valuemin={0}
                aria-valuemax={100}
                tabIndex={0}
              />
              <span className="sync-compare__wipe-tag is-left">{left?.node.title ?? "A"}</span>
              <span className="sync-compare__wipe-tag is-right">{right?.node.title ?? "B"}</span>
              <div className="sync-compare__wipe-pickers">
                {picker("left")}
                {picker("right")}
              </div>
            </>
          ) : null}
          {mode === "diff" ? <span className="sync-compare__diff-hint">黑 = 一致 · 亮 = 差异</span> : null}
        </div>

        <footer className="sync-compare__transport">
          <button type="button" className="sync-compare__play" onClick={togglePlay} aria-label={playing ? "暂停" : "播放"} data-testid="sync-compare-play">
            {playing ? "⏸" : "▶"}
          </button>
          <button type="button" onClick={() => step(-1 / 24)} aria-label="上一帧">⟨</button>
          <button type="button" onClick={() => step(1 / 24)} aria-label="下一帧">⟩</button>
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
