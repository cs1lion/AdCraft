/**
 * Backend round trip for the director command bar.
 *
 * The bar expands a command locally (directorMotion.ts) and previews the
 * result optimistically. This client sends that same intent through the
 * backend's /director-motion endpoint, which expands the preset into ops and
 * runs them through the same all-or-nothing gate as /apply-operations. A
 * rejected batch (an out-of-bounds keyframe, an enum violation) is caught
 * by the backend instead of silently landing in the draft. The optimistic
 * preview is kept either way — the gate only gates persistence, not the
 * live 3D view, which is the point of the director flow.
 *
 * The module is dependency-light (plain fetch on /api/v1) so it can be
 * imported from the workbench without dragging in the v2 client.
 */

import type { SceneScriptRoot } from "../../../types/scene-script";

const SCENE_3D_BASE = "/api/v1/scene-3d";

/** The director /director-motion request body (mirrors directorMotion.ts request). */
export interface DirectorMotionRequest {
  intent: string;
  target_id: string;
  preset_id: string;
  start_frame: number;
  duration_frames: number;
  target_position?: readonly number[] | null;
  stop_distance?: number;
}

export interface DirectorMotionGateResult {
  ok: boolean;
  /** The backend's post-apply script when the gate passed. */
  appliedSceneScript?: SceneScriptRoot;
  /** The ops the backend expanded from the intent (for logging / replay). */
  operations?: Record<string, unknown>[];
  error?: string;
  errorCode?: string;
}

/**
 * POST the director intent to /director-motion. The backend expands the
 * preset into ops and runs them through the same all-or-nothing gate as
 * apply-operations, so the client's optimistic preview and the persisted
 * state stay in lockstep. The caller keeps its preview on rejection.
 */
export async function applyDirectorMotion(
  sceneScript: SceneScriptRoot,
  request: DirectorMotionRequest,
): Promise<DirectorMotionGateResult> {
  const response = await fetch(`${SCENE_3D_BASE}/director-motion`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      scene_script: JSON.parse(JSON.stringify(sceneScript)),
      intent: request.intent,
      target_id: request.target_id,
      preset_id: request.preset_id,
      start_frame: request.start_frame,
      duration_frames: request.duration_frames,
      target_position: request.target_position ?? null,
      stop_distance: request.stop_distance ?? 1.2,
    }),
  });

  const body = (await response.json()) as {
    success?: boolean;
    applied_scene_script?: SceneScriptRoot;
    operations?: Record<string, unknown>[];
    error?: string;
    error_code?: string;
  };

  if (!response.ok) {
    const detail = body as { detail?: Record<string, unknown> };
    const detailObject = detail.detail ?? body;
    return {
      ok: false,
      error: (detailObject.error as string | undefined) ?? `gate rejected the batch (${response.status})`,
      errorCode: (detailObject.error_code as string | undefined) ?? "director_motion_rejected",
    };
  }

  if (!body.success || !body.applied_scene_script) {
    return {
      ok: false,
      error: "the gate returned no applied script",
      errorCode: "director_motion_rejected",
    };
  }

  return {
    ok: true,
    appliedSceneScript: body.applied_scene_script,
    operations: body.operations ?? [],
  };
}

/**
 * Storyboard export client (V3).
 *
 * POSTs the scene script to /scene-3d/storyboard and returns the shot list
 * + flat keyframe-frame strip. The caller can use the frame numbers to call
 * /scene-3d/keyframes for actual rendered stills, or drive the local
 * preview's playhead to those frames for a live storyboard walk-through.
 */

export interface StoryboardShotEntry {
  shot_id: string;
  camera_id: string;
  shot_type: string;
  start_frame: number;
  end_frame: number;
  duration_frames: number;
  description: string;
  transition_intent: string | null;
  keyframe_frames: number[];
}

export interface StoryboardFinding {
  /** "storyboard_no_shots" | "storyboard_shots_leave_gap" | "storyboard_shot_keyframes_short" */
  code: string;
  /** 涉及的镜头或帧范围 */
  subject: string;
  message: string;
}

export interface StoryboardResult {
  ok: boolean;
  sceneName?: string;
  shots?: StoryboardShotEntry[];
  allKeyframeFrames?: number[];
  // E3: advisory findings（空隙/短镜/空分镜）——后端算了就必须透传到 UI
  findings?: StoryboardFinding[];
  error?: string;
  errorCode?: string;
}

export async function exportStoryboard(
  sceneScript: SceneScriptRoot,
): Promise<StoryboardResult> {
  const response = await fetch(`${SCENE_3D_BASE}/storyboard`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ scene_script: JSON.parse(JSON.stringify(sceneScript)) }),
  });

  const body = (await response.json()) as {
    success?: boolean;
    scene_name?: string;
    shots?: StoryboardShotEntry[];
    all_keyframe_frames?: number[];
    findings?: StoryboardFinding[];
    error?: string;
    error_code?: string;
  };

  if (!body.success) {
    return {
      ok: false,
      error: body.error ?? "storyboard export failed",
      errorCode: body.error_code ?? "storyboard_export_failed",
    };
  }

  return {
    ok: true,
    sceneName: body.scene_name,
    shots: body.shots ?? [],
    allKeyframeFrames: body.all_keyframe_frames ?? [],
    findings: Array.isArray(body.findings) ? body.findings : [],
  };
}

/**
 * Continuity suggestions client (V3).
 *
 * POSTs the scene script (and optional speech segments) to
 * /scene-3d/continuity-suggestions. Returns conversational hints the
 * creator can read in the chat/director side, plus an `untranslated`
 * list for findings the translator does not yet know (never dropped
 * silently).
 */

export interface ContinuitySuggestion {
  kind: string;
  source_code: string;
  detail: string;
  message: string;
  subjects: string[];
  remedy?: string;
}

export interface ContinuitySuggestionsResult {
  ok: boolean;
  suggestions?: ContinuitySuggestion[];
  untranslated?: { code: string; detail: string }[];
  error?: string;
  errorCode?: string;
}

export async function fetchContinuitySuggestions(
  sceneScript: SceneScriptRoot,
  segments?: Record<string, unknown>[] | null,
): Promise<ContinuitySuggestionsResult> {
  const response = await fetch(`${SCENE_3D_BASE}/continuity-suggestions`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      scene_script: JSON.parse(JSON.stringify(sceneScript)),
      segments: segments ?? null,
    }),
  });

  const body = (await response.json()) as {
    success?: boolean;
    suggestions?: ContinuitySuggestion[];
    untranslated?: { code: string; detail: string }[];
    error?: string;
    error_code?: string;
  };

  if (!body.success) {
    return {
      ok: false,
      error: body.error ?? "continuity check failed",
      errorCode: body.error_code ?? "continuity_check_failed",
    };
  }

  return {
    ok: true,
    suggestions: body.suggestions ?? [],
    untranslated: body.untranslated ?? [],
  };
}


/**
 * When/then trigger event client for the director command bar.
 *
 * A trigger event ("wait for him to sit down, then the light goes out")
 * is POSTed to /scene-3d/trigger-event. The backend expands the trigger
 * and the then-ops through the same all-or-nothing gate as /director-motion.
 * The caller keeps its optimistic preview on rejection.
 */

export interface TriggerEventRequest {
  trigger: string;
  triggerTargetId: string;
  triggerFrame: number;
  triggerTargetPosition?: readonly number[] | null;
  triggerTargetYaw?: number | null;
  thenOps: Record<string, unknown>[];
  thenFrame: number;
}

export interface TriggerEventGateResult {
  ok: boolean;
  appliedSceneScript?: SceneScriptRoot;
  operations?: Record<string, unknown>[];
  error?: string;
  errorCode?: string;
}

export async function applyTriggerEvent(
  sceneScript: SceneScriptRoot,
  request: TriggerEventRequest,
): Promise<TriggerEventGateResult> {
  const response = await fetch(`${SCENE_3D_BASE}/trigger-event`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      scene_script: JSON.parse(JSON.stringify(sceneScript)),
      trigger: request.trigger,
      trigger_target_id: request.triggerTargetId,
      trigger_frame: request.triggerFrame,
      trigger_target_position: request.triggerTargetPosition ?? null,
      trigger_target_yaw: request.triggerTargetYaw ?? null,
      then_ops: request.thenOps,
      then_frame: request.thenFrame,
    }),
  });

  const body = (await response.json()) as {
    success?: boolean;
    applied_scene_script?: SceneScriptRoot;
    operations?: Record<string, unknown>[];
    error?: string;
    error_code?: string;
  };

  if (!body.success || !body.applied_scene_script) {
    return {
      ok: false,
      error: body.error ?? "trigger event was rejected",
      errorCode: body.error_code ?? "trigger_event_rejected",
    };
  }

  return {
    ok: true,
    appliedSceneScript: body.applied_scene_script,
    operations: body.operations ?? [],
  };
}

// ---------------------------------------------------------------------------
// E6: Scene-3D async render jobs (render/async + poll + cancel)
//
// The render/async family already existed on the backend (RenderJobManager:
// progress + cooperative cancel); the workbench had no entry for it. These
// three calls give the 3D line the same visibility the replica line has:
// submit → job id → poll progress → cancel for real.
// ---------------------------------------------------------------------------

export interface Scene3DRenderJobStatus {
  job_id: string;
  status: string; // pending | running | completed | failed | cancelled
  progress: number;
  error?: string | null;
  result?: {
    output_dir?: string;
    frame_count?: number;
    video_path?: string | null;
    animatic_video_path?: string | null;
    audio_muxed?: boolean;
    duration_seconds?: number;
    blender_version?: string | null;
    warnings?: string[];
  } | null;
}

export async function submitScene3DRender(sceneScript: SceneScriptRoot): Promise<string> {
  const response = await fetch(`${SCENE_3D_BASE}/render/async`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ scene_script: JSON.parse(JSON.stringify(sceneScript)) }),
  });
  const body = (await response.json().catch(() => null)) as {
    job_id?: string;
    detail?: unknown;
  } | null;
  if (response.status !== 200 || !body?.job_id) {
    const detail = typeof body?.detail === "string" ? body.detail : "";
    throw new Error(detail || `渲染提交失败 (HTTP ${response.status})`);
  }
  return String(body.job_id);
}

export async function fetchScene3DRenderJob(jobId: string): Promise<Scene3DRenderJobStatus> {
  const response = await fetch(`${SCENE_3D_BASE}/render/${encodeURIComponent(jobId)}`);
  const body = (await response.json().catch(() => null)) as Scene3DRenderJobStatus | null;
  if (response.status !== 200 || !body) {
    throw new Error(`渲染状态查询失败 (HTTP ${response.status})`);
  }
  return body;
}

export async function cancelScene3DRender(jobId: string): Promise<void> {
  const response = await fetch(`${SCENE_3D_BASE}/render/${encodeURIComponent(jobId)}/cancel`, {
    method: "POST",
  });
  const body = (await response.json().catch(() => null)) as { detail?: unknown } | null;
  if (response.status !== 200) {
    const detail = typeof body?.detail === "string" ? body.detail : "";
    throw new Error(detail || `取消渲染失败 (HTTP ${response.status})`);
  }
}

// ---------------------------------------------------------------------------
// Language-builder AI fallback: a sentence the deterministic keyword map
// cannot parse escalates to /language-fallback (white-model LLM -> ops
// batch -> the same all-or-nothing gate). The applied script comes back;
// a rejection comes back coded so the builder can say what went wrong and
// keep the sentence for a retry.
// ---------------------------------------------------------------------------

export interface LanguageFallbackResult {
  ok: boolean;
  appliedSceneScript?: SceneScriptRoot;
  operationCount?: number;
  error?: string;
  errorCode?: string;
}

export async function requestLanguageFallback(
  sceneScript: SceneScriptRoot,
  text: string,
): Promise<LanguageFallbackResult> {
  const response = await fetch(`${SCENE_3D_BASE}/language-fallback`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      scene_script: JSON.parse(JSON.stringify(sceneScript)),
      text,
    }),
  });

  const body = (await response.json().catch(() => null)) as {
    success?: boolean;
    operation_count?: number;
    applied_scene_script?: SceneScriptRoot;
    error?: string;
    error_code?: string;
    detail?: Record<string, unknown>;
  } | null;

  if (!response.ok) {
    const detail = body?.detail ?? {};
    return {
      ok: false,
      error:
        (detail.error as string | undefined) ??
        body?.error ??
        `AI 兜底请求失败 (HTTP ${response.status})`,
      errorCode:
        (detail.error_code as string | undefined) ??
        body?.error_code ??
        "language_fallback_failed",
    };
  }

  if (!body?.success || !body.applied_scene_script) {
    return {
      ok: false,
      error: body?.error ?? "AI 没能更新场景",
      errorCode: body?.error_code ?? "language_fallback_failed",
    };
  }

  return {
    ok: true,
    appliedSceneScript: body.applied_scene_script,
    operationCount: body.operation_count ?? 0,
  };
}
