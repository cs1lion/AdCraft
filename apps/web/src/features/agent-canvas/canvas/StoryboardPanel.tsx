/**
 * Storyboard + continuity suggestions panel for the 3D editor.
 *
 * Two V3 capabilities wired to the existing endpoints:
 * 1. "出分镜" — POST /scene-3d/storyboard, renders a compact shot list
 *    (shot id, type, frame range, duration, keyframe frames) with a
 *    "seek to frame" button on each row so the director can walk through
 *    the strip in the 3D preview.
 * 2. Continuity suggestions — POST /scene-3d/continuity-suggestions,
 *    renders conversational hints ("转身方向跨镜反了，是故意的吗？") in
 *    the same advisory family as the existing consistency list, but in
 *    the creator's language.
 *
 * The panel is self-contained: it fetches on mount and on every
 * `refreshKey` change (the parent bumps it when the script changes),
 * and renders results inline. No new state machine; the 3D preview
 * stays the source of truth for the picture.
 */

import { useCallback, useEffect, useState } from "react";

import type { SceneScriptRoot } from "../../../types/scene-script";

import {
  exportStoryboard,
  fetchContinuitySuggestions,
  type ContinuitySuggestion,
  type StoryboardShotEntry,
} from "./directorOperationsClient.ts";

export interface StoryboardPanelProps {
  sceneScript: SceneScriptRoot;
  /** Bumped by the parent when the script changes so the panel refetches. */
  refreshKey?: number;
  /** Seek the 3D preview to a frame (wired to playback.seekToFrame). */
  onSeekFrame?: (frame: number) => void;
  disabled?: boolean;
}

type PanelTab = "storyboard" | "continuity";

export function StoryboardPanel({
  sceneScript,
  refreshKey = 0,
  onSeekFrame,
  disabled,
}: StoryboardPanelProps) {
  const [tab, setTab] = useState<PanelTab>("storyboard");
  const [shots, setShots] = useState<StoryboardShotEntry[]>([]);
  const [sceneName, setSceneName] = useState("");
  const [storyboardError, setStoryboardError] = useState<string | null>(null);
  const [storyboardLoading, setStoryboardLoading] = useState(false);

  const [suggestions, setSuggestions] = useState<ContinuitySuggestion[]>([]);
  const [untranslated, setUntranslated] = useState<{ code: string; detail: string }[]>([]);
  const [continuityError, setContinuityError] = useState<string | null>(null);
  const [continuityLoading, setContinuityLoading] = useState(false);

  // Fetch the storyboard when the tab is active and the refresh key changes.
  const loadStoryboard = useCallback(
    async () => {
      setStoryboardLoading(true);
      setStoryboardError(null);
      try {
        const result = await exportStoryboard(sceneScript);
        if (result.ok && result.shots) {
          setShots(result.shots);
          setSceneName(result.sceneName ?? "");
        } else {
          setStoryboardError(result.error ?? "storyboard export failed");
        }
      } catch (error) {
        setStoryboardError(error instanceof Error ? error.message : String(error));
      } finally {
        setStoryboardLoading(false);
      }
    },
    [sceneScript],
  );

  const loadContinuity = useCallback(
    async () => {
      setContinuityLoading(true);
      setContinuityError(null);
      try {
        const result = await fetchContinuitySuggestions(sceneScript, null);
        if (result.ok) {
          setSuggestions(result.suggestions ?? []);
          setUntranslated(result.untranslated ?? []);
        } else {
          setContinuityError(result.error ?? "continuity check failed");
        }
      } catch (error) {
        setContinuityError(error instanceof Error ? error.message : String(error));
      } finally {
        setContinuityLoading(false);
      }
    },
    [sceneScript],
  );

  useEffect(() => {
    if (tab === "storyboard") void loadStoryboard();
    else void loadContinuity();
  }, [tab, refreshKey, loadStoryboard, loadContinuity]);

  const seekToFrame = (frame: number) => {
    onSeekFrame?.(frame);
  };

  const suggestionIcon = (kind: string) => {
    if (kind === "question") return "❓";
    if (kind === "note") return "⚠";
    return "🔧";
  };

  return (
    <div className="scene-script-3d-editor__storyboard" data-testid="scene-script-3d-storyboard-panel">
      <div className="scene-script-3d-editor__storyboard-tabs">
        <button
          type="button"
          className={tab === "storyboard" ? "is-active" : undefined}
          onClick={() => setTab("storyboard")}
          disabled={disabled}
          data-testid="scene-script-3d-storyboard-tab"
        >
          分镜
        </button>
        <button
          type="button"
          className={tab === "continuity" ? "is-active" : undefined}
          onClick={() => setTab("continuity")}
          disabled={disabled}
          data-testid="scene-script-3d-continuity-tab"
        >
          连续性
        </button>
      </div>

      {tab === "storyboard" ? (
        <>
          {storyboardLoading && <p className="scene-script-3d-editor__note" data-testid="scene-script-3d-storyboard-loading">正在生成分镜…</p>}
          {storyboardError && (
            <p className="scene-script-3d-editor__error" data-testid="scene-script-3d-storyboard-error">
              {storyboardError}
            </p>
          )}
          {!storyboardLoading && !storyboardError && shots.length === 0 && (
            <p className="scene-script-3d-editor__note" data-testid="scene-script-3d-storyboard-empty">
              当前场景没有镜头，先添加镜头再出分镜。
            </p>
          )}
          {!storyboardLoading && !storyboardError && shots.length > 0 && (
            <ul className="scene-script-3d-editor__storyboard-list" aria-label="分镜列表">
              {shots.map((shot, index) => (
                <li
                  key={shot.shot_id}
                  className="scene-script-3d-editor__storyboard-row"
                  data-testid={`scene-script-3d-storyboard-shot-${index}`}
                >
                  <span className="scene-script-3d-editor__storyboard-shot-id">{shot.shot_id}</span>
                  <span className="scene-script-3d-editor__storyboard-shot-type">{shot.shot_type}</span>
                  <span className="scene-script-3d-editor__storyboard-shot-frames">
                    {shot.start_frame}–{shot.end_frame}（{shot.duration_frames}f）
                  </span>
                  {shot.description && (
                    <span className="scene-script-3d-editor__storyboard-shot-desc">{shot.description}</span>
                  )}
                  <button
                    type="button"
                    className="scene-script-3d-editor__storyboard-seek"
                    onClick={() => seekToFrame(shot.keyframe_frames[0] ?? shot.start_frame)}
                    disabled={!onSeekFrame}
                    title="跳到该镜头第一个代表帧"
                    data-testid={`scene-script-3d-storyboard-seek-${index}`}
                  >
                    查看
                  </button>
                </li>
              ))}
            </ul>
          )}
        </>
      ) : (
        <>
          {continuityLoading && <p className="scene-script-3d-editor__note" data-testid="scene-script-3d-continuity-loading">正在检查连续性…</p>}
          {continuityError && (
            <p className="scene-script-3d-editor__error" data-testid="scene-script-3d-continuity-error">
              {continuityError}
            </p>
          )}
          {!continuityLoading && !continuityError && suggestions.length === 0 && untranslated.length === 0 && (
            <p className="scene-script-3d-editor__note" data-testid="scene-script-3d-continuity-clean">
              ✓ 连续性检查通过，没有发现跨镜冲突。
            </p>
          )}
          {!continuityLoading && !continuityError && (suggestions.length > 0 || untranslated.length > 0) && (
            <ul className="scene-script-3d-editor__storyboard-list" aria-label="连续性建议">
              {suggestions.map((suggestion, index) => (
                <li
                  key={`suggestion-${index}`}
                  className="scene-script-3d-editor__storyboard-row"
                  data-testid={`scene-script-3d-continuity-suggestion-${index}`}
                >
                  <span aria-hidden="true">{suggestionIcon(suggestion.kind)}</span>
                  <span>{suggestion.message}</span>
                  {suggestion.remedy && (
                    <span className="scene-script-3d-editor__drift-remedy">{suggestion.remedy}</span>
                  )}
                </li>
              ))}
              {untranslated.map((entry, index) => (
                <li
                  key={`untranslated-${index}`}
                  className="scene-script-3d-editor__storyboard-row"
                  data-testid={`scene-script-3d-continuity-untranslated-${index}`}
                >
                  <span aria-hidden="true">⚠</span>
                  <span>{entry.detail}</span>
                  <span className="scene-script-3d-editor__drift-remedy">
                    （检查器发现 code={entry.code}，建议器尚未收录）
                  </span>
                </li>
              ))}
            </ul>
          )}
        </>
      )}
    </div>
  );
}
