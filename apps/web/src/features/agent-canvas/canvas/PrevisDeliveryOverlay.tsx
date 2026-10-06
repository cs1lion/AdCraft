/**
 * PrevisDeliveryOverlay — the central report card the author reads after acting.
 *
 * The reference framework answers an action with a card that covers the middle
 * of the viewport: what the scene now delivers, and what just changed. Until
 * now this product had numbers in the inspector and a compact list under the
 * instruction bar, but nothing that ANSWERS — so "我用一句话说了半天，然后呢？"
 * had no reply anywhere in the UI.
 *
 * This card is deliberately honest about the difference between the two kinds
 * of line it shows:
 *
 *   「已调整」  — derived by diffing the script before/after an edit, so a shot
 *               that did not change is not named and a no-op is not a change.
 *   「整段成片」— computed from the current script: shot count, span, and how
 *               many shots have a published clip. These are facts about the
 *               scene, not claims about work performed.
 *
 * It never prints 「已执行 preview_3D_scene」. That sentence asserts an agent
 * ran, and in this build the instruction channel is not wired to one — so the
 * card says so instead, in the same place the author is already looking.
 */

import { useCallback, useEffect, useMemo } from "react";

import type { SceneScriptRoot } from "../../../types/scene-script";
import type { PublishedPrevisClipEntryV2 } from "../../../types-v2.ts";
import type { SceneEditReport } from "./shotLabels.ts";
import { cameraLabel, shotChangeHeadline, shotDurationSeconds } from "./shotLabels.ts";

export interface PrevisDeliveryOverlayProps {
  /** The current scene; the delivery summary is computed from it. */
  sceneScript: SceneScriptRoot;
  /** Clips published from this scene's shots, for the coverage line. */
  clips: readonly PublishedPrevisClipEntryV2[];
  /** The last edit's report, when an edit just landed. */
  editReport?: SceneEditReport | null;
  /** Where an unwired instruction would have been applied. */
  pendingSubject?: { label: string; scope: "object" | "shot" } | null;
  /** Called when the author dismisses the card. */
  onDismiss: () => void;
}

export function PrevisDeliveryOverlay({
  sceneScript,
  clips,
  editReport = null,
  pendingSubject = null,
  onDismiss,
}: PrevisDeliveryOverlayProps) {
  const frameRate = sceneScript.scene.frame_rate;
  const shots = useMemo(
    () => [...sceneScript.shots].sort((left, right) => left.start_frame - right.start_frame),
    [sceneScript.shots],
  );
  // Derived from `sceneScript` rather than a slice of it: if the prop is ever
  // replaced wholesale the map has to follow, and a dependency on a sub-field
  // is exactly the shape that hides that from the linter (and from me).
  const cameraById = useMemo(() => {
    const map = new Map<string, { camera: SceneScriptRoot["cameras"][number]; index: number }>();
    sceneScript.cameras.forEach((camera, index) => map.set(camera.id, { camera, index }));
    return map;
  }, [sceneScript]);

  const published = useMemo(() => {
    const set = new Set(clips.map((clip) => clip.shot_id));
    return (shotId: string) => set.has(shotId);
  }, [clips]);

  const totalSeconds = useMemo(
    () => shots.reduce((sum, shot) => sum + shotDurationSeconds(shot, frameRate), 0),
    [shots, frameRate],
  );

  // Escape closes the card. The card covers the viewport, so a keyboard escape
  // is not a nicety — it is the only way out for someone who is not looking at
  // the dismiss button.
  const onKeyDown = useCallback(
    (event: KeyboardEvent) => {
      if (event.key === "Escape") onDismiss();
    },
    [onDismiss],
  );
  useEffect(() => {
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [onKeyDown]);

  return (
    <section
      className="previs-delivery"
      data-testid="previs-delivery"
      role="dialog"
      aria-modal="false"
      aria-label="本次预演交付"
    >
      <header className="previs-delivery__header">
        <span className="previs-delivery__title">{sceneScript.scene.name}</span>
        <span className="previs-delivery__meta">
          {shots.length} 个分镜 · {totalSeconds.toFixed(1)}s ·{" "}
          {shots.filter((shot) => published(shot.id)).length}/{shots.length} 已发布片段
        </span>
        <button
          type="button"
          className="previs-delivery__dismiss"
          aria-label="关闭交付报告"
          onClick={onDismiss}
        >
          ×
        </button>
      </header>

      {editReport && editReport.shots.length > 0 && (
        <div className="previs-delivery__section" data-testid="previs-delivery-changes">
          <h3 className="previs-delivery__section-title">已调整</h3>
          <ul className="previs-delivery__changes">
            {editReport.shots.map((shot) => (
              <li key={shot.id}>
                <span className="previs-delivery__change-headline">
                  {shotChangeHeadline(shot)}
                </span>
                <span className="previs-delivery__change-codes">
                  {shot.changes
                    .map((code) => editReport.labels[code] ?? code)
                    .join(" · ")}
                </span>
              </li>
            ))}
          </ul>
        </div>
      )}

      <div className="previs-delivery__section" data-testid="previs-delivery-shots">
        <h3 className="previs-delivery__section-title">整段成片</h3>
        <ol className="previs-delivery__shots">
          {shots.map((shot) => {
            const match = cameraById.get(shot.camera);
            const label = match
              ? cameraLabel(match.camera, match.index)
              : shot.camera;
            const span = `${shot.start_frame / frameRate}–${(shot.end_frame + 1) / frameRate}s`;
            return (
              <li
                key={shot.id}
                data-published={published(shot.id) ? "true" : "false"}
                data-shot-id={shot.id}
              >
                <span className="previs-delivery__shot-label">{label}</span>
                <span className="previs-delivery__shot-span">{span}</span>
                <span className="previs-delivery__shot-state">
                  {published(shot.id) ? "已发布片段" : "未发布"}
                </span>
              </li>
            );
          })}
        </ol>
      </div>

      {pendingSubject && (
        // An instruction the channel could not carry. Say so where the author
        // is looking, with the target it would have applied to.
        <p className="previs-delivery__pending" data-testid="previs-delivery-pending">
          指令尚未接线：它本应作用于「{pendingSubject.label}」。agent 通道未连接，
          场景改动请用导演预设或视口拖拽。
        </p>
      )}
    </section>
  );
}

export default PrevisDeliveryOverlay;
