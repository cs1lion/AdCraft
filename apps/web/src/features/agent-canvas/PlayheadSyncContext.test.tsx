import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import {
  PlayheadSyncProvider,
  usePlayheadSync,
} from "./PlayheadSyncContext.tsx";

function Probe() {
  const { playhead, setFromTimeline, setFromPreview } = usePlayheadSync();
  return (
    <div>
      <span data-testid="state">
        {`${playhead.origin}:${playhead.time.toFixed(3)}:${playhead.playing}`}
      </span>
      <button
        onClick={() => setFromTimeline({ time: 2.5, playing: true })}
      >
        timeline-update
      </button>
      <button
        onClick={() => setFromPreview({ time: 4.0, playing: false })}
      >
        preview-update
      </button>
    </div>
  );
}

afterEach(cleanup);

describe("PlayheadSyncContext", () => {
  it("starts paused at time 0 owned by the timeline", () => {
    render(
      <PlayheadSyncProvider>
        <Probe />
      </PlayheadSyncProvider>,
    );
    expect(screen.getByTestId("state").textContent).toBe("timeline:0.000:false");
  });

  it("tags updates with their origin so each side can ignore echoes", () => {
    render(
      <PlayheadSyncProvider>
        <Probe />
      </PlayheadSyncProvider>,
    );

    fireEvent.click(screen.getByText("timeline-update"));
    expect(screen.getByTestId("state").textContent).toBe("timeline:2.500:true");

    fireEvent.click(screen.getByText("preview-update"));
    expect(screen.getByTestId("state").textContent).toBe("preview:4.000:false");
  });
});
