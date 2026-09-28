/**
 * LocalEngineWorkbench + Scene3DEditSection — the prompt composer and the 3D
 * director surface for the two local-engine nodes.
 *
 * These nodes do not select a catalog provider — speech is synthesized locally
 * and scenes are rendered by Blender — so the panel offers the prompt editor
 * and a Run button, reusing the shared draft machinery. The scene-3d branch
 * adds the interactive editor, whose draft is the node's SceneScript: a
 * content signature decides when the panel re-syncs from the node, and local
 * edits win until an explicit save or revert (never clobber the author's work
 * silently).
 *
 * Everything the scene-3d executor publishes onto the node is parsed here and
 * handed to the editor, because a report nobody can see is not a report
 * (V0.2 §12 的核心问题 / ADR 0005: queryable, never silent).
 */

import { lazy, Suspense, useCallback, useEffect, useMemo, useState, type RefObject } from "react";
import { createPortal } from "react-dom";

import { SendIcon } from "../../../icons.tsx";
import type { CanvasNodeV2, NodeRuntimeV2, ProjectAssetSummaryV2 } from "../../../types-v2.ts";
import type { SceneScriptRoot } from "../../../types/scene-script";
import { AgentCanvasAudioPlayer } from "../canvas/AgentCanvasAudioPlayer.tsx";
import { AudioBedEditor } from "./AudioBedEditor.tsx";
import { DialogueAlignmentPanel } from "../canvas/DialogueAlignmentPanel.tsx";
import { DialogueLipSyncPanel } from "../canvas/DialogueLipSyncPanel.tsx";
import { Scene3DRenderControls } from "../canvas/Scene3DRenderControls.tsx";
import { FourLinePromptEditor } from "./FourLinePromptEditor.tsx";
import { NodeWorkbenchError } from "./NodeWorkbenchError.tsx";
import { SceneImageIntake } from "../canvas/SceneImageIntake.tsx";
import { WhiteModelOpLog } from "../canvas/WhiteModelOpLog.tsx";
import {
  clearScene3dDraft,
  readScene3dDraft,
  writeScene3dDraft,
} from "../canvas/scene3dDraft.ts";
import {
  DIRECTOR_TAKES_CONTENT_KEY,
  parseDirectorTakes,
  serializeDirectorTakes,
  type DirectorTake,
} from "../canvas/directorTakes.ts";
import { VoiceCastDialogueLines } from "./VoiceCastDialogueLines.tsx";
import {
  describeObjectPointer,
  objectPointerToken,
} from "../canvas/objectPointer.ts";
import type { SceneObjectRef } from "../canvas/sceneScriptEditModel";
import type { NodeWorkbenchDraft } from "./useNodeWorkbenchDraft.ts";
import {
  AUDIO_BED_CONTENT_KEY,
  parseAudioBedConfig,
  type AudioBedScript,
} from "./audioBedConfig.ts";
import type { AlignedLine } from "../canvas/DialogueAlignmentPanel.tsx";
import type { AlignedSpeechSegment } from "../timeline/dialogueSubtitleCues.ts";
import type { PatchNode } from "./workbenchTypes.ts";
import "./scene-3d-workbench.css";
import "./audio-bed-workbench.css";

// three.js is a ~1 MB dependency: keep it in an async chunk so the workbench
// bundle stays within the perf budget (same pattern as SceneScriptPanel).
const SceneScript3DEditor = lazy(() =>
  import("../canvas/SceneScript3DEditor.tsx").then((module) => ({
    default: module.SceneScript3DEditor,
  })),
);

const PLACEHOLDERS: Partial<Record<CanvasNodeV2["node_type"], string>> = {
  "voice-cast": "Enter the dialogue to be spoken.",
  "scene-3d": "Describe the scene: setting, characters, camera, and action.",
};

const RUN_LABELS: Partial<Record<CanvasNodeV2["node_type"], string>> = {
  "voice-cast": "Run voice-cast node",
  "scene-3d": "Run scene-3d node",
};

/** Key under node structured_content carrying the persisted SceneScript. */
const SCENE_SCRIPT_CONTENT_KEY = "scene_script";
/** Per-line dialogue the voice-cast node speaks (§14.7). */
const DIALOGUE_LINES_CONTENT_KEY = "dialogue_lines";
/** Saved transition readings (V0.2 §9 局部分叉). */
const TRANSITION_VARIANTS_CONTENT_KEY = "transition_variants";

export function LocalEngineWorkbench({
  node,
  runtime = null,
  draft,
  promptEditorRef,
  patchNode,
  characterAssets = [],
  propAssets = [],
  sceneAssets = [],
  autoLipSync = null,
  referenceBindings = null,
  outputAsset = null,
  alignedSpeechLines = null,
  onLinesAligned,
  speechAudioUrl = null,
}: {
  node: CanvasNodeV2;
  runtime?: NodeRuntimeV2 | null;
  draft: NodeWorkbenchDraft;
  promptEditorRef?: RefObject<HTMLTextAreaElement | null>;
  patchNode?: PatchNode;
  characterAssets?: CharacterAssetOption[];
  propAssets?: CharacterAssetOption[];
  sceneAssets?: CharacterAssetOption[];
  outputAsset?: ProjectAssetSummaryV2 | null;
  alignedSpeechLines?: readonly AlignedLine[] | null;
  onLinesAligned?: (lines: AlignedLine[]) => void;
  autoLipSync?: AutoLipSyncFacts | null;
  referenceBindings?: readonly ReferenceBinding[] | null;
  speechAudioUrl?: string | null;
}) {
  const publishing = runtime?.phase === "publishing";
  // The speech-aware readings price against the bed's script entries, and the
  // bed's speaker→character map decides which character a line is spoken by.
  const { scripts: bedScripts, characterMap: bedCharacterMap } = useMemo(
    () => audioBedParts(node.structured_content?.[AUDIO_BED_CONTENT_KEY]),
    [node.structured_content],
  );
  const hasAudioBed = node.structured_content?.[AUDIO_BED_CONTENT_KEY] != null;
  // §8.2: what the author currently points at in the 3D viewport. It is
  // hoisted here — beside the composer — so the pointer and the language layer
  // finally meet; "这个" would otherwise stay ambiguous no matter how
  // precisely it was pointed.
  const [pointedAt, setPointedAt] = useState<SceneObjectRef | null>(null);
  const pointerLabel = describeObjectPointer(pointedAt);
  // A bed run needs no prompt (the bed IS the content); the classic per-line
  // path does — but an empty prompt must not block a bed run.
  const runDisabled = draft.pending
    || (!hasAudioBed && !draft.prompt.trim())
    || node.status === "working"
    || (node.status === "ready" && publishing);

  return (
    <div className="agent-node-workbench__body">
      {pointerLabel && (
        <div className="agent-node-workbench__pointer" data-testid="workbench-pointer">
          <span>
            🎯 当前指向：<strong>{pointerLabel}</strong>
            ——你在提示词里说“这个”时，指的就是它。
          </span>
          <button
            type="button"
            data-testid="workbench-pointer-write"
            title={`把「${pointerLabel}」写进提示词（可见地追加，不静默修改）`}
            onClick={() => {
              const token = objectPointerToken(pointedAt);
              if (!token) return;
              const trimmed = draft.prompt.trim();
              draft.setPrompt(trimmed ? `${trimmed} ${token}` : token);
            }}
          >
            把指向写进提示
          </button>
        </div>
      )}
      <label className="agent-node-workbench__composer">
        <FourLinePromptEditor
          ariaLabel="Generation prompt"
          value={draft.prompt}
          disabled={draft.pending}
          placeholder={PLACEHOLDERS[node.node_type] ?? "Describe what to create."}
          onChange={(event) => draft.setPrompt(event.currentTarget.value)}
          editorRef={promptEditorRef}
        />
      </label>

      {node.node_type === "scene-3d" ? (
        <Scene3DEditSection
          node={node}
          patchNode={patchNode}
          characterAssets={characterAssets}
          propAssets={propAssets}
          sceneAssets={sceneAssets}
          alignedSpeechLines={alignedSpeechLines}
          speechAudioUrl={speechAudioUrl}
          onSelectionChange={setPointedAt}
        />
      ) : null}
      {node.node_type === "voice-cast" ? (
        <>
          <VoiceCastDialogueLines node={node} patchNode={patchNode} />
          {outputAsset ? (
            <section className="local-engine-workbench__output">
              <AgentCanvasAudioPlayer
                node={node}
                status={node.status}
                asset={outputAsset}
              />
            </section>
          ) : null}
          <AudioBedEditor node={node} patchNode={patchNode} />
          <DialogueAlignmentPanel
            assetId={outputAsset?.asset_id ?? null}
            scripts={bedScripts}
            disabled={draft.pending}
            onLinesAligned={onLinesAligned}
            speakerCharacterMap={bedCharacterMap}
          />
        </>
      ) : null}
      <NodeWorkbenchError draft={draft} />

      <footer className="agent-node-workbench__footer agent-node-workbench__footer--composer">
        <div className="agent-node-workbench__composer-actions">
          <button
            type="button"
            className="agent-node-workbench__run"
            aria-label={RUN_LABELS[node.node_type] ?? "Run node"}
            title="Run node"
            disabled={runDisabled}
            onClick={() => void draft.run()}
          >
            <SendIcon />
          </button>
        </div>
      </footer>
    </div>
  );
}

// ---------------------------------------------------------------------------
// The scene-3d director surface
// ---------------------------------------------------------------------------

/**
 * The bed's speaker→character map (who each role is in the scene) and its
 * script entries, read through the shared bed parser so the workbench and the
 * bed editor cannot disagree about the block's shape.
 */
function audioBedParts(raw: unknown): {
  scripts: AudioBedScript[];
  characterMap: Record<string, string> | null;
} {
  const config = parseAudioBedConfig(raw);
  if (!config) return { scripts: [], characterMap: null };
  const map: Record<string, string> = {};
  for (const role of config.roles) {
    const name = role.name.trim();
    const characterId = (role.character_id ?? "").trim();
    if (name && characterId) map[name] = characterId;
  }
  return {
    scripts: config.scripts,
    characterMap: Object.keys(map).length > 0 ? map : null,
  };
}

/**
 * E4: 多轮记忆的保留集（V0.2 §14.5）——作者已处理过（应用/驳回）的 reading id。
 * 后端把它持久化在 scene-3d 节点的 structured_content.retained_reading_ids；
 * 刷新后由这里读回，交给编辑器喂给提案面板的初始保留集。
 */
function parseRetainedReadingIds(raw: unknown): string[] | undefined {
  if (!Array.isArray(raw)) return undefined;
  const ids = raw.filter((entry): entry is string => typeof entry === "string" && entry.length > 0);
  return ids.length > 0 ? ids : undefined;
}

/** The continuity findings, as the editor's shape (or nothing). */
function parseBlockingFindings(raw: unknown): BlockingFinding[] | null {
  if (!Array.isArray(raw)) return null;
  const findings: BlockingFinding[] = [];
  for (const entry of raw) {
    if (!entry || typeof entry !== "object") continue;
    const finding = entry as Record<string, unknown>;
    if (typeof finding.message !== "string" || typeof finding.remedy !== "string") continue;
    findings.push({
      code: typeof finding.code === "string" ? finding.code : "unknown",
      severity: typeof finding.severity === "string" ? finding.severity : "warning",
      subject: typeof finding.subject === "string" ? finding.subject : "",
      boundary: typeof finding.boundary === "string" ? finding.boundary : "",
      message: finding.message,
      remedy: finding.remedy,
    });
  }
  return findings;
}

/** The declared-reading reconciliation notes (§13 第 4 问), or nothing. */
function parseTransitionIntentNotes(raw: unknown): TransitionIntentNote[] | null {
  if (!Array.isArray(raw)) return null;
  const notes: TransitionIntentNote[] = [];
  for (const entry of raw) {
    if (!entry || typeof entry !== "object") continue;
    const note = entry as Record<string, unknown>;
    if (typeof note.message !== "string") continue;
    notes.push({
      code: typeof note.code === "string" ? note.code : "unknown",
      severity: typeof note.severity === "string" ? note.severity : "info",
      shot_id: typeof note.shot_id === "string" ? note.shot_id : "",
      reading_id: typeof note.reading_id === "string" ? note.reading_id : null,
      message: note.message,
      remedy: typeof note.remedy === "string" ? note.remedy : "",
    });
  }
  return notes;
}

/** The Dramagic pre-render consistency report (§12's core concern). */
function parseConsistency(
  raw: unknown,
): { passed: boolean; issues: ConsistencyFinding[] } | null {
  if (!raw || typeof raw !== "object") return null;
  const report = raw as Record<string, unknown>;
  if (typeof report.passed !== "boolean") return null;
  const rawIssues = Array.isArray(report.issues) ? report.issues : [];
  const issues: ConsistencyFinding[] = [];
  for (const entry of rawIssues) {
    if (!entry || typeof entry !== "object") continue;
    const issue = entry as Record<string, unknown>;
    if (typeof issue.message !== "string") continue;
    issues.push({
      code: typeof issue.code === "string" ? issue.code : "unknown",
      severity: typeof issue.severity === "string" ? issue.severity : "warning",
      subject: typeof issue.subject === "string" ? issue.subject : "",
      message: issue.message,
      remedy: typeof issue.remedy === "string" ? issue.remedy : "",
    });
  }
  return { passed: report.passed, issues };
}

/** Cross-node character drift (V0.2 §5 服装维度). */
function parseWardrobeDrift(
  raw: unknown,
): { checked: boolean; reason?: string | null; findings: DriftFinding[] } | null {
  if (!raw || typeof raw !== "object") return null;
  const report = raw as Record<string, unknown>;
  if (typeof report.checked !== "boolean") return null;
  const rawFindings = Array.isArray(report.findings) ? report.findings : [];
  const findings: DriftFinding[] = [];
  for (const entry of rawFindings) {
    if (!entry || typeof entry !== "object") continue;
    const finding = entry as Record<string, unknown>;
    if (typeof finding.message !== "string" || typeof finding.remedy !== "string") continue;
    findings.push({
      code: typeof finding.code === "string" ? finding.code : "unknown",
      subject: typeof finding.subject === "string" ? finding.subject : "",
      message: finding.message,
      remedy: finding.remedy,
    });
  }
  return {
    checked: report.checked,
    reason: typeof report.reason === "string" ? report.reason : null,
    findings,
  };
}

/**
 * How the last run drove the mouths (ADR 0003: 对齐即实测，不重新估算). The
 * source IS the fact: "estimated" means the mouths are a guess, and the
 * warnings say where the run fell short. Neither was readable anywhere in the
 * UI, so an author could not tell whether the previs mouths were trustworthy.
 */
type ReferenceBinding = {
  asset_id: string;
  semantic_role: string;
  recorded_on: string | null;
  media_type: string;
};

/**
 * The reference assets delivered to this scene-3d node, as the executor
 * published them (``scene3d_reference_bindings``). The previs renderer itself
 * has no input slot for a reference image, so without this the author has no
 * evidence that a bound upstream design node ever arrived — or that its asset
 * was attributed to a SceneScript element.
 */
function parseReferenceBindings(raw: unknown): ReferenceBinding[] | null {
  if (!Array.isArray(raw)) return null;
  const bindings: ReferenceBinding[] = [];
  for (const entry of raw) {
    if (!entry || typeof entry !== "object") continue;
    const binding = entry as Record<string, unknown>;
    const assetId = binding.asset_id;
    if (typeof assetId !== "string" || !assetId) continue;
    bindings.push({
      asset_id: assetId,
      semantic_role:
        typeof binding.semantic_role === "string" ? binding.semantic_role : "",
      recorded_on:
        typeof binding.recorded_on === "string" && binding.recorded_on
          ? binding.recorded_on
          : null,
      media_type: typeof binding.media_type === "string" ? binding.media_type : "",
    });
  }
  return bindings;
}

function parseAutoLipSync(raw: unknown): AutoLipSyncFacts | null {
  if (!raw || typeof raw !== "object") return null;
  const report = raw as Record<string, unknown>;
  const applied = report.applied;
  if (typeof applied !== "boolean") return null;
  const warnings = Array.isArray(report.warnings) ? report.warnings : [];
  return {
    applied,
    duration_source:
      typeof report.duration_source === "string" ? report.duration_source : "none",
    segment_count: typeof report.segment_count === "number" ? report.segment_count : 0,
    warnings: warnings.filter((entry): entry is string => typeof entry === "string"),
  };
}

/** Animatic provenance (V0.2 §14.9 成片侧). */
function parseAnimaticAudio(
  raw: unknown,
): { muxed: boolean; reason?: string | null } | null {
  if (!raw || typeof raw !== "object") return null;
  const report = raw as Record<string, unknown>;
  const muxed = report.muxed;
  if (typeof muxed !== "boolean") return null;
  const reason = report.reason;
  return { muxed, reason: typeof reason === "string" ? reason : null };
}

/** The node's SceneScript, when it already carries one. */
function parseSceneScript(node: CanvasNodeV2): SceneScriptRoot | null {
  const raw = node.structured_content?.[SCENE_SCRIPT_CONTENT_KEY];
  if (!raw || typeof raw !== "object") return null;
  const script = raw as Partial<SceneScriptRoot>;
  if (!script.scene || !Array.isArray(script.characters)) return null;
  return raw as SceneScriptRoot;
}

/** The persisted dialogue lines the editor seeds its panel from. */
function parseDialogueLines(raw: unknown): DialogueLineDraft[] {
  if (!Array.isArray(raw)) return [];
  const lines: DialogueLineDraft[] = [];
  for (const entry of raw) {
    if (!entry || typeof entry !== "object") continue;
    const line = entry as Record<string, unknown>;
    if (typeof line.text !== "string") continue;
    lines.push({
      character_id: typeof line.character_id === "string" ? line.character_id : "",
      text: line.text,
      start_time: typeof line.start_time === "number" ? line.start_time : null,
      emotion: typeof line.emotion === "string" ? line.emotion : null,
    });
  }
  return lines;
}

/** The applied speech segments, for the picker's speech-aware readings. */
function parseSpeechSegments(raw: unknown): AlignedSpeechSegment[] {
  if (!Array.isArray(raw)) return [];
  const segments: AlignedSpeechSegment[] = [];
  for (const entry of raw) {
    if (!entry || typeof entry !== "object") continue;
    const segment = entry as Record<string, unknown>;
    if (typeof segment.text !== "string") continue;
    segments.push({
      segment_id: typeof segment.segment_id === "string" ? segment.segment_id : undefined,
      character_id: typeof segment.character_id === "string" ? segment.character_id : "",
      text: segment.text,
      start_time: typeof segment.start_time === "number" ? segment.start_time : 0,
      end_time: typeof segment.end_time === "number" ? segment.end_time : 0,
    });
  }
  return segments;
}

/** Serialize the dialogue lines the editor hands back for persistence. */
function serializeDialogueLines(lines: DialogueLineDraft[]): Record<string, unknown> {
  return {
    [DIALOGUE_LINES_CONTENT_KEY]: lines.map((line) => ({
      character_id: line.character_id,
      text: line.text,
      start_time: line.start_time,
      emotion: line.emotion,
    })),
  };
}

/** The saved transition variants, as the editor's shape. */
function parseVariants(raw: unknown): TransitionVariant[] {
  if (!Array.isArray(raw)) return [];
  const variants: TransitionVariant[] = [];
  for (const entry of raw) {
    if (!entry || typeof entry !== "object") continue;
    const variant = entry as Record<string, unknown>;
    if (typeof variant.id !== "string" || typeof variant.label !== "string") continue;
    variants.push({
      id: variant.id,
      label: variant.label,
      proposal_id: typeof variant.proposal_id === "string" ? variant.proposal_id : null,
      scene_script:
        variant.scene_script && typeof variant.scene_script === "object"
          ? (variant.scene_script as Record<string, unknown>)
          : ({} as Record<string, unknown>),
    });
  }
  return variants;
}

/** Serialize the variants back for the node (whole-script snapshots). */
function serializeVariants(variants: TransitionVariant[]): Record<string, unknown> {
  return { [TRANSITION_VARIANTS_CONTENT_KEY]: variants };
}

function Scene3DEditSection({
  node,
  patchNode,
  characterAssets = [],
  propAssets = [],
  sceneAssets = [],
  autoLipSync = null,
  referenceBindings = null,
  alignedSpeechLines = null,
  speechAudioUrl = null,
  onSelectionChange,
}: {
  node: CanvasNodeV2;
  patchNode?: PatchNode;
  characterAssets?: CharacterAssetOption[];
  propAssets?: CharacterAssetOption[];
  sceneAssets?: CharacterAssetOption[];
  alignedSpeechLines?: readonly AlignedLine[] | null;
  speechAudioUrl?: string | null;
  onSelectionChange?: (ref: SceneObjectRef | null) => void;
  autoLipSync?: AutoLipSyncFacts | null;
  referenceBindings?: readonly ReferenceBinding[] | null;
}) {
  const persisted = useMemo(() => parseSceneScript(node), [node]);
  const [draftScript, setDraftScript] = useState<SceneScriptRoot | null>(() =>
    (node.workflow_id ? readScene3dDraft(node.workflow_id, node.node_id) : null) ?? persisted,
  );
  // D6: was the initial draft restored from a prior unsaved session? Drives the notice.
  const [restoredDraft, setRestoredDraft] = useState<boolean>(() => {
    if (!persisted || !node.workflow_id) return false;
    const stored = readScene3dDraft(node.workflow_id, node.node_id);
    return stored != null && JSON.stringify(stored) !== JSON.stringify(persisted);
  });
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // Re-sync from the node when its content changes upstream (rerun/replace),
  // unless there are unsaved local edits — never clobber the author's work.
  useEffect(() => {
    setDraftScript((current) =>
      current === persisted ||
      (current !== null && JSON.stringify(current) !== JSON.stringify(persisted))
        ? current
        : persisted,
    );
  }, [persisted]);

  // D6: mirror the unsaved draft to localStorage; clear it once it matches the saved
  // node (explicit save/revert) so a reload restores only real, unsaved edits.
  useEffect(() => {
    if (!node.workflow_id || !draftScript || !persisted) return;
    if (JSON.stringify(draftScript) === JSON.stringify(persisted)) {
      clearScene3dDraft(node.workflow_id, node.node_id);
    } else {
      writeScene3dDraft(node.workflow_id, node.node_id, draftScript);
    }
  }, [draftScript, persisted, node.workflow_id, node.node_id]);

  const draftDirty =
    draftScript !== null &&
    persisted !== null &&
    JSON.stringify(draftScript) !== JSON.stringify(persisted);

  // D6: guard navigation/refresh only while there are unsaved edits (repeatable, honest).
  useEffect(() => {
    if (!draftDirty) return;
    const onBeforeUnload = (event: BeforeUnloadEvent) => {
      event.preventDefault();
      event.returnValue = "";
    };
    window.addEventListener("beforeunload", onBeforeUnload);
    return () => window.removeEventListener("beforeunload", onBeforeUnload);
  }, [draftDirty]);

  // The "restored draft" notice clears itself once the edits are saved or reverted.
  useEffect(() => {
    if (!draftDirty) setRestoredDraft(false);
  }, [draftDirty]);

  const [fullscreen, setFullscreen] = useState(false);
  const [focusShotId, setFocusShotId] = useState<string | null>(null);
  const [speechSegments, setSpeechSegments] = useState<AlignedSpeechSegment[]>([]);
  const persistedLines = useMemo(
    () => parseDialogueLines(node.structured_content?.[DIALOGUE_LINES_CONTENT_KEY]),
    [node.structured_content],
  );
  const persistLines = useCallback(
    (lines: DialogueLineDraft[]) => {
      if (!patchNode) return;
      void Promise.resolve(
        patchNode(
          node.node_id,
          {
            structured_content: {
              ...node.structured_content,
              ...serializeDialogueLines(lines),
            },
          },
          { coalesce: true },
        ),
      ).catch((persistError) => setError(persistError instanceof Error ? persistError.message : "分句保存失败，请重试。"));
    },
    [node.node_id, node.structured_content, patchNode],
  );
  const variants = useMemo(
    () => parseVariants(node.structured_content?.[TRANSITION_VARIANTS_CONTENT_KEY]),
    [node.structured_content],
  );
  const takes = useMemo(
    () => parseDirectorTakes(node.structured_content?.[DIRECTOR_TAKES_CONTENT_KEY]),
    [node.structured_content],
  );
  const persistTakes = useCallback(
    (next: DirectorTake[]) => {
      if (!patchNode) return;
      void Promise.resolve(
        patchNode(
          node.node_id,
          {
            structured_content: {
              ...node.structured_content,
              [DIRECTOR_TAKES_CONTENT_KEY]: serializeDirectorTakes(next),
            },
          },
          { coalesce: true },
        ),
      ).catch((persistError) => setError(persistError instanceof Error ? persistError.message : "Take 保存失败，请重试。"));
    },
    [node.node_id, node.structured_content, patchNode],
  );
  const persistVariants = useCallback(
    (next: TransitionVariant[]) => {
      if (!patchNode) return;
      void Promise.resolve(
        patchNode(
          node.node_id,
          {
            structured_content: {
              ...node.structured_content,
              ...serializeVariants(next),
            },
          },
          { coalesce: true },
        ),
      ).catch((persistError) => setError(persistError instanceof Error ? persistError.message : "变体保存失败，请重试。"));
    },
    [node.node_id, node.structured_content, patchNode],
  );
  const whiteModel = node.structured_content?.white_model === true;
  const characterIds = useMemo(
    () => (draftScript?.characters ?? []).map((character) => character.id),
    [draftScript],
  );
  // The lip-sync panel seeds from the aligned lines when the workflow's
  // voice-cast bed produced them, and from the persisted per-line dialogue
  // otherwise — never from a re-estimate.
  const initialLines = useMemo(
    () =>
      !alignedSpeechLines || alignedSpeechLines.length === 0
        ? null
        : alignedSpeechLines.map((line) => ({
            character_id: line.character_id,
            text: line.text,
            start_time: line.start_time,
            emotion: null,
          })),
    [alignedSpeechLines],
  );
  // The viewport overlay can only speak what has a text AND a measured start
  // (an unaligned line would drift against the mouths).
  const composerSegments = useMemo(
    () =>
      persistedLines
        .filter((line) => line.text.trim() && line.start_time != null)
        .map((line) => ({
          character_id: line.character_id,
          text: line.text,
          start_time: line.start_time ?? 0,
        })),
    [persistedLines],
  );

  const toggleWhiteModel = useCallback(async () => {
    if (!patchNode) return;
    setSaving(true);
    setError(null);
    try {
      await patchNode(node.node_id, {
        structured_content: { ...node.structured_content, white_model: !whiteModel },
      });
    } catch (toggleError) {
      setError(
        toggleError instanceof Error
          ? toggleError.message
          : "切换白模模式失败，请重试。",
      );
    } finally {
      setSaving(false);
    }
  }, [node.node_id, node.structured_content, patchNode, whiteModel]);

  useEffect(() => {
    if (!fullscreen) return;
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") setFullscreen(false);
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [fullscreen]);

  if (!patchNode) return null;
  if (!persisted || !draftScript) {
    return (
      <p className="scene-3d-workbench__hint">
        运行节点生成 SceneScript 后，可在此进入 3D 编辑台放置镜头与调度人物。
      </p>
    );
  }

  const dirty = JSON.stringify(draftScript) !== JSON.stringify(persisted);
  const save = async () => {
    setSaving(true);
    setError(null);
    try {
      await patchNode(node.node_id, {
        structured_content: { ...node.structured_content, [SCENE_SCRIPT_CONTENT_KEY]: draftScript },
      });
    } catch (saveError) {
      setError(saveError instanceof Error ? saveError.message : "场景保存失败，请重试。");
    } finally {
      setSaving(false);
    }
  };

  const section = (
    <section
      className={fullscreen ? "scene-3d-workbench scene-3d-workbench--fullscreen" : "scene-3d-workbench"}
      aria-label="3D 编辑台"
      data-fullscreen={fullscreen ? "true" : undefined}
      data-testid={fullscreen ? "scene-3d-workbench-fullscreen" : undefined}
    >
      <SceneImageIntake
        disabled={saving}
        onSceneScriptGenerated={(script) => setDraftScript(script)}
      />
      <div className="scene-3d-workbench__mode">
        <label className="scene-3d-workbench__mode-toggle">
          <input
            type="checkbox"
            checked={whiteModel}
            disabled={saving}
            onChange={() => void toggleWhiteModel()}
          />
          白模设计模式
        </label>
        <span className="scene-3d-workbench__mode-hint">
          {whiteModel
            ? "开启中：运行节点时，描述经 agent 转为操作批次，通过校验闸门后应用；下方工具为手动编辑面。"
            : "开启后，运行节点按操作批次生成场景（agent 白模设计）。"}
        </span>
        <button
          type="button"
          className="scene-3d-workbench__fullscreen-toggle"
          onClick={() => setFullscreen((current) => !current)}
        >
          {fullscreen ? "⤡ 退出全屏" : "⤢ 全屏导演台"}
        </button>
      </div>
      <WhiteModelOpLog
        report={
          (node.structured_content?.white_model_report as Record<string, unknown> | undefined) ??
          null
        }
      />
      {/* E6: 3D 渲染入口（scene-3d render/async：提交→轮询进度→真取消） */}
      {draftScript && <Scene3DRenderControls sceneScript={draftScript} disabled={saving} />}
      {restoredDraft ? (
        <div className="scene-script-3d-editor__note" data-testid="scene3d-draft-restored">
          已恢复上次未保存的草稿；未保存前离开/刷新页面会再次提醒。
          <button type="button" onClick={() => setRestoredDraft(false)}>
            知道了
          </button>
        </div>
      ) : null}
      {draftScript && (
        <DialogueLipSyncPanel
          sceneScript={draftScript}
          characterIds={characterIds}
          initialLines={initialLines ?? undefined}
          persistedLines={persistedLines}
          onLinesPersist={persistLines}
          workflowId={node.workflow_id}
          sourceNodeId={node.node_id}
          onSceneScriptApplied={setDraftScript}
          onSegmentsApplied={(segments) => setSpeechSegments(segments)}
          onOpenTransitions={setFocusShotId}
          disabled={saving}
          key={alignedSpeechLines ? `aligned-${alignedSpeechLines.length}` : "unseeded"}
        />
      )}
      <Suspense fallback={<p className="scene-3d-workbench__hint">加载 3D 编辑台…</p>}>
        <SceneScript3DEditor
          sceneScript={draftScript}
          onChange={setDraftScript}
          onSave={() => void save()}
          onRevert={() => setDraftScript(persisted)}
          saving={saving}
          dirty={dirty}
          error={error}
          characterAssets={characterAssets}
          propAssets={propAssets}
          sceneAssets={sceneAssets}
          onSelectionChange={onSelectionChange}
          autoLipSync={parseAutoLipSync(node.structured_content?.auto_lip_sync)}
          referenceBindings={parseReferenceBindings(
            node.structured_content?.scene3d_reference_bindings,
          )}
          previewHeight={fullscreen ? 620 : 360}
          dialogueLines={composerSegments}
          speechAudioUrl={speechAudioUrl}
          variants={variants}
          onVariantsChange={persistVariants}
          animaticAudio={parseAnimaticAudio(node.structured_content?.animatic_audio)}
          wardrobeDrift={parseWardrobeDrift(node.structured_content?.scene3d_wardrobe_drift)}
          blockingContinuity={parseBlockingFindings(
            node.structured_content?.scene3d_blocking_continuity,
          )}
          transitionIntentNotes={parseTransitionIntentNotes(
            node.structured_content?.scene3d_transition_intent,
          )}
          consistency={parseConsistency(node.structured_content?.scene3d_consistency)}
          speechSegments={speechSegments}
          focusShotId={focusShotId}
          onFocusShotConsumed={() => setFocusShotId(null)}
          takes={takes}
          onSaveTake={(take) => persistTakes([...takes, take])}
          // E4: 多轮记忆接线（V0.2 §14.5）——补传 workflowId/nodeId 让提案
          // 面板的保留集可持久化；initialEngagedIds 让刷新后保留集恢复。
          // 缺这两个 id 时面板静默不持久化（见 TransitionProposalsPanel）。
          workflowId={node.workflow_id}
          nodeId={node.node_id}
          initialEngagedIds={parseRetainedReadingIds(
            node.structured_content?.retained_reading_ids,
          )}
        />
      </Suspense>
    </section>
  );

  return fullscreen ? createPortal(section, document.body) : section;
}

// The shapes the editor and its panels expect (imported as types so the
// bundle keeps them erased).
type CharacterAssetOption = {
  asset_id: string;
  display_name: string;
  preview_url?: string | null;
};

type DialogueLineDraft = {
  character_id: string;
  text: string;
  start_time: number | null;
  emotion: string | null;
};

type TransitionVariant = {
  id: string;
  label: string;
  proposal_id: string | null;
  scene_script: Record<string, unknown>;
};

type BlockingFinding = {
  code: string;
  severity: string;
  subject: string;
  boundary: string;
  message: string;
  remedy: string;
};

type TransitionIntentNote = {
  code: string;
  severity: string;
  shot_id: string;
  reading_id: string | null;
  message: string;
  remedy: string;
};

type ConsistencyFinding = {
  code: string;
  severity: string;
  subject: string;
  message: string;
  remedy: string;
};

type AutoLipSyncFacts = {
  applied: boolean;
  duration_source: string;
  segment_count: number;
  warnings: string[];
};

type DriftFinding = {
  code: string;
  subject: string;
  message: string;
  remedy: string;
};
