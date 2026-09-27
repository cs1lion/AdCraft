/**
 * ShotStrip — the scene's story structure at a glance (V0.2 §2.2/§2.3).
 *
 * The SceneScript's shot list was invisible: the author could only infer the
 * sequence from the playhead position and the inspector's frame fields. This
 * strip makes the sequence itself the surface: proportional bars (a 6-second
 * shot reads as a wider bar than a 1-second one), the playhead's position,
 * and a click-to-seek on each bar.
 *
 * The per-gap insert button is the last §2.2 semantic — 两个镜头之间 = 新镜头
 * 插入 — and it splits the shot's tail into a continuation of the SAME camera
 * (placing a new viewpoint stays an explicit act). The strip states the
 * minimum it will insert rather than silently refusing (the schema rejects
 * zero-length shots, so "too short" must be said, not swallowed).
 *
 * The leading-edge marker is the explicit transition relation (V0.2 §13 第 5
 * 问): how THIS shot enters. It is a label, not a connector line — a reading
 * is already authored as keyframes inside the script, so a line would be a
 * second copy that can disagree with the first. The marker sits on the
 * boundary because that is where the relation lives.
 *
 * The boundary row underneath names the same relation as a PAIR — 镜1 → 镜2：
 * 声音桥 — because §13's question is about the relation between two shots,
 * and "未登记" must read as a fact about the boundary, not as a missing label
 * on a shot. A shot whose predecessor is unknown (the first one) has no
 * boundary to name.
 */

import type { SceneShot } from "../../../types/scene-script";

/** Minimum seconds of an inserted shot (the strip states this). */
export const INSERT_SHOT_MIN_SECONDS = 0.5;

export interface ShotStripProps {
  shots: readonly SceneShot[];
  /** Total frames in the scene (the strip's full width). */
  totalFrames: number;
  currentFrame: number;
  onSeekFrame: (frame: number) => void;
  onInsertAfter: (shotId: string) => void;
  /**
   * Revoke a declared entry reading (V0.2 §12 "Transition Intent 如何被用户
   * 编辑"). A declaration the author cannot take back is not an edit — and
   * "some cuts are just cuts" is a legitimate state, not an oversight.
   */
  onClearIntent?: (shotId: string) => void;
}

/**
 * The declared reading, readable (pure, for tests and the tooltip).
 *
 * An id the machine invented is shown AS-IS rather than dropped: a validated
 * LLM-proposed reading is still the cut the author chose, and hiding its name
 * would make the label lie about the relation.
 */
export function transitionIntentLabel(readingId: string | null | undefined): string | null {
  const trimmed = (readingId ?? "").trim();
  if (!trimmed) return null;
  return TRANSITION_INTENT_LABELS[trimmed] ?? trimmed;
}

const TRANSITION_INTENT_LABELS: Record<string, string> = {
  continuous_motion: "连续运动",
  gaze_closeup: "视线特写",
  sound_bridge: "声音桥",
  cut_after_line: "说完再切",
  time_jump: "时间跳跃",
  angle_switch: "视角切换",
};

/** Frames each bar spans, in scene order (pure, for tests). */
export function shotBars(
  shots: readonly SceneShot[],
): { shot: SceneShot; startFrame: number; endFrame: number }[] {
  return [...shots]
    .sort((left, right) => left.start_frame - right.start_frame)
    .map((shot) => ({ shot, startFrame: shot.start_frame, endFrame: shot.end_frame }));
}

/** One boundary's relation: which reading carries shot N into shot N+1. */
export interface ShotTransitionRelation {
  /** The shot the relation starts from (null only for the scene's first shot). */
  fromShotId: string | null;
  /** The shot the relation lands on. */
  toShotId: string;
  /** The declared reading id, or null when the boundary is undeclared. */
  readingId: string | null;
  /** The readable label, or null */
  label: string | null;
}

/**
 * The relation shipping each boundary (pure, for tests and the boundary row).
 *
 * The scene's first shot is dropped: it has no predecessor, so the question
 * "how does it enter" has no subject. An undeclared boundary is reported with
 * a null reading rather than skipped — the author must be able to see that a
 * boundary is unclaimed, because an unclaimed boundary is exactly the one a
 * reviewer will ask about.
 */
export function shotTransitionRelations(
  shots: readonly SceneShot[],
): ShotTransitionRelation[] {
  const ordered = shotBars(shots);
  return ordered.slice(1).map(({ shot: to }, index) => {
    const from = ordered[index];
    const readingId = (to.transition_intent ?? "").trim() || null;
    return {
      fromShotId: from.shot.id,
      toShotId: to.id,
      readingId,
      label: transitionIntentLabel(readingId),
    };
  });
}

export function ShotStrip({
  shots,
  totalFrames,
  currentFrame,
  onSeekFrame,
  onInsertAfter,
  onClearIntent,
}: ShotStripProps) {
  const span = totalFrames > 0 ? totalFrames : 1;
  const bars = shotBars(shots);
  const relations = shotTransitionRelations(shots);
  const relationByFromShot = new Map(
    relations.map((relation) => [relation.fromShotId, relation]),
  );
  const playheadPercent = Math.min(100, Math.max(0, (currentFrame / span) * 100));

  if (bars.length === 0) return null;

  return (
    <div className="shot-strip" data-testid="shot-strip">
      <span className="shot-strip__title">镜头序列</span>
      <div className="shot-strip__track">
        {bars.map(({ shot, startFrame, endFrame }) => {
          const left = (startFrame / span) * 100;
          const width = Math.max(1.5, ((endFrame - startFrame + 1) / span) * 100);
          const isCurrent = currentFrame >= startFrame && currentFrame <= endFrame;
          const intent = transitionIntentLabel(shot.transition_intent);
          return (
            <button
              key={shot.id}
              type="button"
              className={`shot-strip__bar${isCurrent ? " is-current" : ""}${
                intent ? " has-intent" : ""
              }`}
              style={{ left: `${left}%`, width: `${width}%` }}
              title={`${shot.id}：帧 ${startFrame}–${endFrame}（${shot.camera}）${
                intent ? `\n入镜读法：${intent}` : ""
              }`}
              onClick={() => onSeekFrame(startFrame)}
            >
              <span className="shot-strip__bar-label">{shot.id}</span>
              {intent && (
                <span
                  className="shot-strip__intent"
                  data-testid={`shot-strip-intent-${shot.id}`}
                  data-intent={shot.transition_intent ?? ""}
                  title={`入镜读法：${intent}`}
                >
                  {intent}
                </span>
              )}
            </button>
          );
        })}
        <span
          className="shot-strip__playhead"
          style={{ left: `${playheadPercent}%` }}
          data-testid="shot-strip-playhead"
          aria-hidden="true"
        />
      </div>
      <div className="shot-strip__inserts">
        {bars.map(({ shot }) => {
          const relation = relationByFromShot.get(shot.id);
          return (
            <span className="shot-strip__insert-group" key={`group-${shot.id}`}>
              <button
                type="button"
                className="shot-strip__insert"
                data-testid={`shot-strip-insert-${shot.id}`}
                title={`在 ${shot.id} 之后插入一个同机位新镜头（至少 ${INSERT_SHOT_MIN_SECONDS}s）`}
                onClick={() => onInsertAfter(shot.id)}
              >
                在 {shot.id} 后插入
              </button>
              {relation && (
                <span
                  className={`shot-strip__relation${relation.label ? "" : " is-unclaimed"}`}
                  data-testid={`shot-strip-relation-${relation.fromShotId}-${relation.toShotId}`}
                  data-reading={relation.readingId ?? ""}
                  title={
                    relation.label
                      ? `${relation.fromShotId} → ${relation.toShotId} 以「${relation.label}」衔接`
                      : `${relation.fromShotId} → ${relation.toShotId} 还没有登记读法（未登记的边界正是审片会问的那一个）`
                  }
                >
                  {relation.fromShotId} → {relation.toShotId}：
                  {relation.label ?? "未登记"}
                </span>
              )}
              {shot.transition_intent && onClearIntent && (
                <button
                  type="button"
                  className="shot-strip__clear-intent"
                  data-testid={`shot-strip-clear-intent-${shot.id}`}
                  title={`取消 ${shot.id} 的入镜读法登记（这一镜不再声明它从哪个读法接入；镜头本身不变）`}
                  onClick={() => onClearIntent(shot.id)}
                >
                  取消登记 · {transitionIntentLabel(shot.transition_intent)}
                </button>
              )}
            </span>
          );
        })}
      </div>
    </div>
  );
}
