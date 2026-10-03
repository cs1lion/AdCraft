/**
 * SceneScript3DEditor — the interactive 3D director surface.
 *
 * Two interaction paths, one state:
 * - the tray adds low-poly assets (generated enums; unknown kinds fail loud);
 * - the viewport selects/drags/places, and the inspector writes through the
 *   pure edit model (sceneScriptEditModel). Playback and editing are two modes of
 *   the same script.
 *
 * The live consistency mirror of the backend gate (scene_consistency.py)
 * shows identity risks while the author builds, not after hitting render.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import type {
  SceneEnvironment,
  SceneProp,
  SceneScriptRoot,
} from "../../../types/scene-script";
import { describeObjectPointer, objectPointerToken } from "./objectPointer.ts";

// §8.2: re-exported so a consumer of the editor can name the pointer without
// reaching into a second module (the definitions live in objectPointer.ts).
export { describeObjectPointer, objectPointerToken };
import type { SceneVec3 } from "./sceneScriptAxes";
import {
  ENVIRONMENT_TYPES,
  PROP_TYPES,
  type EnvironmentTypeName,
  type PropTypeName,
} from "../../../types/scene-script.generated";
import { SceneAssetTray } from "./SceneAssetTray.tsx";
import {
  SceneScriptPlaybackProvider,
  useSceneScriptPlayback,
} from "./SceneScriptPlaybackContext";
import { SceneScript3DPreview, type SpeechOverlayLine } from "./SceneScript3DPreview";
import { LayerOwnershipNote } from "./LayerOwnershipNote.tsx";
import { DirectorCommandBar } from "./DirectorCommandBar.tsx";
import { StoryboardPanel } from "./StoryboardPanel.tsx";

import { nextTakeLabel } from "./directorTakes.ts";
import { INSERT_SHOT_MIN_SECONDS, ShotStrip } from "./ShotStrip.tsx";
import { TransitionProposalsPanel, type TransitionSpeechSegment } from "./TransitionProposalsPanel.tsx";
import type { TransitionVariant } from "./transitionVariants.ts";
import { checkSceneScriptConsistency } from "./sceneScriptConsistency.ts";
import {
  GESTURE_SAMPLE_STEP_FRAMES,
  keyframesFromGesturePath,
} from "./cameraGesturePath.ts";
import { replaceCameraKeyframesInWindow } from "./cameraMotionPresets.ts";

import { checkBlockingContinuity } from "./blockingContinuity.ts";
import {
  addCameraAtFrame,
  addEnvironmentObject,
  addPropObject,
  captureCameraKeyframe,
  captureCharacterKeyframe,
  characterPositionAtFrame,
  characterStateAtFrame,
  interpolateCameraState,
  moveCameraAtFrame,
  moveSceneObjectAtFrame,
  rotateCharacterAtFrame,
  rotateStaticObject,
  scaleStaticObject,
  sceneObjectPositionAtFrame,
  setCameraLookAtAtFrame,
  setCameraShotType,
  setCharacterPalette,
  insertShotAtBoundary,
  bindEnvironmentAsset,
  bindPropAsset,
  setPropHeld,
  setShotTransitionIntent,
  MAX_APPEARANCE_PALETTE_COLORS,
  type SceneObjectRef,
} from "./sceneScriptEditModel";
import {
  CAMERA_MOTION_PRESETS,
  applyCameraMotionPreset,
  type CameraMotionPresetId,
} from "./cameraMotionPresets.ts";
import {
  APPROACH_DEFAULT_STOP_DISTANCE,
  CHARACTER_MOTION_PRESETS,
  applyCharacterMotionPreset,
  countSpeakingFramesInWindow,
  type CharacterMotionPresetId,
} from "./characterMotionPresets.ts";

/** Human-readable names for the low-poly asset kinds (tray + tooltips). */
const KIND_LABELS: Record<string, string> = {
  wall: "墙",
  pillar: "柱",
  floor: "地面",
  gable_roof: "坡顶",
  flat_roof: "平顶",
  door: "门",
  window: "窗",
  stairs: "楼梯",
  platform: "平台",
  tree: "树",
  rock: "岩石",
  fence: "栅栏",
  ground: "地表",
  round_table: "圆桌",
  rect_table: "方桌",
  chair: "椅子",
  stool: "凳子",
  lantern: "灯笼",
  box: "箱子",
  crate: "板条箱",
  vase: "花瓶",
  weapon: "武器",
  scroll: "卷轴",
  book: "书",
  cup: "杯",
};

const OBJECT_KIND_LABELS: Record<SceneObjectRef["kind"], string> = {
  character: "角色",
  prop: "道具",
  environment: "环境",
  camera: "相机",
};

const SHOT_TYPES = ["wide", "medium", "closeup", "over_shoulder", "pov", "top_down"];

/** One cross-node drift finding, as the executor publishes it. */
export interface DriftFinding {
  code: string;
  subject: string;
  message: string;
  remedy: string;
}

/** One continuity finding on a shot boundary (V0.2 §5 运动方向). */
export interface BlockingFinding {
  code: string;
  severity: string;
  subject: string;
  /** The boundary it was found on, as ``"{a}→{b}"``. */
  boundary: string;
  message: string;
  remedy: string;
}

/**
 * One finding of the Dramagic pre-render consistency report (V0.2's core
 * concern). The messages arrive in English from the backend gate; the editor
 * stays one language, so each code carries a Chinese label and the backend
 * prose rides along as the detail.
 */
export interface ConsistencyFinding {
  code: string;
  /** "error" or "warning". */
  severity: string;
  subject: string;
  message: string;
  remedy: string;
}

/** Chinese labels for the consistency codes, so the editor reads as one language. */
const CONSISTENCY_LABELS: Record<string, string> = {
  character_unbound: "角色未绑定资产",
  character_color_collision: "两个角色同色",
  camera_unused: "有摄影机没被用",
  shot_coverage_gap: "镜头覆盖有空缺",
  scene_empty: "场景是空的",
};

function consistencyLabel(code: string): string {
  return CONSISTENCY_LABELS[code] ?? code;
}

/**
 * How the last run drove the mouths (ADR 0003): the alignment decides whether
 * the lip-sync is trustworthy, and "estimated" is the case that must be said
 * out loud — an estimate is a guess wearing a measurement's clothes.
 */
export interface AutoLipSyncFacts {
  applied: boolean;
  /** "measured" | "mixed" | "estimated" | "none". */
  duration_source: string;
  segment_count: number;
  warnings: string[];
}

/**
 * One reference asset the executor delivered to this node (V0.2 §2.1/
 * "资产驱动场景"): what arrived, in which role, and whether the applier could
 * attribute it to a SceneScript element without guessing.
 */
export interface ReferenceBinding {
  asset_id: string;
  semantic_role: string;
  /** The SceneScript field the asset was stamped onto, or null when ambiguous. */
  recorded_on: string | null;
  media_type: string;
}

const REFERENCE_ROLE_LABELS: Record<string, string> = {
  scene: "场景设计",
  scene_board: "场景设计板",
  scene_reference: "场景参考",
  environment_reference: "环境参考",
  character: "角色设计",
  character_reference: "角色参考",
  subject_reference: "主体参考",
  product: "产品设计",
  product_reference: "产品参考",
  prop: "道具设计",
  prop_reference: "道具参考",
};

const RECORDED_ON_LABELS: Record<string, string> = {
  scene_asset_id: "环境资产绑定",
  character_asset_id: "角色资产绑定",
  prop_asset_id: "道具资产绑定",
};

/** What a reference role is called in the author's language. */
function referenceRoleLabel(role: string): string {
  return REFERENCE_ROLE_LABELS[role] ?? role;
}

const DURATION_SOURCE_LABELS: Record<string, string> = {
  measured: "实测",
  mixed: "部分实测",
  estimated: "估算",
  none: "无",
};

/** One reconciliation note between a declared reading and those findings. */
export interface TransitionIntentNote {
  code: string;
  /** "info" (the reading explains the finding) or "warning" (it contradicts). */
  severity: string;
  shot_id: string;
  reading_id: string | null;
  message: string;
  remedy: string;
}

/**
 * Why the last render came out silent (V0.2 §14.9 成片侧). The executor
 * publishes these reasons on the node; the workbench translates them so an
 * author never has to guess why the previs has no sound.
 */
const ANIMATIC_SKIP_LABELS: Record<string, string> = {
  no_speech_binding: "🔇 场景没有绑定台词：渲染为无声预演",
  keyframes_only_render: "🔇 本次渲染只出了关键帧（省时模式）：未混入床音",
  speech_asset_unresolved: "🔇 绑定的音频床资产未解析：渲染为无声预演",
};

/** A reason prefix (e.g. ``mux_failed: ...``) renders through this fallback. */
function animaticSkipLabel(reason: string | null | undefined): string {
  if (!reason) return "🔇 最近一次渲染没有床音";
  if (reason.startsWith("mux_failed")) return "🔇 床音混入失败：渲染为无声预演";
  return ANIMATIC_SKIP_LABELS[reason] ?? "🔇 最近一次渲染没有床音";
}

export interface SceneScript3DEditorProps {
  sceneScript: SceneScriptRoot;
  onChange: (next: SceneScriptRoot) => void;
  onSave: () => void;
  onRevert: () => void;
  saving?: boolean;
  dirty?: boolean;
  error?: string | null;
  /** Character assets offered for identity binding (the Dramagic lock). */
  characterAssets?: CharacterAssetOption[];
  propAssets?: CharacterAssetOption[];
  sceneAssets?: CharacterAssetOption[];
  /**
   * What the viewport currently points at (§8.2). Hoisted so the natural
   * language layer can name "这个" instead of guessing which object the
   * author means — the pointer and the language must meet somewhere.
   */
  onSelectionChange?: (ref: SceneObjectRef | null) => void;
  /**
   * The automatic lip-sync pass the last run applied, as the executor
   * published it (``structured_content.auto_lip_sync``).
   */
  autoLipSync?: AutoLipSyncFacts | null;
  /**
   * The reference assets delivered to this node (V0.2 §2.1 资产驱动场景),
   * as the executor published them in ``scene3d_reference_bindings``.
   */
  referenceBindings?: readonly ReferenceBinding[] | null;
  /** Viewport height in px (the full-screen workbench asks for more). */
  previewHeight?: number;
  /**
   * Dialogue lines for the in-viewport speech overlay. The lines ride on the
   * node (persisted by the lip-sync panel), so the 3D viewport shows "who
   * says what, when" without the author leaving the director surface.
   */
  dialogueLines?: readonly SpeechOverlayLine[];
  /** Animatic audio: the workflow's speech track, played with the playhead. */
  speechAudioUrl?: string | null;
  /**
   * Whether the node's last RENDER carries the dialogue bed (V0.2 §14.9
   * 成片侧), and why not when it doesn't — published by the executor as
   * ``structured_content.animatic_audio`` so the reviewer can ask.
   */
  animaticAudio?: { muxed: boolean; reason?: string | null } | null;
  /**
   * Cross-node character drift (V0.2 §5 服装维度): findings the node executor
   * published as ``structured_content.scene3d_wardrobe_drift`` — the identity
   * binding checked against the workflow's OTHER scene-3d nodes.
   */
  wardrobeDrift?: { checked: boolean; reason?: string | null; findings: DriftFinding[] } | null;
  /**
   * Continuity findings on the shot boundaries (V0.2 §5 运动方向), published
   * as ``structured_content.scene3d_blocking_continuity``.
   */
  blockingContinuity?: readonly BlockingFinding[] | null;
  /**
   * The declared reading reconciled with those findings (V0.2 §13 第 4 问),
   * published as ``structured_content.scene3d_transition_intent``.
   */
  transitionIntentNotes?: readonly TransitionIntentNote[] | null;
  /**
   * The Dramagic pre-render consistency report (V0.2's core concern:
   * 场景一致性), published as ``structured_content.scene3d_consistency``.
   */
  consistency?: { passed: boolean; issues: ConsistencyFinding[] } | null;
  /**
   * Speech segments measured by the applied lip-sync run. The Transition
   * Intent picker prices its speech-aware readings against them: "说多久 →
   * 切多长" must read the same timeline the mouths rode on.
   */
  speechSegments?: readonly TransitionSpeechSegment[];
  /**
   * Saved transition variants (V0.2 §9 局部分叉): readings the author kept
   * for comparison, persisted on the node by the workbench.
   */
  variants?: readonly TransitionVariant[];
  onVariantsChange?: (variants: TransitionVariant[]) => void;
  /**
   * Director takes (V3): labelled snapshots for A/B comparison. The
   * workbench persists them on the node; the editor shows a save-take
   * button and a take picker.
   */
  takes?: readonly import("./directorTakes.ts").DirectorTake[];
  onSaveTake?: (take: import("./directorTakes.ts").DirectorTake) => void;
  /**
   * Advisory jump target (V0.2 §15): a shot id an advisory pointed at. The
   * playhead moves into that shot (so the picker's pair forms) and the
   * readings fetch once; the parent clears the signal via
   * `onFocusShotConsumed`.
   */
  /**
   * The workflow and node ids that back this node in the agent-canvas DB.
   * Forwarded to TransitionProposalsPanel so retained_reading_ids can be
   * persisted on the node across sessions.
   */
  workflowId?: string | null;
  nodeId?: string | null;
  /**
   * Reading ids already persisted on the node
   * (structured_content.retained_reading_ids). Forwarded to
   * TransitionProposalsPanel as initialEngagedIds so a refresh restores
   * multi-round memory.
   */
  initialEngagedIds?: readonly string[];
  focusShotId?: string | null;
  onFocusShotConsumed?: () => void;
}

export function SceneScript3DEditor({
  sceneScript,
  onChange,
  onSave,
  onRevert,
  saving = false,
  dirty = false,
  error = null,
  characterAssets = [],
  propAssets = [],
  sceneAssets = [],
  onSelectionChange,
  autoLipSync = null,
  referenceBindings = null,
  previewHeight = 360,
  dialogueLines = [],
  speechAudioUrl = null,
  animaticAudio = null,
  wardrobeDrift = null,
  blockingContinuity = null,
  transitionIntentNotes = null,
  consistency = null,
  speechSegments = [],
  variants = [],
  onVariantsChange,
  workflowId = null,
  nodeId = null,
  initialEngagedIds = [],
  takes = [],
  onSaveTake,
  focusShotId = null,
  onFocusShotConsumed,
}: SceneScript3DEditorProps) {
  return (
    <SceneScriptPlaybackProvider sceneScript={sceneScript}>
      <SceneScript3DEditorContent
        sceneScript={sceneScript}
        onChange={onChange}
        onSave={onSave}
        onRevert={onRevert}
        saving={saving}
        dirty={dirty}
        error={error}
        characterAssets={characterAssets}
        propAssets={propAssets}
        sceneAssets={sceneAssets}
        onSelectionChange={onSelectionChange}
        autoLipSync={autoLipSync}
        referenceBindings={referenceBindings}
        previewHeight={previewHeight}
        dialogueLines={dialogueLines}
        speechAudioUrl={speechAudioUrl}
        animaticAudio={animaticAudio}
        wardrobeDrift={wardrobeDrift}
        blockingContinuity={blockingContinuity}
        transitionIntentNotes={transitionIntentNotes}
        consistency={consistency}
        speechSegments={speechSegments}
        variants={variants}
        onVariantsChange={onVariantsChange}
        takes={takes}
        onSaveTake={onSaveTake}
        workflowId={workflowId}
        nodeId={nodeId}
        initialEngagedIds={initialEngagedIds}
        focusShotId={focusShotId}
        onFocusShotConsumed={onFocusShotConsumed}
      />
    </SceneScriptPlaybackProvider>
  );
}

function SceneScript3DEditorContent({
  sceneScript,
  onChange,
  onSave,
  onRevert,
  saving,
  dirty,
  error,
  characterAssets = [],
  propAssets = [],
  sceneAssets = [],
  onSelectionChange,
  autoLipSync = null,
  referenceBindings = null,
  previewHeight = 360,
  dialogueLines = [],
  speechAudioUrl = null,
  animaticAudio = null,
  wardrobeDrift = null,
  blockingContinuity = null,
  transitionIntentNotes = null,
  consistency = null,
  speechSegments = [],
  variants = [],
  onVariantsChange,
  workflowId = null,
  nodeId = null,
  initialEngagedIds = [],
  takes = [],
  onSaveTake,
  focusShotId = null,
  onFocusShotConsumed,
}: SceneScript3DEditorProps) {
  const [selectedObject, setSelectedObject] = useState<SceneObjectRef | null>(null);
  const [placementMode, setPlacementMode] = useState(false);
  const [gestureMode, setGestureMode] = useState(false);
  const [gestureError, setGestureError] = useState<string | null>(null);
  const [gestureSeconds, setGestureSeconds] = useState("2");
  const playback = useSceneScriptPlayback();

  // Live consistency mirror of the backend gate (scene_consistency.py) plus
  // the cross-shot blocking continuity (blocking_continuity.py, the V0.2
  // Continuity State core). Advisories only: the author sees identity and
  // continuity risks while building, not after hitting render.
  const issues = useMemo(
    () => [
      ...checkSceneScriptConsistency(sceneScript),
      ...checkBlockingContinuity(sceneScript),
    ],
    [sceneScript],
  );
  const frameRef = useRef(playback.currentFrame);
  frameRef.current = playback.currentFrame;

  const handleDragCommit = useCallback(
    (ref: SceneObjectRef, position: SceneVec3) => {
      onChange(moveSceneObjectAtFrame(sceneScript, ref, frameRef.current, position));
    },
    [onChange, sceneScript],
  );

  const handlePlacementCommit = useCallback(
    (placement: { position: SceneVec3; lookAt: SceneVec3 }) => {
      const frame = frameRef.current;
      const selectedCamera = selectedObject?.kind === "camera" ? selectedObject.id : null;
      if (selectedCamera) {
        const camera = sceneScript.cameras.find((candidate) => candidate.id === selectedCamera);
        const groundPosition = sceneObjectPositionAtFrame(
          sceneScript,
          { kind: "camera", id: selectedCamera },
          frame,
        ) ?? [0, 0, 1.6];
        const existingLookAt = camera
          ? interpolateCameraState(camera, frame)?.lookAt ?? [0, 0, 1.2]
          : [0, 0, 1.2];
        let next = moveCameraAtFrame(sceneScript, selectedCamera, frame, [
          placement.position[0],
          placement.position[1],
          groundPosition[2],
        ]);
        next = setCameraLookAtAtFrame(next, selectedCamera, frame, [
          placement.lookAt[0],
          placement.lookAt[1],
          existingLookAt[2],
        ]);
        onChange(next);
      } else {
        const next = addCameraAtFrame(sceneScript, {
          position: [placement.position[0], placement.position[1], 1.6],
          lookAt: [placement.lookAt[0], placement.lookAt[1], 1.2],
          shotType: "wide",
          description: "placed camera",
        });
        onChange(next);
        const created = next.cameras[next.cameras.length - 1];
        if (created) setSelectedObject({ kind: "camera", id: created.id });
      }
      setPlacementMode(false);
    },
    [onChange, sceneScript, selectedObject],
  );

  // The shot the playhead sits inside: the outgoing shot of a transition.
  // The playhead is a real dependency: scrubbing changes which shot the
  // picker's pair starts from, so the memo must recompute on frame change
  // (it used to read a ref with shot-only deps and went stale on scrub).
  const currentShotId = useMemo(() => {
    const frame = playback.currentFrame;
    const atFrame = sceneScript.shots.find(
      (shot) => frame >= shot.start_frame && frame <= shot.end_frame,
    );
    return atFrame?.id ?? sceneScript.shots[0]?.id ?? null;
  }, [sceneScript.shots, playback.currentFrame]);

  /**
   * Advisory jump: when the lip-sync panel points at a boundary shot, move
   * the playhead inside it (never onto its first frame — the shot test is
   * inclusive, so the pair forms) and tell the parent the signal is spent.
   * The picker then auto-fetches the readings for THAT pair (V0.2 §15).
   *
   * The spent-signal guard matters: the playback value re-identifies on
   * every frame, and a re-run would yank the playhead back mid-playback.
   */
  const focusedShotRef = useRef<string | null>(null);
  useEffect(() => {
    if (!focusShotId) {
      focusedShotRef.current = null;
      return;
    }
    if (focusedShotRef.current === focusShotId) return;
    focusedShotRef.current = focusShotId;
    const shot = sceneScript.shots.find((candidate) => candidate.id === focusShotId);
    if (shot) {
      const fps = sceneScript.scene.frame_rate > 0 ? sceneScript.scene.frame_rate : 30;
      const targetFrame = Math.min(
        shot.start_frame + Math.max(1, Math.round(fps / 2)),
        shot.end_frame,
      );
      playback.seekToFrame(targetFrame);
    }
    onFocusShotConsumed?.();
  }, [focusShotId, sceneScript.shots, sceneScript.scene.frame_rate, playback, onFocusShotConsumed]);

  /**
   * Draw-a-path camera motion: the drawn polyline becomes sampled camera
   * keyframes (constant speed along the author's line, gaze ahead, authored
   * eye height preserved). Only works with a camera selected — the gesture
   * authors THAT camera's move.
   */
  const handleGestureCommit = useCallback(
    (points: SceneVec3[]) => {
      const cameraId = selectedObject?.kind === "camera" ? selectedObject.id : null;
      if (!cameraId) {
        setGestureError("先选择一个相机，再用它画出运镜轨迹。");
        return;
      }
      const camera = sceneScript.cameras.find((candidate) => candidate.id === cameraId);
      const frame = frameRef.current;
      const anchorHeight = camera?.keyframes.find((keyframe) => keyframe.frame === frame)?.position[2]
        ?? camera?.keyframes[0]?.position[2]
        ?? 1.6;
      const durationFrames = Math.max(
        1,
        Math.round((Number(gestureSeconds) || 1) * sceneScript.scene.frame_rate),
      );
      const result = keyframesFromGesturePath(points, {
        startFrame: frame,
        durationFrames,
        anchorHeight,
        frameRate: sceneScript.scene.frame_rate,
      });
      if (result.keyframes.length === 0) {
        setGestureError("这条轨迹没有位移（单击不是运镜）。");
        return;
      }
      setGestureError(null);
      onChange(
        replaceCameraKeyframesInWindow(sceneScript, cameraId, result.keyframes, {
          startFrame: frame,
          durationFrames,
        }),
      );
      setGestureMode(false);
    },
    [onChange, sceneScript, selectedObject, gestureSeconds],
  );

  const captureKeyframe = useCallback(() => {
    const frame = frameRef.current;
    if (!selectedObject) return;
    if (selectedObject.kind === "character") {
      onChange(captureCharacterKeyframe(sceneScript, selectedObject.id, frame));
    } else if (selectedObject.kind === "camera") {
      onChange(captureCameraKeyframe(sceneScript, selectedObject.id, frame));
    }
  }, [onChange, sceneScript, selectedObject]);

  const addEnvironment = useCallback(
    (kind: EnvironmentTypeName) => {
      onChange(addEnvironmentObject(sceneScript, kind));
    },
    [onChange, sceneScript],
  );

  const addProp = useCallback(
    (kind: PropTypeName) => {
      onChange(addPropObject(sceneScript, kind));
    },
    [onChange, sceneScript],
  );

  return (
    <div className="scene-script-3d-editor scene-script-3d-editor--with-tray">
      <header className="scene-script-3d-editor__draft-header">
        <div>
          <strong>3D 场景草稿</strong>
          <span role="status" aria-live="polite" className={`scene-script-3d-editor__dirty${dirty ? " is-dirty" : ""}`}>
            {saving ? "保存中…" : dirty ? "有未保存修改" : "已保存"}
          </span>
          <p>编辑先在草稿中预览；保存场景才会更新节点。预览渲染使用当前草稿，不会代替保存。</p>
        </div>
        <div className="scene-script-3d-editor__draft-actions">
          <button type="button" onClick={onRevert} disabled={!dirty || saving} title="丢弃全部未保存修改，恢复节点中已保存的场景">
            撤销修改
          </button>
          <button type="button" className="scene-script-3d-editor__save" onClick={onSave} disabled={!dirty || saving}>
            {saving ? "正在保存场景…" : "保存场景"}
          </button>
        </div>
        {error && <p role="alert" className="scene-script-3d-editor__error">{error}</p>}
      </header>
      <details className="scene-script-3d-editor__quick-guide">
        <summary>操作指南 · 选择、移动与镜头</summary>
        <ol>
          <li>点击人物、道具或相机选中对象，在右侧检查器调整参数；地面拖动改变位置。</li>
          <li>先暂停并定位时间轴，再捕获关键帧。导演口令与微调作用于当前草稿。</li>
          <li>放置相机：点击地面设机位，再点击设注视点；Esc 取消。画运镜前先选中相机。</li>
          <li>满意后保存场景；预览渲染需要本机 Blender，声音开关只影响视口试听。</li>
        </ol>
      </details>
      <SceneAssetTray onAddEnvironment={addEnvironment} onAddProp={addProp} disabled={saving} />
      {issues.length > 0 && (
        <ul className="scene-script-3d-editor__consistency" aria-label="场景一致性提示">
          {issues.map((issue, index) => (
            <li key={`${issue.code}-${index}`} data-issue-code={issue.code}>
              <button
                type="button"
                title={`${issue.remedy}（点击选中：${issue.subject}）`}
                onClick={() => {
                  const subject = issue.subject.split(",")[0].trim();
                  if (
                    // Identity checks AND cross-shot blocking continuity both
                    // point at a character: selecting it opens the inspector
                    // where the motion presets live (the usual remedy).
                    (issue.code.startsWith("character_")
                      || issue.code === "facing_flip"
                      || issue.code === "position_jump")
                    && sceneScript.characters.some((character) => character.id === subject)
                  ) {
                    setSelectedObject({ kind: "character", id: subject });
                  } else if (
                    issue.code === "camera_unused"
                    && sceneScript.cameras.some((camera) => camera.id === subject)
                  ) {
                    setSelectedObject({ kind: "camera", id: subject });
                  } else if (
                    // Held-item checks (V0.2 §5) point at props: selecting one
                    // opens the inspector where its holder can be changed.
                    issue.code.startsWith("held_item_")
                    && sceneScript.props.some((prop) => prop.id === subject)
                  ) {
                    setSelectedObject({ kind: "prop", id: subject });
                  }
                }}
              >
                {issue.message}
              </button>
            </li>
          ))}
        </ul>
      )}
      <div className="scene-script-3d-editor__toolbar">
        <button
          type="button"
          className={placementMode ? "is-active" : undefined}
          onClick={() => {
            setPlacementMode((current) => !current);
            setGestureMode(false);
            setGestureError(null);
          }}
          aria-pressed={placementMode}
          title="第一次点击设机位，第二次点击设注视点，Esc 取消"
        >
          {placementMode ? "取消放置" : "放置相机"}
        </button>
        <button
          type="button"
          onClick={captureKeyframe}
          disabled={
            !selectedObject
            || (selectedObject.kind !== "character" && selectedObject.kind !== "camera")
          }
          title="把当前帧的插值状态固化为关键帧"
        >
          捕获关键帧
        </button>
        {placementMode && (
          <span className="scene-script-3d-editor__placement-hint">
            {selectedObject?.kind === "camera"
              ? "重新放置所选相机的机位与注视点"
              : "点击两次放置一个新相机（将自动新建镜头）"}
          </span>
        )}
        <button
          type="button"
          className={gestureMode ? "is-active" : undefined}
          onClick={() => {
            setGestureMode((current) => !current);
            setPlacementMode(false);
            setGestureError(null);
          }}
          aria-pressed={gestureMode}
          title="在地面拖出一条轨迹，系统按常速采样成相机关键帧（V0.2 §8.3）"
        >
          {gestureMode ? "取消画运镜" : "画运镜"}
        </button>
        {gestureMode && (
          <>
            <input
              type="number"
              min={0.5}
              step={0.5}
              value={gestureSeconds}
              aria-label="画运镜时长 (s)"
              title="轨迹走完用的秒数（常速）"
              onChange={(event) => setGestureSeconds(event.target.value)}
            />
            <span className="scene-script-3d-editor__placement-hint">
              按住地面拖动画出轨迹；需选中一个相机
            </span>
          </>
        )}
        {gestureError && <span className="scene-script-3d-editor__error">{gestureError}</span>}
      </div>
      {animaticAudio && (
        <p
          className="scene-script-3d-editor__animatic"
          data-testid="scene-script-3d-animatic"
          data-muxed={animaticAudio.muxed ? "true" : "false"}
        >
          {animaticAudio.muxed
            ? "🔊 最近一次渲染已带上台词床音（animatic：480P 画面 + 真实语音）"
            : animaticSkipLabel(animaticAudio.reason)}
        </p>
      )}
      {/* 导演口令条（V0.3 导演台 MVP）：一条确定性的指令直接调度选中对象，
          预览即时变化；自由语音层随后映射到同一个 DirectorMotionCommand。 */}
      <DirectorCommandBar
        sceneScript={sceneScript}
        onApply={onChange}
        selectedObject={selectedObject}
        playheadFrame={playback.currentFrame}
        onNudge={(next) => onChange(next)}
        disabled={saving}
      />
      <StoryboardPanel
        sceneScript={sceneScript}
        refreshKey={sceneScript.shots.length}
        onSeekFrame={(frame) => playback.seekToFrame(frame)}
        disabled={saving}
      />
      {autoLipSync?.applied && (
        <p
          className={`scene-script-3d-editor__drift${
            autoLipSync.duration_source === "estimated" ? " is-error" : ""
          }`}
          data-testid="scene-script-3d-auto-lip-sync"
        >
          {autoLipSync.duration_source === "estimated" ? "⚠ " : "✓ "}
          已按 {autoLipSync.segment_count} 句台词写入唇形（时长来源：
          {DURATION_SOURCE_LABELS[autoLipSync.duration_source] ?? autoLipSync.duration_source}）
          {autoLipSync.duration_source === "estimated" &&
            "：估算来自文本长度而不是真实对齐——嘴动得对不上，重跑一次对齐更稳"}
          {autoLipSync.warnings.map((warning) => (
            <span
              key={warning}
              className="scene-script-3d-editor__drift-remedy"
            >
              {warning}
            </span>
          ))}
        </p>
      )}
      <LayerOwnershipNote />
      {/* §13 第 4 问: the reading the author declared, checked against what
          the keyframes actually do. Publishing it on the node is not enough
          — the point is to reach the person who declared it. */}
      {(transitionIntentNotes ?? []).map((note, index) => (
        <p
          key={`intent-${note.shot_id}-${index}`}
          className={`scene-script-3d-editor__intent${
            note.severity === "warning" ? " is-stale" : ""
          }`}
          data-testid={`scene-script-3d-intent-${index}`}
        >
          {note.message}
          <span className="scene-script-3d-editor__drift-remedy">{note.remedy}</span>
        </p>
      ))}
      {(blockingContinuity ?? []).map((finding, index) => (
        <p
          key={`blocking-${finding.boundary}-${index}`}
          className="scene-script-3d-editor__drift"
          data-testid={`scene-script-3d-blocking-${index}`}
        >
          {finding.message}
          <span className="scene-script-3d-editor__drift-remedy">{finding.remedy}</span>
        </p>
      ))}
      {/* 资产驱动场景: what this previs node was FED. A bound upstream
          scene-design or character node has no other trace in the previs (the
          renderer has no input slot for a reference image), so an author who
          bound one could not see that it arrived — or that it was attributed
          to an element. Showing the delivery makes the edge claimable. */}
      {(referenceBindings ?? []).map((binding, index) => (
        <p
          key={`reference-${binding.asset_id}-${index}`}
          className="scene-script-3d-editor__drift"
          data-testid={`scene-script-3d-reference-${index}`}
          data-asset={binding.asset_id}
          data-role={binding.semantic_role}
          data-recorded-on={binding.recorded_on ?? ""}
        >
          ⇢ 参考输入：{referenceRoleLabel(binding.semantic_role)}（{binding.asset_id}
          {binding.media_type ? ` · ${binding.media_type}` : ""}）
          {binding.recorded_on
            ? `→ 已标注到${RECORDED_ON_LABELS[binding.recorded_on] ?? binding.recorded_on}`
            : "→ 未标注到具体元素（同类元素有多个，交由作者决定）"}
        </p>
      ))}
      {wardrobeDrift?.checked &&
        wardrobeDrift.findings.map((finding, index) => (
          <p
            key={`${finding.code}-${index}`}
            className="scene-script-3d-editor__drift"
            data-testid={`scene-script-3d-drift-${index}`}
          >
            {finding.message}
            <span className="scene-script-3d-editor__drift-remedy">{finding.remedy}</span>
          </p>
        ))}
      {/* 场景一致性（V0.2 §12 的核心问题）: the pre-render gate's report.
          Errors first — an unbound character or a dead camera is the failure
          the Dramagic lock exists to catch, and it must not sit below the
          cosmetic warnings in the author's reading order. */}
      {(consistency?.issues ?? [])
        .slice()
        .sort((left, right) =>
          left.severity === right.severity
            ? 0
            : left.severity === "error"
              ? -1
              : 1,
        )
        .map((finding, index) => (
          <p
            key={`consistency-${finding.code}-${index}`}
            className={`scene-script-3d-editor__drift${
              finding.severity === "error" ? " is-error" : ""
            }`}
            data-testid={`scene-script-3d-consistency-${index}`}
          >
            {finding.severity === "error" ? "⛔ " : "⚠ "}
            {consistencyLabel(finding.code)}
            {finding.subject ? `：${finding.subject}` : ""}
            <span className="scene-script-3d-editor__drift-remedy">{finding.remedy}</span>
          </p>
        ))}
      <div className="scene-script-3d-editor__stage">
        <SceneScript3DPreview
          sceneScript={sceneScript}
          height={previewHeight}
          dialogueLines={dialogueLines}
          speechAudioUrl={speechAudioUrl}
          editMode
          selectedObject={selectedObject}
          onSelect={(ref) => {
            setSelectedObject(ref);
            // The pointer is the language layer's only clue about which object
            // "这个" means (§8.2), so it goes up rather than staying in here.
            onSelectionChange?.(ref);
          }}
          onDragCommit={handleDragCommit}
          placementMode={placementMode}
          onPlacementCommit={handlePlacementCommit}
          onPlacementCancel={() => setPlacementMode(false)}
          gestureMode={gestureMode}
          onGestureCommit={handleGestureCommit}
          onGestureCancel={() => {
            setGestureMode(false);
            setGestureError(null);
          }}
        />
      </div>
      {/* V0.2 §12: a declared reading must be revocable. Without this the
          relation is write-once, and "这个切不需要读法" would have no
          expression anywhere in the UI. */}
      {/* Director takes（V3）：把当前场景存成一条可对比/可回滚的快照。 */}
      {onSaveTake && (
        <div className="scene-script-3d-editor__takes">
          <button
            type="button"
            className="scene-script-3d-editor__take-save"
            data-testid="scene-script-3d-take-save"
            onClick={() =>
              onSaveTake({
                id: `take_${Date.now()}`,
                label: nextTakeLabel(takes),
                scene_script: JSON.parse(JSON.stringify(sceneScript)) as Record<string, unknown>,
                operations: [],
                frame: playback.currentFrame,
              })
          }
          >
            存 take
          </button>
          {takes.map((take) => (
            <span
              key={take.id}
              className="scene-script-3d-editor__take"
              data-testid={`scene-script-3d-take-${take.id}`}
            >
              {take.label}
              {take.operations.length > 0 && (
                <em className="scene-script-3d-editor__take-ops">{take.operations.length} ops</em>
              )}
              <button
                type="button"
                data-testid={`scene-script-3d-take-restore-${take.id}`}
                onClick={() => onChange(take.scene_script as unknown as SceneScriptRoot)}
                title="恢复这个版本"
              >
                恢复
              </button>
            </span>
          ))}
        </div>
      )}
            <ShotStrip
        shots={sceneScript.shots}
        totalFrames={sceneScript.scene.duration * sceneScript.scene.frame_rate}
        currentFrame={playback.currentFrame}
        onSeekFrame={(frame) => playback.seekToFrame(frame)}
        onInsertAfter={(shotId) =>
          onChange(
            insertShotAtBoundary(
              sceneScript,
              shotId,
              Math.max(1, Math.round(INSERT_SHOT_MIN_SECONDS * sceneScript.scene.frame_rate)),
            ),
          )
        }
        onClearIntent={(shotId) =>
          onChange(setShotTransitionIntent(sceneScript, shotId, null))
        }
      />
      <aside className="scene-script-3d-editor__inspector">
        <SceneScriptEditPanel
          sceneScript={sceneScript}
          selectedObject={selectedObject}
          onChange={onChange}
          characterAssets={characterAssets}
          propAssets={propAssets}
          sceneAssets={sceneAssets}
          previewHeight={previewHeight}
        />
        <TransitionProposalsPanel
          sceneScript={sceneScript}
          currentShotId={currentShotId}
          onChange={onChange}
          disabled={saving}
          speechSegments={speechSegments}
          variants={variants}
          onVariantsChange={onVariantsChange}
          workflowId={workflowId}
          nodeId={nodeId}
          initialEngagedIds={initialEngagedIds}
          autoFetchShotId={focusShotId}
        />

      </aside>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Selected-object inspector
// ---------------------------------------------------------------------------

function SceneScriptEditPanel({
  sceneScript,
  selectedObject,
  onChange,
  characterAssets,
  propAssets,
  sceneAssets,
  previewHeight,
}: {
  sceneScript: SceneScriptRoot;
  selectedObject: SceneObjectRef | null;
  onChange: (next: SceneScriptRoot) => void;
  characterAssets: CharacterAssetOption[];
  propAssets?: CharacterAssetOption[];
  sceneAssets?: CharacterAssetOption[];
  previewHeight: number;
}) {
  const { currentFrame } = useSceneScriptPlayback();

  if (!selectedObject) {
    return (
      <div className="scene-script-3d-editor__empty">
        <p>在 3D 视口中点击角色、道具或相机进行编辑。</p>
        <p className="scene-script-3d-editor__hint">
          拖拽移动位置（保持高度）；保存后写回画布节点。
        </p>
      </div>
    );
  }

  const { kind, id } = selectedObject;
  const scenePosition = sceneObjectPositionAtFrame(sceneScript, selectedObject, currentFrame);

  return (
    <div className="scene-script-3d-editor__panel">
      <header className="scene-script-3d-editor__panel-header">
        <span className="scene-script-3d-editor__kind">{OBJECT_KIND_LABELS[kind]}</span>
        <strong title={id}>{id}</strong>
        {kind === "character" && (
          <span className="scene-script-3d-editor__frame">帧 {currentFrame}</span>
        )}
      </header>

      {kind === "character" && scenePosition && (
        <CharacterFields
          sceneScript={sceneScript}
          characterId={id}
          frame={currentFrame}
          position={scenePosition}
          rotationY={characterStateAtFrame(
            sceneScript.characters.find((character) => character.id === id)!,
            currentFrame,
          ).rotationY}
          onChange={onChange}
          characterAssets={characterAssets}
        />
      )}

      {(kind === "prop" || kind === "environment") && scenePosition && (
        <StaticFields
          sceneScript={sceneScript}
          kind={kind}
          id={id}
          onChange={onChange}
          assetOptions={kind === "prop" ? propAssets : sceneAssets}
        />
      )}

      {kind === "camera" && (
        <CameraFields sceneScript={sceneScript} cameraId={id} frame={currentFrame} onChange={onChange} />
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Character fields (identity binding is the Dramagic lock)
// ---------------------------------------------------------------------------

function CharacterFields({
  sceneScript,
  characterId,
  frame,
  position,
  rotationY,
  onChange,
  characterAssets,
  propAssets,
  sceneAssets,
}: {
  sceneScript: SceneScriptRoot;
  characterId: string;
  frame: number;
  position: SceneVec3;
  rotationY: number;
  onChange: (next: SceneScriptRoot) => void;
  characterAssets: CharacterAssetOption[];
  propAssets?: CharacterAssetOption[];
  sceneAssets?: CharacterAssetOption[];
}) {
  const character = sceneScript.characters.find((candidate) => candidate.id === characterId)!;
  // Hooks first: the render below has early returns.
  const [presetId, setPresetId] = useState<CharacterMotionPresetId>("walk_to");
  const [presetSeconds, setPresetSeconds] = useState("2");
  const [presetNote, setPresetNote] = useState<string | null>(null);
  const [presetTargetId, setPresetTargetId] = useState("");
  const [presetStop, setPresetStop] = useState(String(APPROACH_DEFAULT_STOP_DISTANCE));
  const move = (axis: 0 | 1 | 2, value: number) => {
    const next: SceneVec3 = [position[0], position[1], position[2]];
    next[axis] = value;
    onChange(moveSceneObjectAtFrame(sceneScript, { kind: "character", id: characterId }, frame, next));
  };
  const boundAsset =
    characterAssets.find((asset) => asset.asset_id === (character.character_asset_id ?? "")) ?? null;
  const bind = (assetId: string) => {
    onChange({
      ...sceneScript,
      characters: sceneScript.characters.map((candidate) =>
        candidate.id === characterId
          ? { ...candidate, character_asset_id: assetId || null }
          : candidate,
      ),
    });
  };

  const preset = CHARACTER_MOTION_PRESETS.find((candidate) => candidate.id === presetId)!;
  /**
   * A preset target is another object's CURRENT position (walk to the crate,
   * approach the other character) or — with nothing chosen — one metre along
   * the character's own facing. Objects are listed with their kind so a prop
   * and a character with confusing ids stay distinguishable.
   */
  const targetOptions = useMemo(() => {
    const options: { id: string; label: string }[] = [];
    for (const other of sceneScript.characters) {
      if (other.id === characterId) continue;
      options.push({ id: other.id, label: `角色 · ${other.id}` });
    }
    for (const prop of sceneScript.props) {
      options.push({ id: prop.id, label: `道具 · ${prop.id}` });
    }
    for (const object of sceneScript.environment) {
      options.push({ id: object.id, label: `环境 · ${object.id}` });
    }
    return options;
  }, [sceneScript, characterId]);

  const presetTarget = useMemo((): SceneVec3 | null => {
    if (!presetTargetId) return null;
    const other = sceneScript.characters.find((candidate) => candidate.id === presetTargetId);
    if (other) return characterPositionAtFrame(other, frame);
    const prop = sceneScript.props.find((candidate) => candidate.id === presetTargetId);
    if (prop) return prop.position;
    const object = sceneScript.environment.find((candidate) => candidate.id === presetTargetId);
    return object?.position ?? null;
  }, [presetTargetId, sceneScript, frame]);

  const applyPreset = () => {
    const frames = Math.max(
      1,
      Math.round((Number(presetSeconds) || 1) * sceneScript.scene.frame_rate),
    );
    const fallback: SceneVec3 = [
      position[0] + Math.sin((rotationY * Math.PI) / 180),
      position[1] + Math.cos((rotationY * Math.PI) / 180),
      position[2],
    ];
    // The speech layer is locked (V0.2 §14.13): count the sampled frames that
    // land inside a speech window BEFORE applying — those keep action "talk"
    // while the body is re-blocked. The author is told, not surprised.
    const character = sceneScript.characters.find((candidate) => candidate.id === characterId);
    const speakingFrames = character
      ? countSpeakingFramesInWindow(character.keyframes, frame, frames)
      : 0;
    onChange(
      applyCharacterMotionPreset(sceneScript, characterId, presetId, {
        startFrame: frame,
        durationFrames: frames,
        target: presetTarget ?? fallback,
        stopDistance: Number(presetStop) || APPROACH_DEFAULT_STOP_DISTANCE,
      }),
    );
    setPresetNote(
      speakingFrames > 0
        ? `已应用 · 🔒 ${speakingFrames} 帧在说话：唇形已保留（锁住 Audio 重做 Visual）`
        : "已应用。",
    );
  };

  return (
    <>
      <label className="scene-script-3d-editor__field">
        <span>角色资产绑定</span>
        <select
          aria-label="角色资产绑定"
          value={character.character_asset_id ?? ""}
          onChange={(event) => bind(event.target.value)}
        >
          <option value="">未绑定（多镜头场景会被标记）</option>
          {characterAssets.map((asset) => (
            <option key={asset.asset_id} value={asset.asset_id}>
              {asset.display_name}
            </option>
          ))}
        </select>
      </label>
      {/* 服装色板：the declaration the next scene inherits. Without it the
          wardrobe drift gate has nothing to compare and "把 Scene 02 的她换成
          黑风衣" is invisible across nodes — each node holds its own script,
          and nobody can see the other node while painting. */}
      <div className="scene-script-3d-editor__field">
        <span>服装色板</span>
        <div className="scene-script-3d-editor__preset-row">
          {(character.appearance.palette ?? Array.from({ length: 2 }, () => "")).map(
            (entry, index) => (
              <input
                key={index}
                type="color"
                aria-label={`为角色 ${characterId} 声明服装色板第 ${index + 1} 色`}
                value={entry || character.appearance.color || "#8B4513"}
                onChange={(event) => {
                  const next = [
                    ...(character.appearance.palette ?? ["", ""]),
                  ].slice(0, MAX_APPEARANCE_PALETTE_COLORS);
                  while (next.length < MAX_APPEARANCE_PALETTE_COLORS) next.push("");
                  next[index] = event.target.value;
                  onChange(setCharacterPalette(sceneScript, characterId, next));
                }}
              />
            ),
          )}
          <button
            type="button"
            onClick={() => onChange(setCharacterPalette(sceneScript, characterId, [null, null]))}
          >
            清除
          </button>
        </div>
        <small>
          声明后，同一角色资产在其它场景节点的色板不一致会被标记（换装要让叙事说明，
          而不是静默漂移）；留空表示这一维还没决定。
        </small>
      </div>
      {boundAsset && (
        <figure className="scene-script-3d-editor__reference" data-testid="character-reference">
          {boundAsset.preview_url ? (
            <img src={boundAsset.preview_url} alt={`${boundAsset.display_name} 参考图`} loading="lazy" />
          ) : (
            <span className="scene-script-3d-editor__reference-empty">无参考图</span>
          )}
          <figcaption>{boundAsset.display_name}</figcaption>
        </figure>
      )}
      <Vec3Field
        label="位置"
        value={position}
        onChange={move}
        hint="Blender Z-up：x 右 · y 前 · z 上"
      />
      <NumberField
        label="朝向 (rotation_y °)"
        value={Math.round(rotationY * 100) / 100}
        onChange={(value) => onChange(rotateCharacterAtFrame(sceneScript, characterId, frame, value))}
      />
      {/* Motion presets: before this, moving a character meant typing
          position vectors into keyframes — a walk across the room was nine
          keyframes of arithmetic with the facing wrong the whole way. The
          preset authors the whole move (sampled path + facing + actions). */}
      <div className="scene-script-3d-editor__field scene-script-3d-editor__preset">
        <span>动作预设</span>
        <div className="scene-script-3d-editor__preset-row">
          <select
            aria-label={`为角色 ${characterId} 选择动作预设`}
            value={presetId}
            onChange={(event) => setPresetId(event.target.value as CharacterMotionPresetId)}
          >
            {CHARACTER_MOTION_PRESETS.map((entry) => (
              <option key={entry.id} value={entry.id}>
                {entry.label} — {entry.description}
              </option>
            ))}
          </select>
          {preset.needsTarget && (
            <select
              aria-label={`为角色 ${characterId} 选择动作目标`}
              value={presetTargetId}
              onChange={(event) => setPresetTargetId(event.target.value)}
            >
              <option value="">面朝方向 1 米处</option>
              {targetOptions.map((option) => (
                <option key={option.id} value={option.id}>
                  {option.label}
                </option>
              ))}
            </select>
          )}
          {presetId === "approach" && (
            <input
              type="number"
              min={0.1}
              step={0.1}
              value={presetStop}
              aria-label={`为角色 ${characterId} 设置靠近停止距离 (m)`}
              title="靠近停止距离（米）"
              onChange={(event) => setPresetStop(event.target.value)}
            />
          )}
          <input
            type="number"
            min={0.5}
            step={0.5}
            value={presetSeconds}
            aria-label={`为角色 ${characterId} 设置动作时长 (s)`}
            title="动作时长（秒）"
            onChange={(event) => setPresetSeconds(event.target.value)}
          />
          <button
            type="button"
            data-testid={`character-preset-apply-${characterId}`}
            onClick={applyPreset}
          >
            应用到帧 {frame}
          </button>
        </div>
        {presetNote && (
          <p className="scene-script-3d-editor__hint" data-testid={`character-preset-note-${characterId}`}>
            {presetNote}
          </p>
        )}
      </div>
      <KeyframeStrip
        keyframes={character.keyframes.map((keyframe) => keyframe.frame)}
        currentFrame={frame}
      />
    </>
  );
}

// ---------------------------------------------------------------------------
// Static object fields (props / environment)
// ---------------------------------------------------------------------------

function StaticFields({
  sceneScript,
  kind,
  id,
  onChange,
  assetOptions = [],
}: {
  sceneScript: SceneScriptRoot;
  kind: "prop" | "environment";
  id: string;
  onChange: (next: SceneScriptRoot) => void;
  /** Assets of the matching semantic kind (props ← product_*, scenes ← scene_*). */
  assetOptions?: readonly CharacterAssetOption[];
}) {
  const object = kind === "prop"
    ? sceneScript.props.find((candidate) => candidate.id === id)
    : sceneScript.environment.find((candidate) => candidate.id === id);
  if (!object) return null;
  const position = object.position;
  const move = (axis: 0 | 1 | 2, value: number) => {
    const next: SceneVec3 = [position[0], position[1], position[2]];
    next[axis] = value;
    onChange(moveSceneObjectAtFrame(sceneScript, { kind, id }, 0, next));
  };
  // Held items only exist on props (environment is fixed by definition). When
  // kind === "prop" the object above was already found in `script.props`, so
  // the narrowing cast is exact rather than hopeful.
  const heldProp: SceneProp | null = kind === "prop" ? (object as SceneProp) : null;
  const boundAssetId = (object as SceneProp).prop_asset_id
    ?? (object as SceneEnvironment).scene_asset_id
    ?? null;
  const bindAsset = (assetId: string) => {
    if (kind === "prop") {
      onChange(bindPropAsset(sceneScript, id, assetId));
    } else {
      onChange(bindEnvironmentAsset(sceneScript, id, assetId));
    }
  };
  return (
    <>
      {/* The Dramagic lock, past characters: a prop derived from a generated
          asset and an environment taken from a scene board are the same
          identity claim, and the claim needs somewhere to live. */}
      <label className="scene-script-3d-editor__field">
        <span>{kind === "prop" ? "道具资产绑定" : "场景资产绑定"}</span>
        <select
          aria-label={kind === "prop" ? `道具 ${id} 资产绑定` : `环境 ${id} 资产绑定`}
          value={boundAssetId ?? ""}
          onChange={(event) => bindAsset(event.target.value)}
        >
          <option value="">未绑定（多镜头场景会被标记）</option>
          {assetOptions.map((asset) => (
            <option key={asset.asset_id} value={asset.asset_id}>
              {asset.display_name}
            </option>
          ))}
        </select>
      </label>
      <Vec3Field label="位置" value={position} onChange={move} />
      <NumberField
        label="朝向 (rotation_y °)"
        value={object.rotation_y ?? 0}
        onChange={(value) => onChange(rotateStaticObject(sceneScript, kind, id, value))}
      />
      <NumberField
        label="缩放 (scale)"
        value={object.scale ?? 1}
        onChange={(value) => onChange(scaleStaticObject(sceneScript, kind, id, value))}
      />
      {kind === "prop" && (
        /* Held items (V0.2 §5): declaring a holder makes the prop ride that
           character's hand across every shot — the "伞在右手/下一镜到左手"
           failure stops being representable. The authored position becomes
           the rest position, which is why the hint says so out loud. */
        <>
          <div className="scene-script-3d-editor__field">
            <span>持有者</span>
            <select
              aria-label={`道具 ${id} 的持有者`}
              value={heldProp?.held_by ?? ""}
              onChange={(event) =>
                onChange(
                  setPropHeld(
                    sceneScript,
                    id,
                    event.target.value || null,
                    heldProp?.held_side ?? "right",
                  ),
                )
              }
            >
              <option value="">无（固定摆放）</option>
              {sceneScript.characters.map((character) => (
                <option key={character.id} value={character.id}>
                  {character.id}
                </option>
              ))}
            </select>
          </div>
          {heldProp?.held_by && (
            <>
              <div className="scene-script-3d-editor__field">
                <span>持手</span>
                <select
                  aria-label={`道具 ${id} 的持手`}
                  value={heldProp.held_side ?? "right"}
                  onChange={(event) =>
                    onChange(
                      setPropHeld(
                        sceneScript,
                        id,
                        heldProp.held_by ?? null,
                        event.target.value === "left" ? "left" : "right",
                      ),
                    )
                  }
                >
                  <option value="right">右手</option>
                  <option value="left">左手</option>
                </select>
              </div>
              <p className="scene-script-3d-editor__hint" data-testid={`held-hint-${id}`}>
                位置由 {heldProp.held_by} 的手部跟随（预览与渲染一致）；上方手写位置仅在未持有时生效。
              </p>
            </>
          )}
        </>
      )}
    </>
  );
}

// ---------------------------------------------------------------------------
// Camera fields (pose + shot type + motion presets)
// ---------------------------------------------------------------------------

function CameraFields({
  sceneScript,
  cameraId,
  frame,
  onChange,
}: {
  sceneScript: SceneScriptRoot;
  cameraId: string;
  frame: number;
  onChange: (next: SceneScriptRoot) => void;
}) {
  // Hooks first: the early return below must not change the hook order.
  const [presetId, setPresetId] = useState<CameraMotionPresetId>("push_in");
  const [presetSeconds, setPresetSeconds] = useState("2");
  const camera = sceneScript.cameras.find((candidate) => candidate.id === cameraId);
  if (!camera) return null;
  const keyframe = camera.keyframes.find((candidate) => candidate.frame === frame)
    ?? camera.keyframes[0];
  const lookAt = keyframe?.look_at ?? [0, 0, 1];
  return (
    <>
      <Vec3Field
        label="机位"
        value={keyframe?.position ?? [0, 0, 0]}
        onChange={(axis, value) => {
          const position: SceneVec3 = [
            keyframe?.position[0] ?? 0,
            keyframe?.position[1] ?? 0,
            keyframe?.position[2] ?? 0,
          ];
          position[axis] = value;
          onChange(moveCameraAtFrame(sceneScript, cameraId, frame, position));
        }}
      />
      <Vec3Field
        label="注视点 (look_at)"
        value={lookAt}
        onChange={(axis, value) => {
          const next: SceneVec3 = [lookAt[0], lookAt[1], lookAt[2]];
          next[axis] = value;
          onChange(setCameraLookAtAtFrame(sceneScript, cameraId, frame, next));
        }}
      />
      <label className="scene-script-3d-editor__field">
        <span>景别 (shot_type)</span>
        <select
          value={camera.shot_type}
          onChange={(event) => onChange(setCameraShotType(sceneScript, cameraId, event.target.value))}
        >
          {SHOT_TYPES.map((shotType) => (
            <option key={shotType} value={shotType}>
              {shotType}
            </option>
          ))}
        </select>
      </label>
      {/* Motion presets: hand-authoring an orbit means computing the arc by
          hand. The preset writes SAMPLED keyframes so the renderer's linear
          interpolation traces the curve (two keys would cut a chord). */}
      <div className="scene-script-3d-editor__field scene-script-3d-editor__preset">
        <span>运镜预设</span>
        <div className="scene-script-3d-editor__preset-row">
          <select
            aria-label={`为相机 ${cameraId} 选择运镜预设`}
            value={presetId}
            onChange={(event) => setPresetId(event.target.value as CameraMotionPresetId)}
          >
            {CAMERA_MOTION_PRESETS.map((preset) => (
              <option key={preset.id} value={preset.id}>
                {preset.label} — {preset.description}
              </option>
            ))}
          </select>
          <input
            type="number"
            min={0.5}
            step={0.5}
            value={presetSeconds}
            aria-label={`为相机 ${cameraId} 设置运镜时长 (s)`}
            title="运镜时长（秒）"
            onChange={(event) => setPresetSeconds(event.target.value)}
          />
          <button
            type="button"
            data-testid={`camera-preset-apply-${cameraId}`}
            onClick={() => {
              const frames = Math.max(
                1,
                Math.round((Number(presetSeconds) || 1) * sceneScript.scene.frame_rate),
              );
              onChange(
                applyCameraMotionPreset(sceneScript, cameraId, presetId, {
                  startFrame: frame,
                  durationFrames: frames,
                }),
              );
            }}
          >
            应用到帧 {frame}
          </button>
        </div>
      </div>
      <KeyframeStrip keyframes={camera.keyframes.map((keyframe) => keyframe.frame)} currentFrame={frame} />
    </>
  );
}

// ---------------------------------------------------------------------------
// Field primitives
// ---------------------------------------------------------------------------

function Vec3Field({
  label,
  value,
  onChange,
  hint,
}: {
  label: string;
  value: SceneVec3;
  onChange: (axis: 0 | 1 | 2, value: number) => void;
  hint?: string;
}) {
  return (
    <fieldset className="scene-script-3d-editor__field scene-script-3d-editor__field--vec3">
      <legend>
        {label}
        {hint && <span className="scene-script-3d-editor__hint"> · {hint}</span>}
      </legend>
      <NumberField compact label="x" value={value[0]} onChange={(next) => onChange(0, next)} />
      <NumberField compact label="y" value={value[1]} onChange={(next) => onChange(1, next)} />
      <NumberField compact label="z" value={value[2]} onChange={(next) => onChange(2, next)} />
    </fieldset>
  );
}

/**
 * A number input that commits on blur/Enter (not per keystroke): the edit
 * model writes a keyframe per commit, so typing "1.5" must not produce three
 * intermediate keyframes.
 */
function NumberField({
  label,
  value,
  onChange,
  compact = false,
}: {
  label: string;
  value: number;
  onChange: (value: number) => void;
  compact?: boolean;
}) {
  const [draft, setDraft] = useState(String(value));
  const [editing, setEditing] = useState(false);
  const shown = editing ? draft : String(value);
  const commit = () => {
    setEditing(false);
    const parsed = Number.parseFloat(draft);
    if (Number.isFinite(parsed) && Math.abs(parsed - value) > 1e-6) {
      onChange(parsed);
    } else {
      setDraft(String(value));
    }
  };
  return (
    <label className={`scene-script-3d-editor__field${compact ? " scene-script-3d-editor__field--compact" : ""}`}>
      <span>{label}</span>
      <input
        type="number"
        step="0.1"
        value={shown}
        onFocus={() => {
          setEditing(true);
          setDraft(String(value));
        }}
        onChange={(event) => setDraft(event.target.value)}
        onBlur={commit}
        onKeyDown={(event) => {
          if (event.key === "Enter") event.currentTarget.blur();
        }}
      />
    </label>
  );
}

function KeyframeStrip({
  keyframes,
  currentFrame,
}: {
  keyframes: number[];
  currentFrame: number;
}) {
  if (keyframes.length === 0) return null;
  return (
    <div className="scene-script-3d-editor__keyframes">
      <span>{keyframes.length} 个关键帧</span>
      <div className="scene-script-3d-editor__keyframe-list">
        {keyframes.map((frame) => (
          <span
            key={frame}
            className={`scene-script-3d-editor__keyframe${frame === currentFrame ? " is-current" : ""}`}
            title={`帧 ${frame}`}
          >
            ◆{frame}
          </span>
        ))}
      </div>
    </div>
  );
}

/** Character asset offered for identity binding. */
export interface CharacterAssetOption {
  asset_id: string;
  display_name: string;
  preview_url?: string | null;
}
