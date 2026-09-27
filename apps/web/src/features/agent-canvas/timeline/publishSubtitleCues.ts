/**
 * Publish dialogue-driven subtitle cues to the timeline's subtitle track
 * (ADR 0007 + ADR 0008: the timeline is the single assembly surface).
 *
 * The cues come from the lip-sync service's per-segment timings — the same
 * boundaries the mouths animate on — so publishing is a mechanical write.
 * Failures are per cue and coded; nothing is silently dropped.
 *
 * Idempotence: the published clips carry the scene node's id as their
 * ``source_node_id``, so a second publish REPLACES this node's earlier cues
 * instead of stacking duplicates (an alignment re-run would otherwise double
 * every caption). Clips the author moved or trimmed by hand are replaced too
 * — that is the point of a republish, and the result message says how many
 * were replaced.
 */

import { createClip, deleteClip, getTimeline, listTracks } from "./timelineApi.ts";
import type { SubtitleCueRequest } from "./dialogueSubtitleCues.ts";

export interface SubtitlePublishResult {
  created: number;
  /** Cues removed before writing (this node's previous publish). */
  replaced: number;
  failed: { index: number; message: string }[];
}

export class SubtitleTrackMissingError extends Error {
  readonly code = "subtitle_track_missing";

  constructor() {
    super("该工作流的时间线上没有字幕轨。");
    this.name = "SubtitleTrackMissingError";
  }
}

/**
 * Remove the subtitle-track clips this scene node published before.
 *
 * Without a source trace the second publish stacks duplicates; without the
 * delete-first step the timeline drifts from the alignment it claims to ride.
 */
async function replacePreviousCues(
  workflowId: string,
  subtitleTrackId: string,
  sourceNodeId: string,
): Promise<number> {
  let timeline;
  try {
    timeline = await getTimeline(workflowId);
  } catch {
    // An unreadable timeline must not block the publish: the new cues are
    // still correct, and a stale duplicate is visible to the author (and
    // removable by hand) rather than silently lost.
    return 0;
  }
  const previous = timeline.tracks
    .find((track) => track.track_id === subtitleTrackId)
    ?.clips.filter((clip) => clip.source_node_id === sourceNodeId);
  if (!previous || previous.length === 0) return 0;
  let removed = 0;
  for (const clip of previous) {
    try {
      await deleteClip(workflowId, clip.clip_id);
      removed += 1;
    } catch {
      // Keep going: a partially-cleared track still gets the fresh cues.
    }
  }
  return removed;
}

/**
 * Replace this node's subtitle cues with the given set, in order. Partial
 * failure is a result, not an exception: earlier cues may land and a later
 * one reject.
 */
export async function publishSubtitleCues(
  workflowId: string,
  cues: readonly SubtitleCueRequest[],
  options: { sourceNodeId?: string | null } = {},
): Promise<SubtitlePublishResult> {
  const tracks = await listTracks(workflowId);
  const subtitleTrack = tracks.find((track) => track.type === "subtitle");
  if (!subtitleTrack) throw new SubtitleTrackMissingError();

  const replaced =
    options.sourceNodeId != null
      ? await replacePreviousCues(workflowId, subtitleTrack.track_id, options.sourceNodeId)
      : 0;

  const failed: { index: number; message: string }[] = [];
  let created = 0;
  for (const [index, cue] of cues.entries()) {
    try {
      await createClip(workflowId, {
        track_id: subtitleTrack.track_id,
        start_time: cue.start_time,
        duration: cue.duration,
        subtitle_text: cue.subtitle_text,
        label: cue.label,
        // Trace the publish back to the scene node that owns the dialogue:
        // this is what makes the next publish a replace, not a duplicate.
        source_node_id: options.sourceNodeId ?? null,
      });
      created += 1;
    } catch (error) {
      failed.push({
        index,
        message: error instanceof Error ? error.message : String(error),
      });
    }
  }
  return { created, replaced, failed };
}
