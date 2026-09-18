/**
 * SceneScript Playback Context - shared playback state for 3D preview.
 *
 * Moves playback state (current time, playing status) out of the
 * SceneScript3DPreview component so that:
 * 1. Switching tabs in SceneScriptPanel does not lose playback position
 * 2. Info/JSON tabs can display current frame / active shot
 * 3. External components (e.g., EditingTimeline) can sync via onTimeChange
 *
 * Usage:
 *   <SceneScriptPlaybackProvider sceneScript={script} onTimeChange={cb}>
 *     <SceneScript3DPreview />
 *     <SceneInfoPanel />
 *   </SceneScriptPlaybackProvider>
 *
 *   const { currentFrame, isPlaying, play, pause, toggle, seek } = useSceneScriptPlayback();
 */

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";

// Minimal structural slice of a scene script needed for playback timing.
// (Kept local so this context does not depend on scene-script authoring types.)
interface PlaybackSceneScript {
  scene: { frame_rate: number; duration: number };
}

// ---------------------------------------------------------------------------
// Context value type
// ---------------------------------------------------------------------------

export interface SceneScriptPlaybackContextValue {
  /** Current frame number (0-indexed) */
  currentFrame: number;
  /** Current time in seconds */
  currentTime: number;
  /** Whether playback is active */
  isPlaying: boolean;
  /** Total number of frames in the scene */
  totalFrames: number;
  /** Scene duration in seconds */
  duration: number;
  /** Frames per second */
  fps: number;
  /** Start playback */
  play: () => void;
  /** Pause playback */
  pause: () => void;
  /** Toggle play/pause */
  toggle: () => void;
  /** Seek to a specific frame */
  seekToFrame: (frame: number) => void;
  /** Seek to a specific time in seconds */
  seekToTime: (time: number) => void;
  /** Reset to frame 0 and pause */
  reset: () => void;
}

const SceneScriptPlaybackContext =
  createContext<SceneScriptPlaybackContextValue | null>(null);

// ---------------------------------------------------------------------------
// Hook
// ---------------------------------------------------------------------------

export function useSceneScriptPlayback(): SceneScriptPlaybackContextValue {
  const ctx = useContext(SceneScriptPlaybackContext);
  if (!ctx) {
    throw new Error(
      "useSceneScriptPlayback must be used within a SceneScriptPlaybackProvider",
    );
  }
  return ctx;
}

// ---------------------------------------------------------------------------
// Provider
// ---------------------------------------------------------------------------

export interface SceneScriptPlaybackProviderProps {
  sceneScript: PlaybackSceneScript;
  children: ReactNode;
  /** Optional callback when playback time changes (for external sync) */
  onTimeChange?: (timeSeconds: number, frame: number) => void;
  /** Optional callback when play/pause state changes (for external sync) */
  onPlayingChange?: (playing: boolean) => void;
  /**
   * Externally driven transport (e.g. the global timeline). When provided,
   * the provider mirrors the time/playing state; its own RAF ticks do not
   * echo time updates back while the external side is the clock source.
   */
  externalPlayhead?: { time: number; playing: boolean } | null;
  /** Auto-play on mount */
  autoPlay?: boolean;
}

export function SceneScriptPlaybackProvider({
  sceneScript,
  children,
  onTimeChange,
  onPlayingChange,
  externalPlayhead = null,
  autoPlay = false,
}: SceneScriptPlaybackProviderProps) {
  const fps = sceneScript.scene.frame_rate;
  const duration = sceneScript.scene.duration;
  const totalFrames = Math.max(1, Math.round(duration * fps));

  const [currentFrame, setCurrentFrame] = useState(0);
  const [isPlaying, setIsPlaying] = useState(autoPlay);

  // Refs for the animation loop (avoid stale closures)
  const frameRef = useRef(0);
  const lastTimeRef = useRef<number | null>(null);
  const rafRef = useRef<number | null>(null);
  const onTimeChangeRef = useRef(onTimeChange);
  onTimeChangeRef.current = onTimeChange;
  const onPlayingChangeRef = useRef(onPlayingChange);
  onPlayingChangeRef.current = onPlayingChange;
  // True while an external transport (global timeline) owns the clock; our
  // RAF ticks then advance visuals without echoing time updates back.
  const externallyDrivenRef = useRef(false);

  // Keep frameRef in sync with currentFrame when seeking
  useEffect(() => {
    frameRef.current = currentFrame;
  }, [currentFrame]);

  // Mirror externally driven seeks (time in seconds; quantize to our fps).
  const externalTime = externalPlayhead?.time;
  const externalPlaying = externalPlayhead?.playing;
  useEffect(() => {
    if (externalTime === undefined) return;
    const targetFrame = Math.max(
      0,
      Math.min(totalFrames - 1, Math.round(externalTime * fps)),
    );
    frameRef.current = targetFrame;
    setCurrentFrame((previous) => (previous === targetFrame ? previous : targetFrame));
  }, [externalTime, fps, totalFrames]);

  useEffect(() => {
    if (externalPlaying === undefined) return;
    externallyDrivenRef.current = externalPlaying;
    setIsPlaying((previous) =>
      previous === externalPlaying ? previous : externalPlaying,
    );
  }, [externalPlaying]);

  // Animation loop using requestAnimationFrame
  useEffect(() => {
    if (!isPlaying) {
      lastTimeRef.current = null;
      if (rafRef.current !== null) {
        cancelAnimationFrame(rafRef.current);
        rafRef.current = null;
      }
      return;
    }

    const tick = (timestamp: number) => {
      if (lastTimeRef.current === null) {
        lastTimeRef.current = timestamp;
      }
      const deltaSeconds = (timestamp - lastTimeRef.current) / 1000;
      lastTimeRef.current = timestamp;

      // Advance frame based on real elapsed time
      frameRef.current = (frameRef.current + deltaSeconds * fps) % totalFrames;
      const newFrame = Math.floor(frameRef.current);

      setCurrentFrame(newFrame);

      // Notify external listener, unless an external transport owns the clock.
      if (onTimeChangeRef.current && !externallyDrivenRef.current) {
        onTimeChangeRef.current(newFrame / fps, newFrame);
      }

      rafRef.current = requestAnimationFrame(tick);
    };

    rafRef.current = requestAnimationFrame(tick);

    return () => {
      if (rafRef.current !== null) {
        cancelAnimationFrame(rafRef.current);
        rafRef.current = null;
      }
    };
  }, [isPlaying, fps, totalFrames]);

  // Playback controls
  const play = useCallback(() => {
    setIsPlaying(true);
    if (!externallyDrivenRef.current) onPlayingChangeRef.current?.(true);
  }, []);
  const pause = useCallback(() => {
    setIsPlaying(false);
    if (!externallyDrivenRef.current) onPlayingChangeRef.current?.(false);
  }, []);
  const toggle = useCallback(() => {
    setIsPlaying((currentlyPlaying) => {
      if (!externallyDrivenRef.current) {
        onPlayingChangeRef.current?.(!currentlyPlaying);
      }
      return !currentlyPlaying;
    });
  }, []);

  const seekToFrame = useCallback(
    (frame: number) => {
      const clamped = Math.max(0, Math.min(totalFrames - 1, Math.floor(frame)));
      frameRef.current = clamped;
      setCurrentFrame(clamped);
      if (onTimeChangeRef.current && !externallyDrivenRef.current) {
        onTimeChangeRef.current(clamped / fps, clamped);
      }
    },
    [totalFrames, fps],
  );

  const seekToTime = useCallback(
    (time: number) => {
      seekToFrame(time * fps);
    },
    [seekToFrame, fps],
  );

  const reset = useCallback(() => {
    setIsPlaying(false);
    frameRef.current = 0;
    setCurrentFrame(0);
    if (!externallyDrivenRef.current) {
      onPlayingChangeRef.current?.(false);
      onTimeChangeRef.current?.(0, 0);
    }
  }, []);

  const value = useMemo<SceneScriptPlaybackContextValue>(
    () => ({
      currentFrame,
      currentTime: currentFrame / fps,
      isPlaying,
      totalFrames,
      duration,
      fps,
      play,
      pause,
      toggle,
      seekToFrame,
      seekToTime,
      reset,
    }),
    [currentFrame, isPlaying, totalFrames, duration, fps, play, pause, toggle, seekToFrame, seekToTime, reset],
  );

  return (
    <SceneScriptPlaybackContext.Provider value={value}>
      {children}
    </SceneScriptPlaybackContext.Provider>
  );
}
