/**
 * Scene3DPillRow — the scene-3d quick-entry pills.
 *
 * The reference framework's node panel opens with a row of pills (+参考 / 标记 /
 * 特效 / 角色库 / 运镜) so the author can reach the common surfaces without
 * hunting through a long editor.
 *
 * This renders ONLY the pills whose capability exists in this repo, and each
 * pill is a shortcut to a surface that is already on the page:
 *
 *   +参考  → SceneImageIntake         (drop a still, get a blockout)
 *   角色库 → SceneAssetTray           (the low-poly primitive palette)
 *   运镜   → the director command bar (camera motion presets)
 *
 * 标记 and 特效 are deliberately ABSENT. This repo has no marking or effects
 * feature, and a pill that opens nothing would be exactly the kind of
 * decorative control the engineering standard forbids (§4: an observable
 * surface must do what it says). If those capabilities are built, they get a
 * pill here — not before.
 *
 * The row is a navigation affordance, so it owns only scroll-and-flash. Every
 * pill's target is a real, already-mounted surface; nothing here creates state
 * the editor would have to unwind.
 */

import { useCallback, useRef } from "react";

export interface Scene3DPillRowProps {
  /** Suppressed while a save is in flight, like the surfaces it points at. */
  disabled?: boolean;
}

interface Pill {
  label: string;
  /** testid of the already-mounted surface this pill reveals. */
  target: string;
  /** Why this pill exists, in the author's terms. */
  title: string;
}

const PILLS: readonly Pill[] = [
  {
    label: "+参考",
    target: "scene-image-intake-drop",
    title: "参考图建景：丢一张静物照，生成同构低多边形场景",
  },
  {
    label: "角色库",
    target: "scene-asset-tray",
    title: "低多边形素材库：环境与道具原语，点一下即入景",
  },
  {
    label: "运镜",
    target: "scene-script-3d-director",
    title: "导演指令：推拉摇移等机位预设，与微调、触发事件",
  },
];

export function Scene3DPillRow({ disabled = false }: Scene3DPillRowProps) {
  const flashTimerRef = useRef<number | null>(null);

  const reveal = useCallback((target: string) => {
    const element = document.querySelector(`[data-testid="${target}"]`);
    if (!element) return;
    element.scrollIntoView({ block: "center", behavior: "smooth" });
    // A one-shot ring, so the author sees WHERE the pill took them: the 3D
    // section is long and scrollable, and a silent jump reads as nothing
    // having happened.
    element.setAttribute("data-pill-flash", "true");
    if (flashTimerRef.current !== null) window.clearTimeout(flashTimerRef.current);
    flashTimerRef.current = window.setTimeout(() => {
      element.removeAttribute("data-pill-flash");
      flashTimerRef.current = null;
    }, 900);
  }, []);

  return (
    <div className="scene-3d-pill-row" data-testid="scene-3d-pill-row" role="group" aria-label="场景快捷入口">
      {PILLS.map((pill) => (
        <button
          key={pill.label}
          type="button"
          className="scene-3d-pill-row__pill"
          data-testid={`scene-3d-pill-${pill.target}`}
          data-pill={pill.label}
          title={pill.title}
          disabled={disabled}
          onClick={() => reveal(pill.target)}
        >
          {pill.label}
        </button>
      ))}
      {/* Why three pills and not five: the reference's 标记/特效 have no
          counterpart here. Saying so is cheaper than a dead button. */}
      <span className="scene-3d-pill-row__note" data-testid="scene-3d-pill-row-note">
        标记 / 特效：本仓暂无此能力，故不出占位按钮
      </span>
    </div>
  );
}

export default Scene3DPillRow;
