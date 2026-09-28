/**
 * Director command bar — the live "喊话台" discussed for the 3D previs flow.
 * The bar is the MVP of the intent-level motion layer: instead of the author
 * hand-picking a preset in the inspector and choosing seconds, the director
 * types or picks a command and the 3D preview updates optimistically. Each
 * command is one of the deterministic presets already shipped in
 * cameraMotionPresets / characterMotionPresets, expanded locally via
 * directorMotion. The preview updates optimistically through onChange, and the
 * SAME op batch is POSTed through the backend apply-operations gate
 * (directorOperationsClient): when the gate passes the bar adopts its
 * post-apply script, when it rejects the optimistic preview is kept and the
 * reason surfaced.
 * Deliberate scope for the MVP:
 * - no free-form natural language yet; commands are a curated vocabulary
 *   (preset id + target + seconds). The free-form layer plugs in later by
 *   mapping LLM output onto the same DirectorMotionCommand shape.
 * - optimistic preview + gate persistence: no local rollback, because onChange
 *   is the editor's undo/save pipeline; the backend gate is the authoritative
 *   check that a batch is legal to persist.
 */

import { useMemo, useState } from "react";
import type { SceneScriptRoot } from "../../../types/scene-script";
import type { SceneVec3 } from "./sceneScriptAxes.ts";
import { CAMERA_MOTION_PRESETS } from "./cameraMotionPresets.ts";
import { CHARACTER_MOTION_PRESETS } from "./characterMotionPresets.ts";
import { expandDirectorMotionIntent } from "./directorMotion.ts";
import { sceneObjectPositionAtFrame, type SceneObjectRef } from "./sceneScriptEditModel.ts";
import {
  applyNudge,
  availableNudgesFor,
  NUDGE_LABELS,
  NUDGE_COMMANDS,
  type NudgeCommand,
} from "./directorNudges.ts";
import { useSceneScriptPlayback } from "./SceneScriptPlaybackContext.tsx";
import { applyDirectorMotion } from "./directorOperationsClient.ts";
import { applyTriggerEvent } from "./directorOperationsClient.ts";

export interface DirectorCommandStatus {
  ok: boolean;
  message: string;
}

export interface DirectorCommandBarProps {
  sceneScript: SceneScriptRoot;

  /** Apply the optimistically expanded script; the editor owns undo/save. */

  onApply: (next: SceneScriptRoot) => void;
  /** The object the viewport currently points at ("这个"). */

  selectedObject: SceneObjectRef | null;
  /** The playhead frame, so nudges target the right pose for per-frame objects. */

  playheadFrame?: number;
  /** Apply a nudge-edited script; the editor owns undo/save (same channel as onApply). */

  onNudge?: (next: SceneScriptRoot) => void;

  disabled?: boolean;

}

type PresetEntry = { id: string; label: string };

export function DirectorCommandBar({

  sceneScript,

  onApply,

  selectedObject,

  playheadFrame = 0,

  onNudge,

  disabled,

}: DirectorCommandBarProps) {

  const [targetId, setTargetId] = useState<string>("");

  const [presetId, setPresetId] = useState<string>("");

  const [seconds, setSeconds] = useState("2");

  const [status, setStatus] = useState<DirectorCommandStatus | null>(null);
  const [trigger, setTrigger] = useState<string>("");
  const [triggerTargetId, setTriggerTargetId] = useState<string>("");
  const [triggerSeconds, setTriggerSeconds] = useState<string>("0");
  const [triggerTargetPositionStr, setTriggerTargetPositionStr] = useState<string>("");
  const [triggerTargetYawStr, setTriggerTargetYawStr] = useState<string>("");

  const triggerTargetPosition = useMemo(() => {
    const parts = triggerTargetPositionStr.split(",").map((s) => s.trim());
    if (parts.length === 3) {
      const nums = parts.map((s) => Number(s));
      if (nums.every((n) => !Number.isNaN(n))) return nums as readonly number[];
    }
    return null;
  }, [triggerTargetPositionStr]);

  const triggerTargetYaw = useMemo(() => {
    if (!triggerTargetYawStr) return null;
    const n = Number(triggerTargetYawStr);
    return Number.isNaN(n) ? null : n;
  }, [triggerTargetYawStr]);

  const playback = useSceneScriptPlayback();

  const targets = useMemo(() => {

    const options: { id: string; label: string; intent: "camera_motion" | "character_motion" }[] = [];

    for (const camera of sceneScript.cameras) {

      options.push({ id: camera.id, label: `相机 · ${camera.id}`, intent: "camera_motion" });

    }

    for (const character of sceneScript.characters) {

      options.push({ id: character.id, label: `角色 · ${character.id}`, intent: "character_motion" });

    }

    return options;

  }, [sceneScript]);

  const activeTarget = targets.find((target) => target.id === targetId) ?? null;

  const presets: PresetEntry[] = useMemo(() => {

    if (activeTarget?.intent === "camera_motion") {

      return CAMERA_MOTION_PRESETS.map((preset) => ({ id: preset.id, label: preset.label }));

    }

    if (activeTarget?.intent === "character_motion") {

      return CHARACTER_MOTION_PRESETS.map((preset) => ({ id: preset.id, label: preset.label }));

    }

    return [];

  }, [activeTarget]);

  const needsCharacterTarget = activeTarget?.intent === "character_motion";

  // 微调 (compare-grade) row: the selected object in the viewport, not the

  // preset target — nudges are relative tweaks to "this", applied locally

  // through the editor's onChange (same channel a drag uses), no round trip.

  const nudgeCommands = useMemo(() => {

    if (!selectedObject) return [] as NudgeCommand[];

    return availableNudgesFor(selectedObject.kind);

  }, [selectedObject]);

  const nudge = (command: NudgeCommand) => {

    if (!selectedObject || !onNudge) return;

    onNudge(applyNudge(sceneScript, selectedObject, playheadFrame, command));

  };

  const submitTrigger = async () => {
    if (!trigger || !triggerTargetId) {
      setStatus({ ok: false, message: "请先选择触发条件和目标角色。" });
      return;
    }
    const frame = playback.currentFrame;
    const thenFrame = Math.round(Number(triggerSeconds) || 0) * sceneScript.scene.frame_rate;
    const request = {
      trigger,
      triggerTargetId,
      triggerFrame: frame,
      triggerTargetPosition: triggerTargetPosition,
      triggerTargetYaw: triggerTargetYaw ? Number(triggerTargetYaw) : null,
      thenOps: [],
      thenFrame: frame + thenFrame,
    };
    try {
      const gate = await applyTriggerEvent(sceneScript, request);
      if (gate.ok && gate.appliedSceneScript) {
        onApply(gate.appliedSceneScript);
        setStatus({ ok: true, message: `触发事件已过闸门：${trigger} @ frame ${frame}` });
      } else {
        setStatus({ ok: true, message: `触发事件未过闸门：${gate.error ?? "未知"}` });
      }
    } catch (error) {
      setStatus({ ok: false, message: error instanceof Error ? error.message : String(error) });
    }
  };

  const submit = async () => {

    const frame = playback.currentFrame;

    if (!activeTarget || !presetId) {

      setStatus({ ok: false, message: "先选一个对象和一条指令。" });

      return;

    }

    const durationFrames = Math.max(

      1,

      Math.round((Number(seconds) || 1) * sceneScript.scene.frame_rate),

    );

    // "Walk to that": when the author points at another object while the

    // character preset needs a destination, use that object's position at

    // the current playhead frame. Without a selection the preset falls

    // back to the one-metre-along-facing default (inside directorMotion).

    const targetPosition = needsCharacterTarget

      ? selectedObject

        ? sceneObjectPositionAtFrame(sceneScript, selectedObject, playheadFrame)

        : undefined

      : undefined;

    // sceneObjectPositionAtFrame can return null when the picked object is

    // missing from the script; the preset then falls back to its default.

    const characterTarget = targetPosition ?? undefined;

    try {

      const command = expandDirectorMotionIntent(sceneScript, {

        intent: activeTarget.intent,

        targetId: activeTarget.id,

        presetId,

        startFrame: frame,

        durationFrames,

        targetPosition: characterTarget,

      });

      // Optimistically preview first so the viewport reacts immediately, then

      // run the batch through the backend gate. When the gate passes, adopt its

      // post-apply script so preview and persisted state stay in lockstep; on

      // rejection keep the optimistic preview and surface the reason.

      onApply(command.previewScript);

      const gate = await applyDirectorMotion(sceneScript, command.request);

      if (gate.ok && gate.appliedSceneScript) {

        onApply(gate.appliedSceneScript);

        setStatus({

          ok: true,

          message: `已过闸门：${activeTarget.label} · ${presets.find((entry) => entry.id === presetId)?.label ?? presetId}（${durationFrames} 帧）。`,

        });

      } else {

        setStatus({

          ok: true,

          message: `已预览：${activeTarget.label} · ${presets.find((entry) => entry.id === presetId)?.label ?? presetId}（${gate.error ? `未过闸门：${gate.error}` : "已预览"}）。`,

        });

      }

    } catch (error) {

      setStatus({

        ok: false,

        message: error instanceof Error ? error.message : String(error),

      });

    }

  };

  const selectTarget = (id: string) => {

    setTargetId(id);

    const next = targets.find((target) => target.id === id);

    const nextPresets =

      next?.intent === "camera_motion"

        ? CAMERA_MOTION_PRESETS

        : next?.intent === "character_motion"

          ? CHARACTER_MOTION_PRESETS

          : [];

    setPresetId(nextPresets[0]?.id ?? "");

    setStatus(null);

  };

  return (

    <div

      className="scene-script-3d-editor__director"

      data-testid="scene-script-3d-director"

    >

      <label className="scene-script-3d-editor__field">

        <span>对象</span>

        <select

          aria-label="导演指令对象"

          value={targetId}

          onChange={(event) => selectTarget(event.target.value)}

          disabled={disabled}

        >

          <option value="">选择要调度的对象…</option>

          {targets.map((target) => (

            <option key={target.id} value={target.id}>

              {target.label}

            </option>

          ))}

        </select>

      </label>

      <label className="scene-script-3d-editor__field">

        <span>指令</span>

        <select

          aria-label="导演指令"

          value={presetId}

          onChange={(event) => setPresetId(event.target.value)}

          disabled={disabled || !activeTarget}

        >

          <option value="">

            {activeTarget

              ? "选择一条运动指令…"

              : "（先选对象）"}

          </option>

          {presets.map((preset) => (

            <option key={preset.id} value={preset.id}>

              {preset.label}

            </option>

          ))}

        </select>

      </label>

      <label className="scene-script-3d-editor__field">

        <span>时长(s)</span>

        <input

          type="number"

          min={0.5}

          step={0.5}

          value={seconds}

          aria-label="导演指令时长 (s)"

          onChange={(event) => setSeconds(event.target.value)}

          disabled={disabled}

        />

      </label>

      <button

        type="button"

        className="scene-script-3d-editor__save"

        onClick={submit}

        disabled={disabled || !activeTarget || !presetId}

        data-testid="scene-script-3d-director-submit"

      >

        执行指令

      </button>

      {nudgeCommands.length > 0 && selectedObject ? (

        <div className="scene-script-3d-editor__nudges" data-testid="scene-script-3d-director-nudges">

          <span className="scene-script-3d-editor__nudge-label">

            微调

          </span>

          {nudgeCommands.map((command) => (

            <button

              key={command}

              type="button"

              onClick={() => nudge(command)}

              disabled={disabled}

              data-testid={`scene-script-3d-director-nudge-{$command}`}

            >

              {NUDGE_LABELS[command]}

            </button>

          ))}

        </div>

      ) : null}

      {trigger || triggerTargetId ? (
        <div className="scene-script-3d-editor__nudges" data-testid="scene-script-3d-director-trigger">
          <span className="scene-script-3d-editor__nudge-label">
            触发
          </span>
          <select
            aria-label="触发条件"
            value={trigger}
            onChange={(e) => setTrigger(e.target.value)}
            disabled={disabled}
            data-testid="scene-script-3d-director-trigger-cond"
          >
            <option value="">选择触发条件…</option>
            <option value="sit">坐下 (sit)</option>
            <option value="stand">站立 (stand)</option>
            <option value="line_spoken">台词完成 (line_spoken)</option>
            <option value="arrive">到达 (arrive)</option>
            <option value="face">转身 (face)</option>
          </select>
          <select
            aria-label="触发目标角色"
            value={triggerTargetId}
            onChange={(e) => setTriggerTargetId(e.target.value)}
            disabled={disabled || !trigger}
            data-testid="scene-script-3d-director-trigger-target"
          >
            <option value="">选择角色…</option>
            {sceneScript.characters.map((c) => (
              <option key={c.id} value={c.id}>{c.id}</option>
            ))}
          </select>
          {trigger === "arrive" ? (
            <input
              type="number"
              step="0.5"
              value={triggerTargetPositionStr}
              onChange={(e) => setTriggerTargetPositionStr(e.target.value)}
              disabled={disabled}
              aria-label="到达目标位置 (X,Y,Z)"
              data-testid="scene-script-3d-director-trigger-position"
            />
          ) : null}
          {trigger === "face" ? (
            <input
              type="number"
              step="15"
              value={triggerTargetYawStr}
              onChange={(e) => setTriggerTargetYawStr(e.target.value)}
              disabled={disabled}
              aria-label="转身目标角度 (°)"
              data-testid="scene-script-3d-director-trigger-yaw"
            />
          ) : null}
          <button
            type="button"
            className="scene-script-3d-editor__save"
            onClick={submitTrigger}
            disabled={disabled || !trigger || !triggerTargetId}
            data-testid="scene-script-3d-director-trigger-submit"
          >
            触发时执行
          </button>
        </div>
      ) : null}

      {status && (

        <span

          className={status.ok ? "scene-script-3d-editor__note" : "scene-script-3d-editor__error"}

          data-testid="scene-script-3d-director-status"

        >

          {status.message}

        </span>

      )}

    </div>

  );

}
