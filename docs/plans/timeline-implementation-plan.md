# Timeline-Driven Production Workflow — Implementation Plan

**ADR**: [0007-timeline-driven-production.md](./0007-timeline-driven-production.md)
**Status**: Phase 1–2 complete (timeline-driven export, ffmpeg mixing/ducking, editing UI); Phase 3–5 planned (cross-dissolve and 3+ clip E2E verification pending)
**Last Updated**: 2026-09-17

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
- [ ] Support creating new video nodes from timeline clips

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
- [ ] Support cross-dissolve transitions between video clips (schema fields exist; adapter currently emits `cut`)
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
- [ ] Transition types: none, fade, dissolve, wipe, slide
- [ ] `transition_in_type` / `transition_in_duration` (already in schema)
- [ ] Visual transition indicators between clips
- [ ] ffmpeg xfade filter implementation

### 3.3 Subtitle Track
- [ ] Subtitle clip creation from text/script nodes
- [ ] SRT/ASS export
- [ ] Subtitle styling (font, size, color, position)
- [ ] Burn-in subtitles option during export

### 3.4 Volume Curves
- [ ] Keyframe-based volume automation
- [ ] Visual volume envelope editor
- [ ] Fade in/out handles on audio clips
- [ ] ffmpeg volume filter with expression

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

## Phase 4: 3D & Timeline Bi-Directional Sync 📋 PLANNED

**Goal**: Deep integration between 3D previs and timeline.

### 4.1 Playhead Sync
- [ ] Timeline playhead controls 3D preview frame
- [ ] 3D preview scrubbing updates timeline playhead
- [ ] Frame-accurate sync (timeline fps = 3D scene fps)

### 4.2 Voice → Character Binding
- [ ] `bound_character_id` field on voice clips (already in schema)
- [ ] Visual indicator showing which character speaks
- [ ] Auto-generate lip-sync keyframes from voice audio
- [ ] Rhubarb/Oculus LipSync integration for phoneme-level sync

### 4.3 Camera Track → 3D Camera
- [ ] Camera clips define camera animation in 3D scene
- [ ] Import camera motion from scene-3d nodes
- [ ] Edit camera keyframes in timeline
- [ ] Push camera changes back to 3D scene

### 4.4 Beat Detection
- [ ] BPM detection from BGM track
- [ ] Visual beat markers on timeline
- [ ] Snap clips to beats
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
- [ ] Editing node can export a video with 3+ clips from timeline
- [x] Audio mixing produces correct voice+BGM output (verified by ffmpeg ducking media tests)
- [ ] Video transitions work between clips

### Phase 3
- [ ] Users can trim clips by dragging edges
- [ ] Subtitle track can export SRT
- [ ] Volume curves apply correctly during export

### Phase 4
- [ ] Timeline playhead controls 3D preview frame
- [ ] Voice clips can be bound to characters
- [ ] Beat detection works on BGM tracks

### Phase 5
- [ ] Keyframe animation works on video clips
- [ ] Proxy editing enables smooth playback of 4K footage
- [ ] Color correction can be applied per clip
