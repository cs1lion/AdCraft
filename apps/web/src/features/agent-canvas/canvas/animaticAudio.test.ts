import { describe, expect, it } from "vitest";

import {
  AUDIO_SEEK_TOLERANCE_SECONDS,
  audioTimeForFrame,
  formatAnimaticTime,
  shouldSeekAudio,
} from "./animaticAudio";

describe("animaticAudio", () => {
  it("maps frames to audio seconds with the scene's frame rate", () => {
    expect(audioTimeForFrame(0, 30)).toBe(0);
    expect(audioTimeForFrame(30, 30)).toBe(1);
    expect(audioTimeForFrame(45, 30)).toBe(1.5);
    expect(audioTimeForFrame(10, 0)).toBe(0); // a broken fps must not NaN
    expect(audioTimeForFrame(-5, 30)).toBe(0); // clamped, never negative
  });

  it("seeks when the playhead is dragged far from the audio position", () => {
    // Scrubbing to frame 150 at 30fps while the audio sits at 2s.
    expect(shouldSeekAudio(150, 30, 2)).toBe(true);
    // A frame 0.1s ahead of the audio is normal playback drift.
    expect(shouldSeekAudio(33, 30, 1)).toBe(false);
  });

  it("respects a custom tolerance", () => {
    expect(shouldSeekAudio(60, 30, 1.5, 0.05)).toBe(true);
    expect(shouldSeekAudio(60, 30, 1.5, 1)).toBe(false);
  });

  it("exposes a positive tolerance for the docs and tests", () => {
    expect(AUDIO_SEEK_TOLERANCE_SECONDS).toBeGreaterThan(0);
  });

  it("formats the review readout", () => {
    expect(formatAnimaticTime(0)).toBe("0:00.0");
    expect(formatAnimaticTime(9.5)).toBe("0:09.5");
    expect(formatAnimaticTime(75.2)).toBe("1:15.2");
    expect(formatAnimaticTime(Number.NaN)).toBe("0:00.0");
  });
});
