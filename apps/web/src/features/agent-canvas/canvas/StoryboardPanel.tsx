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

import { useCallback, useEffect, useMemo, useState } from "react";

import type { SceneScriptRoot } from "../../../types/scene-script";
import type { PublishedPrevisClipEntryV2 } from "../../../types-v2.ts";
import { createOperationKey } from "../../../api/operationKey.ts";
import { agentCanvasApi } from "../../../api/agentCanvasApi.ts";

import {
  exportStoryboard,
  fetchContinuitySuggestions,
  type ContinuitySuggestion,
  type StoryboardFinding,
  type StoryboardShotEntry,
} from "./directorOperationsClient.ts";

export interface StoryboardPanelProps {
  sceneScript: SceneScriptRoot;
  /** Bumped by the parent when the script changes so the panel refetches. */
  refreshKey?: number;
  /** Seek the 3D preview to a frame (wired to playback.seekToFrame). */
  onSeekFrame?: (frame: number) => void;
  disabled?: boolean;
  /** ADR 0017: present without these two ids hides the publish action. */
  workflowId?: string | null;
  nodeId?: string | null;
  /** Reverse lineage from the scene-3d node content (published_previs_clips). */
  publishedClips?: readonly PublishedPrevisClipEntryV2[];
  /** Called after a successful publish so the canvas can refresh lineage. */
  onPublished?: () => void;
}

type PanelTab = "storyboard" | "continuity";

export function StoryboardPanel({
  sceneScript,
  refreshKey = 0,
  onSeekFrame,
  disabled,
  workflowId = null,
  nodeId = null,
  publishedClips = [],
  onPublished,
}: StoryboardPanelProps) {
  const [tab, setTab] = useState<PanelTab>("storyboard");
  const [shots, setShots] = useState<StoryboardShotEntry[]>([]);
  const [sceneName, setSceneName] = useState("");
  // E3: 分镜 advisory findings（空隙/短镜/空分镜）——后端算了就必须显示
  const [findings, setFindings] = useState<StoryboardFinding[]>([]);
  const [storyboardError, setStoryboardError] = useState<string | null>(null);
  const [storyboardLoading, setStoryboardLoading] = useState(false);

  // ADR 0017: per-shot publish state. Optimistic: the row flips to 已发布
  // immediately on success (from the authoritative API response), and the
  // canvas refresh lands the node via SSE — the two merge by node_id.
  const [publishingShotId, setPublishingShotId] = useState<string | null>(null);
  const [publishError, setPublishError] = useState<{ shotId: string; message: string } | null>(
    null,
  );
  const [localPublishedClips, setLocalPublishedClips] = useState<PublishedPrevisClipEntryV2[]>(
    [],
  );

  const publishedClipsAll = useMemo(() => {
    const seen = new Set(publishedClips.map((clip) => clip.node_id));
    return [...publishedClips, ...localPublishedClips.filter((clip) => !seen.has(clip.node_id))];
  }, [publishedClips, localPublishedClips]);

  const publishShot = useCallback(
    async (shotId: string) => {
      if (!workflowId || !nodeId || publishingShotId) return;
      setPublishingShotId(shotId);
      setPublishError(null);
      try {
        const result = await agentCanvasApi.publishPrevisClip(
          workflowId,
          nodeId,
          { shot_id: shotId },
          createOperationKey("previs-clip"),
        );
        setLocalPublishedClips((current) => [
          ...current,
          {
            node_id: result.node.node_id,
            shot_id: shotId,
            clip_asset_id: result.clip_asset.asset_id,
            take_id: null,
          },
        ]);
        onPublished?.();
      } catch (error) {
        setPublishError({
          shotId,
          message: error instanceof Error ? error.message : String(error),
        });
      } finally {
        setPublishingShotId(null);
      }
    },
    [workflowId, nodeId, publishingShotId, onPublished],
  );

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
          setFindings(result.findings ?? []);
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
          {/* E3: advisory findings——空隙/短镜/空分镜逐条可见（不阻断出分镜） */}
          {!storyboardLoading && !storyboardError && findings.length > 0 && (
            <div
              className="scene-script-3d-editor__storyboard-findings"
              data-testid="scene-script-3d-storyboard-findings"
              role="status"
            >
              <div className="scene-script-3d-editor__storyboard-findings-title">
                ⚠ 分镜检查发现 {findings.length} 处（参考，不阻断出分镜）：
              </div>
              <ul>
                {findings.map((finding, index) => (
                  <li key={`${finding.code}_${finding.subject}_${index}`}>
                    <span className="scene-script-3d-editor__storyboard-finding-subject">
                      {finding.subject}
                    </span>
                    ：{finding.message}
                  </li>
                ))}
              </ul>
            </div>
          )}
          {!storyboardLoading && !storyboardError && shots.length > 0 && (
            <ul className="scene-script-3d-editor__storyboard-list" aria-label="分镜列表">
              {shots.map((shot, index) => {
                const published = publishedClipsAll.some((clip) => clip.shot_id === shot.shot_id);
                return (
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
                  {workflowId && nodeId && (
                    published ? (
                      <span
                        className="scene-script-3d-editor__storyboard-published"
                        data-testid={`scene-script-3d-storyboard-published-${index}`}
                        title="该镜头的预演参考片段已在画布上"
                      >
                        ✓ 已发布
                      </span>
                    ) : (
                      <button
                        type="button"
                        className="scene-script-3d-editor__storyboard-seek"
                        onClick={() => void publishShot(shot.shot_id)}
                        disabled={disabled || publishingShotId !== null}
                        title="把该镜头从 animatic 裁切成预演参考片段并发布到画布（ADR 0017）"
                        data-testid={`scene-script-3d-storyboard-publish-${index}`}
                      >
                        {publishingShotId === shot.shot_id ? "发布中…" : "发布预演片段"}
                      </button>
                    )
                  )}
                  {publishError?.shotId === shot.shot_id && (
                    <span className="scene-script-3d-editor__error" data-testid={`scene-script-3d-storyboard-publish-error-${index}`}>
                      {publishError.message}
                    </span>
                  )}
                </li>
                );
              })}
            </ul>
          )}
          {publishedClipsAll.length > 0 && (
            <div
              className="scene-script-3d-editor__storyboard-findings"
              data-testid="scene-script-3d-published-clips"
              role="status"
            >
              <div className="scene-script-3d-editor__storyboard-findings-title">
                🎬 已发布预演片段（{publishedClips.length}）— 在画布上与分镜片段连线即成为生成参考：
              </div>
              <ul>
                {publishedClipsAll.map((clip, index) => (
                  <li key={`${clip.node_id}-${index}`}>
                    <span className="scene-script-3d-editor__storyboard-shot-id">{clip.shot_id}</span>
                    ：片段节点 {clip.node_id}
                  </li>
                ))}
              </ul>
            </div>
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
