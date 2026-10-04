/**
 * SceneEditReportPanel — the "what did that edit actually change" readout.
 *
 * The reference framework answers a director's edit in one sentence: "飞船起飞的
 * 动画已加在「机位05 | 飞船俯瞰」对应的镜像段（4.5s-8.0s）". This component
 * renders the structured facts behind that sentence, which the backend
 * `scene_edit_report` derives by DIFFING the script before and after — never by
 * trusting the ops that were asked for. That distinction is the whole point:
 * an op that changed nothing (a move to the position already held) must not be
 * reported as a change, and a caller cannot be told something that did not
 * happen.
 *
 * It deliberately renders FACTS, not prose. The backend supplies the Chinese
 * label per change code; the wording of a summary sentence belongs to whoever
 * owns the voice, and inventing one here would be a claim this component cannot
 * back up.
 */

import { useMemo } from "react";

import type { SceneEditReport } from "./shotLabels";
import { shotChangeHeadline } from "./shotLabels";

export interface SceneEditReportPanelProps {
  report: SceneEditReport | null;
  /** Frame rate of the script, for the span readout. */
  frameRate: number;
}

export function SceneEditReportPanel({ report, frameRate }: SceneEditReportPanelProps) {
  // Declared before the early returns: hooks may not be conditional.
  const orphans = useMemo(() => {
    if (!report) return [] as [string, string[]][];
    const shotIds = new Set(report.shots.map((shot) => shot.id));
    return Object.entries(report.changes)
      .filter(([id, codes]) => !shotIds.has(id) && codes.length > 0)
      .map(([id, codes]) => [id, codes.map((code) => report.labels[code] ?? code)] as [string, string[]]);
  }, [report]);

  if (!report) return null;
  // An honest "nothing changed" beats an empty box: an author who just ran a
  // preset that resolved to a no-op must be able to see that it was a no-op.
  if (report.change_count === 0) {
    return (
      <p className="scene-edit-report scene-edit-report--empty" data-testid="scene-edit-report">
        这次调整没有改变场景内容。
      </p>
    );
  }

  return (
    <section className="scene-edit-report" data-testid="scene-edit-report" aria-label="本次调整的影响">
      <header className="scene-edit-report__header">
        <span className="scene-edit-report__title">已调整</span>
        <span className="scene-edit-report__count">
          {report.change_count} 处 · {report.shots.length}/{report.shot_count} 个镜头
        </span>
      </header>

      {report.shots.length > 0 && (
        <ul className="scene-edit-report__shots">
          {report.shots.map((shot) => (
            <li key={shot.id} className="scene-edit-report__shot" data-shot-id={shot.id}>
              <span className="scene-edit-report__shot-headline">{shotChangeHeadline(shot)}</span>
              <span className="scene-edit-report__shot-changes">
                {shot.changes.map((code) => report.labels[code] ?? code).join(" · ")}
              </span>
            </li>
          ))}
        </ul>
      )}

      {/* Objects that belong to no shot (a prop nobody animated) are still part
          of the answer; dropping them would under-report what the author did. */}
      {orphans.length > 0 && (
        <p className="scene-edit-report__orphans">
          {orphans.map(([id, codes]) => `${id}（${codes.join("、")}）`).join("；")}
        </p>
      )}
    </section>
  );
}

export default SceneEditReportPanel;
