/**
 * PlayheadSyncContext - bridges the global timeline transport and the 3D
 * scene-script previews rendered inside canvas nodes.
 *
 * Time is shared in seconds (not frames) so timelines and scenes with
 * different frame rates stay aligned; each side quantizes to its own fps
 * when seeking.
 *
 * `origin` records who last moved the playhead. The other side mirrors the
 * update, while the originator ignores it, preventing RAF echo loops.
 */

import {
  createContext,
  useCallback,
  useContext,
  useMemo,
  useState,
  type ReactNode,
} from "react";

export type PlayheadOrigin = "timeline" | "preview";

export interface PlayheadState {
  /** Playhead position in seconds. */
  time: number;
  /** Whether the originator transport is playing. */
  playing: boolean;
  /** Side that produced the latest update. */
  origin: PlayheadOrigin;
}

export interface PlayheadSyncContextValue {
  playhead: PlayheadState;
  /** Timeline transport reports a local scrub or tick. */
  setFromTimeline: (
    patch: Partial<Pick<PlayheadState, "time" | "playing">>,
  ) => void;
  /** A 3D preview reports a local scrub or play/pause toggle. */
  setFromPreview: (
    patch: Partial<Pick<PlayheadState, "time" | "playing">>,
  ) => void;
}

const PlayheadSyncContext = createContext<PlayheadSyncContextValue | null>(null);

export function PlayheadSyncProvider({ children }: { children: ReactNode }) {
  const [playhead, setPlayhead] = useState<PlayheadState>({
    time: 0,
    playing: false,
    origin: "timeline",
  });

  const setFromTimeline = useCallback<
    PlayheadSyncContextValue["setFromTimeline"]
  >((patch) => {
    setPlayhead((previous) => ({ ...previous, ...patch, origin: "timeline" }));
  }, []);

  const setFromPreview = useCallback<
    PlayheadSyncContextValue["setFromPreview"]
  >((patch) => {
    setPlayhead((previous) => ({ ...previous, ...patch, origin: "preview" }));
  }, []);

  const value = useMemo<PlayheadSyncContextValue>(
    () => ({ playhead, setFromTimeline, setFromPreview }),
    [playhead, setFromTimeline, setFromPreview],
  );

  return (
    <PlayheadSyncContext.Provider value={value}>
      {children}
    </PlayheadSyncContext.Provider>
  );
}

/** Returns the sync bridge, or null when rendered outside the canvas page. */
export function useOptionalPlayheadSync(): PlayheadSyncContextValue | null {
  return useContext(PlayheadSyncContext);
}

export function usePlayheadSync(): PlayheadSyncContextValue {
  const context = useContext(PlayheadSyncContext);
  if (!context) {
    throw new Error("usePlayheadSync must be used within a PlayheadSyncProvider");
  }
  return context;
}
