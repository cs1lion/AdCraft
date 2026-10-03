import { StrictMode } from "react";
import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { GlobalTimelinePanel } from "./GlobalTimelinePanel.tsx";
import { TIMELINE_DROP_MIME } from "./timelineDropPayload.ts";
import {
  PlayheadSyncProvider,
  usePlayheadSync,
} from "../PlayheadSyncContext.tsx";
import type {
  TimelineClipV1,
  TimelineDuckingConfigV1,
  TimelineTrackV1,
  TimelineV1,
} from "./timelineTypes.ts";
import {
  createClip,
  deleteClip,
  getClipBeats,
  getMediaToolchainCapabilities,
  getTimeline,
  listLatestAudioDegradations,
  moveClip,
  updateClip,
  updateTimeline,
  updateTrack,
} from "./timelineApi.ts";

vi.mock("./timelineApi.ts", () => ({
  getTimeline: vi.fn(),
  updateTimeline: vi.fn(),
  updateTrack: vi.fn(),
  createClip: vi.fn(),
  updateClip: vi.fn(),
  moveClip: vi.fn(),
  deleteClip: vi.fn(),
  getClipBeats: vi.fn(),
  getMediaToolchainCapabilities: vi.fn(),
  listLatestAudioDegradations: vi.fn(),
  subtitleExportUrl: (workflowId: string, format: string) =>
    `/api/v2/workflows/${workflowId}/timeline/subtitles?format=${format}`,
  AUDIO_DUCKING_UNAVAILABLE: "audio_ducking_unavailable",
}));

const WORKFLOW_ID = "wf-timeline-ui";
const TIMESTAMP = "2026-09-17T00:00:00+00:00";

function makeClip(overrides: Partial<TimelineClipV1> = {}): TimelineClipV1 {
  return {
    clip_id: "clip_unset",
    track_id: "track_unset",
    start_time: 0,
    duration: 2,
    source_start: 0,
    source_duration: null,
    asset_id: null,
    asset_version_id: null,
    source_node_id: null,
    fade_in: null,
    fade_out: null,
    transition_in_type: null,
    transition_in_duration: null,
    transition_out_type: null,
    transition_out_duration: null,
    bound_character_id: null,
    label: null,
    color: null,
    subtitle_text: null,
    subtitle_style: null,
    created_at: TIMESTAMP,
    updated_at: TIMESTAMP,
    ...overrides,
  };
}

function makeTrack(overrides: Partial<TimelineTrackV1> & {
  track_id: string;
  type: TimelineTrackV1["type"];
}): TimelineTrackV1 {
  const { track_id, type } = overrides;
  return {
    timeline_id: "timeline_1",
    name: type.charAt(0).toUpperCase() + type.slice(1),
    muted: false,
    volume: 1,
    locked: false,
    display_order: 0,
    clips: [],
    created_at: TIMESTAMP,
    updated_at: TIMESTAMP,
    ...overrides,
    track_id,
    type,
  };
}

function makeTimeline(overrides: Partial<TimelineV1> = {}): TimelineV1 {
  return {
    timeline_id: "timeline_1",
    workflow_id: WORKFLOW_ID,
    duration_seconds: 10,
    fps: 30,
    ducking: null,
    subtitle_burn_in: true,
    tracks: [],
    created_at: TIMESTAMP,
    updated_at: TIMESTAMP,
    ...overrides,
  };
}

const voiceTrack = makeTrack({
  track_id: "track_voice",
  type: "voice",
  name: "Voice",
  display_order: 1,
  clips: [
    makeClip({
      clip_id: "clip_voice_1",
      track_id: "track_voice",
      label: "Voice line 1",
    }),
  ],
});

const bgmTrack = makeTrack({
  track_id: "track_bgm",
  type: "bgm",
  name: "BGM",
  display_order: 2,
  clips: [makeClip({ clip_id: "clip_bgm_1", track_id: "track_bgm", duration: 8 })],
});

const videoTrack = makeTrack({
  track_id: "track_video",
  type: "video",
  name: "Video",
  display_order: 0,
  clips: [
    makeClip({
      clip_id: "clip_video_1",
      track_id: "track_video",
      label: "Video clip 1",
    }),
  ],
});

function renderPanel() {
  return render(<GlobalTimelinePanel workflowId={WORKFLOW_ID} />);
}

function stubTimelineSave(fixture: TimelineV1) {
  vi.mocked(updateTimeline).mockImplementation(async (_workflowId, payload) => ({
    ...fixture,
    ducking: payload.ducking ?? null,
    subtitle_burn_in:
      payload.subtitle_burn_in ?? fixture.subtitle_burn_in,
  }));
}

describe("GlobalTimelinePanel — audio track controls", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(getTimeline).mockResolvedValue(
      makeTimeline({ tracks: [videoTrack, voiceTrack, bgmTrack] }),
    );
    vi.mocked(getMediaToolchainCapabilities).mockResolvedValue({
      status: "ready",
      feature_flags: { audio_ducking: true },
    });
    vi.mocked(listLatestAudioDegradations).mockResolvedValue([]);
    vi.mocked(updateTrack).mockImplementation(async (_workflowId, trackId, patch) => {
      const source = [videoTrack, voiceTrack, bgmTrack].find((t) => t.track_id === trackId);
      return { ...(source as TimelineTrackV1), ...patch };
    });
  });

  afterEach(cleanup);

  it("uses the authored short program duration instead of a ten-second ruler minimum", async () => {
    vi.mocked(getTimeline).mockResolvedValue(makeTimeline({ duration_seconds: 8 }));
    renderPanel();
    expect(await screen.findByText(/8\.0s · 30fps · 0 clips/)).toBeTruthy();
    expect(screen.queryByText(/10\.0s · 30fps · 0 clips/)).toBeNull();
  });

  it("PATCHes muted when the voice-track mute button is clicked", async () => {
    renderPanel();

    const muteButton = await screen.findByRole("button", { name: "Mute Voice" });
    fireEvent.click(muteButton);

    await waitFor(() =>
      expect(updateTrack).toHaveBeenCalledWith(WORKFLOW_ID, "track_voice", { muted: true }),
    );
    // Optimistic UI flips to an unmute action.
    expect(screen.getByRole("button", { name: "Unmute Voice" })).toBeTruthy();
  });

  it("PATCHes volume when an audio-track volume slider moves", async () => {
    renderPanel();

    const slider = await screen.findByRole("slider", { name: "BGM track volume" });
    fireEvent.change(slider, { target: { value: "0.45" } });

    await waitFor(() =>
      expect(updateTrack).toHaveBeenCalledWith(WORKFLOW_ID, "track_bgm", { volume: 0.45 }),
    );
  });

  it("renders no mute or volume control for non-audio tracks", async () => {
    renderPanel();
    await screen.findByRole("button", { name: "Mute Voice" });

    expect(screen.queryByRole("button", { name: "Mute Video" })).toBeNull();
    expect(screen.queryByRole("slider", { name: "Video track volume" })).toBeNull();
  });

  it("disables mute and volume controls on a locked track", async () => {
    const lockedBgm = { ...bgmTrack, locked: true };
    vi.mocked(getTimeline).mockResolvedValue(
      makeTimeline({ tracks: [voiceTrack, lockedBgm] }),
    );
    renderPanel();

    const muteButton = await screen.findByRole("button", { name: "Mute BGM" });
    expect(muteButton.hasAttribute("disabled")).toBe(true);
    expect(screen.getByRole("slider", { name: "BGM track volume" }).hasAttribute("disabled")).toBe(
      true,
    );
  });
});

describe("GlobalTimelinePanel — selected clip inspector", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(getTimeline).mockResolvedValue(
      makeTimeline({ tracks: [videoTrack, voiceTrack, bgmTrack] }),
    );
    vi.mocked(getMediaToolchainCapabilities).mockResolvedValue({
      status: "ready",
      feature_flags: { audio_ducking: true },
    });
    vi.mocked(listLatestAudioDegradations).mockResolvedValue([]);
    vi.mocked(updateClip).mockImplementation(async (_workflowId, _clipId, patch) => ({
      ...makeClip(),
      ...patch,
      clip_id: _clipId as string,
    }));
    vi.mocked(deleteClip).mockResolvedValue(undefined);
  });

  afterEach(cleanup);

  it("preserves dirty edits through refresh and requires deliberate reload for a changed clip", async () => {
    const view = render(<GlobalTimelinePanel workflowId={WORKFLOW_ID} externalRefreshNonce={0} />);
    fireEvent.click(await screen.findByRole("button", { name: "Video clip 1" }));
    const label = screen.getByLabelText("Clip label") as HTMLInputElement;
    fireEvent.change(label, { target: { value: "Unsaved label" } });
    vi.mocked(getTimeline).mockResolvedValue(makeTimeline({ tracks: [{
      ...videoTrack, clips: [{ ...videoTrack.clips[0], duration: 4 }],
    }] }));
    view.rerender(<GlobalTimelinePanel workflowId={WORKFLOW_ID} externalRefreshNonce={1} />);
    await screen.findByTestId("timeline-inspector-stale");
    expect(label.value).toBe("Unsaved label");
    expect((screen.getByTestId("timeline-inspector-save") as HTMLButtonElement).disabled).toBe(true);
    fireEvent.click(screen.getByRole("button", { name: "Reload clip (discard unsaved edits)" }));
    expect(label.value).toBe("Video clip 1");
    expect((screen.getByLabelText("Clip duration in seconds") as HTMLInputElement).value).toBe("4");
    expect(screen.queryByTestId("timeline-inspector-stale")).toBeNull();
  });

  it("retains rejected save draft and error through an unchanged refresh, then retries", async () => {
    vi.mocked(updateClip).mockRejectedValueOnce(new Error("Clip save rejected"));
    const view = render(<GlobalTimelinePanel workflowId={WORKFLOW_ID} externalRefreshNonce={0} />);
    fireEvent.click(await screen.findByRole("button", { name: "Video clip 1" }));
    fireEvent.change(screen.getByLabelText("Clip label"), { target: { value: "Retry label" } });
    fireEvent.click(screen.getByTestId("timeline-inspector-save"));
    await screen.findByText("Clip save rejected");
    expect(getTimeline).toHaveBeenCalledTimes(1);
    view.rerender(<GlobalTimelinePanel workflowId={WORKFLOW_ID} externalRefreshNonce={1} />);
    await waitFor(() => expect(getTimeline).toHaveBeenCalledTimes(2));
    expect((screen.getByLabelText("Clip label") as HTMLInputElement).value).toBe("Retry label");
    expect(screen.getByText("Clip save rejected")).toBeTruthy();
    fireEvent.click(screen.getByTestId("timeline-inspector-save"));
    await waitFor(() => expect(updateClip).toHaveBeenCalledTimes(2));
    await waitFor(() => expect(screen.queryByText("Clip save rejected")).toBeNull());
  });

  it.each(["resolve", "reject"] as const)("ignores late %s inspector save after a workflow change", async (outcome) => {
    let resolve!: (clip: TimelineClipV1) => void;
    let reject!: (error: Error) => void;
    vi.mocked(updateClip).mockReturnValueOnce(new Promise((yes, no) => { resolve = yes; reject = no; }));
    const view = renderPanel();
    fireEvent.click(await screen.findByRole("button", { name: "Video clip 1" }));
    fireEvent.change(screen.getByLabelText("Clip label"), { target: { value: "Old project draft" } });
    fireEvent.click(screen.getByTestId("timeline-inspector-save"));
    vi.mocked(getTimeline).mockResolvedValue(makeTimeline({
      workflow_id: "wf-other", tracks: [{ ...videoTrack, clips: [{ ...videoTrack.clips[0], label: "New project clip" }] }],
    }));
    view.rerender(<GlobalTimelinePanel workflowId="wf-other" />);
    fireEvent.click(await screen.findByRole("button", { name: "New project clip" }));
    await act(async () => {
      if (outcome === "resolve") resolve({ ...videoTrack.clips[0], label: "Old project draft" });
      else reject(new Error("Old project failure"));
    });
    await waitFor(() => expect((screen.getByTestId("timeline-inspector-save") as HTMLButtonElement).disabled).toBe(false));
    expect((screen.getByLabelText("Clip label") as HTMLInputElement).value).toBe("New project clip");
    expect(screen.queryByText("Old project failure")).toBeNull();
    expect(screen.queryByRole("button", { name: "Old project draft" })).toBeNull();
  });

  it("establishes a clean baseline after successful save so later refresh hydrates", async () => {
    vi.mocked(updateClip).mockResolvedValueOnce({ ...videoTrack.clips[0], label: "Saved label" });
    const view = render(<GlobalTimelinePanel workflowId={WORKFLOW_ID} externalRefreshNonce={0} />);
    fireEvent.click(await screen.findByRole("button", { name: "Video clip 1" }));
    fireEvent.change(screen.getByLabelText("Clip label"), { target: { value: "Saved label" } });
    fireEvent.click(screen.getByTestId("timeline-inspector-save"));
    await screen.findByRole("button", { name: "Saved label" });
    vi.mocked(getTimeline).mockResolvedValue(makeTimeline({ tracks: [{
      ...videoTrack, clips: [{ ...videoTrack.clips[0], label: "Refreshed after save" }],
    }] }));
    view.rerender(<GlobalTimelinePanel workflowId={WORKFLOW_ID} externalRefreshNonce={1} />);
    await waitFor(() => expect((screen.getByLabelText("Clip label") as HTMLInputElement).value).toBe("Refreshed after save"));
    expect(screen.queryByTestId("timeline-inspector-stale")).toBeNull();
  });

  it("ignores a late external refresh after switching workflow", async () => {
    let resolve!: (timeline: TimelineV1) => void;
    const view = render(<GlobalTimelinePanel workflowId={WORKFLOW_ID} externalRefreshNonce={0} />);
    await screen.findByRole("button", { name: "Video clip 1" });
    vi.mocked(getTimeline).mockReturnValueOnce(new Promise((yes) => { resolve = yes; }));
    view.rerender(<GlobalTimelinePanel workflowId={WORKFLOW_ID} externalRefreshNonce={1} />);
    await waitFor(() => expect(getTimeline).toHaveBeenCalledTimes(2));
    vi.mocked(getTimeline).mockResolvedValue(makeTimeline({ workflow_id: "wf-other", tracks: [voiceTrack] }));
    view.rerender(<GlobalTimelinePanel workflowId="wf-other" externalRefreshNonce={1} />);
    await screen.findByRole("button", { name: "Voice line 1" });
    await act(async () => { resolve(makeTimeline({ tracks: [videoTrack] })); });
    await waitFor(() => expect(screen.queryByRole("button", { name: "Video clip 1" })).toBeNull());
    expect(screen.getByRole("button", { name: "Voice line 1" })).toBeTruthy();
  });

  it("discards the old draft on selection change and closes when the selected clip is removed", async () => {
    const view = render(<GlobalTimelinePanel workflowId={WORKFLOW_ID} externalRefreshNonce={0} />);
    fireEvent.click(await screen.findByRole("button", { name: "Video clip 1" }));
    fireEvent.change(screen.getByLabelText("Clip label"), { target: { value: "Discarded" } });
    fireEvent.click(screen.getByRole("button", { name: "Voice line 1" }));
    expect((screen.getByLabelText("Clip label") as HTMLInputElement).value).toBe("Voice line 1");
    vi.mocked(getTimeline).mockResolvedValue(makeTimeline({ tracks: [videoTrack] }));
    view.rerender(<GlobalTimelinePanel workflowId={WORKFLOW_ID} externalRefreshNonce={1} />);
    await waitFor(() => expect(screen.queryByTestId("timeline-clip-inspector")).toBeNull());
    expect(screen.queryByText("Discarded")).toBeNull();
  });

  it("saves precise timing, trim and fade edits for an audio clip (empty clears to null)", async () => {
    renderPanel();

    fireEvent.click(await screen.findByRole("button", { name: "Voice line 1" }));
    const inspector = await screen.findByTestId("timeline-clip-inspector");

    fireEvent.change(within(inspector).getByLabelText("Clip duration in seconds"), {
      target: { value: "3.5" },
    });
    fireEvent.change(within(inspector).getByLabelText("Source trim length in seconds"), {
      target: { value: "" },
    });
    fireEvent.change(within(inspector).getByLabelText("Fade in duration in seconds"), {
      target: { value: "0.2" },
    });
    fireEvent.change(within(inspector).getByLabelText("Fade out duration in seconds"), {
      target: { value: "" },
    });
    fireEvent.change(within(inspector).getByLabelText("Clip label"), {
      target: { value: "" },
    });

    fireEvent.click(within(inspector).getByTestId("timeline-inspector-save"));

    await waitFor(() => expect(updateClip).toHaveBeenCalledTimes(1));
    const [, clipId, payload] = vi.mocked(updateClip).mock.calls[0];
    expect(clipId).toBe("clip_voice_1");
    expect(payload).toEqual({
      start_time: 0,
      duration: 3.5,
      source_start: 0,
      source_duration: null,
      fade_in: 0.2,
      fade_out: null,
      volume_keyframes: null,
      bound_character_id: null,
      label: null,
    });
  });

  it("never sends fade fields from a non-audio clip inspector", async () => {
    renderPanel();

    fireEvent.click(await screen.findByRole("button", { name: "Video clip 1" }));
    const inspector = await screen.findByTestId("timeline-clip-inspector");
    expect(within(inspector).queryByLabelText("Fade in duration in seconds")).toBeNull();
    expect(within(inspector).queryByLabelText("Fade out duration in seconds")).toBeNull();

    fireEvent.click(within(inspector).getByTestId("timeline-inspector-save"));
    await waitFor(() => expect(updateClip).toHaveBeenCalledTimes(1));
    const payload = vi.mocked(updateClip).mock.calls[0][2];
    expect(payload.fade_in).toBeUndefined();
    expect(payload.fade_out).toBeUndefined();
    expect(payload.volume_keyframes).toBeUndefined();
    expect(within(inspector).queryByTestId("timeline-volume-envelope")).toBeNull();
  });

  it("seeds edge anchors and saves a keyframed volume envelope", async () => {
    renderPanel();

    fireEvent.click(await screen.findByRole("button", { name: "Voice line 1" }));
    const inspector = await screen.findByTestId("timeline-clip-inspector");
    const envelope = within(inspector).getByTestId("timeline-volume-envelope");
    expect(within(envelope).queryByTestId(/timeline-envelope-point-/)).toBeNull();

    // jsdom has no layout; give the SVG the editor's pixel box.
    const svg = within(envelope).getByRole("img");
    const rectSpy = vi
      .spyOn(svg, "getBoundingClientRect")
      .mockReturnValue({
        x: 0, y: 0, top: 0, left: 0, right: 228, bottom: 64,
        width: 228, height: 64, toJSON: () => ({}),
      } as DOMRect);
    // Click at (114, 32) -> t=1.0s (duration 2), gain 0.5.
    fireEvent.click(svg.querySelector("rect") as SVGRectElement, {
      clientX: 114,
      clientY: 32,
    });

    const points = within(envelope).getAllByTestId(/timeline-envelope-point-/);
    expect(points).toHaveLength(3);

    fireEvent.click(within(inspector).getByTestId("timeline-inspector-save"));
    await waitFor(() => expect(updateClip).toHaveBeenCalledTimes(1));
    expect(vi.mocked(updateClip).mock.calls[0][2].volume_keyframes).toEqual([
      { time_seconds: 0, value: 1 },
      { time_seconds: 1, value: 0.5 },
      { time_seconds: 2, value: 1 },
    ]);
    rectSpy.mockRestore();
  });

  it("clears a stored volume envelope with an explicit null payload", async () => {
    const envelopedVoice = {
      ...voiceTrack,
      clips: [
        makeClip({
          clip_id: "clip_voice_1",
          track_id: "track_voice",
          label: "Voice line 1",
          volume_keyframes: [
            { time_seconds: 0, value: 1 },
            { time_seconds: 2, value: 0 },
          ],
        }),
      ],
    };
    vi.mocked(getTimeline).mockResolvedValue(
      makeTimeline({ tracks: [videoTrack, envelopedVoice, bgmTrack] }),
    );
    renderPanel();

    fireEvent.click(await screen.findByRole("button", { name: "Voice line 1" }));
    const inspector = await screen.findByTestId("timeline-clip-inspector");
    const envelope = within(inspector).getByTestId("timeline-volume-envelope");
    expect(within(envelope).getAllByTestId(/timeline-envelope-point-/)).toHaveLength(2);

    fireEvent.click(within(envelope).getByTestId("timeline-envelope-clear"));
    expect(within(envelope).queryByTestId(/timeline-envelope-point-/)).toBeNull();

    fireEvent.click(within(inspector).getByTestId("timeline-inspector-save"));
    await waitFor(() => expect(updateClip).toHaveBeenCalledTimes(1));
    expect(vi.mocked(updateClip).mock.calls[0][2].volume_keyframes).toBeNull();
  });

  it("saves incoming and outgoing transitions for a video clip", async () => {
    renderPanel();

    fireEvent.click(await screen.findByRole("button", { name: "Video clip 1" }));
    const inspector = await screen.findByTestId("timeline-clip-inspector");

    fireEvent.change(within(inspector).getByTestId("timeline-transition-in-type"), {
      target: { value: "dissolve" },
    });
    fireEvent.change(within(inspector).getByTestId("timeline-transition-in-duration"), {
      target: { value: "0.5" },
    });
    fireEvent.change(within(inspector).getByTestId("timeline-transition-out-type"), {
      target: { value: "fade" },
    });
    fireEvent.change(within(inspector).getByTestId("timeline-transition-out-duration"), {
      target: { value: "0.3" },
    });

    fireEvent.click(within(inspector).getByTestId("timeline-inspector-save"));

    await waitFor(() => expect(updateClip).toHaveBeenCalledTimes(1));
    const payload = vi.mocked(updateClip).mock.calls[0][2];
    expect(payload.transition_in_type).toBe("dissolve");
    expect(payload.transition_in_duration).toBe(0.5);
    expect(payload.transition_out_type).toBe("fade");
    expect(payload.transition_out_duration).toBe(0.3);
  });

  it("clears both transition type and duration when the edge is set back to None", async () => {
    renderPanel();

    fireEvent.click(await screen.findByRole("button", { name: "Video clip 1" }));
    const inspector = await screen.findByTestId("timeline-clip-inspector");

    const inType = within(inspector).getByTestId("timeline-transition-in-type");
    fireEvent.change(inType, { target: { value: "wipe" } });
    fireEvent.change(within(inspector).getByTestId("timeline-transition-in-duration"), {
      target: { value: "0.4" },
    });
    fireEvent.change(inType, { target: { value: "" } });

    fireEvent.click(within(inspector).getByTestId("timeline-inspector-save"));

    await waitFor(() => expect(updateClip).toHaveBeenCalledTimes(1));
    const payload = vi.mocked(updateClip).mock.calls[0][2];
    expect(payload.transition_in_type).toBeNull();
    expect(payload.transition_in_duration).toBeNull();
    expect(payload.transition_out_type).toBeNull();
    expect(payload.transition_out_duration).toBeNull();
  });

  it("renders wipe/slide transitions without an unsupported-render note", async () => {
    renderPanel();

    fireEvent.click(await screen.findByRole("button", { name: "Video clip 1" }));
    const inspector = await screen.findByTestId("timeline-clip-inspector");

    fireEvent.change(within(inspector).getByTestId("timeline-transition-in-type"), {
      target: { value: "slide" },
    });
    expect(
      within(inspector).queryByTestId("timeline-transition-render-note"),
    ).toBeNull();
  });

  it("blocks save when a transition type is chosen without a positive duration", async () => {
    renderPanel();

    fireEvent.click(await screen.findByRole("button", { name: "Video clip 1" }));
    const inspector = await screen.findByTestId("timeline-clip-inspector");

    fireEvent.change(within(inspector).getByTestId("timeline-transition-in-type"), {
      target: { value: "dissolve" },
    });
    fireEvent.click(within(inspector).getByTestId("timeline-inspector-save"));

    expect(await within(inspector).findByRole("alert")).toBeTruthy();
    expect(updateClip).not.toHaveBeenCalled();
  });

  it("hides transition controls on audio clip inspectors", async () => {
    renderPanel();

    fireEvent.click(await screen.findByRole("button", { name: "Voice line 1" }));
    const inspector = await screen.findByTestId("timeline-clip-inspector");

    expect(within(inspector).queryByTestId("timeline-transitions")).toBeNull();
    expect(
      within(inspector).queryByTestId("timeline-transition-in-type"),
    ).toBeNull();
  });

  it("marks clip rows that carry incoming or outgoing transitions", async () => {
    vi.mocked(getTimeline).mockResolvedValue(
      makeTimeline({
        tracks: [
          makeTrack({
            track_id: "track_video",
            type: "video",
            clips: [
              makeClip({
                clip_id: "clip_video_t1",
                track_id: "track_video",
                label: "With dissolve in",
                transition_in_type: "dissolve",
                transition_in_duration: 0.5,
              }),
              makeClip({
                clip_id: "clip_video_t2",
                track_id: "track_video",
                start_time: 2,
                label: "No transitions",
              }),
            ],
          }),
        ],
      }),
    );
    renderPanel();

    const clipWithTransition = await screen.findByRole("button", {
      name: "With dissolve in",
    });
    expect(clipWithTransition.getAttribute("data-clip-transition-in")).toBe("dissolve");
    expect(clipWithTransition.getAttribute("data-clip-transition-out")).toBeNull();
    expect(
      within(clipWithTransition).getByTestId(
        "timeline-clip-transition-in-badge",
      ),
    ).toBeTruthy();
    expect(
      within(clipWithTransition).queryByTestId(
        "timeline-clip-transition-out-badge",
      ),
    ).toBeNull();

    const plainClip = screen.getByRole("button", { name: "No transitions" });
    expect(plainClip.getAttribute("data-clip-transition-in")).toBeNull();
    expect(
      within(plainClip).queryByTestId("timeline-clip-transition-in-badge"),
    ).toBeNull();
  });

  it("blocks save and shows an error when duration is non-positive", async () => {
    renderPanel();

    fireEvent.click(await screen.findByRole("button", { name: "Voice line 1" }));
    const inspector = await screen.findByTestId("timeline-clip-inspector");
    fireEvent.change(within(inspector).getByLabelText("Clip duration in seconds"), {
      target: { value: "0" },
    });
    fireEvent.click(within(inspector).getByTestId("timeline-inspector-save"));

    expect(await within(inspector).findByRole("alert")).toBeTruthy();
    expect(updateClip).not.toHaveBeenCalled();
  });

  it("deletes the selected clip and closes the inspector", async () => {
    renderPanel();

    fireEvent.click(await screen.findByRole("button", { name: "Voice line 1" }));
    const inspector = await screen.findByTestId("timeline-clip-inspector");
    fireEvent.click(within(inspector).getByTestId("timeline-inspector-delete"));

    await waitFor(() =>
      expect(deleteClip).toHaveBeenCalledWith(WORKFLOW_ID, "clip_voice_1"),
    );
    await waitFor(() =>
      expect(screen.queryByTestId("timeline-clip-inspector")).toBeNull(),
    );
  });
});

describe("GlobalTimelinePanel — ducking settings popover", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(getMediaToolchainCapabilities).mockResolvedValue({
      status: "ready",
      feature_flags: { audio_ducking: true },
    });
    vi.mocked(listLatestAudioDegradations).mockResolvedValue([]);
  });

  afterEach(cleanup);

  it("saves a custom ducking override via PATCH", async () => {
    const fixture = makeTimeline({ tracks: [voiceTrack, bgmTrack] });
    vi.mocked(getTimeline).mockResolvedValue(fixture);
    stubTimelineSave(fixture);
    renderPanel();

    fireEvent.click(await screen.findByTestId("timeline-ducking-button"));
    const popover = await screen.findByTestId("timeline-ducking-popover");
    expect(within(popover).queryByText(/Add at least one Voice and one BGM clip/)).toBeNull();

    fireEvent.change(within(popover).getByLabelText("Threshold (dB) value"), {
      target: { value: "-20" },
    });
    fireEvent.click(within(popover).getByTestId("timeline-ducking-save"));

    await waitFor(() => expect(updateTimeline).toHaveBeenCalledTimes(1));
    expect(vi.mocked(updateTimeline).mock.calls[0][1]).toEqual({
      ducking: {
        enabled: true,
        threshold_db: -20,
        ratio: 12,
        attack_ms: 50,
        release_ms: 250,
        makeup_gain_db: 0,
      } satisfies TimelineDuckingConfigV1,
    });
    await waitFor(() =>
      expect(screen.queryByTestId("timeline-ducking-popover")).toBeNull(),
    );
  });

  it("rejects out-of-range parameters without calling the API", async () => {
    const fixture = makeTimeline({ tracks: [voiceTrack, bgmTrack] });
    vi.mocked(getTimeline).mockResolvedValue(fixture);
    stubTimelineSave(fixture);
    renderPanel();

    fireEvent.click(await screen.findByTestId("timeline-ducking-button"));
    const popover = await screen.findByTestId("timeline-ducking-popover");
    fireEvent.change(within(popover).getByLabelText("Threshold (dB) value"), {
      target: { value: "-200" },
    });
    fireEvent.click(within(popover).getByTestId("timeline-ducking-save"));

    expect(within(popover).getByText(/outside their valid range/)).toBeTruthy();
    expect(updateTimeline).not.toHaveBeenCalled();
  });

  it("resets to renderer auto-defaults with an explicit null payload", async () => {
    const fixture = makeTimeline({
      tracks: [voiceTrack, bgmTrack],
      ducking: {
        enabled: true,
        threshold_db: -18,
        ratio: 8,
        attack_ms: 40,
        release_ms: 300,
        makeup_gain_db: 1,
      },
    });
    vi.mocked(getTimeline).mockResolvedValue(fixture);
    stubTimelineSave(fixture);
    renderPanel();

    fireEvent.click(await screen.findByTestId("timeline-ducking-button"));
    const popover = await screen.findByTestId("timeline-ducking-popover");
    const resetButton = within(popover).getByRole("button", { name: "Reset to Auto" });
    expect(resetButton.hasAttribute("disabled")).toBe(false);
    fireEvent.click(resetButton);

    await waitFor(() =>
      expect(updateTimeline).toHaveBeenCalledWith(WORKFLOW_ID, { ducking: null }),
    );
  });

  it("keeps Reset to Auto disabled while no stored override exists", async () => {
    const fixture = makeTimeline({ tracks: [voiceTrack, bgmTrack] });
    vi.mocked(getTimeline).mockResolvedValue(fixture);
    renderPanel();

    fireEvent.click(await screen.findByTestId("timeline-ducking-button"));
    const popover = await screen.findByTestId("timeline-ducking-popover");
    expect(
      within(popover).getByRole("button", { name: "Reset to Auto" }).hasAttribute("disabled"),
    ).toBe(true);
  });

  it("warns when voice and BGM clips are not both present", async () => {
    vi.mocked(getTimeline).mockResolvedValue(makeTimeline({ tracks: [videoTrack, voiceTrack] }));
    renderPanel();

    fireEvent.click(await screen.findByTestId("timeline-ducking-button"));
    const popover = await screen.findByTestId("timeline-ducking-popover");
    expect(within(popover).getByText(/Add at least one Voice and one BGM clip/)).toBeTruthy();
  });

  it("surfaces renderer-side ducking incompatibility inside the popover", async () => {
    vi.mocked(getMediaToolchainCapabilities).mockResolvedValue({
      status: "degraded",
      feature_flags: { audio_ducking: false },
      missing_requirements: ["ffmpeg"],
    });
    vi.mocked(getTimeline).mockResolvedValue(makeTimeline({ tracks: [voiceTrack, bgmTrack] }));
    renderPanel();

    fireEvent.click(await screen.findByTestId("timeline-ducking-button"));
    const popover = await screen.findByTestId("timeline-ducking-popover");
    const warning = await within(popover).findByTestId("timeline-ducking-unsupported");
    expect(warning.textContent).toContain("sidechaincompress");
  });
});

describe("GlobalTimelinePanel — degradation banner & capability probe", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(getTimeline).mockResolvedValue(
      makeTimeline({ tracks: [videoTrack, voiceTrack, bgmTrack] }),
    );
    vi.mocked(getMediaToolchainCapabilities).mockResolvedValue({
      status: "ready",
      feature_flags: { audio_ducking: true },
    });
  });

  afterEach(cleanup);

  it("probes media toolchain capabilities once on mount", async () => {
    vi.mocked(listLatestAudioDegradations).mockResolvedValue([]);
    renderPanel();
    await screen.findByTestId("timeline-ducking-button");

    expect(getMediaToolchainCapabilities).toHaveBeenCalledTimes(1);
  });

  it("shows the latest audio degradation event and allows dismissing it", async () => {
    vi.mocked(listLatestAudioDegradations).mockResolvedValue([
      {
        seq: 3,
        created_at: TIMESTAMP,
        payload: {
          export_id: "export_abc123",
          degradations: ["audio_ducking_unavailable"],
        },
      },
      {
        seq: 11,
        created_at: TIMESTAMP,
        payload: {
          export_id: "export_def456",
          degradations: ["audio_ducking_unavailable"],
        },
      },
    ]);
    renderPanel();

    const banner = await screen.findByTestId("timeline-audio-degradation-banner");
    expect(banner.textContent).toContain("sidechaincompress");
    expect(banner.textContent).toContain("def456");

    fireEvent.click(within(banner).getByRole("button", { name: "Dismiss degradation notice" }));
    await waitFor(() =>
      expect(screen.queryByTestId("timeline-audio-degradation-banner")).toBeNull(),
    );
  });

  it("renders no banner when no degradation events exist", async () => {
    vi.mocked(listLatestAudioDegradations).mockResolvedValue([]);
    renderPanel();
    await screen.findByTestId("timeline-ducking-button");

    expect(screen.queryByTestId("timeline-audio-degradation-banner")).toBeNull();
  });
});

describe("GlobalTimelinePanel — cross-track drag & edge snapping", () => {
  // Ruler is 24px tall; each rendered track row is TRACK_HEIGHT (48px);
  // the content area starts after the 150px label column.
  const CONTENT_LEFT = 150;
  const TRACK_RECTS: Record<string, { top: number; bottom: number }> = {
    track_video: { top: 24, bottom: 72 },
    track_voice: { top: 72, bottom: 120 },
    track_bgm: { top: 120, bottom: 168 },
  };

  let rectSpy: ReturnType<typeof vi.spyOn>;

  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(getTimeline).mockResolvedValue(
      makeTimeline({ tracks: [videoTrack, voiceTrack, bgmTrack] }),
    );
    vi.mocked(getMediaToolchainCapabilities).mockResolvedValue({
      status: "ready",
      feature_flags: { audio_ducking: true },
    });
    vi.mocked(listLatestAudioDegradations).mockResolvedValue([]);
    vi.mocked(updateClip).mockResolvedValue(makeClip());
    vi.mocked(moveClip).mockResolvedValue(makeClip());

    rectSpy = vi
      .spyOn(HTMLElement.prototype, "getBoundingClientRect")
      .mockImplementation(function mockRect(this: HTMLElement) {
        const trackId = this.getAttribute?.("data-track-id");
        const bounds = trackId ? TRACK_RECTS[trackId] : undefined;
        const rect = bounds ?? { top: 0, bottom: 0 };
        return {
          left: bounds ? CONTENT_LEFT : 0,
          right: bounds ? 1000 : 0,
          top: rect.top,
          bottom: rect.bottom,
          width: bounds ? 1000 - CONTENT_LEFT : 0,
          height: bounds ? rect.bottom - rect.top : 0,
          x: bounds ? CONTENT_LEFT : 0,
          y: rect.top,
          toJSON: () => ({}),
        } as DOMRect;
      });
  });

  afterEach(() => {
    rectSpy.mockRestore();
    cleanup();
  });

  it("drops a voice clip onto BGM with edge snapping and POSTs the move", async () => {
    renderPanel();
    const clip = await screen.findByRole("button", { name: "Voice line 1" });

    // Start mid voice row; drag 320px (8s) right into the BGM row.
    fireEvent.mouseDown(clip, { clientX: 200, clientY: 96 });
    fireEvent.mouseMove(screen.getByTestId("timeline-scroll-container"), {
      clientX: 520,
      clientY: 144,
    });

    // BGM clip ends at exactly 8s — the gold guide must appear.
    expect(screen.getByTestId("timeline-snap-guide")).toBeTruthy();

    fireEvent.mouseUp(screen.getByTestId("timeline-scroll-container"), {
      clientX: 520,
      clientY: 144,
    });

    await waitFor(() => expect(moveClip).toHaveBeenCalledTimes(1));
    expect(vi.mocked(moveClip).mock.calls[0]).toEqual([
      WORKFLOW_ID,
      "clip_voice_1",
      { track_id: "track_bgm", start_time: 8 },
    ]);
    expect(updateClip).not.toHaveBeenCalled();
  });

  it("cancels and resyncs when dropped on an incompatible video row", async () => {
    renderPanel();
    const clip = await screen.findByRole("button", { name: "Voice line 1" });

    fireEvent.mouseDown(clip, { clientX: 200, clientY: 96 });
    fireEvent.mouseMove(screen.getByTestId("timeline-scroll-container"), {
      clientX: 300,
      clientY: 48,
    });
    fireEvent.mouseUp(screen.getByTestId("timeline-scroll-container"), {
      clientX: 300,
      clientY: 48,
    });

    await waitFor(() => expect(getTimeline).toHaveBeenCalledTimes(2));
    expect(moveClip).not.toHaveBeenCalled();
    expect(updateClip).not.toHaveBeenCalled();

    // After resync the clip is back on its original voice track.
    const voiceRow = screen.getByRole("button", { name: "Voice track" });
    expect(within(voiceRow).getByRole("button", { name: "Voice line 1" })).toBeTruthy();
  });

  it("keeps a same-track horizontal drag on the PATCH updateClip path", async () => {
    renderPanel();
    const clip = await screen.findByRole("button", { name: "Voice line 1" });

    fireEvent.mouseDown(clip, { clientX: 200, clientY: 96 });
    fireEvent.mouseMove(screen.getByTestId("timeline-scroll-container"), {
      clientX: 300,
      clientY: 96,
    });
    fireEvent.mouseUp(screen.getByTestId("timeline-scroll-container"), {
      clientX: 300,
      clientY: 96,
    });

    await waitFor(() => expect(updateClip).toHaveBeenCalledTimes(1));
    expect(vi.mocked(updateClip).mock.calls[0]).toEqual([
      WORKFLOW_ID,
      "clip_voice_1",
      { start_time: 2.5, duration: 2 },
    ]);
    expect(moveClip).not.toHaveBeenCalled();
  });

  it("merges the server's canonical clip after a successful trim so the source window stays current", async () => {
    const canonical = makeClip({
      clip_id: "clip_video_1",
      track_id: "track_video",
      label: "Video clip 1",
      start_time: 3,
      duration: 1,
      source_start: 2,
      source_duration: 1,
    });
    vi.mocked(updateClip).mockResolvedValue(canonical);
    renderPanel();
    const clip = await screen.findByRole("button", { name: "Video clip 1" });

    fireEvent.mouseDown(within(clip).getByTitle("Trim start"), { clientX: 200, clientY: 48 });
    fireEvent.mouseMove(screen.getByTestId("timeline-scroll-container"), {
      clientX: 240,
      clientY: 48,
    });
    fireEvent.mouseUp(screen.getByTestId("timeline-scroll-container"), {
      clientX: 240,
      clientY: 48,
    });

    await waitFor(() => expect(updateClip).toHaveBeenCalledTimes(1));
    // The first click after a drag is consumed by the click-after-drag
    // guard; a second click selects the clip and opens the inspector.
    const clipAfterDrag = await screen.findByRole("button", { name: "Video clip 1" });
    fireEvent.click(clipAfterDrag);
    fireEvent.click(clipAfterDrag);
    const inspector = await screen.findByTestId("timeline-clip-inspector");
    const sourceIn = within(inspector).getByLabelText(
      "Source trim in-point in seconds",
    ) as HTMLInputElement;
    const sourceLength = within(inspector).getByLabelText(
      "Source trim length in seconds",
    ) as HTMLInputElement;
    expect(sourceIn.value).toBe("2");
    expect(sourceLength.value).toBe("1");
  });

  it("resyncs a rejected drag after StrictMode replays effect setup", async () => {
    vi.mocked(updateClip).mockRejectedValueOnce(new Error("StrictMode rejection"));
    const errorSpy = vi.spyOn(console, "error").mockImplementation(() => {});
    render(<StrictMode><GlobalTimelinePanel workflowId={WORKFLOW_ID} /></StrictMode>);
    const clip = await screen.findByRole("button", { name: "Video clip 1" });
    const calls = vi.mocked(getTimeline).mock.calls.length;
    fireEvent.mouseDown(within(clip).getByTitle("Trim end"), { clientX: 200, clientY: 48 });
    fireEvent.mouseMove(screen.getByTestId("timeline-scroll-container"), { clientX: 240, clientY: 48 });
    fireEvent.mouseUp(screen.getByTestId("timeline-scroll-container"));
    await waitFor(() => expect(getTimeline).toHaveBeenCalledTimes(calls + 1));
    expect(screen.getByTestId("timeline-operation-error")).toBeTruthy();
    expect(screen.getByRole("button", { name: "Video clip 1" }).style.width).toBe("80px");
    errorSpy.mockRestore();
  });

  it("surfaces a visible error and resyncs when a clip write is rejected", async () => {
    vi.mocked(updateClip).mockRejectedValueOnce(new Error("rejection"));
    vi.mocked(getTimeline)
      .mockResolvedValueOnce(makeTimeline({ tracks: [videoTrack] }))
      .mockImplementation(() =>
        Promise.resolve(makeTimeline({ tracks: [videoTrack] })),
      );
    const errorSpy = vi.spyOn(console, "error").mockImplementation(() => {});
    renderPanel();
    const clip = await screen.findByRole("button", { name: "Video clip 1" });

    fireEvent.mouseDown(clip, { clientX: 200, clientY: 48 });
    fireEvent.mouseMove(screen.getByTestId("timeline-scroll-container"), {
      clientX: 300,
      clientY: 48,
    });
    fireEvent.mouseUp(screen.getByTestId("timeline-scroll-container"), {
      clientX: 300,
      clientY: 48,
    });

    await waitFor(() =>
      expect(
        screen.getByText(/Couldn't save the clip change/),
      ).toBeTruthy(),
    );
    await waitFor(() => expect(getTimeline).toHaveBeenCalledTimes(2));
    expect(screen.getByRole("button", { name: "Video clip 1" })).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Dismiss timeline error" }));
    expect(screen.queryByTestId("timeline-operation-error")).toBeNull();
    expect(screen.getByTestId("timeline-scroll-container")).toBeTruthy();
    errorSpy.mockRestore();
  });


  it.each(["resolve", "reject"])("ignores late %s drag completion across A → B → A", async (outcome) => {
    let resolve!: (clip: TimelineClipV1) => void;
    let reject!: (error: Error) => void;
    vi.mocked(updateClip).mockReturnValueOnce(new Promise((yes, no) => { resolve = yes; reject = no; }));
    const view = renderPanel();
    const clip = await screen.findByRole("button", { name: "Video clip 1" });
    fireEvent.mouseDown(within(clip).getByTitle("Trim end"), { clientX: 200, clientY: 48 });
    fireEvent.mouseMove(screen.getByTestId("timeline-scroll-container"), { clientX: 240, clientY: 48 });
    fireEvent.mouseUp(screen.getByTestId("timeline-scroll-container"));
    expect(updateClip).toHaveBeenCalledTimes(1);
    vi.mocked(getTimeline).mockResolvedValueOnce(makeTimeline({ workflow_id: "B", tracks: [videoTrack] }));
    view.rerender(<GlobalTimelinePanel workflowId="B" />);
    await screen.findByRole("button", { name: "Video clip 1" });
    vi.mocked(getTimeline).mockResolvedValueOnce(makeTimeline({ tracks: [videoTrack] }));
    view.rerender(<GlobalTimelinePanel workflowId={WORKFLOW_ID} />);
    const fresh = await screen.findByRole("button", { name: "Video clip 1" });
    const calls = vi.mocked(getTimeline).mock.calls.length;
    await act(async () => {
      if (outcome === "resolve") resolve(makeClip({ clip_id: "clip_video_1", track_id: "track_video", label: "Stale canonical", duration: 9 }));
      else reject(new Error("Old drag failure"));
    });
    expect(screen.queryByRole("button", { name: "Stale canonical" })).toBeNull();
    expect(screen.queryByTestId("timeline-operation-error")).toBeNull();
    expect(getTimeline).toHaveBeenCalledTimes(calls);
    expect(fresh.style.width).toBe("80px");
  });

  it("keeps drag writes single-flight until the canonical trim has merged", async () => {
    let resolve!: (clip: TimelineClipV1) => void;
    vi.mocked(updateClip).mockReturnValueOnce(new Promise((yes) => { resolve = yes; }));
    renderPanel();
    const clip = await screen.findByRole("button", { name: "Video clip 1" });
    const drag = () => {
      fireEvent.mouseDown(within(clip).getByTitle("Trim end"), { clientX: 200, clientY: 48 });
      fireEvent.mouseMove(screen.getByTestId("timeline-scroll-container"), { clientX: 240, clientY: 48 });
      fireEvent.mouseUp(screen.getByTestId("timeline-scroll-container"));
    };
    drag(); drag();
    expect(updateClip).toHaveBeenCalledTimes(1);
    expect(clip.style.width).toBe("120px");
    await act(async () => resolve(makeClip({ ...videoTrack.clips[0], duration: 3, source_duration: 3 })));
    drag();
    expect(updateClip).toHaveBeenCalledTimes(2);
  });

  it("quantizes same-track drags to the selected 1s snap grid", async () => {
    renderPanel();
    const clip = await screen.findByRole("button", { name: "Voice line 1" });

    fireEvent.click(screen.getByTestId("timeline-snap-grid-second"));

    // 110px = 2.75s; on the 1s grid the new start must round to 3s.
    fireEvent.mouseDown(clip, { clientX: 200, clientY: 96 });
    fireEvent.mouseMove(screen.getByTestId("timeline-scroll-container"), {
      clientX: 310,
      clientY: 96,
    });
    fireEvent.mouseUp(screen.getByTestId("timeline-scroll-container"), {
      clientX: 310,
      clientY: 96,
    });

    await waitFor(() => expect(updateClip).toHaveBeenCalledTimes(1));
    expect(vi.mocked(updateClip).mock.calls[0]).toEqual([
      WORKFLOW_ID,
      "clip_voice_1",
      { start_time: 3, duration: 2 },
    ]);
  });

  it("cancels and resyncs when a same-track drop would overlap another clip", async () => {
    const crowdedVideo = makeTrack({
      track_id: "track_video",
      type: "video",
      name: "Video",
      display_order: 0,
      clips: [
        makeClip({
          clip_id: "c_first",
          track_id: "track_video",
          label: "First",
          start_time: 0,
          duration: 2,
        }),
        makeClip({
          clip_id: "c_second",
          track_id: "track_video",
          label: "Second",
          start_time: 5,
          duration: 2,
        }),
      ],
    });
    vi.mocked(getTimeline).mockResolvedValue(
      makeTimeline({ tracks: [crowdedVideo] }),
    );
    renderPanel();
    const clip = await screen.findByRole("button", { name: "First" });

    // 180px = 4.5s: dragging the 2s first clip to 4.5s overlaps 5–7s.
    fireEvent.mouseDown(clip, { clientX: 200, clientY: 48 });
    fireEvent.mouseMove(screen.getByTestId("timeline-scroll-container"), {
      clientX: 380,
      clientY: 48,
    });
    fireEvent.mouseUp(screen.getByTestId("timeline-scroll-container"), {
      clientX: 380,
      clientY: 48,
    });

    await waitFor(() => expect(getTimeline).toHaveBeenCalledTimes(2));
    expect(updateClip).not.toHaveBeenCalled();
    expect(moveClip).not.toHaveBeenCalled();
  });

  it("marks overlapping clips with data-clip-overlap but not back-to-back clips", async () => {
    const overlapTrack = makeTrack({
      track_id: "track_video",
      type: "video",
      name: "Video",
      display_order: 0,
      clips: [
        makeClip({ clip_id: "c_a", track_id: "track_video", label: "A", duration: 2 }),
        makeClip({
          clip_id: "c_b",
          track_id: "track_video",
          label: "B",
          start_time: 1.5,
          duration: 2,
        }),
        makeClip({
          clip_id: "c_c",
          track_id: "track_video",
          label: "C",
          start_time: 3.5,
          duration: 1,
        }),
      ],
    });
    vi.mocked(getTimeline).mockResolvedValue(
      makeTimeline({ tracks: [overlapTrack] }),
    );
    renderPanel();
    await screen.findByRole("button", { name: "A" });

    const rows = screen.getAllByTestId("timeline-clip");
    const byId = Object.fromEntries(
      rows.map((row) => [row.getAttribute("aria-label"), row]),
    );
    expect(byId.A?.getAttribute("data-clip-overlap")).toBe("true");
    expect(byId.B?.getAttribute("data-clip-overlap")).toBe("true");
    // C starts exactly when B ends (3.5s) — touching is not an overlap.
    expect(byId.C?.getAttribute("data-clip-overlap")).toBeNull();
  });

  it("trims the right edge and pins the used source window to the new length", async () => {
    renderPanel();
    const clip = await screen.findByRole("button", { name: "Voice line 1" });
    const trimEnd = within(clip).getByTitle("Trim end");

    // +40px = +1s: the 2s clip grows to 3s; source_duration must follow so
    // the renderer reveals another second of media instead of padding.
    fireEvent.mouseDown(trimEnd, { clientX: 200, clientY: 96 });
    fireEvent.mouseMove(screen.getByTestId("timeline-scroll-container"), {
      clientX: 240,
      clientY: 96,
    });
    fireEvent.mouseUp(screen.getByTestId("timeline-scroll-container"), {
      clientX: 240,
      clientY: 96,
    });

    await waitFor(() => expect(updateClip).toHaveBeenCalledTimes(1));
    expect(vi.mocked(updateClip).mock.calls[0]).toEqual([
      WORKFLOW_ID,
      "clip_voice_1",
      { start_time: 0, duration: 3, source_duration: 3 },
    ]);
    expect(moveClip).not.toHaveBeenCalled();
  });

  it("trims the left edge and slides the source in-point along with it", async () => {
    renderPanel();
    const clip = await screen.findByRole("button", { name: "Voice line 1" });
    const trimStart = within(clip).getByTitle("Trim start");

    // +40px = +1s: the clip becomes 1s long starting at 1s while the right
    // edge stays put, so the remaining media starts at source 1s (the
    // visible content must not jump).
    fireEvent.mouseDown(trimStart, { clientX: 200, clientY: 96 });
    fireEvent.mouseMove(screen.getByTestId("timeline-scroll-container"), {
      clientX: 240,
      clientY: 96,
    });
    fireEvent.mouseUp(screen.getByTestId("timeline-scroll-container"), {
      clientX: 240,
      clientY: 96,
    });

    await waitFor(() => expect(updateClip).toHaveBeenCalledTimes(1));
    expect(vi.mocked(updateClip).mock.calls[0]).toEqual([
      WORKFLOW_ID,
      "clip_voice_1",
      { start_time: 1, duration: 1, source_start: 1, source_duration: 1 },
    ]);
  });

  it("clamps a left-edge trim so it cannot reveal media before the source head", async () => {
    const trimTrack = makeTrack({
      track_id: "track_video",
      type: "video",
      name: "Video",
      display_order: 0,
      clips: [
        makeClip({
          clip_id: "c_trim",
          track_id: "track_video",
          label: "Trimmy",
          start_time: 5,
          duration: 2,
          source_start: 2,
        }),
      ],
    });
    vi.mocked(getTimeline).mockResolvedValue(
      makeTimeline({ tracks: [trimTrack] }),
    );
    renderPanel();
    const clip = await screen.findByRole("button", { name: "Trimmy" });
    const trimStart = within(clip).getByTitle("Trim start");

    // -120px = -3s but only 2s of source headroom exists, so the edge clamps
    // at 3s: the clip grows to 4s with source in-point reaching exactly 0.
    fireEvent.mouseDown(trimStart, { clientX: 300, clientY: 48 });
    fireEvent.mouseMove(screen.getByTestId("timeline-scroll-container"), {
      clientX: 180,
      clientY: 48,
    });
    fireEvent.mouseUp(screen.getByTestId("timeline-scroll-container"), {
      clientX: 180,
      clientY: 48,
    });

    await waitFor(() => expect(updateClip).toHaveBeenCalledTimes(1));
    expect(vi.mocked(updateClip).mock.calls[0]).toEqual([
      WORKFLOW_ID,
      "c_trim",
      { start_time: 3, duration: 4, source_start: 0, source_duration: 4 },
    ]);
  });
});

describe("GlobalTimelinePanel — live refresh & orphan clips", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(getTimeline).mockResolvedValue(
      makeTimeline({ tracks: [videoTrack] }),
    );
    vi.mocked(getMediaToolchainCapabilities).mockResolvedValue({
      status: "ready",
      feature_flags: { audio_ducking: true },
    });
    vi.mocked(listLatestAudioDegradations).mockResolvedValue([]);
  });

  afterEach(cleanup);

  it("refetches when externalRefreshNonce grows, but not on a repeated nonce", async () => {
    const props = { workflowId: WORKFLOW_ID, externalRefreshNonce: 0 };
    const { rerender } = render(<GlobalTimelinePanel {...props} />);
    await screen.findByRole("button", { name: "Video clip 1" });
    expect(getTimeline).toHaveBeenCalledTimes(1);

    rerender(<GlobalTimelinePanel {...props} externalRefreshNonce={42} />);
    await waitFor(() => expect(getTimeline).toHaveBeenCalledTimes(2));

    rerender(<GlobalTimelinePanel {...props} externalRefreshNonce={42} />);
    // Past the 250ms debounce window, no further fetch must have happened.
    await new Promise((resolve) => setTimeout(resolve, 320));
    expect(getTimeline).toHaveBeenCalledTimes(2);
  });

  it("does not refetch solely because the nonce prop was mounted at zero", async () => {
    render(<GlobalTimelinePanel workflowId={WORKFLOW_ID} externalRefreshNonce={10} />);
    await screen.findByRole("button", { name: "Video clip 1" });
    await new Promise((resolve) => setTimeout(resolve, 320));
    expect(getTimeline).toHaveBeenCalledTimes(1);
  });

  it("flags clips whose source node is missing, but not manual clips", async () => {
    const orphanTrack = makeTrack({
      track_id: "track_video",
      type: "video",
      clips: [
        makeClip({
          clip_id: "clip_alive",
          track_id: "track_video",
          source_node_id: "node_alive",
          label: "Alive shot",
        }),
        makeClip({
          clip_id: "clip_gone",
          track_id: "track_video",
          start_time: 2,
          source_node_id: "node_gone",
          label: "Gone shot",
        }),
        makeClip({
          clip_id: "clip_manual",
          track_id: "track_video",
          start_time: 4,
          source_node_id: null,
          label: "Manual shot",
        }),
      ],
    });
    vi.mocked(getTimeline).mockResolvedValue(
      makeTimeline({ tracks: [orphanTrack] }),
    );

    render(
      <GlobalTimelinePanel
        workflowId={WORKFLOW_ID}
        workflowNodeIds={new Set(["node_alive"])}
      />,
    );

    const orphan = await screen.findByRole("button", {
      name: "Gone shot (source node deleted)",
    });
    expect(orphan.getAttribute("data-clip-orphan")).toBe("true");
    expect(orphan.getAttribute("title")).toContain("source node deleted");
    expect(
      screen.getByRole("button", { name: "Alive shot" }).getAttribute(
        "data-clip-orphan",
      ),
    ).toBeNull();
    expect(
      screen.getByRole("button", { name: "Manual shot" }).getAttribute(
        "data-clip-orphan",
      ),
    ).toBeNull();
  });

  it("treats all clips as healthy when no node set is provided", async () => {
    const sourcedTrack = makeTrack({
      track_id: "track_video",
      type: "video",
      clips: [
        makeClip({
          clip_id: "clip_sourced",
          track_id: "track_video",
          source_node_id: "node_anything",
          label: "Sourced shot",
        }),
      ],
    });
    vi.mocked(getTimeline).mockResolvedValue(
      makeTimeline({ tracks: [sourcedTrack] }),
    );

    render(<GlobalTimelinePanel workflowId={WORKFLOW_ID} />);

    const clip = await screen.findByRole("button", { name: "Sourced shot" });
    expect(clip.getAttribute("data-clip-orphan")).toBeNull();
  });

  it("shows an orphan cleanup notice in the inspector and deletes from it", async () => {
    const orphanTrack = makeTrack({
      track_id: "track_video",
      type: "video",
      clips: [
        makeClip({
          clip_id: "clip_gone",
          track_id: "track_video",
          source_node_id: "node_gone",
          label: "Gone shot",
        }),
      ],
    });
    vi.mocked(getTimeline).mockResolvedValue(
      makeTimeline({ tracks: [orphanTrack] }),
    );
    vi.mocked(deleteClip).mockResolvedValue(undefined);

    render(
      <GlobalTimelinePanel
        workflowId={WORKFLOW_ID}
        workflowNodeIds={new Set(["someone_else"])}
      />,
    );

    fireEvent.click(
      await screen.findByRole("button", {
        name: "Gone shot (source node deleted)",
      }),
    );
    const notice = await screen.findByTestId("timeline-orphan-inspector-notice");
    expect(notice.textContent).toContain("Source node deleted");
    const deleteButton = screen.getByRole("button", {
      name: "Delete orphan clip",
    });
    fireEvent.click(deleteButton);

    await waitFor(() =>
      expect(deleteClip).toHaveBeenCalledWith(WORKFLOW_ID, "clip_gone"),
    );
    await waitFor(() =>
      expect(screen.queryByTestId("timeline-clip-inspector")).toBeNull(),
    );
  });

  it("highlights the clip originating from the canvas-selected node", async () => {
    const linkedTrack = makeTrack({
      track_id: "track_video",
      type: "video",
      clips: [
        makeClip({
          clip_id: "clip_alive",
          track_id: "track_video",
          source_node_id: "node_alive",
          label: "Alive shot",
        }),
        makeClip({
          clip_id: "clip_other",
          track_id: "track_video",
          start_time: 2,
          source_node_id: "node_other",
          label: "Other shot",
        }),
      ],
    });
    vi.mocked(getTimeline).mockResolvedValue(
      makeTimeline({ tracks: [linkedTrack] }),
    );

    render(
      <GlobalTimelinePanel
        workflowId={WORKFLOW_ID}
        workflowNodeIds={new Set(["node_alive", "node_other"])}
        highlightedSourceNodeId="node_alive"
      />,
    );

    const linked = await screen.findByRole("button", { name: "Alive shot" });
    expect(linked.getAttribute("data-clip-canvas-linked")).toBe("true");
    expect(
      screen.getByRole("button", { name: "Other shot" }).getAttribute(
        "data-clip-canvas-linked",
      ),
    ).toBeNull();
  });

  it("invokes onClipClick with the clicked clip for canvas focus wiring", async () => {
    const linkedTrack = makeTrack({
      track_id: "track_video",
      type: "video",
      clips: [
        makeClip({
          clip_id: "clip_alive",
          track_id: "track_video",
          source_node_id: "node_alive",
          label: "Alive shot",
        }),
      ],
    });
    vi.mocked(getTimeline).mockResolvedValue(
      makeTimeline({ tracks: [linkedTrack] }),
    );
    const onClipClick = vi.fn();

    render(
      <GlobalTimelinePanel
        workflowId={WORKFLOW_ID}
        workflowNodeIds={new Set(["node_alive"])}
        onClipClick={onClipClick}
      />,
    );

    fireEvent.click(await screen.findByRole("button", { name: "Alive shot" }));
    expect(onClipClick).toHaveBeenCalledTimes(1);
    expect(onClipClick.mock.calls[0][0].clip_id).toBe("clip_alive");
    expect(onClipClick.mock.calls[0][0].source_node_id).toBe("node_alive");
  });
});

describe("GlobalTimelinePanel — promote clips to video nodes", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(getMediaToolchainCapabilities).mockResolvedValue({
      status: "ready",
      feature_flags: { audio_ducking: true },
    });
    vi.mocked(listLatestAudioDegradations).mockResolvedValue([]);
    vi.mocked(updateClip).mockResolvedValue(makeClip());
  });

  afterEach(cleanup);

  it("creates a video node for a manual video clip and links the clip", async () => {
    const manualTrack = makeTrack({
      track_id: "track_video",
      type: "video",
      clips: [
        makeClip({
          clip_id: "clip_manual",
          track_id: "track_video",
          source_node_id: null,
          label: "Manual shot",
        }),
      ],
    });
    vi.mocked(getTimeline).mockResolvedValue(
      makeTimeline({ tracks: [manualTrack] }),
    );
    const onCreateVideoNode = vi.fn().mockResolvedValue("node_new_123");

    render(
      <GlobalTimelinePanel
        workflowId={WORKFLOW_ID}
        workflowNodeIds={new Set()}
        onCreateVideoNode={onCreateVideoNode}
      />,
    );

    fireEvent.click(await screen.findByRole("button", { name: "Manual shot" }));
    const notice = await screen.findByTestId("timeline-manual-clip-notice");
    expect(notice.textContent).toContain("not linked to a canvas node");

    fireEvent.click(screen.getByTestId("timeline-create-video-node"));

    await waitFor(() =>
      expect(onCreateVideoNode).toHaveBeenCalledWith(
        expect.objectContaining({ clip_id: "clip_manual" }),
      ),
    );
    await waitFor(() =>
      expect(updateClip).toHaveBeenCalledWith(WORKFLOW_ID, "clip_manual", {
        source_node_id: "node_new_123",
      }),
    );
    // The panel resyncs so linkage/orphan markers reflect the new node.
    await waitFor(() => expect(getTimeline).toHaveBeenCalledTimes(2));
  });

  it("offers re-link for an orphan video clip and links the replacement", async () => {
    const orphanTrack = makeTrack({
      track_id: "track_video",
      type: "video",
      clips: [
        makeClip({
          clip_id: "clip_orphan",
          track_id: "track_video",
          source_node_id: "node_gone",
          label: "Orphan shot",
        }),
      ],
    });
    vi.mocked(getTimeline).mockResolvedValue(
      makeTimeline({ tracks: [orphanTrack] }),
    );
    const onCreateVideoNode = vi.fn().mockResolvedValue("node_replacement");

    render(
      <GlobalTimelinePanel
        workflowId={WORKFLOW_ID}
        workflowNodeIds={new Set(["someone_else"])}
        onCreateVideoNode={onCreateVideoNode}
      />,
    );

    fireEvent.click(
      await screen.findByRole("button", {
        name: "Orphan shot (source node deleted)",
      }),
    );
    expect(screen.queryByTestId("timeline-manual-clip-notice")).toBeNull();
    fireEvent.click(screen.getByTestId("timeline-relink-video-node"));

    await waitFor(() =>
      expect(updateClip).toHaveBeenCalledWith(WORKFLOW_ID, "clip_orphan", {
        source_node_id: "node_replacement",
      }),
    );
  });

  it("hides promotion without the handler or on non-video tracks", async () => {
    const mixedTimeline = makeTimeline({ tracks: [videoTrack, voiceTrack] });
    vi.mocked(getTimeline).mockResolvedValue(mixedTimeline);
    const onCreateVideoNode = vi.fn().mockResolvedValue("node_unused");

    // Manual video clip but no handler prop: no affordance at all.
    render(<GlobalTimelinePanel workflowId={WORKFLOW_ID} />);
    fireEvent.click(await screen.findByRole("button", { name: "Video clip 1" }));
    expect(screen.queryByTestId("timeline-manual-clip-notice")).toBeNull();
    expect(screen.queryByTestId("timeline-create-video-node")).toBeNull();
    cleanup();

    // Handler present, but a voice clip is never promoted to a video node.
    render(
      <GlobalTimelinePanel
        workflowId={WORKFLOW_ID}
        onCreateVideoNode={onCreateVideoNode}
      />,
    );
    fireEvent.click(await screen.findByRole("button", { name: "Voice line 1" }));
    expect(screen.queryByTestId("timeline-manual-clip-notice")).toBeNull();
    expect(screen.queryByTestId("timeline-relink-video-node")).toBeNull();
    expect(onCreateVideoNode).not.toHaveBeenCalled();
  });

  it("shows an error and does not link when node creation fails", async () => {
    const manualTrack = makeTrack({
      track_id: "track_video",
      type: "video",
      clips: [
        makeClip({
          clip_id: "clip_manual",
          track_id: "track_video",
          source_node_id: null,
          label: "Manual shot",
        }),
      ],
    });
    vi.mocked(getTimeline).mockResolvedValue(
      makeTimeline({ tracks: [manualTrack] }),
    );
    const onCreateVideoNode = vi
      .fn()
      .mockRejectedValue(new Error("node creation boom"));

    render(
      <GlobalTimelinePanel
        workflowId={WORKFLOW_ID}
        workflowNodeIds={new Set()}
        onCreateVideoNode={onCreateVideoNode}
      />,
    );

    fireEvent.click(await screen.findByRole("button", { name: "Manual shot" }));
    fireEvent.click(screen.getByTestId("timeline-create-video-node"));

    const error = await screen.findByTestId("timeline-video-node-error");
    expect(error.textContent).toContain("node creation boom");
    expect(updateClip).not.toHaveBeenCalled();
  });
});

describe("GlobalTimelinePanel — subtitle authoring", () => {
  const subtitleTrack = makeTrack({
    track_id: "track_subtitle",
    type: "subtitle",
    name: "Subtitles",
    display_order: 5,
    clips: [
      makeClip({
        clip_id: "clip_sub_1",
        track_id: "track_subtitle",
        start_time: 1,
        duration: 2,
        label: "Intro cue",
        subtitle_text: "Hello world",
        subtitle_style: {
          font_size: 48,
          position: "bottom",
          primary_color: "#ffffff",
          outline_color: "#000000",
          bold: true,
          italic: false,
        },
      }),
    ],
  });

  const plainSubtitleTrack = makeTrack({
    track_id: "track_subtitle",
    type: "subtitle",
    name: "Subtitles",
    display_order: 5,
    clips: [
      makeClip({
        clip_id: "clip_sub_plain",
        track_id: "track_subtitle",
        start_time: 0,
        duration: 2,
        label: "Plain cue",
        subtitle_text: "Plain text",
      }),
    ],
  });

  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(getTimeline).mockResolvedValue(
      makeTimeline({ tracks: [videoTrack, subtitleTrack] }),
    );
    vi.mocked(getMediaToolchainCapabilities).mockResolvedValue({
      status: "ready",
      feature_flags: { audio_ducking: true },
    });
    vi.mocked(listLatestAudioDegradations).mockResolvedValue([]);
    vi.mocked(updateClip).mockImplementation(async (_workflowId, _clipId, patch) => ({
      ...makeClip(),
      ...patch,
      clip_id: _clipId as string,
    }));
    vi.mocked(createClip).mockResolvedValue(makeClip({ clip_id: "clip_sub_new" }));
  });

  afterEach(cleanup);

  it("saves subtitle text and full style payload for a subtitle clip", async () => {
    renderPanel();

    fireEvent.click(await screen.findByRole("button", { name: "Intro cue" }));
    const inspector = await screen.findByTestId("timeline-subtitle-editor");

    fireEvent.change(within(inspector).getByLabelText("Subtitle text"), {
      target: { value: "Updated line" },
    });
    fireEvent.change(within(inspector).getByLabelText("Subtitle font family"), {
      target: { value: "Noto Sans" },
    });
    fireEvent.change(within(inspector).getByLabelText("Subtitle font size"), {
      target: { value: "64" },
    });
    fireEvent.change(within(inspector).getByLabelText("Subtitle text colour"), {
      target: { value: "#ff8800" },
    });
    fireEvent.change(within(inspector).getByLabelText("Subtitle outline colour"), {
      target: { value: "#101010" },
    });
    fireEvent.change(within(inspector).getByLabelText("Subtitle position"), {
      target: { value: "top" },
    });
    fireEvent.click(within(inspector).getByLabelText("Subtitle bold"));
    fireEvent.click(within(inspector).getByLabelText("Subtitle italic"));

    fireEvent.click(
      within(screen.getByTestId("timeline-clip-inspector")).getByTestId(
        "timeline-inspector-save",
      ),
    );

    await waitFor(() => expect(updateClip).toHaveBeenCalledTimes(1));
    const payload = vi.mocked(updateClip).mock.calls[0][2];
    expect(payload.subtitle_text).toBe("Updated line");
    expect(payload.subtitle_style).toEqual({
      font_family: "Noto Sans",
      font_size: 64,
      primary_color: "#ff8800",
      outline_color: "#101010",
      position: "top",
      bold: false,
      italic: true,
    });
  });

  it("clears subtitle text and style when both are emptied", async () => {
    renderPanel();

    fireEvent.click(await screen.findByRole("button", { name: "Intro cue" }));
    const inspector = await screen.findByTestId("timeline-subtitle-editor");

    fireEvent.change(within(inspector).getByLabelText("Subtitle text"), {
      target: { value: "   " },
    });
    fireEvent.change(within(inspector).getByLabelText("Subtitle font size"), {
      target: { value: "" },
    });
    fireEvent.click(within(inspector).getByLabelText("Subtitle bold"));
    fireEvent.click(
      within(inspector).getByLabelText("Reset subtitle text colour to default"),
    );
    fireEvent.click(
      within(inspector).getByLabelText("Reset subtitle outline colour to default"),
    );
    fireEvent.change(within(inspector).getByLabelText("Subtitle position"), {
      target: { value: "" },
    });

    fireEvent.click(
      within(screen.getByTestId("timeline-clip-inspector")).getByTestId(
        "timeline-inspector-save",
      ),
    );

    await waitFor(() => expect(updateClip).toHaveBeenCalledTimes(1));
    const payload = vi.mocked(updateClip).mock.calls[0][2];
    expect(payload.subtitle_text).toBeNull();
    expect(payload.subtitle_style).toBeNull();
  });

  it("hydrates an unstyled subtitle cue into default form values", async () => {
    vi.mocked(getTimeline).mockResolvedValue(
      makeTimeline({ tracks: [plainSubtitleTrack] }),
    );
    renderPanel();

    fireEvent.click(await screen.findByRole("button", { name: "Plain cue" }));
    const inspector = await screen.findByTestId("timeline-subtitle-editor");

    expect(
      (within(inspector).getByLabelText("Subtitle text") as HTMLTextAreaElement)
        .value,
    ).toBe("Plain text");
    expect(
      (within(inspector).getByLabelText("Subtitle font size") as HTMLInputElement)
        .value,
    ).toBe("");
    expect(
      (within(inspector).getByLabelText("Subtitle bold") as HTMLInputElement).checked,
    ).toBe(false);
  });

  it("blocks save when the subtitle font size is out of range", async () => {
    renderPanel();

    fireEvent.click(await screen.findByRole("button", { name: "Intro cue" }));
    const inspector = await screen.findByTestId("timeline-subtitle-editor");
    fireEvent.change(within(inspector).getByLabelText("Subtitle font size"), {
      target: { value: "5" },
    });
    fireEvent.click(
      within(screen.getByTestId("timeline-clip-inspector")).getByTestId(
        "timeline-inspector-save",
      ),
    );

    expect(await screen.findByRole("alert")).toBeTruthy();
    expect(updateClip).not.toHaveBeenCalled();
  });

  it("shows the subtitle editor only for subtitle clips and never transitions", async () => {
    renderPanel();

    // Subtitle clip: subtitle editor visible, transitions hidden.
    fireEvent.click(await screen.findByRole("button", { name: "Intro cue" }));
    const clipInspector = await screen.findByTestId("timeline-clip-inspector");
    expect(
      within(clipInspector).getByTestId("timeline-subtitle-editor"),
    ).toBeTruthy();
    expect(
      within(clipInspector).queryByTestId("timeline-transitions"),
    ).toBeNull();

    // Video clip: transitions visible, subtitle editor hidden.
    fireEvent.click(screen.getByRole("button", { name: "Video clip 1" }));
    expect(
      within(clipInspector).getByTestId("timeline-transitions"),
    ).toBeTruthy();
    expect(
      within(clipInspector).queryByTestId("timeline-subtitle-editor"),
    ).toBeNull();
  });

  it("renders the subtitle text inside the clip row", async () => {
    const { container } = renderPanel();
    await screen.findByRole("button", { name: "Intro cue" });

    const row = container.querySelector('[data-clip-subtitle="Hello world"]');
    expect(row).not.toBeNull();
    expect(row?.textContent).toContain("Hello world");
    expect(row?.textContent).not.toContain("Intro cue");
  });

  it("creates a subtitle clip after the last cue via the track add button", async () => {
    renderPanel();

    fireEvent.click(await screen.findByTestId("timeline-add-subtitle"));

    await waitFor(() => expect(createClip).toHaveBeenCalledTimes(1));
    expect(vi.mocked(createClip).mock.calls[0]).toEqual([
      WORKFLOW_ID,
      {
        track_id: "track_subtitle",
        start_time: 3,
        duration: 2,
        subtitle_text: "New subtitle",
      },
    ]);
  });

  it("disables the add button on a locked subtitle track", async () => {
    const lockedTrack = { ...subtitleTrack, locked: true };
    vi.mocked(getTimeline).mockResolvedValue(
      makeTimeline({ tracks: [lockedTrack] }),
    );
    renderPanel();

    const addButton = await screen.findByTestId("timeline-add-subtitle");
    expect(addButton.hasAttribute("disabled")).toBe(true);
    fireEvent.click(addButton);
    expect(createClip).not.toHaveBeenCalled();
  });

  it("PATCHes subtitle_burn_in from the toolbar checkbox", async () => {
    const fixture = makeTimeline({ tracks: [subtitleTrack], subtitle_burn_in: true });
    stubTimelineSave(fixture);
    renderPanel();

    const checkbox = (await screen.findByLabelText(
      "Burn subtitles into exported video",
    )) as HTMLInputElement;
    expect(checkbox.checked).toBe(true);
    fireEvent.click(checkbox);

    await waitFor(() =>
      expect(updateTimeline).toHaveBeenCalledWith(WORKFLOW_ID, {
        subtitle_burn_in: false,
      }),
    );
  });

  it("links SRT and ASS sidecar downloads in the toolbar", async () => {
    renderPanel();

    const srt = await screen.findByTestId("timeline-subtitle-export-srt");
    expect(srt.getAttribute("href")).toBe(
      `/api/v2/workflows/${WORKFLOW_ID}/timeline/subtitles?format=srt`,
    );
    expect(srt.getAttribute("download")).toBe("subtitles.srt");
    const ass = screen.getByTestId("timeline-subtitle-export-ass");
    expect(ass.getAttribute("href")).toBe(
      `/api/v2/workflows/${WORKFLOW_ID}/timeline/subtitles?format=ass`,
    );
    expect(ass.getAttribute("download")).toBe("subtitles.ass");
  });
});

describe("GlobalTimelinePanel — voice clip character binding", () => {
  const CHARACTERS = [
    { id: "char_mei", label: "Mei" },
    { id: "char_robot", label: null },
  ];

  function renderBindingPanel(tracks: TimelineTrackV1[]) {
    vi.mocked(getTimeline).mockResolvedValue(makeTimeline({ tracks }));
    return render(
      <GlobalTimelinePanel
        workflowId={WORKFLOW_ID}
        availableCharacters={CHARACTERS}
      />,
    );
  }

  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(getMediaToolchainCapabilities).mockResolvedValue({
      status: "ready",
      feature_flags: { audio_ducking: false },
    });
    vi.mocked(listLatestAudioDegradations).mockResolvedValue([]);
    vi.mocked(updateClip).mockImplementation(async (_workflowId, _clipId, patch) => ({
      ...makeClip(),
      ...patch,
      clip_id: _clipId as string,
    }));
  });

  afterEach(cleanup);

  it("binds a voice clip to a canvas character and persists it", async () => {
    renderBindingPanel([voiceTrack, bgmTrack]);

    fireEvent.click(await screen.findByRole("button", { name: "Voice line 1" }));
    const inspector = await screen.findByTestId("timeline-clip-inspector");
    const select = within(inspector).getByLabelText(
      "Bound speaking character",
    ) as HTMLSelectElement;

    const optionValues = Array.from(select.options).map((option) => option.value);
    expect(optionValues).toEqual(["", "char_mei", "char_robot"]);

    fireEvent.change(select, { target: { value: "char_mei" } });
    fireEvent.click(within(inspector).getByTestId("timeline-inspector-save"));

    await waitFor(() => expect(updateClip).toHaveBeenCalledTimes(1));
    expect(vi.mocked(updateClip).mock.calls[0][2].bound_character_id).toBe(
      "char_mei",
    );
  });

  it("clears a binding by choosing Unbound and shows a speaker badge", async () => {
    const boundVoiceTrack: TimelineTrackV1 = {
      ...voiceTrack,
      clips: [
        makeClip({
          clip_id: "clip_voice_1",
          track_id: "track_voice",
          label: "Voice line 1",
          bound_character_id: "char_mei",
        }),
      ],
    };
    renderBindingPanel([boundVoiceTrack, bgmTrack]);

    const clip = (await screen.findAllByTestId("timeline-clip")).find(
      (element) => element.getAttribute("data-clip-character") === "char_mei",
    );
    expect(clip).toBeTruthy();
    expect(
      within(clip as HTMLElement).getByTestId("timeline-clip-character-badge"),
    ).toBeTruthy();

    fireEvent.click(await screen.findByRole("button", { name: "Voice line 1" }));
    const inspector = await screen.findByTestId("timeline-clip-inspector");
    const select = within(inspector).getByLabelText(
      "Bound speaking character",
    ) as HTMLSelectElement;
    expect(select.value).toBe("char_mei");

    fireEvent.change(select, { target: { value: "" } });
    fireEvent.click(within(inspector).getByTestId("timeline-inspector-save"));

    await waitFor(() => expect(updateClip).toHaveBeenCalledTimes(1));
    expect(vi.mocked(updateClip).mock.calls[0][2].bound_character_id).toBeNull();
  });

  it("offers no speaker binding on bgm clips", async () => {
    renderBindingPanel([voiceTrack, bgmTrack]);

    const clips = await screen.findAllByTestId("timeline-clip");
    const bgmClip = clips.find((element) =>
      (element.getAttribute("aria-label") ?? "").includes("8.00 seconds long"),
    );
    expect(bgmClip).toBeTruthy();
    fireEvent.click(bgmClip as HTMLElement);
    const inspector = await screen.findByTestId("timeline-clip-inspector");
    expect(
      within(inspector).queryByLabelText("Bound speaking character"),
    ).toBeNull();
  });
});

describe("GlobalTimelinePanel — beat detection", () => {
  const beatBgmTrack = makeTrack({
    track_id: "track_bgm",
    type: "bgm",
    name: "BGM",
    display_order: 2,
    clips: [
      makeClip({
        clip_id: "clip_bgm_1",
        track_id: "track_bgm",
        start_time: 0,
        duration: 8,
        source_start: 0,
        asset_id: "asset_bgm_1",
      }),
    ],
  });
  const TRACK_RECTS: Record<string, { top: number; bottom: number }> = {
    track_voice: { top: 72, bottom: 120 },
    track_bgm: { top: 120, bottom: 168 },
  };

  let rectSpy: ReturnType<typeof vi.spyOn>;

  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(getTimeline).mockResolvedValue(
      makeTimeline({ tracks: [voiceTrack, beatBgmTrack] }),
    );
    vi.mocked(getMediaToolchainCapabilities).mockResolvedValue({
      status: "ready",
      feature_flags: { audio_ducking: false },
    });
    vi.mocked(listLatestAudioDegradations).mockResolvedValue([]);
    vi.mocked(moveClip).mockResolvedValue(makeClip());
    vi.mocked(getClipBeats).mockResolvedValue({
      bpm: 120,
      beats: [0, 0.5, 1],
      confidence: 0.9,
    });

    rectSpy = vi
      .spyOn(HTMLElement.prototype, "getBoundingClientRect")
      .mockImplementation(function mockRect(this: HTMLElement) {
        const trackId = this.getAttribute?.("data-track-id");
        const bounds = trackId ? TRACK_RECTS[trackId] : undefined;
        const rect = bounds ?? { top: 0, bottom: 0 };
        return {
          left: bounds ? 150 : 0,
          right: bounds ? 1000 : 0,
          top: rect.top,
          bottom: rect.bottom,
          width: bounds ? 850 : 0,
          height: bounds ? rect.bottom - rect.top : 0,
          x: bounds ? 150 : 0,
          y: rect.top,
          toJSON: () => ({}),
        } as DOMRect;
      });
  });

  afterEach(() => {
    rectSpy.mockRestore();
    cleanup();
  });

  it("detects beats, shows the summary, and draws source-mapped markers", async () => {
    renderPanel();

    const clips = await screen.findAllByTestId("timeline-clip");
    const bgmClip = clips.find((element) =>
      (element.getAttribute("aria-label") ?? "").includes("8.00 seconds long"),
    ) as HTMLElement;
    fireEvent.click(bgmClip);
    const inspector = await screen.findByTestId("timeline-clip-inspector");

    fireEvent.click(within(inspector).getByTestId("timeline-detect-beats"));

    await waitFor(() => expect(getClipBeats).toHaveBeenCalledTimes(1));
    expect(vi.mocked(getClipBeats).mock.calls[0]).toEqual([
      WORKFLOW_ID,
      "clip_bgm_1",
    ]);
    expect(within(inspector).getByTestId("timeline-beat-summary").textContent).toBe(
      "120.0 BPM · 3 beats",
    );

    const markers = within(bgmClip).getAllByTestId("timeline-beat-marker");
    expect(markers).toHaveLength(3);
    expect(markers.map((marker) => (marker as HTMLElement).style.left)).toEqual([
      "0px",
      "20px",
      "40px",
    ]);
  });

  it("surfaces a friendly error when the clip has no audio asset", async () => {
    vi.mocked(getClipBeats).mockRejectedValue(
      new Error("This clip has no linked audio asset to analyze."),
    );
    renderPanel();

    fireEvent.click(await screen.findByRole("button", { name: "Voice line 1" }));
    const inspector = await screen.findByTestId("timeline-clip-inspector");

    fireEvent.click(within(inspector).getByTestId("timeline-detect-beats"));

    expect(
      await within(inspector).findByTestId("timeline-beat-error"),
    ).toBeTruthy();
    expect(within(inspector).getByTestId("timeline-beat-error").textContent).toBe(
      "This clip has no linked audio asset to analyze.",
    );
  });

  it("snaps a dragged clip to a detected beat and can be toggled off", async () => {
    renderPanel();

    const snapToggle = await screen.findByTestId("timeline-snap-beats");
    expect(snapToggle.getAttribute("aria-pressed")).toBe("true");

    // Analyze the BGM clip first so its beats become snap candidates.
    const clips = screen.getAllByTestId("timeline-clip");
    const bgmClip = clips.find((element) =>
      (element.getAttribute("aria-label") ?? "").includes("8.00 seconds long"),
    ) as HTMLElement;
    fireEvent.click(bgmClip);
    fireEvent.click(
      within(await screen.findByTestId("timeline-clip-inspector")).getByTestId(
        "timeline-detect-beats",
      ),
    );
    await waitFor(() => expect(getClipBeats).toHaveBeenCalledTimes(1));

    // Drag the voice clip +0.5s (20px): the 0.5s beat pulls the gold guide.
    const voiceClip = screen.getByRole("button", { name: "Voice line 1" });
    fireEvent.mouseDown(voiceClip, { clientX: 200, clientY: 96 });
    fireEvent.mouseMove(screen.getByTestId("timeline-scroll-container"), {
      clientX: 220,
      clientY: 96,
    });
    expect(screen.getByTestId("timeline-snap-guide")).toBeTruthy();
    fireEvent.mouseUp(screen.getByTestId("timeline-scroll-container"), {
      clientX: 220,
      clientY: 96,
    });

    fireEvent.click(snapToggle);
    expect(snapToggle.getAttribute("aria-pressed")).toBe("false");
  });
});

function SyncProbe() {
  const { playhead, setFromPreview } = usePlayheadSync();
  return (
    <>
      <span data-testid="sync-state">
        {`${playhead.origin}:${playhead.time.toFixed(3)}:${playhead.playing}`}
      </span>
      <button
        type="button"
        onClick={() => setFromPreview({ time: 1.5, playing: false })}
      >
        probe-preview-seek
      </button>
      <button type="button" onClick={() => setFromPreview({ playing: true })}>
        probe-preview-play
      </button>
    </>
  );
}

function renderPanelWithSync() {
  return render(
    <PlayheadSyncProvider>
      <GlobalTimelinePanel workflowId={WORKFLOW_ID} />
      <SyncProbe />
    </PlayheadSyncProvider>,
  );
}

describe("GlobalTimelinePanel — 3D preview playhead sync", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(getTimeline).mockResolvedValue(makeTimeline());
    vi.mocked(getMediaToolchainCapabilities).mockResolvedValue({
      status: "ready",
      feature_flags: { audio_ducking: false },
    });
    vi.mocked(listLatestAudioDegradations).mockResolvedValue([]);
  });

  afterEach(cleanup);

  it("reports frame steps to the shared playhead as timeline-origin", async () => {
    renderPanelWithSync();

    const nextFrame = await screen.findByTitle("Next frame");
    fireEvent.click(nextFrame);

    expect(screen.getByText("0.03s")).toBeTruthy();
    expect(screen.getByTestId("sync-state").textContent).toBe(
      "timeline:0.033:false",
    );
  });

  it("mirrors a preview-origin scrub onto its own playhead", async () => {
    renderPanelWithSync();

    await screen.findByTitle("Next frame");
    fireEvent.click(screen.getByText("probe-preview-seek"));

    expect(await screen.findByText("1.50s")).toBeTruthy();
    expect(screen.getByTestId("sync-state").textContent).toBe(
      "preview:1.500:false",
    );
  });

  it("starts its transport when a linked preview starts playing", async () => {
    renderPanelWithSync();

    await screen.findByTitle("Next frame");
    fireEvent.click(screen.getByText("probe-preview-play"));

    // Transport ownership flips to the timeline as soon as its RAF ticks.
    await waitFor(() =>
      expect(screen.getByTestId("sync-state").textContent).toMatch(
        /^timeline:.*:true$/,
      ),
    );
    // Stop the loop so RAF does not outlive the test.
    fireEvent.click(screen.getByTitle("Pause"));
    expect(screen.getByTitle("Play")).toBeTruthy();
  });
});

// ---------------------------------------------------------------------------
// External drag-in (ADR 0007 Phase 3.6): assets / camera moves -> tracks
// ---------------------------------------------------------------------------

/**
 * Minimal DataTransfer stand-in: jsdom does not implement the interface, and
 * the panel reads only `types`/`getData` while writing nothing on drop.
 */
function makeDataTransfer(entries: Record<string, string>) {
  return {
    types: Object.keys(entries),
    getData: (type: string) => entries[type] ?? "",
    setData: () => {},
  };
}

function dropPayload(payload: Record<string, unknown>): Record<string, string> {
  return { [TIMELINE_DROP_MIME]: JSON.stringify(payload) };
}

describe("GlobalTimelinePanel — external drag-in", () => {
  afterEach(cleanup);
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(getTimeline).mockResolvedValue(
      makeTimeline({
        tracks: [
          videoTrack,
          voiceTrack,
          bgmTrack,
          makeTrack({ track_id: "track_camera", type: "camera", name: "Camera", display_order: 3 }),
        ],
      }),
    );
    vi.mocked(getMediaToolchainCapabilities).mockResolvedValue({
      status: "ready",
      feature_flags: { audio_ducking: true },
    });
    vi.mocked(listLatestAudioDegradations).mockResolvedValue([]);
    vi.mocked(createClip).mockImplementation(async (_workflowId, payload) =>
      makeClip({
        clip_id: "clip_dropped",
        track_id: payload.track_id,
        start_time: payload.start_time ?? 0,
        duration: payload.duration ?? 2,
        asset_id: payload.asset_id ?? null,
        source_node_id: payload.source_node_id ?? null,
        label: payload.label ?? null,
      }),
    );
  });

  function videoTrackContent(): HTMLElement {
    return document.querySelector(
      '[data-track-id="track_video"]',
    ) as HTMLElement;
  }

  it("drops a video asset onto the video track at the snapped position", async () => {
    renderPanel();
    await screen.findAllByTestId("timeline-clip");
    const content = videoTrackContent();

    fireEvent.dragOver(content, {
      dataTransfer: makeDataTransfer(
        dropPayload({
          kind: "asset",
          asset_id: "asset_video_1",
          media_type: "video",
          label: "赌场内部",
          duration_seconds: 5.5,
        }),
      ),
    });
    expect(content.getAttribute("data-drop-hover")).toBe("valid");

    fireEvent.drop(content, {
      clientX: 150,
      dataTransfer: makeDataTransfer(
        dropPayload({
          kind: "asset",
          asset_id: "asset_video_1",
          media_type: "video",
          label: "赌场内部",
          duration_seconds: 5.5,
        }),
      ),
    });

    await waitFor(() => {
      expect(vi.mocked(createClip)).toHaveBeenCalledTimes(1);
    });
    const [workflowId, payload] = vi.mocked(createClip).mock.calls[0];
    expect(workflowId).toBe(WORKFLOW_ID);
    expect(payload.track_id).toBe("track_video");
    expect(payload.duration).toBe(5.5);
    expect(payload.asset_id).toBe("asset_video_1");
    expect(payload.label).toBe("赌场内部");
    // jsdom returns a zero rect for getBoundingClientRect -> start 0; the
    // quantization itself is unit-tested in timelineDropPayload.test.ts.
    expect(payload.start_time).toBeGreaterThanOrEqual(0);
  });

  it("marks incompatible tracks invalid on hover and still resolves a compatible one on drop", async () => {
    renderPanel();
    await screen.findAllByTestId("timeline-clip");
    const cameraContent = document.querySelector(
      '[data-track-id="track_camera"]',
    ) as HTMLElement;

    fireEvent.dragOver(cameraContent, {
      dataTransfer: makeDataTransfer(
        dropPayload({ kind: "asset", asset_id: "a", media_type: "audio" }),
      ),
    });
    expect(cameraContent.getAttribute("data-drop-hover")).toBe("invalid");

    fireEvent.drop(cameraContent, {
      clientX: 150,
      dataTransfer: makeDataTransfer(
        dropPayload({ kind: "asset", asset_id: "a", media_type: "audio" }),
      ),
    });
    await waitFor(() => {
      expect(vi.mocked(createClip)).toHaveBeenCalledTimes(1);
    });
    // audio cannot land on camera: falls back to the first audio track.
    expect(vi.mocked(createClip).mock.calls[0][1].track_id).toBe("track_voice");
  });

  it("drops a camera payload onto the camera track with the scene-3d node link", async () => {
    renderPanel();
    await screen.findAllByTestId("timeline-clip");
    const cameraContent = document.querySelector(
      '[data-track-id="track_camera"]',
    ) as HTMLElement;

    fireEvent.drop(cameraContent, {
      clientX: 150,
      dataTransfer: makeDataTransfer(
        dropPayload({
          kind: "camera",
          asset_id: "node_scene3d_1",
          media_type: "camera",
          camera_node_id: "node_scene3d_1",
          label: "B2 运镜",
        }),
      ),
    });

    await waitFor(() => {
      expect(vi.mocked(createClip)).toHaveBeenCalledTimes(1);
    });
    const payload = vi.mocked(createClip).mock.calls[0][1];
    expect(payload.track_id).toBe("track_camera");
    expect(payload.asset_id).toBeNull(); // camera clips have no media asset
    expect(payload.source_node_id).toBe("node_scene3d_1");
  });

  it("surfaces an error when no compatible track exists", async () => {
    vi.mocked(getTimeline).mockResolvedValue(
      makeTimeline({ tracks: [videoTrack] }),
    );
    renderPanel();
    await screen.findAllByTestId("timeline-clip");
    const cameraPayload = dropPayload({
      kind: "camera",
      asset_id: "node_scene3d_1",
      media_type: "camera",
    });

    fireEvent.drop(videoTrackContent(), {
      clientX: 150,
      dataTransfer: makeDataTransfer(cameraPayload),
    });

    await screen.findByTestId("timeline-drop-error");
    expect(vi.mocked(createClip)).not.toHaveBeenCalled();
  });

  it("ignores drags that do not carry the timeline payload", async () => {
    renderPanel();
    await screen.findAllByTestId("timeline-clip");
    const content = videoTrackContent();

    fireEvent.dragOver(content, {
      dataTransfer: makeDataTransfer({ "text/plain": "some random text" }),
    });
    fireEvent.drop(content, {
      clientX: 150,
      dataTransfer: makeDataTransfer({ "text/plain": "some random text" }),
    });

    expect(content.getAttribute("data-drop-hover")).toBeNull();
    expect(vi.mocked(createClip)).not.toHaveBeenCalled();
  });

  it("uses the source duration default when the payload has none", async () => {
    renderPanel();
    await screen.findAllByTestId("timeline-clip");

    fireEvent.drop(videoTrackContent(), {
      clientX: 150,
      dataTransfer: makeDataTransfer(
        dropPayload({ kind: "asset", asset_id: "a", media_type: "video" }),
      ),
    });

    await waitFor(() => {
      expect(vi.mocked(createClip)).toHaveBeenCalledTimes(1);
    });
    expect(vi.mocked(createClip).mock.calls[0][1].duration).toBe(3);
  });
});

// ---------------------------------------------------------------------------
// ADR 0008 phase switch (director / editor faces of one timeline)
// ---------------------------------------------------------------------------

describe("GlobalTimelinePanel — timeline phase switch", () => {
  afterEach(cleanup);
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(getTimeline).mockResolvedValue(
      makeTimeline({
        tracks: [
          makeTrack({
            track_id: "track_video",
            type: "video",
            name: "Video",
            display_order: 0,
            clips: [
              makeClip({
                clip_id: "clip_video_1",
                track_id: "track_video",
                label: "Video clip 1",
                start_time: 3,
                duration: 2,
                bound_character_id: "char_lin",
              }),
            ],
          }),
          voiceTrack,
        ],
      }),
    );
    vi.mocked(getMediaToolchainCapabilities).mockResolvedValue({
      status: "ready",
      feature_flags: { audio_ducking: true },
    });
    vi.mocked(listLatestAudioDegradations).mockResolvedValue([]);
  });

  it("defaults to the editor face with the switch visible", () => {
    renderPanel();
    const group = screen.getByTestId("timeline-phase-switch");
    expect(group).toBeTruthy();
    expect(screen.getByRole("button", { name: "剪辑态" }).getAttribute("aria-pressed")).toBe("true");
    // Editor face: no intent annotations, no director hint.
    expect(screen.queryByTestId("timeline-clip-intent")).toBeNull();
    expect(screen.queryByTestId("timeline-director-hint")).toBeNull();
  });

  it("director face annotates clips with their shot intent", async () => {
    renderPanel();
    // The fixture has two clips (video + voice): wait for the list, not one.
    await screen.findAllByTestId("timeline-clip");
    fireEvent.click(screen.getByRole("button", { name: "导演态" }));

    expect(screen.getByRole("button", { name: "导演态" }).getAttribute("aria-pressed")).toBe("true");
    expect(await screen.findByTestId("timeline-director-hint")).toBeTruthy();

    // The video clip shows its window (3.0–5.0s) and its speaker.
    const intents = screen.getAllByTestId("timeline-clip-intent");
    const videoIntent = intents.find((node) => node.textContent?.includes("3.0–5.0s"));
    expect(videoIntent).toBeTruthy();
    expect(videoIntent?.textContent).toContain("char_lin");
    // The voice clip is annotated too (its window), without a speaker here.
    const voiceIntent = intents.find((node) => node.textContent?.includes("0.0–2.0s"));
    expect(voiceIntent).toBeTruthy();
  });

  it("switches back to the editor face", async () => {
    renderPanel();
    await screen.findAllByTestId("timeline-clip");
    fireEvent.click(screen.getByRole("button", { name: "导演态" }));
    expect((await screen.findAllByTestId("timeline-clip-intent")).length).toBeGreaterThan(0);

    fireEvent.click(screen.getByRole("button", { name: "剪辑态" }));
    expect(screen.queryByTestId("timeline-clip-intent")).toBeNull();
    expect(screen.queryByTestId("timeline-director-hint")).toBeNull();
  });
});

// ---------------------------------------------------------------------------
// ADR 0008 P2: director-face shot-intent summary in the inspector
// ---------------------------------------------------------------------------

describe("GlobalTimelinePanel — director shot intent summary", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(getTimeline).mockResolvedValue(
      makeTimeline({
        tracks: [
          makeTrack({
            track_id: "track_video",
            type: "video",
            name: "Video",
            display_order: 0,
            clips: [
              makeClip({
                clip_id: "clip_video_dir",
                track_id: "track_video",
                label: "Intent clip",
                start_time: 3,
                duration: 2,
                bound_character_id: "char_lin",
              }),
            ],
          }),
          voiceTrack,
        ],
      }),
    );
    vi.mocked(getMediaToolchainCapabilities).mockResolvedValue({
      status: "ready",
      feature_flags: { audio_ducking: true },
    });
    vi.mocked(listLatestAudioDegradations).mockResolvedValue([]);
    vi.mocked(updateClip).mockImplementation(async (_workflowId, _clipId, patch) => ({
      ...makeClip(),
      ...patch,
      clip_id: _clipId as string,
    }));
  });

  afterEach(cleanup);

  it("shows the shot-intent summary for a video clip in director face", async () => {
    renderPanel();
    fireEvent.click(await screen.findByRole("button", { name: "Intent clip" }));
    await screen.findByTestId("timeline-clip-inspector");

    // Editor face: no intent summary.
    expect(screen.queryByTestId("timeline-clip-director-summary")).toBeNull();

    fireEvent.click(screen.getByRole("button", { name: "导演态" }));
    const summary = await screen.findByTestId("timeline-clip-director-summary");
    expect(summary.textContent).toContain("镜头意图");
    expect(summary.textContent).toContain("3–5.0s");
    expect(summary.textContent).toContain("char_lin");
    expect(summary.textContent).toContain("预演/语音参考切片驱动视频生成");
  });

  it("shows the lip-sync intent for a voice clip in director face", async () => {
    renderPanel();
    fireEvent.click(await screen.findByRole("button", { name: "Voice line 1" }));
    await screen.findByTestId("timeline-clip-inspector");

    fireEvent.click(screen.getByRole("button", { name: "导演态" }));
    const summary = await screen.findByTestId("timeline-clip-director-summary");
    expect(summary.textContent).toContain("台词音频驱动 3D 唇形关键帧");
  });
});


describe("GlobalTimelinePanel — workflow operation isolation", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(getTimeline).mockImplementation(async (workflowId) => makeTimeline({ workflow_id: workflowId, tracks: [videoTrack, voiceTrack, bgmTrack] }));
    vi.mocked(getMediaToolchainCapabilities).mockResolvedValue({ status: "ready", feature_flags: { audio_ducking: true } });
    vi.mocked(listLatestAudioDegradations).mockResolvedValue([]);
  });
  afterEach(cleanup);

  it.each(["track", "burn-in", "ducking"])("does not let old %s rejection/finally release a new operation after A → B → A", async (kind) => {
    let rejectOld!: (error: Error) => void;
    let resolveNew!: () => void;
    const old = new Promise<never>((_, no) => { rejectOld = no; });
    const next = new Promise<never>((yes) => { resolveNew = () => yes(undefined as never); });
    if (kind === "track") vi.mocked(updateTrack).mockReturnValueOnce(old).mockReturnValueOnce(next);
    else vi.mocked(updateTimeline).mockReturnValueOnce(old).mockReturnValueOnce(next);
    const trigger = () => {
      if (kind === "track") fireEvent.click(screen.getByRole("button", { name: "Mute Voice" }));
      else if (kind === "burn-in") fireEvent.click(within(screen.getByTestId("timeline-subtitle-burn-in")).getByRole("checkbox"));
      else {
        fireEvent.click(screen.getByTitle("Auto-ducking settings (lower BGM while voice plays)"));
        fireEvent.click(screen.getByTestId("timeline-ducking-save"));
      }
    };
    const view = renderPanel();
    await screen.findByRole("button", { name: "Video clip 1" });
    trigger();
    view.rerender(<GlobalTimelinePanel workflowId="B" />);
    await screen.findByRole("button", { name: "Video clip 1" });
    view.rerender(<GlobalTimelinePanel workflowId={WORKFLOW_ID} />);
    await screen.findByRole("button", { name: "Video clip 1" });
    trigger();
    const calls = vi.mocked(getTimeline).mock.calls.length;
    await act(async () => rejectOld(new Error("Stale operation")));
    expect(screen.queryByText("Stale operation")).toBeNull();
    expect(getTimeline).toHaveBeenCalledTimes(calls);
    const busy = kind === "track" ? screen.getByRole("button", { name: "Unmute Voice" })
      : kind === "burn-in" ? within(screen.getByTestId("timeline-subtitle-burn-in")).getByRole("checkbox")
      : screen.getByTestId("timeline-ducking-save");
    expect((busy as HTMLButtonElement).disabled).toBe(true);
    // Unmount invalidates the new operation before settling its fixture promise.
    view.unmount();
    await act(async () => resolveNew());
  });


  it("ignores a beat rejection after selecting away and back without clearing the newer loading state", async () => {
    let rejectOld!: (error: Error) => void;
    let rejectNew!: (error: Error) => void;
    vi.mocked(getClipBeats)
      .mockReturnValueOnce(new Promise((_, no) => { rejectOld = no; }))
      .mockReturnValueOnce(new Promise((_, no) => { rejectNew = no; }));
    const view = renderPanel();
    const bgm = await screen.findByRole("button", { name: "Clip from 0.00 seconds, 8.00 seconds long" });
    fireEvent.click(bgm);
    fireEvent.click(screen.getByTestId("timeline-detect-beats"));
    fireEvent.click(screen.getByRole("button", { name: "Video clip 1" }));
    fireEvent.click(bgm);
    fireEvent.click(screen.getByTestId("timeline-detect-beats"));
    expect(getClipBeats).toHaveBeenCalledTimes(2);
    await act(async () => rejectOld(new Error("Old beat failure")));
    expect(screen.queryByText("Old beat failure")).toBeNull();
    expect((screen.getByTestId("timeline-detect-beats") as HTMLButtonElement).disabled).toBe(true);
    view.unmount();
    await act(async () => rejectNew(new Error("Unmounted analysis")));
  });

  it("does not link an old promoted node into a re-entered workflow", async () => {
    let resolve!: (id: string) => void;
    const create = vi.fn(() => new Promise<string>((yes) => { resolve = yes; }));
    const view = render(<GlobalTimelinePanel workflowId={WORKFLOW_ID} onCreateVideoNode={create} />);
    fireEvent.click(await screen.findByRole("button", { name: "Video clip 1" }));
    fireEvent.click(screen.getByTestId("timeline-create-video-node"));
    view.rerender(<GlobalTimelinePanel workflowId="B" onCreateVideoNode={create} />);
    await screen.findByRole("button", { name: "Video clip 1" });
    view.rerender(<GlobalTimelinePanel workflowId={WORKFLOW_ID} onCreateVideoNode={create} />);
    await screen.findByRole("button", { name: "Video clip 1" });
    await act(async () => resolve("old-node"));
    expect(updateClip).not.toHaveBeenCalled();
    expect(screen.queryByText(/Failed to create/)).toBeNull();
    expect(screen.getByRole("button", { name: "Video clip 1" })).toBeTruthy();
  });
});
