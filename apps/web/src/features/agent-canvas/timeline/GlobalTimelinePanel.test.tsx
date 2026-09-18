import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { GlobalTimelinePanel } from "./GlobalTimelinePanel.tsx";
import type {
  TimelineClipV1,
  TimelineDuckingConfigV1,
  TimelineTrackV1,
  TimelineV1,
} from "./timelineTypes.ts";
import {
  deleteClip,
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
  updateClip: vi.fn(),
  moveClip: vi.fn(),
  deleteClip: vi.fn(),
  getMediaToolchainCapabilities: vi.fn(),
  listLatestAudioDegradations: vi.fn(),
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

  it("shows a render note for wipe/slide transitions", async () => {
    renderPanel();

    fireEvent.click(await screen.findByRole("button", { name: "Video clip 1" }));
    const inspector = await screen.findByTestId("timeline-clip-inspector");

    expect(
      within(inspector).queryByTestId("timeline-transition-render-note"),
    ).toBeNull();
    fireEvent.change(within(inspector).getByTestId("timeline-transition-in-type"), {
      target: { value: "slide" },
    });
    expect(
      within(inspector).getByTestId("timeline-transition-render-note").textContent,
    ).toMatch(/exported as a cut/);
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
