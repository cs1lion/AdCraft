import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import {
  SceneScriptPlaybackProvider,
  useSceneScriptPlayback,
} from "./SceneScriptPlaybackContext.tsx";

const SCENE = {
  scene: {
    name: "Test scene",
    environment: "indoor",
    lighting: "neutral",
    duration: 5,
    frame_rate: 30,
  },
  characters: [],
  props: [],
  environment: [],
  cameras: [],
  shots: [],
  speech_bindings: [],
};

function Harness() {
  const { currentFrame, currentTime, isPlaying, toggle, seekToTime } =
    useSceneScriptPlayback();
  return (
    <div>
      <span data-testid="frame">{currentFrame}</span>
      <span data-testid="time">{currentTime.toFixed(3)}</span>
      <span data-testid="playing">{String(isPlaying)}</span>
      <button onClick={toggle}>toggle</button>
      <button onClick={() => seekToTime(2)}>seek-local</button>
    </div>
  );
}

afterEach(() => {
  cleanup();
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

describe("local scene playback clock", () => {
  function manualFrames() {
    let nextId = 0;
    const pending = new Map<number, FrameRequestCallback>();
    vi.stubGlobal("requestAnimationFrame", (callback: FrameRequestCallback) => {
      pending.set(++nextId, callback); return nextId;
    });
    vi.stubGlobal("cancelAnimationFrame", (id: number) => pending.delete(id));
    return (time: number) => act(() => {
      const current = [...pending.values()]; pending.clear();
      for (const callback of current) callback(time);
    });
  }

  it("plays all 60 frames, holds frame59 at the end, then replays from zero", () => {
    const tick = manualFrames();
    const onPlayingChange = vi.fn();
    render(<SceneScriptPlaybackProvider sceneScript={{ scene: { duration: 2, frame_rate: 30 } }} onPlayingChange={onPlayingChange}><Harness /></SceneScriptPlaybackProvider>);
    fireEvent.click(screen.getByText("toggle"));
    tick(0);
    for (let time = 16; time <= 2000; time += 16) tick(time);
    expect(screen.getByTestId("frame").textContent).toBe("59");
    expect(screen.getByTestId("playing").textContent).toBe("false");
    expect(onPlayingChange).toHaveBeenLastCalledWith(false);
    fireEvent.click(screen.getByText("toggle"));
    expect(screen.getByTestId("frame").textContent).toBe("0");
    tick(4000); tick(5000);
    expect(screen.getByTestId("frame").textContent).toBe("30");
  });

  it("retains subframe elapsed time across React commits and resumes without a wall-clock jump", () => {
    const tick = manualFrames();
    render(<SceneScriptPlaybackProvider sceneScript={SCENE}><Harness /></SceneScriptPlaybackProvider>);
    fireEvent.click(screen.getByText("toggle")); tick(0);
    for (let time = 10; time <= 1000; time += 10) tick(time);
    expect(screen.getByTestId("frame").textContent).toBe("30");
    fireEvent.click(screen.getByText("toggle")); tick(5000);
    expect(screen.getByTestId("frame").textContent).toBe("30");
    fireEvent.click(screen.getByText("toggle")); tick(6000); tick(6500);
    expect(screen.getByTestId("frame").textContent).toBe("45");
  });
});

describe("SceneScriptPlaybackProvider external sync", () => {
  it("seeks to an externally driven time, quantized to its fps", () => {
    const onTimeChange = vi.fn();
    render(
      <SceneScriptPlaybackProvider
        sceneScript={SCENE}
        externalPlayhead={{ time: 1, playing: false }}
        onTimeChange={onTimeChange}
      >
        <Harness />
      </SceneScriptPlaybackProvider>,
    );

    expect(screen.getByTestId("frame").textContent).toBe("30");
    expect(screen.getByTestId("time").textContent).toBe("1.000");
    // External seeks must not echo back through onTimeChange.
    expect(onTimeChange).not.toHaveBeenCalled();
  });

  it("clamps external time into the scene duration", () => {
    render(
      <SceneScriptPlaybackProvider
        sceneScript={SCENE}
        externalPlayhead={{ time: 99, playing: false }}
      >
        <Harness />
      </SceneScriptPlaybackProvider>,
    );

    // duration 5s @ 30fps -> last frame is 150 - 1.
    expect(screen.getByTestId("frame").textContent).toBe("149");
  });

  it("mirrors external play state without reporting onPlayingChange", () => {
    const onPlayingChange = vi.fn();
    render(
      <SceneScriptPlaybackProvider
        sceneScript={SCENE}
        externalPlayhead={{ time: 0, playing: true }}
        onPlayingChange={onPlayingChange}
      >
        <Harness />
      </SceneScriptPlaybackProvider>,
    );

    expect(screen.getByTestId("playing").textContent).toBe("true");
    expect(onPlayingChange).not.toHaveBeenCalled();
  });

  it("reports local toggles and seeks when no external transport drives it", () => {
    const onTimeChange = vi.fn();
    const onPlayingChange = vi.fn();
    render(
      <SceneScriptPlaybackProvider
        sceneScript={SCENE}
        onTimeChange={onTimeChange}
        onPlayingChange={onPlayingChange}
      >
        <Harness />
      </SceneScriptPlaybackProvider>,
    );

    fireEvent.click(screen.getByText("toggle"));
    expect(onPlayingChange).toHaveBeenCalledWith(true);

    fireEvent.click(screen.getByText("seek-local"));
    expect(onTimeChange).toHaveBeenCalledWith(2, 60);
  });
});
