/**
 * VoiceCastDialogueLines — 每句是一个 Audio Event 的编舞台（V0.2 §14.7 内容层/表演层）。
 *
 * The whole-text path made a one-word change cost a whole take: the node owned
 * one blob, so there was nothing to address. This editor gives the node LINES,
 * each with its own id, words, emotion, and — crucially — a per-line
 * REGENERATE request, because "same words, a different performance" is the
 * 表演层 the doc asks for and the only way to say it is per line.
 *
 * What the backend then guarantees (and this surface makes visible): an
 * unchanged line's take is REUSED, the manifest says which lines this run
 * rebuilt and how long each one is, and the offsets tell the timeline that
 * follows where everything now sits.
 *
 * Mutually exclusive with the audio-bed editor by construction: the executor
 * checks the bed first, so a node carrying both beds is honest about it.
 */

import { useEffect, useMemo, useState } from "react";

import type { CanvasNodeV2 } from "../../../types-v2.ts";
import type { PatchNode } from "./workbenchTypes.ts";
import {
  MAX_DIALOGUE_LINES,
  MAX_LINE_CHARS,
  MAX_LINE_EMOTION_CHARS,
  parseDialogueLines,
  planLineSynthesis,
} from "../dialogue/voiceCastLines.ts";

/** One row of the draft. */
export interface DialogueLineDraft {
  id: string;
  text: string;
  emotion: string;
  /** Ask for a fresh take of the SAME words (表演层). */
  regenerate: boolean;
}

const LINE_ID_RULE = /^[A-Za-z0-9_-]{1,48}$/;

/** Read the node's block into a draft (tolerant: unknown shapes become rows). */
export function dialogueLinesFromNode(node: CanvasNodeV2): DialogueLineDraft[] {
  const raw = node.structured_content?.dialogue_lines;
  if (!Array.isArray(raw)) return [];
  return raw.flatMap((entry) => {
    if (!entry || typeof entry !== "object") return [];
    const record = entry as Record<string, unknown>;
    const id = String(record.id ?? record.line_id ?? "");
    const text = String(record.text ?? "");
    if (!id && !text) return [];
    return [{ id, text, emotion: String(record.emotion ?? ""), regenerate: false }];
  });
}

/** Validate the draft against the backend's rules (save gate + display). */
export function validateDialogueLines(
  rows: readonly DialogueLineDraft[],
): { code: string; message: string }[] {
  const issues: { code: string; message: string }[] = [];
  if (rows.length === 0) {
    issues.push({ code: "dialogue_lines_required", message: "至少一行台词。" });
    return issues;
  }
  if (rows.length > MAX_DIALOGUE_LINES) {
    issues.push({
      code: "dialogue_lines_too_many",
      message: `逐行台词最多 ${MAX_DIALOGUE_LINES} 行。`,
    });
  }
  const seen = new Set<string>();
  rows.forEach((row, index) => {
    const at = `第 ${index + 1} 行`;
    if (!row.id.trim()) {
      issues.push({ code: "dialogue_line_id_required", message: `${at} 缺少 id。` });
    } else if (!LINE_ID_RULE.test(row.id.trim())) {
      issues.push({
        code: "dialogue_line_id_invalid",
        message: `${at} 的 id 只能用字母数字与 -_，且不超过 48 字符。`,
      });
    } else if (seen.has(row.id.trim())) {
      issues.push({ code: "dialogue_line_id_duplicate", message: `${at} 的 id「${row.id}」重复。` });
    }
    seen.add(row.id.trim());
    if (!row.text.trim()) {
      issues.push({ code: "dialogue_line_text_required", message: `${at}（${row.id}）没有台词。` });
    } else if (row.text.trim().length > MAX_LINE_CHARS) {
      issues.push({
        code: "dialogue_line_too_long",
        message: `${at} 超过 ${MAX_LINE_CHARS} 字符。`,
      });
    }
    if (row.emotion.trim().length > MAX_LINE_EMOTION_CHARS) {
      issues.push({
        code: "dialogue_line_emotion_too_long",
        message: `${at} 的情绪标注超过 ${MAX_LINE_EMOTION_CHARS} 字符，写成一句短语。`,
      });
    }
  });
  return issues;
}

export function VoiceCastDialogueLines({
  node,
  patchNode,
}: {
  node: CanvasNodeV2;
  patchNode?: PatchNode;
}) {
  const [rows, setRows] = useState<DialogueLineDraft[]>(() => dialogueLinesFromNode(node));
  const [dirty, setDirty] = useState(false);

  // Re-sync from the node when its content changes upstream (rerun, another
  // surface, a collaboration patch) — but never while the author is typing.
  const signature = useMemo(
    () => JSON.stringify(dialogueLinesFromNode(node)),
    // eslint-disable-next-line react-hooks/exhaustive-deps -- the node object is
    // a fresh reference on every render; the block's contents are the signal.
    [node.structured_content?.dialogue_lines],
  );
  useEffect(() => {
    if (!dirty) setRows(dialogueLinesFromNode(node));
  }, [signature, dirty, node]);

  const issues = validateDialogueLines(rows);
  const savedLines = useMemo(
    () =>
      parseDialogueLines(
        dialogueLinesFromNode(node).map((row) => ({
          id: row.id,
          text: row.text,
          emotion: row.emotion,
        })),
      ),
    [signature],
  );

  const update = (index: number, patch: Partial<DialogueLineDraft>) => {
    setDirty(true);
    setRows((current) =>
      current.map((row, position) => (position === index ? { ...row, ...patch } : row)),
    );
  };

  const save = () => {
    if (!patchNode || issues.length > 0) return;
    void patchNode(node.node_id, {
      // Merge: the prompt and every other key survive.
      structured_content: {
        ...node.structured_content,
        dialogue_lines: rows
          .filter((row) => row.id.trim() && row.text.trim())
          .map((row) => {
            const entry: Record<string, string> = { id: row.id.trim(), text: row.text.trim() };
            if (row.emotion.trim()) entry.emotion = row.emotion.trim();
            return entry;
          }),
        regenerate_line_ids: rows
          .filter((row) => row.regenerate && row.id.trim())
          .map((row) => row.id.trim()),
      },
    });
    setDirty(false);
  };

  const manifest = (node.structured_content?.dialogue_line_manifest ?? null) as
    | { line_id?: string; text?: string; emotion?: string; duration_seconds?: number | null; offset_seconds?: number; regenerated?: boolean }[]
    | null;
  const dropped = (node.structured_content?.dialogue_lines_dropped ?? null) as string[] | null;

  return (
    <section className="voice-cast-lines" data-testid="voice-cast-lines">
      <header className="voice-cast-lines__head">
        <h4>逐行台词（每句是一个 Audio Event）</h4>
        <button
          type="button"
          onClick={() => {
            setDirty(true);
            setRows((current) => [
              ...current,
              { id: `line_${current.length + 1}`, text: "", emotion: "", regenerate: false },
            ]);
          }}
        >
          + 一行
        </button>
      </header>
      <p className="voice-cast-lines__hint">
        改了哪一句就只重做哪一句——没动的句子沿用已有录音，不重复计费。
        「重做」是对同样的字要另一遍表演（换情绪、 or simply 再来一次）。
      </p>
      {rows.map((row, index) => (
        <div className="voice-cast-lines__row" key={`row-${index}`}>
          <input
            aria-label={`第 ${index + 1} 行 id`}
            placeholder="id"
            value={row.id}
            onChange={(event) => update(index, { id: event.target.value })}
          />
          <input
            aria-label={`第 ${index + 1} 行台词`}
            placeholder="台词"
            value={row.text}
            onChange={(event) => update(index, { text: event.target.value })}
          />
          <input
            aria-label={`第 ${index + 1} 行情绪`}
            placeholder="情绪（如：压低声音）"
            value={row.emotion}
            onChange={(event) => update(index, { emotion: event.target.value })}
          />
          <label className="voice-cast-lines__regen">
            <input
              type="checkbox"
              aria-label={`重做第 ${index + 1} 行`}
              checked={row.regenerate}
              onChange={(event) => update(index, { regenerate: event.target.checked })}
            />
            重做
          </label>
          <button
            type="button"
            aria-label={`删除第 ${index + 1} 行`}
            onClick={() => {
              setDirty(true);
              setRows((current) => current.filter((_, position) => position !== index));
            }}
          >
            ×
          </button>
        </div>
      ))}
      {issues.length > 0 && (
        <ul className="voice-cast-lines__issues" data-testid="voice-cast-lines-issues">
          {issues.map((issue) => (
            <li key={issue.code + issue.message}>{issue.message}</li>
          ))}
        </ul>
      )}
      <button
        type="button"
        className="voice-cast-lines__save"
        data-testid="voice-cast-lines-save"
        disabled={!patchNode || issues.length > 0 || !dirty}
        onClick={save}
      >
        {dirty ? `保存逐行台词 ●（${rows.filter((row) => row.regenerate).length} 句标记重做）` : "保存逐行台词"}
      </button>

      {dropped && dropped.length > 0 && (
        <ul className="voice-cast-lines__dropped" data-testid="voice-cast-lines-dropped">
          {dropped.map((reason) => (
            <li key={reason}>{reason}</li>
          ))}
        </ul>
      )}

      {Array.isArray(manifest) && manifest.length > 0 && (
        <table className="voice-cast-lines__manifest" data-testid="voice-cast-lines-manifest">
          <caption>上一次成音的每一句（executor 发布）</caption>
          <thead>
            <tr>
              <th>id</th>
              <th>起点</th>
              <th>时长</th>
              <th>情绪</th>
              <th>本run重做</th>
            </tr>
          </thead>
          <tbody>
            {manifest.map((entry, index) => (
              <tr key={`${entry.line_id}-${index}`}>
                <td>{entry.line_id}</td>
                <td>{entry.offset_seconds ?? "—"}s</td>
                <td>{entry.duration_seconds ?? "—"}s</td>
                <td>{entry.emotion || "—"}</td>
                <td>{entry.regenerated ? "是" : "否"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      {savedLines.length > 0 && (
        <p className="voice-cast-lines__reuse" data-testid="voice-cast-lines-reuse">
          {(() => {
            const plan = planLineSynthesis(savedLines, {
              cacheDir: "voicecast-per-line-cache",
              fileExists: () => true,
              regenerateIds: (node.structured_content?.regenerate_line_ids ?? []) as string[],
            });
            const redo = plan.toSynthesize.length;
            return redo === 0
              ? "保存后重跑：所有句子都有现成录音，只会重新拼接，不调 TTS。"
              : `保存后重跑：${savedLines.length - redo} 句沿用现成录音，${redo} 句重新合成。`;
          })()}
        </p>
      )}
    </section>
  );
}
