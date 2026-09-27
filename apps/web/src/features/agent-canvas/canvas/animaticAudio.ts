/**
 * Animatic audio sync — the playhead drives the voice.
 *
 * V0.2 §7/§14.9: Preview must be a JUDGEABLE review surface. The picture is
 * low-poly, but the voice is the real thing, and the author has to be able to
 * hear it at the right moment — while playing AND while scrubbing ("播放、
 * Scrub、指出问题"). So the audio element follows the playhead both ways:
 *
 * - playing: the audio runs in real time beside the rAF frame clock;
 * - scrubbing/paused: the audio SEEKs to the frame's time, so dragging the
 *   playhead previews the dialogue exactly where the frame is.
 *
 * The seek rule is deliberately drift-tolerant: while playing, the audio
 * element owns the clock and the frames follow it, so a small difference
 * must NOT trigger a seek (that would stutter the voice every tick).
 */

/** The audio time (seconds) a frame maps to. */
export function audioTimeForFrame(frame: number, frameRate: number): number {
  if (frameRate <= 0 || !Number.isFinite(frameRate)) return 0;
  return Math.max(0, frame) / frameRate;
}

/** Beyond this drift (seconds) the audio element is re-seeked. */
export const AUDIO_SEEK_TOLERANCE_SECONDS = 0.2;

/**
 * Whether the audio element should be re-seeked to the frame's time.
 *
 * `audioTime` is the element's currentTime. Scrubbing moves it far from the
 * frame's time (seek); natural playback keeps it close (no seek — the audio
 * IS the clock while playing).
 */
export function shouldSeekAudio(
  frame: number,
  frameRate: number,
  audioTime: number,
  tolerance: number = AUDIO_SEEK_TOLERANCE_SECONDS,
): boolean {
  const target = audioTimeForFrame(frame, frameRate);
  return Math.abs(audioTime - target) > tolerance;
}

/** Format a time for the review surface's readout (m:ss.t). */
export function formatAnimaticTime(seconds: number): string {
  const safe = Number.isFinite(seconds) && seconds > 0 ? seconds : 0;
  const minutes = Math.floor(safe / 60);
  const rest = safe - minutes * 60;
  return `${minutes}:${rest.toFixed(1).padStart(4, "0")}`;
}
