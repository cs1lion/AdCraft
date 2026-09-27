/**
 * Dialogue lip-sync panel — the scene side of 台词驱动.
 *
 * The audio bed is one take with no per-line timestamps (see
 * DialogueAlignmentPanel on the voice-cast side). This panel takes the
 * dialogue lines, drives them through the speech timeline (measured TTS
 * durations when the engine reports them, estimated otherwise — the summary
 * says which), and applies the resulting lip-sync keyframes to the SceneScript
 * via ``POST /scene-3d/dialogue-lipsync``. The returned script becomes the
 * workbench draft: the mouths now move in the 3D viewport, the Blender
 * render, and the video-model prompt bundle.
 *
 * Lines may carry an explicit start_time (e.g. recovered by the alignment
 * panel on the voice-cast side) — those anchors are honoured.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import type { SceneScriptRoot } from "../../../types/scene-script";
import {
  dialogueLinesEqual,
  serializeDialogueLines,
  type PersistedDialogueLine,
} from "./dialogueLinesPersistence.ts";
import { buildSubtitleCues, type AlignedSpeechSegment } from "../timeline/dialogueSubtitleCues.ts";
import { publishSubtitleCues } from "../timeline/publishSubtitleCues.ts";
import { bumpTimelineMutationRefresh } from "../timeline/timelineMutationRefresh.ts";
import "../workbench/scene-3d-workbench.css";

/** Short labels for the advisory codes (the backend owns the wording). */
const SHOT_ADVISORY_LABELS: Record<string, string> = {
  line_crosses_cut: "话音跨切点",
  cross_talk_in_tight_shot: "单人构图表双说",
  shot_without_speech: "无台词镜头",
};

/** Emotion-continuity findings (V0.2 §5 情绪维度；backend owns the wording). */
const EMOTION_ADVISORY_LABELS: Record<string, string> = {
  emotion_whiplash: "情绪跨切突变",
};

/** One advisory as the lip-sync summary serializes it. */
interface ShotAdvisoryPayload {
  code: string;
  message: string;
  remedy: string;
  shot_id?: string | null;
  /** Transition Intent readings that execute this advisory's remedy. */
  proposal_ids?: string[];
}

/** One word's timing, as the forced alignment reports it. */
export interface DialogueWordTiming {
  text: string;
  start: number;
  end: number;
}

export interface DialogueLine {
  character_id: string;
  text: string;
  start_time?: number | null;
  emotion?: string | null;
  /**
   * Word-level timings (whisperX): the mouth moves WITH the words. Absent
   * when the alignment had none — the service keeps its metronome.
   */
  word_timings?: DialogueWordTiming[] | null;
}

export interface DialogueLipSyncPanelProps {
  /** The current scene draft (lip-sync is applied to it). */
  sceneScript: SceneScriptRoot;
  /** Character ids available as speakers (from the scene itself). */
  characterIds: string[];
  /** Pre-seeded lines (e.g. carried over from the script node or bed). */
  initialLines?: DialogueLine[];
  onSceneScriptApplied: (script: SceneScriptRoot) => void;
  disabled?: boolean;
  /** Workflow whose timeline subtitle track receives the cues. */
  workflowId?: string | null;
  /** Scene node id: the publish trace that makes a re-publish a replace. */
  sourceNodeId?: string | null;
  /**
   * Lines already persisted on the node (the panel's own storage). The
   * alignment handoff (initialLines) wins when present; without either, the
   * panel starts from one empty row as before.
   */
  persistedLines?: PersistedDialogueLine[] | null;
  /**
   * Persist the lines onto the node: a reload must not lose the author's
   * per-line timing or the speaker mapping (the bed keeps neither).
   */
  onLinesPersist?: (lines: PersistedDialogueLine[]) => void;
  /**
   * The segments the applied run actually measured. Lifted once per apply:
   * the Transition Intent picker prices its speech-aware readings against
   * THE SAME timeline the mouths ride on — never a re-estimate (captions,
   * mouths and cuts must not drift apart).
   */
  onSegmentsApplied?: (segments: AlignedSpeechSegment[]) => void;
  /**
   * An advisory whose remedy is a cut move (V0.2 §15): jump to the
   * Transition Intent picker for that boundary shot. The picker then shows
   * the readings that execute the remedy — "提醒" gains a landing.
   */
  onOpenTransitions?: (shotId: string) => void;
}

export function DialogueLipSyncPanel({
  sceneScript,
  characterIds,
  initialLines = [],
  onSceneScriptApplied,
  disabled = false,
  workflowId = null,
  sourceNodeId = null,
  persistedLines = null,
  onLinesPersist,
  onSegmentsApplied,
  onOpenTransitions,
}: DialogueLipSyncPanelProps) {
  const [lines, setLines] = useState<DialogueLine[]>(() => {
    if (initialLines.length > 0) return initialLines;
    if (persistedLines && persistedLines.length > 0) return persistedLines;
    return [{ character_id: characterIds[0] ?? "", text: "", start_time: null, emotion: null }];
  });
  const [applying, setApplying] = useState(false);
  // Debounced persistence: per-keystroke PATCHes would hammer the API, and
  // the intermediate values are worthless (the service reads the final
  // lines). The latest value always wins; the timer is flushed on unmount.
  const persistTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const linesRef = useRef(lines);
  linesRef.current = lines;
  const persistNow = useCallback(() => {
    if (!onLinesPersist) return;
    if (persistTimerRef.current) {
      clearTimeout(persistTimerRef.current);
      persistTimerRef.current = null;
    }
    const serializable = serializeDialogueLines(
      linesRef.current.map((line) => ({
        character_id: line.character_id,
        text: line.text,
        start_time: line.start_time ?? null,
        emotion: line.emotion ?? null,
      })),
    );
    if (!dialogueLinesEqual(serializable, persistedLines ?? [])) {
      onLinesPersist(serializable);
    }
  }, [onLinesPersist, persistedLines]);
  useEffect(() => {
    if (!onLinesPersist) return;
    if (persistTimerRef.current) clearTimeout(persistTimerRef.current);
    persistTimerRef.current = setTimeout(() => {
      persistTimerRef.current = null;
      persistNow();
    }, 600);
    return () => {
      if (persistTimerRef.current) clearTimeout(persistTimerRef.current);
    };
  }, [lines, persistNow, onLinesPersist]);
  // Flush on unmount: closing the workbench right after an edit must not
  // lose it (the debounce may still be pending).
  useEffect(() => persistNow, [persistNow]);
  const [error, setError] = useState<string | null>(null);
  const [summary, setSummary] = useState<Record<string, unknown> | null>(null);
  const [publishing, setPublishing] = useState(false);
  const [publishMessage, setPublishMessage] = useState<string | null>(null);
  const [publishError, setPublishError] = useState<string | null>(null);

  const speechLines = lines.filter((line) => line.character_id && line.text.trim());

  const updateLine = (index: number, patch: Partial<DialogueLine>) => {
    setLines((current) =>
      current.map((line, i) => (i === index ? { ...line, ...patch } : line)),
    );
  };

  /**
   * Publish cue clips for the given segments (the lip-sync boundaries, so
   * captions never drift from the mouths). A re-publish REPLACES this node's
   * earlier cues — idempotent by construction, which is what makes the
   * automatic publish-on-apply safe.
   */
  const publishCues = useCallback(
    async (segments: AlignedSpeechSegment[]) => {
      if (!workflowId || segments.length === 0) return;
      setPublishing(true);
      setPublishError(null);
      setPublishMessage(null);
      try {
        const { cues, skipped } = buildSubtitleCues(segments);
      // sourceNodeId makes a re-publish REPLACE this node's earlier cues
      // instead of stacking duplicates.
      const result = await publishSubtitleCues(workflowId, cues, { sourceNodeId });
      const parts = [`已上字幕轨 ${result.created} 条`];
      if (result.replaced > 0) {
        parts.unshift(`替换 ${result.replaced} 条旧 cues`);
      }
      if (skipped.length > 0) {
        parts.push(`${skipped.length} 条跳过（空文本/时长为零/时间非法）`);
      }
      if (result.failed.length > 0) {
        parts.push(`${result.failed.length} 条写入失败`);
      }
        setPublishMessage(parts.join(" · "));
        if (result.failed.length > 0) {
          setPublishError(result.failed[0].message);
        }
        // The publish mutates the timeline from this surface; an open timeline
        // panel hears nothing over SSE, so signal it explicitly.
        if (result.created > 0 || result.replaced > 0) {
          bumpTimelineMutationRefresh();
        }
      } catch (error) {
        setPublishError(error instanceof Error ? error.message : "字幕上轨失败，请重试。");
      } finally {
        setPublishing(false);
      }
    },
    [workflowId, sourceNodeId],
  );

  const apply = useCallback(async () => {
    if (speechLines.length === 0) return;
    setApplying(true);
    setError(null);
    try {
      const response = await fetch("/api/v1/scene-3d/dialogue-lipsync", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          scene_script: sceneScript,
          dialogue_lines: speechLines.map((line) => ({
            character_id: line.character_id,
            text: line.text.trim(),
            start_time: line.start_time ?? undefined,
            emotion: line.emotion ?? undefined,
            // Word timings ride along so the mouth moves with the words.
            word_timings:
              line.word_timings && line.word_timings.length > 0
                ? line.word_timings
                : undefined,
          })),
          syllables_per_second: 4.0,
        }),
      });
      const body = await response.json().catch(() => null);
      if (response.status !== 200 || !body?.scene_script) {
        const detail = body?.detail;
        throw new Error(
          (typeof detail === "object" && detail?.error) ||
            `唇形应用失败 (HTTP ${response.status})`,
        );
      }
      onSceneScriptApplied(body.scene_script as SceneScriptRoot);
      setSummary(body.summary ?? {});
      // The measured timings ride on to the Transition Intent picker: the
      // speech-aware readings must be priced against the same timeline the
      // mouths just rode on, never a re-estimate.
      const applied = Array.isArray(body.summary?.segments)
        ? (body.summary.segments as AlignedSpeechSegment[])
        : [];
      if (applied.length > 0) onSegmentsApplied?.(applied);
      // Subtitle cues follow the SAME authorial act (C-mode chain: bed →
      // align → lip-sync → subtitles). Re-publishing is an idempotent
      // replace of THIS node's cues, so applying twice never stacks. The
      // button below stays for a manual re-publish after later edits.
      if (applied.length > 0 && workflowId) {
        setPublishing(true);
        try {
          await publishCues(applied);
        } catch {
          // The mouths are already applied; a failed cue publish is reported
          // by the publish surface, never by failing the apply.
        } finally {
          setPublishing(false);
        }
      }
    } catch (applyError) {
      setError(applyError instanceof Error ? applyError.message : "唇形应用失败，请重试。");
    } finally {
      setApplying(false);
    }
  }, [sceneScript, speechLines, onSceneScriptApplied, onSegmentsApplied, workflowId, publishCues]);

  // The publishable cues are the service's own segment timings: re-estimating
  // here would drift the captions from the mouths.
  // Shot advisories from the same run that applied the lip-sync: the speech
  // timeline and the shot list read against each other.
  const shotAdvisories = useMemo(() => {
    const raw = summary?.shot_advisories;
    if (!Array.isArray(raw)) return [];
    return raw.filter(
      (entry): entry is ShotAdvisoryPayload =>
        Boolean(entry) &&
        typeof entry === "object" &&
        typeof (entry as { code?: unknown }).code === "string",
    );
  }, [summary]);
  // Emotion continuity (V0.2 §5): the same "the machine notices" surface, a
  // different dimension — does the emotion carry across the cut?
  const emotionAdvisories = useMemo(() => {
    const raw = summary?.emotion_advisories;
    if (!Array.isArray(raw)) return [];
    return raw.filter(
      (entry): entry is ShotAdvisoryPayload =>
        Boolean(entry) &&
        typeof entry === "object" &&
        typeof (entry as { code?: unknown }).code === "string",
    );
  }, [summary]);
  const allAdvisories = useMemo(
    () => [
      ...shotAdvisories.map((advisory) => ({ ...advisory, family: "shot" as const })),
      ...emotionAdvisories.map((advisory) => ({ ...advisory, family: "emotion" as const })),
    ],
    [shotAdvisories, emotionAdvisories],
  );
  // QA registry (ADR 0003 §5): the report the lip-sync run published. Only
  // the warn/fail entries surface — a pass is the compliment and stays quiet.
  const qaWarnings = useMemo(() => {
    const raw = summary?.qa_report;
    if (!raw || typeof raw !== "object") return [];
    const outcomes = (raw as { outcomes?: unknown }).outcomes;
    if (!Array.isArray(outcomes)) return [];
    return outcomes
      .filter(
        (entry): entry is { check: string; reason: string; status: string } =>
          Boolean(entry) &&
          typeof entry === "object" &&
          typeof (entry as { check?: unknown }).check === "string" &&
          typeof (entry as { reason?: unknown }).reason === "string" &&
          (entry as { status?: unknown }).status !== "pass",
      )
      .map((entry) => ({
        check: entry.check,
        reason: entry.reason,
        status: entry.status,
      }));
  }, [summary]);
  const qaWarningCount = qaWarnings.length;
  const appliedSegments = useMemo(() => {
    const raw = summary?.segments;
    return Array.isArray(raw) ? (raw as AlignedSpeechSegment[]) : null;
  }, [summary]);

  const publish = useCallback(async () => {
    if (!appliedSegments || appliedSegments.length === 0) return;
    await publishCues(appliedSegments);
  }, [appliedSegments, publishCues]);

  if (characterIds.length === 0) {
    return (
      <p className="dialogue-lipsync__empty">
        场景里还没有角色——先在左侧托盘添加角色，再回来绑定台词。
      </p>
    );
  }

  return (
    <section className="dialogue-lipsync" data-testid="dialogue-lipsync">
      <div className="dialogue-lipsync__head">
        <strong>台词驱动唇形</strong>
        <span className="dialogue-lipsync__hint">
          台词经语音时间线转为唇形关键帧，位置与朝向自动保持——重做 Audio 层不会踩碎你写的走位（V0.2 §14.13）
        </span>
      </div>

      {lines.map((line, index) => (
        <div className="dialogue-lipsync__row" key={`line-${index}`}>
          {/* Reorder (V0.2 §14.7 结构层: 两句台词对调): the row order IS the
              speech timeline's order, so swapping rows re-times the scene.
              The buttons sit before the speaker so the reading order is
              left-to-right: order, who, what, when, delivery, remove. */}
          <div className="dialogue-lipsync__reorder">
            <button
              type="button"
              aria-label={`第 ${index + 1} 行上移`}
              disabled={index === 0}
              title="与上一句对调（结构层编辑）"
              onClick={() =>
                setLines((current) =>
                  current.map((entry, i) => {
                    if (i === index - 1) return current[index];
                    if (i === index) return current[index - 1];
                    return entry;
                  }),
                )
              }
            >
              ↑
            </button>
            <button
              type="button"
              aria-label={`第 ${index + 1} 行下移`}
              disabled={index === lines.length - 1}
              title="与下一句对调（结构层编辑）"
              onClick={() =>
                setLines((current) =>
                  current.map((entry, i) => {
                    if (i === index + 1) return current[index];
                    if (i === index) return current[index + 1];
                    return entry;
                  }),
                )
              }
            >
              ↓
            </button>
          </div>
          <select
            aria-label={`第 ${index + 1} 行说话人`}
            value={line.character_id}
            onChange={(event) => updateLine(index, { character_id: event.target.value })}
          >
            {characterIds.map((id) => (
              <option key={id} value={id}>
                {id}
              </option>
            ))}
          </select>
          <input
            aria-label={`第 ${index + 1} 行台词`}
            placeholder="台词内容（可用（）标注情绪）"
            value={line.text}
            onChange={(event) => updateLine(index, { text: event.target.value })}
          />
          <input
            className="dialogue-lipsync__start"
            type="number"
            min={0}
            step={0.1}
            placeholder="自动"
            aria-label={`第 ${index + 1} 行开始 (s，可空)`}
            title="对齐恢复的起句时间（对齐即实测）；留空则按读音时长估算铺排"
            value={line.start_time ?? ""}
            onChange={(event) =>
              updateLine(index, {
                start_time:
                  event.target.value === "" ? null : Number(event.target.value),
              })
            }
          />
          {/* Delivery (V0.2 §14.7 表演层: 更慢、更冷淡、情绪更强). The value
              rides the speech segment into the TTS engine and the emotion
              continuity check, so a whiplash across a cut is visible before
              the render, not after. */}
          <input
            className="dialogue-lipsync__emotion"
            aria-label={`第 ${index + 1} 行语气`}
            placeholder="语气（如：压低、克制）"
            title="语气/情绪：进 TTS 发音与情绪连续性检查；留空则由文本推断"
            value={line.emotion ?? ""}
            onChange={(event) =>
              updateLine(index, {
                emotion: event.target.value === "" ? null : event.target.value,
              })
            }
          />
          <button
            type="button"
            aria-label={`删除第 ${index + 1} 行`}
            onClick={() => setLines((current) => current.filter((_, i) => i !== index))}
          >
            ×
          </button>
        </div>
      ))}

      <div className="dialogue-lipsync__actions">
        <button
          type="button"
          onClick={() =>
            setLines((current) => [
              ...current,
              { character_id: characterIds[0] ?? "", text: "", start_time: null, emotion: null },
            ])
          }
        >
          + 台词行
        </button>
        <button
          type="button"
          className="dialogue-lipsync__apply"
          disabled={disabled || applying || speechLines.length === 0}
          onClick={() => void apply()}
        >
          {applying ? "应用中…" : "👄 应用唇形到场景"}
        </button>
      </div>

      {summary && (
        <p className="dialogue-lipsync__summary" data-testid="dialogue-lipsync-summary">
          {String(summary.segment_count ?? 0)} 句 · 时长来源：
          {summary.duration_source === "measured"
            ? "TTS 实测"
            : summary.duration_source === "aligned"
              ? "强制对齐"
              : "文本估算"}
          {Array.isArray(summary.issues) && summary.issues.length > 0
            ? ` · ${summary.issues.length} 个重叠/越界提示`
            : ""}
          {qaWarningCount > 0 ? ` · QA ${qaWarningCount} 项提醒` : ""}
        </p>
      )}
      {qaWarnings.length > 0 && (
        <div className="dialogue-lipsync__qa" data-testid="dialogue-lipsync-qa">
          <span className="dialogue-lipsync__advisories-title">
            质量检查（ADR 0003 QA registry，不阻断）
          </span>
          {qaWarnings.map((warning) => (
            <p key={warning.check} className="dialogue-lipsync__qa-item">
              <span className="dialogue-lipsync__advisory-code">{warning.check}</span>
              {warning.reason}
            </p>
          ))}
        </div>
      )}
      {allAdvisories.length > 0 && (
        // "说多久 → 分镜多长": where the cuts and the dialogue disagree — and
        // whether the emotion carries across them. Advisory only — the author
        // keeps the editor's chair, which is why each line carries its remedy
        // and nothing is auto-applied.
        <div className="dialogue-lipsync__advisories" data-testid="dialogue-shot-advisories">
          <span className="dialogue-lipsync__advisories-title">分镜提示（不自动修改）</span>
          {allAdvisories.map((advisory, index) => {
            // The crossing finding names the readings that execute its
            // remedy (V0.2 §15): the jump button takes the author to the
            // picker for THIS boundary shot, with those readings loaded.
            const executableRemedy =
              onOpenTransitions &&
              (advisory.proposal_ids?.length ?? 0) > 0 &&
              advisory.shot_id
                ? advisory.shot_id
                : null;
            return (
              <p key={`${advisory.code}-${index}`} className="dialogue-lipsync__advisory">
                <span className="dialogue-lipsync__advisory-code">
                  {(advisory.family === "emotion"
                    ? EMOTION_ADVISORY_LABELS[advisory.code]
                    : SHOT_ADVISORY_LABELS[advisory.code]) ?? advisory.code}
                </span>
                {advisory.message}
                <span className="dialogue-lipsync__advisory-remedy">{advisory.remedy}</span>
                {executableRemedy && (
                  <button
                    type="button"
                    className="dialogue-lipsync__advisory-jump"
                    data-testid={`dialogue-advisory-transitions-${index}`}
                    onClick={() => onOpenTransitions?.(executableRemedy)}
                  >
                    🎬 看看怎么接
                  </button>
                )}
              </p>
            );
          })}
        </div>
      )}
      {workflowId && appliedSegments && appliedSegments.length > 0 && (
        <>
          <button
            type="button"
            className="dialogue-lipsync__publish"
            data-testid="dialogue-lipsync-publish"
            disabled={disabled || applying || publishing}
            onClick={() => void publish()}
          >
            {publishing ? "上轨中…" : "🗎 台词上字幕轨"}
          </button>
          <p className="dialogue-lipsync__hint">
            按唇形所用的同一边界写入字幕轨：对齐即实测，不重新估算（应用唇形时已自动发布过一次，此处用于改后重发）
          </p>
        </>
      )}
      {publishMessage && (
        <p className="dialogue-lipsync__publish-result" data-testid="dialogue-lipsync-publish-result">
          {publishMessage}
        </p>
      )}
      {publishError && <p className="dialogue-lipsync__error">{publishError}</p>}
      {error && <p className="dialogue-lipsync__error">{error}</p>}
    </section>
  );
}
