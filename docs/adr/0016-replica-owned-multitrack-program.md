# ADR 0016: Replica-owned multitrack programs use one assembly clock

Status: Accepted for the initial authored-shot composition implementation.

## Context
Canvas TimelineV1 and canonical Final Composition V2 are distinct storage projections. Simple sequence rendering ignored the authored four-second shot windows when the provider delivered longer media. It also cannot consume canonical subtitle/audio editing controls. A third render/execution chain would worsen that split.

## Decision
- Build one pure replica composition plan from the existing ordered AssemblyPlan. Quantize program placements to the Canvas FPS; pin source asset versions and apply explicit source trim.
- Project the same program into Canvas and canonical V2 using the existing bridge and Final Composition renderer. Explicit replica programs and user-edited canonical timelines use `timeline_editor` locally, without changing the installation default.
- Captions are authored `on_screen_text` within the corresponding shot program window. `authored_shot` does not mean measured speech alignment or karaoke timing. Never reuse reference-video word timings as timings of newly generated narration.
- Select voice/BGM/SFX only from existing pinned assets. No automatic TTS/music generation or reference-audio extraction is introduced. Source-video audio is explicitly muted by default. Ducking is explicit and compresses only BGM against narration; SFX are mixed independently.
- Preserve manual/locked Canvas content and `user_edited` canonical timelines by refusing automatic replacement with an actionable result. This first iteration does not silently merge unrelated manual edits across the two stores.
- Stable owned clip identities permit reassembly and removal of obsolete owned captions/audio. Successful reassembly refreshes the mounted timeline even when no new video clips were inserted.
- Fingerprints contain only effective render inputs, including enabled subtitle text/style/windows, FPS, duration, audio roles and enabled ducking. Simple mode ignores canonical features that it does not consume.
- Missing readable subtitle fonts, unsupported ducking, or invalid windows fail explicitly rather than silently dropping features.

## Consequences and boundaries
This establishes frame-clock video + line-caption + role-based audio orchestration, not full Hypit/SVML interoperability, automatic beat/word alignment, or cross-store arbitrary manual-edit reconciliation. A configured readable font is required for burn-in. Real FFmpeg tests lock visible subtitle windows and voice/BGM ducking; browser acceptance locks actual playback and cache reuse.
