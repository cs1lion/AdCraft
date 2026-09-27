/**
 * SceneScript Panel - combines 3D preview with scene info display.
 *
 * Used as the content surface for scene-3d canvas nodes. Shows the
 * low-fidelity 3D preview alongside scene metadata (characters, cameras,
 * shots, duration).
 */

import { useState, useEffect, useCallback, lazy, Suspense } from "react";
import type { SceneScriptRoot } from "../../../types/scene-script";
import {
  SceneScriptPlaybackProvider,
  useSceneScriptPlayback,
} from "./SceneScriptPlaybackContext";
import { getTotalFrames, getActiveCameraId } from "../model/sceneScriptUtils";
import { ReferenceVideoPanel } from "./ReferenceVideoPanel";
import { useOptionalPlayheadSync } from "../PlayheadSyncContext";

// three.js is a ~1 MB dependency: keep it in an async chunk so the canvas
// bundle stays within the perf budget (vendor-three in vite.config.ts +
// check-build-budget.mjs).
const SceneScript3DPreview = lazy(() =>
  import("./SceneScript3DPreview").then((module) => ({ default: module.SceneScript3DPreview })),
);

interface SceneScriptPanelProps {
  sceneScript: SceneScriptRoot;
  narration?: string;
  narrationVoice?: string;
  height?: number;
  onPromptChange?: (prompt: PromptBundle | null) => void;
  /** 当前工作流：拉片复刻创建蓝图节点用。 */
  workflowId?: string | null;
}

type TabKey = "3d" | "info" | "prompt" | "reference" | "narration" | "json";

interface ShotPrompt {
  shot_id: string;
  camera: string;
  duration_seconds: number;
  prompt: string;
  negative_prompt: string;
  camera_description: string;
  characters: string[];
}

interface PromptBundle {
  success: boolean;
  reference_mode: string;
  global_prompt: string;
  global_negative_prompt: string;
  shots: ShotPrompt[];
  reference_instructions: string;
}

export function SceneScriptPanel({
  sceneScript,
  narration,
  narrationVoice = "default",
  height = 360,
  onPromptChange,
  workflowId = null,
}: SceneScriptPanelProps) {
  const [activeTab, setActiveTab] = useState<TabKey>("3d");

  const playheadSync = useOptionalPlayheadSync();
  const externalPlayhead =
    playheadSync && playheadSync.playhead.origin === "timeline"
      ? {
          time: playheadSync.playhead.time,
          playing: playheadSync.playhead.playing,
        }
      : null;

  const tabs: { key: TabKey; label: string }[] = [
    { key: "3d", label: "3D Preview" },
    { key: "info", label: "Scene Info" },
    { key: "prompt", label: "Prompt" },
    { key: "reference", label: "Reference" },
    { key: "narration", label: "Narration" },
    { key: "json", label: "JSON" },
  ];

  return (
    <SceneScriptPlaybackProvider
      sceneScript={sceneScript}
      externalPlayhead={externalPlayhead}
      onTimeChange={(time) => playheadSync?.setFromPreview({ time })}
      onPlayingChange={(playing) => playheadSync?.setFromPreview({ playing })}
    >
      <div
        style={{
          width: "100%",
          height,
          display: "flex",
          flexDirection: "column",
          background: "#1a1a2e",
          borderRadius: 4,
          overflow: "hidden",
        }}
      >
      {/* Tab bar */}
      <div
        style={{
          display: "flex",
          gap: 2,
          padding: "4px 6px",
          background: "#16162a",
          borderBottom: "1px solid #2a2a4a",
        }}
      >
        {tabs.map((tab) => (
          <button
            key={tab.key}
            onClick={() => setActiveTab(tab.key)}
            style={{
              padding: "3px 10px",
              border: "none",
              borderRadius: 3,
              background: activeTab === tab.key ? "#3a3a6a" : "transparent",
              color: activeTab === tab.key ? "#fff" : "#888",
              cursor: "pointer",
              fontSize: 11,
              fontFamily: "monospace",
            }}
          >
            {tab.label}
          </button>
        ))}
      </div>

      {/* Tab content */}
      <div style={{ flex: 1, overflow: "hidden", position: "relative" }}>
        {activeTab === "3d" && (
          <Suspense
            fallback={
              <div
                style={{
                  height: "100%",
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "center",
                  color: "#888",
                  fontSize: 12,
                  fontFamily: "monospace",
                }}
              >
                Loading 3D preview…
              </div>
            }
          >
            <SceneScript3DPreview sceneScript={sceneScript} height={height - 32} />
          </Suspense>
        )}

        {activeTab === "info" && (
          <SceneInfoContent sceneScript={sceneScript} />
        )}

        {activeTab === "prompt" && (
          <PromptEditorContent
            sceneScript={sceneScript}
            onPromptChange={onPromptChange}
          />
        )}

        {activeTab === "reference" && (
          <ReferenceVideoPanel height={height - 32} workflowId={workflowId} />
        )}

        {activeTab === "narration" && (
          <NarrationContent narration={narration} voice={narrationVoice} />
        )}

        {activeTab === "json" && (
          <pre
            style={{
              margin: 0,
              padding: 10,
              overflow: "auto",
              height: "100%",
              color: "#8f8",
              fontSize: 10,
              fontFamily: "monospace",
              whiteSpace: "pre-wrap",
              wordBreak: "break-all",
            }}
          >
            {JSON.stringify(sceneScript, null, 2)}
          </pre>
        )}
      </div>
      </div>
    </SceneScriptPlaybackProvider>
  );
}

// ---------------------------------------------------------------------------
// Prompt Editor tab content - editable video model prompts
// ---------------------------------------------------------------------------

function PromptEditorContent({
  sceneScript,
  onPromptChange,
}: {
  sceneScript: SceneScriptRoot;
  onPromptChange?: (prompt: PromptBundle | null) => void;
}) {
  const [bundle, setBundle] = useState<PromptBundle | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [edited, setEdited] = useState(false);

  const fetchPrompt = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const response = await fetch("/api/v1/scene-3d/prompt", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          scene_script: sceneScript,
          model_supports_reference_video: true,
          model_supports_reference_images: true,
        }),
      });
      if (!response.ok) {
        throw new Error(`HTTP ${response.status}`);
      }
      const data = await response.json();
      setBundle(data);
      setEdited(false);
      onPromptChange?.(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to fetch prompt");
    } finally {
      setLoading(false);
    }
  }, [sceneScript, onPromptChange]);

  useEffect(() => {
    fetchPrompt();
  }, [fetchPrompt]);

  const updateGlobalPrompt = (value: string) => {
    if (!bundle) return;
    setBundle({ ...bundle, global_prompt: value });
    setEdited(true);
  };

  const updateNegativePrompt = (value: string) => {
    if (!bundle) return;
    setBundle({ ...bundle, global_negative_prompt: value });
    setEdited(true);
  };

  const updateShotPrompt = (index: number, value: string) => {
    if (!bundle) return;
    const shots = [...bundle.shots];
    shots[index] = { ...shots[index], prompt: value };
    setBundle({ ...bundle, shots });
    setEdited(true);
  };

  const handleSave = () => {
    onPromptChange?.(bundle);
    setEdited(false);
  };

  if (loading) {
    return (
      <div style={{ padding: 20, color: "#888", fontSize: 12, fontFamily: "monospace" }}>
        Generating video model prompts...
      </div>
    );
  }

  if (error) {
    return (
      <div style={{ padding: 20, color: "#f88", fontSize: 12, fontFamily: "monospace" }}>
        Error: {error}
        <button
          onClick={fetchPrompt}
          style={{
            display: "block",
            marginTop: 10,
            background: "#3a3a6a",
            border: "none",
            color: "#fff",
            padding: "4px 12px",
            borderRadius: 3,
            cursor: "pointer",
            fontSize: 11,
          }}
        >
          Retry
        </button>
      </div>
    );
  }

  if (!bundle) return null;

  return (
    <div
      style={{
        padding: 10,
        overflow: "auto",
        height: "100%",
        color: "#ccc",
        fontSize: 11,
        fontFamily: "monospace",
      }}
    >
      {/* Header bar */}
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
          marginBottom: 8,
          paddingBottom: 6,
          borderBottom: "1px solid #2a2a4a",
        }}
      >
        <span style={{ color: "#888" }}>
          Reference mode: <span style={{ color: "#4f4" }}>{bundle.reference_mode}</span>
        </span>
        <div style={{ display: "flex", gap: 6 }}>
          <button
            onClick={fetchPrompt}
            style={{
              background: "#2a2a4a",
              border: "none",
              color: "#aaa",
              padding: "3px 8px",
              borderRadius: 3,
              cursor: "pointer",
              fontSize: 10,
            }}
          >
            ↻ Regenerate
          </button>
          <button
            onClick={handleSave}
            disabled={!edited}
            style={{
              background: edited ? "#4a6a3a" : "#2a2a4a",
              border: "none",
              color: edited ? "#fff" : "#666",
              padding: "3px 8px",
              borderRadius: 3,
              cursor: edited ? "pointer" : "default",
              fontSize: 10,
            }}
          >
            {edited ? "✓ Save" : "Saved"}
          </button>
        </div>
      </div>

      {/* Global prompt */}
      <div style={{ marginBottom: 10 }}>
        <div style={{ color: "#888", marginBottom: 3, fontSize: 10 }}>GLOBAL PROMPT</div>
        <textarea
          value={bundle.global_prompt}
          onChange={(e) => updateGlobalPrompt(e.target.value)}
          style={{
            width: "100%",
            minHeight: 60,
            background: "#16162a",
            border: "1px solid #2a2a4a",
            borderRadius: 3,
            color: "#cfc",
            padding: 6,
            fontSize: 10,
            fontFamily: "monospace",
            resize: "vertical",
            boxSizing: "border-box",
          }}
        />
      </div>

      {/* Negative prompt */}
      <div style={{ marginBottom: 10 }}>
        <div style={{ color: "#888", marginBottom: 3, fontSize: 10 }}>NEGATIVE PROMPT</div>
        <textarea
          value={bundle.global_negative_prompt}
          onChange={(e) => updateNegativePrompt(e.target.value)}
          style={{
            width: "100%",
            minHeight: 40,
            background: "#16162a",
            border: "1px solid #2a2a4a",
            borderRadius: 3,
            color: "#fcc",
            padding: 6,
            fontSize: 10,
            fontFamily: "monospace",
            resize: "vertical",
            boxSizing: "border-box",
          }}
        />
      </div>

      {/* Per-shot prompts */}
      <div style={{ color: "#888", marginBottom: 6, fontSize: 10 }}>
        PER-SHOT PROMPTS ({bundle.shots.length} shots)
      </div>
      {bundle.shots.map((shot, idx) => (
        <div key={shot.shot_id} style={{ marginBottom: 8 }}>
          <div
            style={{
              display: "flex",
              justifyContent: "space-between",
              color: "#aaf",
              marginBottom: 3,
              fontSize: 10,
            }}
          >
            <span>
              [{idx + 1}] {shot.shot_id} ({shot.camera}, {shot.duration_seconds}s)
            </span>
            <span style={{ color: "#666" }}>{shot.camera_description}</span>
          </div>
          <textarea
            value={shot.prompt}
            onChange={(e) => updateShotPrompt(idx, e.target.value)}
            style={{
              width: "100%",
              minHeight: 50,
              background: "#16162a",
              border: "1px solid #2a2a4a",
              borderRadius: 3,
              color: "#cfc",
              padding: 6,
              fontSize: 10,
              fontFamily: "monospace",
              resize: "vertical",
              boxSizing: "border-box",
            }}
          />
        </div>
      ))}

      {/* Reference instructions */}
      {bundle.reference_instructions && (
        <div style={{ marginTop: 10 }}>
          <div style={{ color: "#888", marginBottom: 3, fontSize: 10 }}>
            REFERENCE INSTRUCTIONS
          </div>
          <div
            style={{
              background: "#16162a",
              border: "1px solid #2a2a4a",
              borderRadius: 3,
              padding: 6,
              color: "#aaf",
              fontSize: 10,
              whiteSpace: "pre-wrap",
            }}
          >
            {bundle.reference_instructions}
          </div>
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Info tab content (uses shared playback context)
// ---------------------------------------------------------------------------

function SceneInfoContent({ sceneScript }: { sceneScript: SceneScriptRoot }) {
  const { currentFrame, currentTime, isPlaying, totalFrames, toggle, seekToFrame, reset } =
    useSceneScriptPlayback();
  const activeCameraId = getActiveCameraId(sceneScript, currentFrame);

  return (
    <div
      style={{
        padding: 10,
        overflow: "auto",
        height: "100%",
        color: "#ccc",
        fontSize: 11,
        fontFamily: "monospace",
      }}
    >
      {/* Playback status bar */}
      <div
        style={{
          background: "#16162a",
          border: "1px solid #2a2a4a",
          borderRadius: 4,
          padding: "6px 8px",
          marginBottom: 8,
        }}
      >
        <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 4 }}>
          <span style={{ color: "#888" }}>Playback:</span>
          <span style={{ color: isPlaying ? "#4f4" : "#ff4" }}>
            {isPlaying ? "▶ Playing" : "⏸ Paused"}
          </span>
        </div>
        <InfoRow label="Frame" value={`${currentFrame} / ${totalFrames}`} />
        <InfoRow label="Time" value={`${currentTime.toFixed(2)}s`} />
        <InfoRow label="Active Camera" value={activeCameraId || "—"} />
        <div style={{ display: "flex", gap: 6, marginTop: 6 }}>
          <button
            onClick={toggle}
            style={{
              flex: 1,
              background: "#3a3a6a",
              border: "none",
              color: "#fff",
              padding: "3px 8px",
              borderRadius: 3,
              cursor: "pointer",
              fontSize: 11,
            }}
          >
            {isPlaying ? "⏸ Pause" : "▶ Play"}
          </button>
          <button
            onClick={reset}
            style={{
              background: "#3a3a6a",
              border: "none",
              color: "#fff",
              padding: "3px 8px",
              borderRadius: 3,
              cursor: "pointer",
              fontSize: 11,
            }}
          >
            ⏮ Reset
          </button>
        </div>
        <input
          type="range"
          min={0}
          max={Math.max(0, totalFrames - 1)}
          value={currentFrame}
          onChange={(e) => seekToFrame(Number(e.target.value))}
          style={{ width: "100%", marginTop: 6 }}
        />
      </div>

      <InfoRow label="Scene" value={sceneScript.scene.name} />
      <InfoRow label="Environment" value={sceneScript.scene.environment} />
      <InfoRow label="Lighting" value={sceneScript.scene.lighting} />
      <InfoRow label="Duration" value={`${sceneScript.scene.duration}s`} />
      <InfoRow label="Frame Rate" value={`${sceneScript.scene.frame_rate} fps`} />
      <InfoRow label="Total Frames" value={String(totalFrames)} />
      <InfoRow label="Characters" value={String(sceneScript.characters.length)} />
      <InfoRow label="Props" value={String(sceneScript.props.length)} />
      <InfoRow label="Cameras" value={String(sceneScript.cameras.length)} />
      <InfoRow label="Shots" value={String(sceneScript.shots.length)} />
    </div>
  );
}

function InfoRow({ label, value }: { label: string; value: string }) {
  return (
    <div style={{ display: "flex", justifyContent: "space-between", padding: "1px 0" }}>
      <span style={{ color: "#888" }}>{label}:</span>
      <span style={{ color: "#fff" }}>{value}</span>
    </div>
  );
}


// ---------------------------------------------------------------------------
// Narration tab content
// ---------------------------------------------------------------------------

function NarrationContent({ narration, voice }: { narration?: string; voice: string }) {
  return (
    <div
      style={{
        padding: 12,
        height: "100%",
        overflow: "auto",
        color: "#ccc",
        fontSize: 12,
        fontFamily: "monospace",
      }}
    >
      <div style={{ marginBottom: 8, color: "#888", fontSize: 10 }}>
        VOICE: {voice}
      </div>
      {narration && narration.trim() ? (
        <div
          style={{
            whiteSpace: "pre-wrap",
            wordBreak: "break-word",
            lineHeight: 1.6,
            color: "#a8d8a8",
          }}
        >
          {narration}
        </div>
      ) : (
        <div style={{ color: "#666", fontStyle: "italic", marginTop: 20 }}>
          No narration set.
          <br />
          <br />
          Add narration text in the node&apos;s structured_content[&quot;narration&quot;] field,
          or describe the voiceover in chat when generating the scene.
          <br />
          <br />
          On run, narration will be synthesized via TTS and muxed into the video.
        </div>
      )}
    </div>
  );
}
