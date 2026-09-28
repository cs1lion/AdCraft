/**
 * Dialogue takes — 听法分叉 (V0.2 §14.13 "不仅能分叉镜头，也能分叉同一句
 * 对白的语气、速度、停顿").
 *
 * The research names the idea in one line: fork the SAME line's tone, speed
 * and pause into different emotional versions, then compare which one suits
 * the picture that follows. The unit is ONE dialogue line and the fork is a
 * DELIVERY DELTA against the line's own direction (``emotion``, V0.2 §14.7
 * 表演层) — which is why this is not ``directorTakes`` (a labelled
 * whole-SceneScript snapshot for "go back to that version") and not
 * ``transitionVariants`` (readings of one boundary).
 *
 * This module mirrors ``app/services/scene3d/dialogue_takes.py``: the same
 * catalogue (ids, labels, deltas), the same cap and the same fail-closed
 * reasons, so the panel can offer the fork without a round trip. Keep them
 * in lockstep — the python suite locks the parity against this file.
 *
 * The last fork (就按稿) is the line exactly as authored: a comparison that
 * omits the original cannot be won.
 */

/** How many forks one line offers (same magnitude as transitionVariants). */
export const MAX_DIALOGUE_TAKES = 4;

/** One reading of a line: the deltas to apply to the authored take. */
export interface DialogueTakeFork {
  id: string;
  /** Creator-facing label (the deliverable the panel lists). */
  label: string;
  /** Relative tempo delta (e.g. -0.15 = 15% slower than authored). */
  tempo_delta: number;
  /** Seconds added to the pause around the line (may be negative). */
  pause_delta: number;
  /** Emotion override; empty = keep the line's own annotation. */
  emotion: string;
  /** One line on what the reading is FOR (shown under the label). */
  note: string;
}

/** The catalogue, in the order the panel lists it. */
export const DIALOGUE_TAKE_FORKS: readonly DialogueTakeFork[] = [
  {
    id: "take_emotion_pressed",
    label: "压下去",
    tempo_delta: -0.15,
    pause_delta: 0.12,
    emotion: "压低",
    note: "更慢、停顿更长：把话按回心里，适合接特写或沉默。",
  },
  {
    id: "take_emotion_lifted",
    label: "提起来",
    tempo_delta: 0.12,
    pause_delta: -0.08,
    emotion: "轻快",
    note: "更快、停顿更短：话赶着画面走，适合接动作或反打。",
  },
  {
    id: "take_emotion_broken",
    label: "顿一顿",
    tempo_delta: -0.05,
    pause_delta: 0.22,
    emotion: "紧绷",
    note: "几乎同速，但句间停顿被拉长：说到一半咽回去。",
  },
  {
    id: "take_emotion_authored",
    label: "就按稿",
    tempo_delta: 0.0,
    pause_delta: 0.0,
    emotion: "",
    note: "照你写的来：用来对照，别让它从比较里消失。",
  },
];

/** Every fork id — for validating a picked take and for the error message. */
export const DIALOGUE_TAKE_FORK_IDS: readonly string[] = DIALOGUE_TAKE_FORKS.map(
  (fork) => fork.id,
);

/** The tempo a fork may resolve to (1.0 = as authored). */
export const MIN_TAKE_TEMPO_RATE = 0.5;
export const MAX_TAKE_TEMPO_RATE = 2.0;

/** The line a fork forks (the panel's row is plain JSON on the way in). */
export interface DialogueTakeLine {
  line_id?: string | null;
  id?: string | null;
  text?: string | null;
  emotion?: string | null;
}

/** One planned fork of one line: a stable id, a label, and the deltas. */
export interface DialogueTake {
  id: string;
  label: string;
  tempo_delta: number;
  pause_delta: number;
  /** The RESOLVED emotion the line carries once this fork is picked. */
  emotion: string;
  line_id: string;
  /** True when the emotion is the line's own, not an override. */
  inherits_emotion: boolean;
  /** The absolute tempo this fork resolves to (1.0 = as authored). */
  tempo_rate: number;
  /** The panel's parameter summary: label + what actually changes. */
  summary: string;
}

/** The forks offered, plus the record of the cap and of a refusal. */
export interface DialogueTakePlan {
  /** Empty when the line cannot be forked (``reason`` says why). */
  takes: DialogueTake[];
  /** null on success; otherwise the sentence the panel shows. */
  reason: string | null;
  /** The machine-readable code for ``reason`` (what a surface switches on). */
  code: string | null;
  /** What the caller asked for (the cap clamps it, visibly). */
  requested_variants: number;
  /** Fork ids the cap trimmed off the end (oldest first). */
  dropped_take_ids: string[];
}

function asString(value: unknown): string {
  return typeof value === "string" ? value : "";
}

function clamp(value: number, low: number, high: number): number {
  return Math.max(low, Math.min(high, value));
}

/** Mirrors the id rule of the per-line dialogue mode. */
const LINE_ID_PATTERN = /^[A-Za-z0-9_-]{1,48}$/;

/** Characters that must not appear in an emotion annotation: it is pasted
 * into the provider's prompt as "(emotion)", so a parenthesis closes it
 * early and a line break splits the line (same rule as step_audio_gen). */
const ANNOTATION_BREAKERS = /[()\n\r\t]/;

/** The panel's parameter summary (mirrors ``DialogueTake.summary``). */
export function dialogueTakeSummary(
  take: Pick<DialogueTake, "label" | "tempo_delta" | "pause_delta" | "emotion" | "inherits_emotion">,
): string {
  const percent = Math.round(take.tempo_delta * 100);
  const tempo = `${percent >= 0 ? "+" : ""}${percent}%`;
  const pause = `${take.pause_delta >= 0 ? "+" : ""}${take.pause_delta.toFixed(2)}s`;
  let emotion = take.emotion || "留空";
  if (take.inherits_emotion && take.emotion) emotion = `${emotion}（稿件原有）`;
  return `${take.label} · 语速 ${tempo} · 停顿 ${pause} · 语气：${emotion}`;
}

/**
 * Plan the forks for one line. Returns an empty list plus a reason when the
 * line cannot be forked — fail closed and named, never a silent empty list
 * (ADR 0005). Prefer this over ``planDialogueTakes`` wherever a creator is
 * on the other side of the result.
 */
export function planDialogueTakesWithReport(
  line: DialogueTakeLine | null | undefined,
  variants: number = MAX_DIALOGUE_TAKES,
): DialogueTakePlan {
  const requested = Number.isFinite(variants) ? Math.trunc(variants) : MAX_DIALOGUE_TAKES;
  const refusal = (reason: string, code: string): DialogueTakePlan => ({
    takes: [],
    reason,
    code,
    requested_variants: requested,
    dropped_take_ids: [],
  });

  if (!line || typeof line !== "object" || Array.isArray(line)) {
    return refusal("这一行不是可分叉的台词行，已拒绝听法分叉。", "dialogue_line_not_a_line");
  }
  const lineId = asString(line.line_id ?? line.id).trim();
  const text = asString(line.text);
  const emotionRaw = asString(line.emotion).trim();
  if (!lineId) {
    return refusal(
      "台词行没有 id：听法分叉要能指回是哪一句（逐行模式的 id 规则同样适用）。",
      "dialogue_line_id_missing",
    );
  }
  if (!LINE_ID_PATTERN.test(lineId)) {
    return refusal(
      `台词行 id「${lineId}」只能用字母数字与 -_ 且不超过 48 字符，已拒绝分叉。`,
      "dialogue_line_id_invalid",
    );
  }
  if (!text.trim()) {
    return refusal(
      `「${lineId}」没有台词文本：分叉的是同一句话的语气，空句无可分叉。`,
      "dialogue_line_text_empty",
    );
  }
  if (text.trim().length > 400) {
    return refusal(
      `「${lineId}」的台词超过 400 字符，已拒绝分叉（与逐行台词同一上限）。`,
      "dialogue_line_text_too_long",
    );
  }
  if (emotionRaw.length > 64) {
    return refusal(
      `「${lineId}」的情绪标注「${emotionRaw}」超过 64 字符，已拒绝分叉。`,
      "dialogue_line_emotion_too_long",
    );
  }
  if (ANNOTATION_BREAKERS.test(emotionRaw)) {
    return refusal(
      `「${lineId}」的情绪标注「${emotionRaw}」含括号或换行：它会拼进 TTS 的 (emotion) ` +
        "标注里，provider 会把整句切开，已拒绝分叉。",
      "dialogue_line_emotion_unbalanced",
    );
  }
  if (requested < 1) {
    return refusal(
      `听法分叉数量至少为 1（收到了 ${requested}），已拒绝分叉。`,
      "dialogue_take_variants_below_one",
    );
  }

  // Only the CAP drops forks: asking for two of four is a choice, not an
  // eviction, so nothing is reported as dropped until the catalogue is
  // longer than the cap itself.
  const offered = DIALOGUE_TAKE_FORKS.slice(0, Math.min(requested, MAX_DIALOGUE_TAKES));
  const dropped = DIALOGUE_TAKE_FORKS.slice(MAX_DIALOGUE_TAKES).map((fork) => fork.id);
  const takes: DialogueTake[] = offered.map((fork) => {
    const inherits = fork.emotion === "";
    const take: DialogueTake = {
      id: fork.id,
      label: fork.label,
      tempo_delta: fork.tempo_delta,
      pause_delta: fork.pause_delta,
      emotion: inherits ? emotionRaw : fork.emotion,
      line_id: lineId,
      inherits_emotion: inherits,
      tempo_rate: clamp(1 + fork.tempo_delta, MIN_TAKE_TEMPO_RATE, MAX_TAKE_TEMPO_RATE),
      summary: "",
    };
    take.summary = dialogueTakeSummary(take);
    return take;
  });
  return {
    takes,
    reason: null,
    code: null,
    requested_variants: requested,
    dropped_take_ids: dropped,
  };
}

/**
 * The forks of one line, as a list. An unusable line yields [] — use
 * ``planDialogueTakesWithReport`` when the reason must survive.
 */
export function planDialogueTakes(
  line: DialogueTakeLine | null | undefined,
  variants: number = MAX_DIALOGUE_TAKES,
): DialogueTake[] {
  return planDialogueTakesWithReport(line, variants).takes;
}

/** True when the cap gave fewer forks than were asked for. */
export function dialogueTakePlanCapped(plan: DialogueTakePlan): boolean {
  return plan.requested_variants > plan.takes.length;
}

/** The catalogue fork behind a take, an id, or itself (null when unknown). */
export function dialogueTakeFork(
  take: DialogueTake | string | DialogueTakeFork | null | undefined,
): DialogueTakeFork | null {
  if (!take) return null;
  if (typeof take === "object" && "note" in take) return take as DialogueTakeFork;
  const id = (typeof take === "string" ? take : asString(take.id)).trim();
  return DIALOGUE_TAKE_FORKS.find((fork) => fork.id === id) ?? null;
}

/** The absolute values a picked fork puts on a line (null when unusable). */
export function resolveDialogueTake(
  line: DialogueTakeLine | null | undefined,
  take: DialogueTake | string | DialogueTakeFork | null | undefined,
  baseTempoRate = 1,
  basePauseSeconds = 0,
): { tempo_rate: number; pause_seconds: number; emotion: string } | null {
  const fork = dialogueTakeFork(take);
  if (!fork) return null;
  // The whole catalogue, so the baseline fork (就按稿) is always there to
  // answer "what does this line say about itself?" — resolve() is not a
  // function of how many forks the caller happened to ask for.
  const plan = planDialogueTakesWithReport(line);
  if (plan.reason !== null) return null;
  const authored = plan.takes.find((entry) => entry.inherits_emotion);
  return {
    tempo_rate: clamp(
      baseTempoRate + fork.tempo_delta,
      MIN_TAKE_TEMPO_RATE,
      MAX_TAKE_TEMPO_RATE,
    ),
    pause_seconds: Math.max(0, Number((basePauseSeconds + fork.pause_delta).toFixed(3))),
    emotion: fork.emotion || (authored?.emotion ?? ""),
  };
}

/**
 * The patch a picked fork puts on the line, shaped for the existing
 * per-line edit path (the same one the 语气 input drives) instead of a
 * second line model. Returns null when either side is unusable.
 */
export function applyDialogueTake(
  line: DialogueTakeLine | null | undefined,
  take: DialogueTake | string | DialogueTakeFork | null | undefined,
): { emotion: string; tempo_delta: number; pause_delta: number } | null {
  const fork = dialogueTakeFork(take);
  if (!fork) return null;
  const parameters = resolveDialogueTake(line, fork);
  if (!parameters) return null;
  return {
    emotion: parameters.emotion,
    tempo_delta: fork.tempo_delta,
    pause_delta: fork.pause_delta,
  };
}
