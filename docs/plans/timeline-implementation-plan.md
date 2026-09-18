# Timeline-Driven Production Workflow — Implementation Plan

**ADR**: [0007-timeline-driven-production.md](./0007-timeline-driven-production.md)
**Status**: Phase 1–3 complete (timeline-driven export, ffmpeg mixing/ducking, cross-dissolve/wipe/slide rendering, editing UI; clip transition authoring UI, full subtitle track — cue authoring, styles, SRT/ASS export, ASS burn-in and text/script node multi-cue backfill; keyframed volume curves/fades; edge-drag trimming with source-window linkage); Phase 4 partial — 4.1 playhead sync, 4.2 voice→character binding, and 4.4 beat detection/markers/snapping complete; 4.3 camera track and lip-sync / auto edit points remain
**Last Updated**: 2026-09-19

## Overview

This plan implements a professional timeline orchestration layer on top of the
existing node-based canvas. The timeline defines when each asset (video / voice /
bgm / sfx / camera / subtitle) plays on a time-axis, and how clips are trimmed,
transitioned, and mixed.

**Core Principle**: Timeline is the orchestration layer, nodes are the execution
layer. Nodes generate assets; the timeline arranges them in time.

---

## Phase 1: Data Model + API + Basic UI ✅ COMPLETED

**Goal**: Establish the timeline data model, REST API, and a read-only UI panel.

### Backend ✅
- [x] Database tables: `timelines`, `timeline_tracks`, `timeline_clips`
- [x] SQLAlchemy Models: `TimelineRow`, `TimelineTrackRow`, `TimelineClipRow`
- [x] Pydantic Schemas: `TimelineV1`, `TimelineTrackV1`, `TimelineClipV1` + Create/Update/Move
- [x] Repository: `TimelineRepository` (CRUD + auto-create default timeline with 6 tracks)
- [x] API Endpoints: 8 routes (GET/PATCH timeline, GET/PATCH tracks, POST/PATCH/DELETE/POST:move clips)
- [x] Router registration in `app/api/v2/router.py`
- [x] Session management fix (yield dependency with proper cleanup)

### Frontend ✅
- [x] Type definitions: `timeline/timelineTypes.ts`
- [x] API client: `timeline/timelineApi.ts` (8 API functions)
- [x] Timeline panel component: `timeline/GlobalTimelinePanel.tsx`
  - 6 tracks with distinct colors and icons
  - Time ruler (second-level ticks, highlighted every 5s)
  - Clip display (position, duration, label, color)
  - Collapsible/expandable
  - Click-to-select with highlight
  - Track mute/lock status display
  - Auto-calculate total duration
- [x] Integration into `AgentCanvasPageSurface.tsx`
- [x] TypeScript compilation passes (`tsc --noEmit`)

### Auto-Create Clips ✅
- [x] `TimelineClipAutoCreator` service
  - Node type → track type mapping (video→video, voice-cast→voice, scene-3d→camera, audio→sfx/bgm)
  - Semantic role → track type mapping (bgm→bgm, sfx→sfx, subtitle→subtitle)
  - Auto-append clips after last clip on track
  - Default duration 3s when unknown
- [x] Integration via `media_ready_publisher` callback in `DynamicCanvasScheduler`
- [x] Error handling (failures logged, don't block node execution)

### Verification ✅
- [x] 6/6 API tests pass (GET timeline, create video/voice clip, get with clips, move, delete)
- [x] Backend import verification passes
- [x] Frontend TypeScript compilation passes

---

## Phase 2: Timeline-Driven Shot Generation + Basic Mixing ✅ MOSTLY COMPLETE

**Goal**: Make the timeline drive video generation and basic audio mixing.

### 2.1 Timeline → Shot Mapping
- [x] Define shot boundaries from video track clips
- [x] Each video clip = one shot with start/end time
- [x] Map clips to existing video nodes (via `source_node_id`)
- [x] Support creating new video nodes from timeline clips (inspector action
  on manual/orphan video clips: host surface creates a video-generation
  node, the clip is re-linked to it via explicit-null-capable PATCH
  `source_node_id`, and the node's first media publish refreshes the clip
  in place through the idempotent upsert)

### 2.2 Editing Node Consumption
- [x] Modify `editing` node to consume timeline data
- [x] Read video clips from timeline instead of manual reference list
- [x] Read voice/bgm/sfx clips for audio mixing
- [x] Preserve backward compatibility (timeline is optional; integration accepts `None`)

### 2.3 Basic Audio Mixing
- [x] ffmpeg-based audio mixing pipeline
  - Mix voice + bgm + sfx tracks
  - Apply track volumes (0.0-1.0)
  - Apply clip-level fade in/out
  - Auto-ducking: lower BGM volume when voice is active
- [x] Audio ducking algorithm (ffmpeg `sidechaincompress`, voice mix as key)
  - Detect voice clip ranges (sidechain keyed from voice track)
  - Ratio-based gain reduction (default threshold -30 dB / ratio 12, user-tunable)
  - Smooth transitions (50 ms attack / 250 ms release)
  - Capability probe + graceful static-mix fallback + `editing_export_audio_degraded` event

### 2.4 Precise Video Concatenation
- [x] ffmpeg concat filter with exact frame timing
- [x] Handle variable clip durations
- [x] Support cross-dissolve transitions between video clips (adapter maps
  adjacent clips' `transition_in/out` dissolve edges onto the incoming
  entry, shortest edge wins capped to half a clip; renderer joins pieces
  with a frame-quantised `xfade=transition=fade` chain, audio concat and
  tpad keep the fixed timeline duration; non-adjacent/unsupported edges
  fall back to cut with a conversion warning)
- [x] Generate black frames for gaps in video track (`color=c=black` gap pieces)

### 2.5 Timeline Playback
- [x] Playhead position tracking
- [x] Play/pause controls
- [x] Frame-by-frame stepping
- [ ] Sync with 3D preview (when scene-3d clip is active)

### 2.6 Timeline Editing UI ✅
- [x] Per-track mute toggle and volume slider for voice/bgm/sfx (locked tracks protected)
- [x] Selected-clip inspector: start/duration/source trim/label + audio fade in/out
- [x] Nullable clip fields clear via explicit-null PATCH semantics
- [x] Ducking settings popover: threshold/ratio/attack/release/makeup, Reset-to-Auto
- [x] Renderer capability probe (`audio_ducking` flag) with unsupported-renderer warning
- [x] Audio degradation banner (latest `editing_export_audio_degraded` event, polling)

---

## Phase 3: Professional Editing Capabilities 📋 PLANNED

**Goal**: Add professional video editing features.

### 3.1 Clip Trimming
- [x] Drag clip edges to trim start/end
- [x] `source_start` / `source_duration` fields (already in schema)
- [x] Visual trim handles on clips
- [ ] Preview trimmed content

### 3.2 Transitions
- [x] Transition types: none, fade, dissolve, wipe, slide (inspector in/out
  selectors with duration validation; wipe/slide render as libavfilter
  `wipeleft`/`slideleft` xfade joins — mismatched edges prefer the incoming
  type with a warning, gaps/dangling edges/zero-duration fall back to a cut)
- [x] `transition_in_type` / `transition_in_duration` plus out-edge
  counterparts (already in schema; video clips only, cleared via null PATCH)
- [x] Visual transition indicators on clip rows (in/out edge badges, type +
  duration in clip tooltip)
- [x] ffmpeg xfade filter implementation (delivered in 2.4: fade/dissolve
  back-to-back edges with duration clamping)

### 3.3 Subtitle Track
- [x] Manual subtitle clip authoring (subtitle-track "+" button; cue text
  edited in the clip inspector; empty cues are skipped on export)
- [x] SRT/ASS export (`GET /workflows/{id}/timeline/subtitles?format=srt|ass`
  sidecar download; ASS carries per-cue font/size/colour/position/bold/italic;
  muted subtitle tracks are excluded; `.srt`/`.ass` links in the panel header)
- [x] Subtitle styling (font, size, colour, position, bold/italic; validated
  8–160px font size; explicit-null clears text/style)
- [x] Auto-creation of subtitle clips from text/script node assets (the
  node output JSON is parsed for `structured_output.subtitleLines`
  (float seconds) or provider `cues` (`HH:MM:SS,mmm`); one clip per cue
  is synced by ordinal position — matched clips refresh text/timing/asset
  pointers while preserving the user's label and per-clip style, surplus
  clips are deleted, manual clips are never touched; unreadable or
  unrecognized assets fall back to the legacy single clip)
- [x] Burn-in subtitles option during export (timeline `subtitle_burn_in`
  flag + toolbar toggle; renderer stages an ASS sidecar next to the export
  and mounts the libass `ass` filter after the final video chain, with the
  configured server font dir exposed via `fontsdir`; missing libass/font is
  an observable `subtitle_burn_in_unavailable` degradation and the export
  proceeds without burned text)

### 3.4 Volume Curves
- [x] Keyframe-based volume automation (`timeline_clips.volume_keyframes_json`,
  clip-relative points `(time_seconds, value 0–1)`, ≤64 points; PATCH
  explicit-null clears; agent editing adapter passes ≥2-point envelopes)
- [x] Visual volume envelope editor (SVG polyline in the audio-clip
  inspector: click adds points, drag moves, double-click/right-click removes,
  Clear sends an explicit null; points clamp to clip duration and 0–1 gain)
- [x] Fade in/out handles on audio clips (existing inspector inputs; fades
  are rendered through the same piecewise envelope as keyframes — the native
  `afade` filter's timestamps proved unreliable on the target build)
- [x] ffmpeg gain automation rendered as quantised constant-`volume` pieces
  (`atrim` + `asetpts` + `volume`, unified `aresample`/`aformat` before
  `asplit`, then `concat`) — a runtime `volume=if(…)` expression was rejected
  after real-FFmpeg testing; verified end-to-end by media acceptance tests
  sampling head/middle/tail levels of the exported audio

### 3.5 Clip Drag & Drop
- [x] Drag clips horizontally to change start time (snaps to 1/fps frames)
- [x] Drag clips between tracks (audio↔audio / visual↔visual only; locked or
  incompatible rows reject the drop and trigger a server resync; move
  validated server-side against same-timeline target track, 404 otherwise)
- [x] Snap to grid (frame / 0.1s / 0.5s / 1s selector in the panel header;
  move and both resize modes quantize to the selected grid)
- [x] Snap to other clip edges (start/end edges of all other clips plus 0
  and the playhead; 10px threshold, nearest valid candidate, gold guide line)
- [x] Overlap detection and resolution (same-track overlapping drops are
  rejected and trigger a server resync; back-to-back edges are allowed;
  existing overlaps are flagged with a red outline in the panel)
- [x] Edge-drag trimming (left/right handles on every unlocked clip; trim-in
  slides `source_start` with the edge so the remaining media stays anchored,
  and both trims pin the used source window (`source_duration`) to the new
  clip length; bounded by source headroom — no revealing media before the
  source — and a one-frame minimum; same grid/edge snapping and overlap
  rejection as moves; precise numeric trimming stays available in the
  inspector)

### 3.6 Multi-Select & Batch Operations
- [ ] Select multiple clips (Ctrl+click, box select)
- [ ] Batch move/delete
- [ ] Batch property editing

### 3.7 Node Lifecycle Alignment ✅
- [x] Idempotent auto-clips: a node rerun refreshes the existing clip in place
  (asset pointers + duration) instead of appending a duplicate shot; the
  user's arrangement (start time, trim, fades, label) is preserved; an
  unresolvable duration on rerun keeps the existing clip length
- [x] Timeline-scoped upsert keyed on (timeline_id, source_node_id) so reruns
  can never touch another timeline's clips
- [x] Panel live-refreshes on `node_output_published` SSE events (max-seq
  nonce across chat + document streams, 250ms debounce, deferred while
  dragging and flushed on drop)
- [x] Orphan clips (source node deleted) get an amber dashed outline and
  tooltip in the panel, so the retained clips can be reviewed/cleaned up
- [x] Orphan cleanup affordance (delete/re-link action from the inspector)
- [x] Clip ↔ canvas node bi-directional focus (click clip to locate node)

---

## Phase 4: 3D & Timeline Bi-Directional Sync 🚧 IN PROGRESS

**Goal**: Deep integration between 3D previs and timeline.

### 4.1 Playhead Sync
- [x] Timeline playhead controls 3D preview frame
- [x] 3D preview scrubbing updates timeline playhead
- [x] Frame-accurate sync (shared time in seconds; each side quantizes to its own fps)

### 4.2 Voice → Character Binding
- [x] `bound_character_id` field on voice clips (already in schema)
- [x] Visual indicator showing which character speaks
- [ ] Auto-generate lip-sync keyframes from voice audio
- [ ] Rhubarb/Oculus LipSync integration for phoneme-level sync

### 4.3 Camera Track → 3D Camera
- [ ] Camera clips define camera animation in 3D scene
- [ ] Import camera motion from scene-3d nodes
- [ ] Edit camera keyframes in timeline
- [ ] Push camera changes back to 3D scene

### 4.4 Beat Detection
- [x] BPM detection from BGM track (numpy onset-flux + autocorrelation; ffmpeg decode)
- [x] Visual beat markers on timeline
- [x] Snap clips to beats
- [ ] Auto-generate edit points on beats

---

## Phase 5: Advanced Director Tools 📋 PLANNED

**Goal**: Professional director-level tools.

### 5.1 Keyframe Animation
- [ ] Property keyframes (position, scale, rotation, opacity)
- [ ] Curve editor (ease in/out, linear, custom bezier)
- [ ] Apply to video clips (Ken Burns effect)
- [ ] Apply to text/subtitle clips

### 5.2 Proxy Editing
- [ ] Generate low-res proxy files for smooth editing
- [ ] Toggle between proxy and full-res
- [ ] Auto-relink when exporting

### 5.3 Color Correction
- [ ] Per-clip color grading (brightness, contrast, saturation, hue)
- [ ] LUT support
- [ ] Comparison view (before/after)
- [ ] Copy/paste grade between clips

### 5.4 Multi-Camera Editing
- [ ] Multiple camera angles in camera track
- [ ] Switch between angles at any time
- [ ] Visual multi-cam view
- [ ] Auto-sync by timecode

---

## Risk Mitigation

### Backward Compatibility
- All existing nodes work without timeline
- Timeline is opt-in (auto-created on first access)
- Editing nodes fall back to manual reference list if no timeline clips

### Performance
- Timeline queries indexed by workflow_id, track_id
- Clip creation is async (doesn't block node execution)
- Frontend virtualizes long timelines (>100 clips)

### Data Integrity
- Timeline clips reference assets by asset_id (not file paths)
- Deleting a node doesn't delete its timeline clips (they become orphaned)
- Orphaned clips are visually flagged in the panel (amber dashed outline) and
  can be manually cleaned up; a rerun of an existing node never duplicates a
  clip (in-place upsert, §3.7)

---

## Testing Strategy

### Unit Tests
- Repository CRUD operations
- Auto-creator track type mapping
- API request/response validation

### Integration Tests
- Node execution → auto clip creation
- Timeline → editing node consumption
- Audio mixing pipeline
- Video concatenation with transitions

### E2E Tests
- Full workflow: create nodes → execute → timeline auto-populates → edit timeline → export
- Browser automation for timeline UI interactions

---

## Documentation

- [x] ADR 0007: Design decision document
- [x] This implementation plan
- [ ] API documentation (OpenAPI/Swagger)
- [ ] User guide: How to use the timeline
- [ ] Developer guide: Extending the timeline
- [ ] Migration guide: Existing projects → timeline

---

## Dependencies & Prerequisites

### Backend
- SQLAlchemy (already used)
- Pydantic (already used)
- FastAPI (already used)
- ffmpeg (already used for video processing)

### Frontend
- React (already used)
- TypeScript (already used)
- No new external dependencies for Phase 1-2
- Phase 3+ may need a drag-and-drop library (react-dnd or similar)

---

## Success Metrics

### Phase 1
- [x] Timeline API responds in <100ms
- [x] Auto-clip creation doesn't slow down node execution
- [x] Frontend panel renders 6 tracks + 50 clips smoothly

### Phase 2
- [x] Editing node can export a video with 3+ clips from timeline
- [x] Audio mixing produces correct voice+BGM output (verified by ffmpeg ducking media tests)
- [x] Video transitions work between clips (real-ffmpeg media tests for
  dissolve/wipe/slide xfade joins and a three-clip mixed chain)

### Phase 3
- [x] Users can trim clips by dragging edges (left/right handles move the
  source window with the edge; source-headroom and one-frame bounds)
- [x] Subtitle track can export SRT (and styled ASS)
- [x] Volume curves apply correctly during export

### Phase 4
- [x] Timeline playhead controls 3D preview frame
- [x] Voice clips can be bound to characters
- [x] Beat detection works on BGM tracks

### Phase 5
- [ ] Keyframe animation works on video clips
- [ ] Proxy editing enables smooth playback of 4K footage
- [ ] Color correction can be applied per clip
