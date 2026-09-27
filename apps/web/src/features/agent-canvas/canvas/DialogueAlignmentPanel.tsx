/**
 * Dialogue alignment panel — the C mode's UI trigger.
 *
 * The audio bed is one take: dialogue, SFX, ambience and BGM mixed together,
 * with no per-line timestamps. This panel runs forced alignment over the
 * node's output asset (``POST /scene-3d/align-speech``) and shows the
 * recovered per-line timings, WHICH ENGINE actually ran, and the
 * low-confidence lines that must not drive lip-sync silently.
 *
 * Scope: this panel recovers the timings and hands them to the scene-3d
 * node's lip-sync editor via ``onLinesAligned`` — closing the C-mode loop
 * (bed → alignment → keyframes) in the product surface.
 */

import { useCallback, useState } from "react";

import "../workbench/scene-3d-workbench.css";

/** One word's timing, as the forced alignment reports it. */
export interface AlignedWordTiming {
  text: string;
  start: number;
  end: number;
}

export interface AlignedLine {
  segment_id: string;
  character_id: string;
  text: string;
  start_time: number;
  end_time: number;
  confidence: number;
  align_source: string;
  /** B-mode regeneration provenance (the endpoint's automatic re-measure). */
  regenerated?: boolean;
  duration_source?: string | null;
  /**
   * Word-level timings (whisperX only): the scene side drives the mouth per
   * word instead of on a metronome. Absent from the estimated layout.
   */
  word_timings?: AlignedWordTiming[] | null;
}

export interface DialogueAlignmentPanelProps {
  /** The node's output asset (the generated bed). */
  assetId: string | null;
  /** Speaker-tagged script lines from the node's audio_bed block. {speaker, text}. */
  scripts: { speaker?: string; text?: string }[];
  disabled?: boolean;
  /**
   * C-mode handoff: the aligned lines leave this panel for the scene-3d
   * node's lip-sync editor (they live in page-level state because the two
   * panels live in different node workbenches).
   */
  onLinesAligned?: (lines: AlignedLine[]) => void;
  /**
   * Bed speaker name -> scene character id, from the bed roles' optional
   * ``character_id``. Without it, an author who names roles with display
   * names (林澈) hands the lip-sync editor speakers the scene never defined
   * — and the editor's dropdown would select nothing.
   */
  speakerCharacterMap?: Record<string, string> | null;
}

const ENGINE_LABELS: Record<string, string> = {
  whisperx: "WhisperX 实测对齐",
  estimated: "确定性估算铺排（未实测）",
};

export function DialogueAlignmentPanel({
  assetId,
  scripts,
  disabled = false,
  onLinesAligned,
  speakerCharacterMap = null,
}: DialogueAlignmentPanelProps) {
  const [running, setRunning] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [lines, setLines] = useState<AlignedLine[] | null>(null);
  const [alignSource, setAlignSource] = useState<string | null>(null);
  const [lowConfidence, setLowConfidence] = useState<string[]>([]);
  const [regeneratedCount, setRegeneratedCount] = useState(0);
  const [regenerationSource, setRegenerationSource] = useState<string | null>(null);

  const speechLines = scripts.filter(
    (script) => (script.speaker ?? "").trim() && (script.text ?? "").trim(),
  );

  const run = useCallback(async () => {
    if (!assetId || speechLines.length === 0) return;
    setRunning(true);
    setError(null);
    try {
      const response = await fetch("/api/v1/scene-3d/align-speech", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          asset_id: assetId,
          lines: speechLines.map((script, index) => ({
            character_id: (script.speaker ?? "").trim(),
            text: (script.text ?? "").trim(),
            segment_id: `seg_${index}`,
          })),
          speech_only: true,
        }),
      });
      const body = await response.json().catch(() => null);
      if (response.status !== 200 || !body) {
        const detail = body?.detail;
        throw new Error(
          (typeof detail === "object" && detail?.error) ||
            `对齐失败 (HTTP ${response.status})`,
        );
      }
      const segments: AlignedLine[] = body.segments ?? [];
      setLines(segments);
      setAlignSource(body.align_source ?? null);
      setLowConfidence(body.low_confidence_ids ?? []);
      // B-mode regeneration: the endpoint re-measures weak lines on its own;
      // the panel shows what happened instead of leaving it in a warning.
      setRegeneratedCount((body.regenerated_ids ?? []).length);
      setRegenerationSource(body.regeneration_duration_source ?? null);
      // The alignment is faithful to the BED (display names). The handoff to
      // the scene side carries scene character ids, so the lip-sync editor's
      // speaker dropdown selects a real character instead of nothing.
      onLinesAligned?.(
        segments.map((line) => {
          const mapped = speakerCharacterMap?.[line.character_id];
          return mapped && mapped !== line.character_id
            ? { ...line, character_id: mapped }
            : line;
        }),
      );
    } catch (alignError) {
      setError(alignError instanceof Error ? alignError.message : "对齐失败，请重试。");
    } finally {
      setRunning(false);
    }
  // onLinesAligned / speakerCharacterMap are intentionally outside the deps:
  // callers pass page-level state setters and freshly-parsed config objects;
  // re-running alignment on identity churn would discard the handoff.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [assetId, speechLines]);

  const mappedCharacterFor = (speaker: string): string | null => {
    const mapped = speakerCharacterMap?.[speaker];
    return mapped && mapped !== speaker ? mapped : null;
  };

  if (!assetId || speechLines.length === 0) return null;

  return (
    <section className="dialogue-alignment" data-testid="dialogue-alignment">
      <div className="dialogue-alignment__head">
        <button
          type="button"
          className="dialogue-alignment__run"
          disabled={disabled || running}
          onClick={() => void run()}
        >
          {running ? "对齐中…" : "🎯 台词对齐"}
        </button>
        <span className="dialogue-alignment__hint">
          床音不含逐句时间戳；对齐恢复每句起止（{speechLines.length} 句）
        </span>
      </div>

      {alignSource && (
        <p className="dialogue-alignment__engine">
          对齐引擎：{ENGINE_LABELS[alignSource] ?? alignSource}
        </p>
      )}

      {lowConfidence.length > 0 && (
        <p className="dialogue-alignment__low-confidence">
          ⚠ {lowConfidence.length} 句低于唇形置信阈值：驱动口型前需逐句重生成或显式接受估算带
        </p>
      )}
      {regeneratedCount > 0 && (
        <p className="dialogue-alignment__regenerated" data-testid="dialogue-alignment-regenerated">
          🔧 {regeneratedCount} 句已按 B 模式重测时长（来源：
          {regenerationSource === "measured" ? "TTS 实测" : "确定性估算"}）；起句时间仍来自对齐——长度可信不等于位置可信
        </p>
      )}
      {lines && lines.length > 0 && (
        <ol className="dialogue-alignment__lines">
          {lines.map((line) => (
            <li
              key={line.segment_id}
              data-low-confidence={
                lowConfidence.includes(line.segment_id) ? "true" : undefined
              }
            >
              <span className="dialogue-alignment__who">
                {line.character_id}
                {mappedCharacterFor(line.character_id) && (
                  <span className="dialogue-alignment__who-mapped">
                    {" → "}
                    {mappedCharacterFor(line.character_id)}
                  </span>
                )}
              </span>
              <span className="dialogue-alignment__text">{line.text}</span>
              <span className="dialogue-alignment__time">
                {line.start_time.toFixed(2)}s – {line.end_time.toFixed(2)}s
              </span>
              <span className="dialogue-alignment__confidence">
                {Math.round(line.confidence * 100)}%
              </span>
              {line.regenerated && (
                <span
                  className="dialogue-alignment__regen"
                  data-testid={`dialogue-alignment-regen-${line.segment_id}`}
                  title="该句时长按 B 模式重测（起句时间仍来自对齐）"
                >
                  B 模式重测
                </span>
              )}
            </li>
          ))}
        </ol>
      )}
      {error && <p className="dialogue-alignment__error">{error}</p>}
    </section>
  );
}
