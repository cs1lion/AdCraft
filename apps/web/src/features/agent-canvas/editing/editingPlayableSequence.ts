import type { EditingVideoEntryV2 } from "../../../types-v2.ts";
import { buildTimelineSegments, type TimelineSegment } from "./editingTimelineMath.ts";
import type { EditingBoundInput } from "./editingModel.ts";

type EditingVideoInput = EditingBoundInput<EditingVideoEntryV2>;

export interface PlayableEditingSequence {
  videos: EditingVideoInput[];
  inactiveVideos: EditingVideoInput[];
  segments: TimelineSegment[];
  /** 时间线尺长度：导入源总长（或后端固定时长）——重启用禁用 clip 时尺不跳。 */
  duration: number;
  /**
   * 可播放长度：可播放片段裁切窗的汇总末端。与 duration 是两个口径——
   * 尺可以比内容长（禁用/未就绪的源不播放但不从尺上消失），播放/钳位/
   * BGM 只认这一段（否则 BGM 会在没有画面的舞台上播放，播放头钳不到真实末端）。
   */
  playableDuration: number;
}

export function isBackendReadyEditingVideo(input: EditingVideoInput): boolean {
  return input.entry.enabled
    && input.asset?.status === "ready"
    && (input.node === null || input.node.status === "ready");
}

export function isPlayableEditingVideo(input: EditingVideoInput): boolean {
  return isBackendReadyEditingVideo(input) && Boolean(input.asset?.media_url);
}

export function buildPlayableEditingSequence(
  inputs: readonly EditingVideoInput[],
  fixedTimelineDuration?: number,
): PlayableEditingSequence {
  const videos = inputs.filter(isPlayableEditingVideo);
  const sourceDurations = inputs.map((input) => (
    input.asset?.duration_seconds
      ?? input.entry.trim_end_seconds
      ?? input.entry.trim_start_seconds + 0.5
  ));
  const timelineDuration = Math.max(
    0,
    fixedTimelineDuration ?? sourceDurations.reduce((total, duration) => total + duration, 0),
  );
  const segments = buildTimelineSegments(videos.map((input) => ({
    referenceId: input.referenceId,
    sourceDuration: input.asset?.duration_seconds
      ?? input.entry.trim_end_seconds
      ?? input.entry.trim_start_seconds + 0.5,
    trimStart: input.entry.trim_start_seconds,
    trimEnd: input.entry.trim_end_seconds,
    timelineStart: input.entry.timeline_start_seconds,
  })), timelineDuration);
  const videosByReferenceId = new Map(videos.map((input) => [input.referenceId, input]));
  return {
    videos: segments.flatMap((segment) => {
      const input = videosByReferenceId.get(segment.referenceId);
      return input ? [input] : [];
    }),
    inactiveVideos: inputs.filter((input) => !isPlayableEditingVideo(input)),
    segments,
    duration: timelineDuration,
    playableDuration: segments.reduce(
      (total, segment) => Math.max(total, segment.timelineEnd),
      0,
    ),
  };
}
