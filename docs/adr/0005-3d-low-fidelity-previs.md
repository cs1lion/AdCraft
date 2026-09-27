# 3D Low-fidelity Previs for Controllable Video Production

## Context

AdCraft's current storyboard-to-video path relies on text-driven image/video generation. Shot composition, camera movement, character blocking, and spatial consistency are expressed through natural-language prompts and are therefore non-deterministic: regenerating a shot can change the camera angle, character positions drift between shots, and complex camera moves (push-in, tracking, orbit) are unreliable.

Marketing and short-film production (ADR 0002 `content_kind: short_film`) increasingly requires cinematographic control — precise shot framing, repeatable camera moves, and spatial continuity across cuts. The film/games industry solves this with **previsualization (previs)**: low-fidelity 3D scenes that lock down blocking, camera, and timing before expensive high-fidelity rendering.

This ADR introduces a 3D low-fidelity previs capability into AdCraft: a user describes a scene in natural language, the system produces a structured 3D scene description, renders a low-fidelity animated reference, and uses that reference (keyframes + geometric control signals + prompts) to guide high-fidelity video generation.

**Relationship to existing work:**
- ADR 0003 (dialogue/speech track) already defines `duration_mode: bound | free` and a `speech_audio` asset. The previs timeline consumes the speech track's timing in `bound` mode and aligns character action/lip-sync to it.
- ADR 0003 Appendix (P5 stateful storyboard) records a three-layer separation (fixed setup / mutable state / cinematography) and plan-vs-actual verification. This ADR's SceneScript is the concrete carrier for that mutable-state + cinematography layer; P5's storyboard-state ideas are re-evaluated here rather than imported wholesale.
- Existing `storyboard` node produces 2D shot descriptions. The 3D previs is a **new node type**, not a replacement; a workflow may use either or both.

## Decisions

### 1. SceneScript as the canonical intermediate format

A structured JSON description — `SceneScript` — is the single source of truth between the LLM parser, the frontend 3D preview, the backend Blender renderer, and the video-prompt generator. It is not a prompt; it is a validated domain object.

Top-level sections:
- `scene`: name, environment kind, lighting preset, total duration
- `characters`: id, type (low-poly human initially), appearance, keyframes (position, rotation_y, action enum)
- `props`: id, type, position, scale
- `environment_objects`: walls, pillars, floors, roofs
- `cameras`: id, shot_type enum, keyframes (position, look_at target)
- `shots`: id, camera ref, start_frame, end_frame, description
- `speech_bindings` (optional): character id → speech_audio asset ref, for `bound`-mode timing alignment

SceneScript is defined as Pydantic models in `apps/api/app/schemas/scene_script.py` and regenerated into TypeScript for the web via the existing contract-sync pipeline. Hand-editing generated types is forbidden (engineering standard §2).

**Rationale:** a shared validated format lets each layer evolve independently — the LLM parser can improve without touching the renderer, and the frontend preview can add interactivity without changing the backend.

### 2. Dual-engine rendering: Three.js preview + Blender headless final

Two renderers consume SceneScript, each with a distinct job:

| Engine | Role | Quality | Latency | Deploy |
| --- | --- | --- | --- | --- |
| Three.js (@react-three/fiber) in the web canvas node | Real-time interactive preview, editing, playback | Low-fidelity (intentional) | Immediate | Browser |
| Blender 5.x headless (`--background --python`) | Final low-fidelity render: PNG sequences, MP4, geometric control passes (depth/normal/optical-flow) | Higher (Eevee for preview, Cycles for final) | Seconds–minutes per shot | Backend worker, Blender in container |

The frontend never calls Blender directly. It renders SceneScript in Three.js for live feedback. When the user confirms or requests a render, the backend renders with Blender and returns the asset.

**Rationale:** Three.js gives the interactivity a canvas node needs; Blender gives the render-pass flexibility (depth, normal, motion vectors) that pure browser rendering cannot easily produce. Both consume the same SceneScript, so preview and final are consistent by construction.

### 3. New node type `scene-3d`, not a modification of `storyboard`

A new workflow node type `scene-3d` (category `visual_planning`) is added to the node catalog. It carries:
- Input slot: natural-language scene description (or upstream script/character/scene assets)
- Output slot: `scene_script` asset (the validated JSON), plus rendered `lowfi_animation` asset (MP4) and `keyframe_images` asset

The existing `storyboard` node remains untouched. A `short_film` workflow may chain `storyboard` → `scene-3d` → `video`, or use `scene-3d` standalone.

**Rationale:** separating the node avoids coupling 2D storyboard semantics to 3D previs and keeps each node's contract small. Users who don't need 3D control are unaffected.

### 4. Geometric control signals for video-model guidance

The Blender renderer produces, per shot, not only the color keyframe but also optional geometric passes:
- **Depth map** — per-pixel camera-space distance
- **Normal map** — per-pixel surface orientation
- **Optical flow / motion vectors** — per-pixel 2D displacement between frames

These are delivered alongside the color keyframe and the generated prompt to the video model as control references (analogous to ControlNet conditioning). The video-model provider layer abstracts which signals a given provider accepts; unsupported passes are omitted with a queryable degradation marker (engineering standard §4).

**Rationale:** this is the core controllability advantage of 3D previs over text-to-video. A color reference alone leaves spatial structure to the model's imagination; depth/normal/motion signals lock it down.

### 4a. Video-model reference fallback: 5 keyframe images when reference video is unsupported

Not all video models accept a reference video or motion-vector input. When a provider cannot consume the low-fidelity animation MP4 or geometric control passes, the system falls back to **5 keyframe images per shot** as visual reference.

Fallback hierarchy (per provider, determined by capability fingerprinting):

| Provider capability | Reference input | Quality of control |
| --- | --- | --- |
| Reference video + control signals | MP4 + depth/normal/flow + prompt | Highest — full motion + geometry |
| Reference video only | MP4 + prompt | High — motion preserved, geometry approximate |
| Reference images only (first frame / multi-frame) | 5 keyframe images + prompt | Medium — composition preserved, motion interpolated by model |
| Text only | Prompt only | Lowest — no spatial guarantee |

The 5 keyframe images are extracted per shot at: frame 0 (start), 25%, 50% (mid), 75%, and last frame. They are delivered as a numbered image sequence with the shot description as context. The prompt generator explicitly notes "these 5 frames are keyframes of a continuous camera move; interpolate smoothly between them" to guide the model's motion synthesis.

This fallback is a **queryable degradation** (engineering standard §4): when a provider falls to image-only or text-only, the execution result carries a `previs_control_level` marker (`full` / `video_only` / `images_only` / `text_only`) so the user knows how much control was actually applied. No silent degradation.

**Rationale:** 3D previs's value is controllability. Even when a model can't consume the full animation, 5 well-chosen keyframes preserve composition, character positions, and camera trajectory far better than text alone. The fallback ensures the feature works with every video provider, not only those with reference-video support.

### 5. Speech-track alignment via `duration_mode`

When a `scene-3d` node is downstream of a `voice-cast` node (ADR 0003):
- `bound` mode: the speech track's measured durations drive shot timing and character keyframe placement. The SceneScript `shots` and character `keyframes` are generated to fit the speech timeline; lip-sync (head micro-motion initially, viseme-driven shape keys later) is driven by the final mixed audio.
- `free` mode: the 3D timeline is independent; speech is overlaid in final composition, and the QA registry warns on speech-vs-shot duration mismatches.

This reuses ADR 0003's `duration_mode` semantics without introducing a second timing system.

### 6. Low-poly asset library, procedurally composed

Initial characters and props are composed from primitive geometry (cubes, spheres, cylinders, cones) — the same approach validated in the Blender prototype. A `scene3d_assets` module provides named presets (`lowpoly_human`, `round_table`, `pillar`, `gable_roof`, `lantern`) parameterized by color and scale. Assets are referenced by id in SceneScript, not inlined.

**Rationale:** primitives keep the asset surface small, deterministic, and fast to render in both Three.js and Blender. Higher-fidelity assets can be added later without changing the SceneScript schema (asset id is an indirection).

### 7. Plan-vs-actual verification in the QA registry

The QA registry (introduced in ADR 0003 §5) gains 3D-previs checks:
- SceneScript validity (schema validation, no overlapping shot ranges, camera keyframes within shot bounds)
- Render completeness (every shot has at least one keyframe; expected frame count matches)
- `bound`-mode speech-vs-shot duration alignment (reuses ADR 0003's check pattern)
- Geometric-pass availability (warn, not fail, when a provider cannot consume a produced pass)

Failures block execution-result commit; warnings emit queryable events. This is the concrete realization of ADR 0003 Appendix's "plan-vs-actual dual track."

## Withdrawn candidates (recorded honestly)

- **Text-only shot descriptions with enhanced prompting.** Rejected: cannot guarantee spatial consistency or repeatable camera moves; the core problem is determinism, not prompt quality.
- **Frontend-only 3D (Three.js preview, no Blender).** Rejected: cannot produce depth/normal/motion control passes or render-quality MP4; the video-model guidance would be limited to color keyframes.
- **Importing an external previs tool (e.g. Blender Studio, Unreal) as a service.** Rejected: violates the native-fusion principle (ADR 0003 §1); adds a heavy dependency and a second UI paradigm. Blender is used only as a headless renderer, invisible to the user.
- **Replacing the `storyboard` node with 3D previs.** Rejected: 2D storyboard remains the right tool for many ad workflows; 3D previs is an additional capability, not a migration target.
- **NeRF / 3D Gaussian Splatting for scene reconstruction.** Deferred: promising for lowering scene-creation cost, but requires a separate research track and is not needed for the initial controllability goal. Recorded as a possible P6+ extension.

## Provider layer support

- **Blender runtime:** pinned version (5.x LTS) in the backend worker container; render calls go through a `BlenderRenderer` service (`apps/api/app/services/scene3d/blender_renderer.py`) that manages subprocess invocation, timeout, and artifact collection. No vendor keys required.
- **Video model providers:** the existing provider layer (`v2_provider_executor.py`, `provider_model_catalog.py`) is extended to accept optional `control_signals` (depth/normal/flow image refs) on video-generation calls. Providers that do not support control signals ignore them; the capability is fingerprinted per provider (`ready/degraded/unsupported`, matching the existing ffmpeg capability pattern).
- **TTS / speech:** reused from ADR 0003; no new provider.
- **LLM for SceneScript generation:** reused from the existing agent runtime; the `video_agent_3d_storyboard` skill defines the prompt contract. No new model provider.

Credentials never enter the repository (engineering standard §7).

## 实施状态（2026-09-26 回填）

本 ADR 的核心决策（SceneScript 是唯一规范中间格式）未变；施工分解在 `docs/plans/3d-previs-construction.md`（P0–P6）与 `docs/plans/3d-workbench-and-pipeline-completion.md`（工作台 P0–P5）逐项登记。代码现状要点：

- **SceneScript + 全链路**：`schemas/scene_script.py`（校验器 + mutation 测试）→ Three.js 实时预览 → Blender 渲染 → 视频提示词包；`scene3d/` 下 parser / blender_converter / blender_renderer / encoder / keyframes / control_passes（depth/normal/flow）+ `previs_control_level` 能力指纹降级链（full/video_only/images_only/text_only，可查询）。
- **交互工作台**：`SceneScript3DEditor`（选择-拖拽-放置相机-关键帧捕获-检查器保存）、运镜预设 + 地面画轨迹（常速采样）、角色动作预设、资产托盘、角色资产绑定（Dramagic 式身份锁，绑定后显示参考图）。
- **审片与连续性**：`scene_consistency.py`（一致性闸门，warning 级不阻断）+ `blocking_continuity.py`（跨镜头走位连续性，Continuity State 可算内核；**2026-09-27 起首次接入执行器**——此前只有定义与测试、无调用者，转身在产品里无人看得见）+ `transition_intent_reconciliation.py`（§13 第 4 问：把『什么必须连续』与『什么发生改变』对上账——变化类读法解释连续性 findings，承诺连续的读法被它反驳；两个看门用两种约定指同一条边界，已统一为『出镜 id 在前』一次 join 服务两者）+ `held_items.py`（Continuity State 的道具维度：持有声明 → 预览与 Blender 同步跟随持有者的手，"伞换手"成为不可表示状态）+ `emotion_continuity.py`（Continuity State 的情绪维度：跨切情绪突变且无停顿可读作有时，advisory 提问不判决；L-cut 不误报；切在停顿处不出建议） + `wardrobe_drift.py`（Continuity State 的服装维度可算部分：同一角色资产跨 scene-3d 节点的外观漂移、绑定冲突与**声明的色板漂移**（`character_palette_drift`），执行器发布 `scene3d_wardrobe_drift`；工作流脚本读不到时明说，不伪装通过）+ `CharacterAppearance.palette`（服装的**声明**侧：1-4 hex、可选、加性；检查器「服装色板」字段经 `setCharacterPalette` 写入，按 author 的正式声明比较而非从绑定资产的图里取色——代理编造颜色等于编造资产绑定唯一要钉住的东西；未声明 = 还没决定，跳过而不是误报；资产侧同事实的落点与消费见 **ADR 0011**（Proposed：资产是真相源、预演是不得编造的代理，两条落点路径 B 过渡 / A 终点）+ `shot_advisor.py`（台词驱动分镜顾问）+ `transition_proposals.py`（A→B 衔接方案：连续运动/视线特写/声音桥/说完再切/时间跳跃/视角切换） + `transitionVariants.ts`（局部分叉：读法可存为方案并排恢复，整份脚本快照、上限 4 且界面明示） + shotTransitionRelations（§13 第 5 问：边界作为一对被命名——s1 → s2：声音桥，未登记边以 null 上报而非跳过，因为「这条边界还没人认领」本身就是审片会问的事）+ `SceneShot.transition_intent` 与 `intent_audit`（§13 第 5 问：转场关系用**标签**而非连线——读法本身已作为关键帧写在脚本里，连线只会成为可与之矛盾的第二份拷贝；标签把哪一镜以何种读法接入（**可撤销**：镜头条的取消登记，写而不撤不算编辑）记在镜头上，镜头条边界楔标可见，登记即可校验，读法不再成立时报出它自己的理由与补救）+ 480P 预览带真实台词音频（animatic）。
- **Animatic 成片侧（V0.2 §14.9）**：scene-3d 节点渲染的 MP4 在完整动画渲染后混入台词床音（`mux_audio_to_video`——此前是死代码）；`animatic_audio` provenance（muxed/asset_ref/reason）发布在节点上，四种原因可查询，混入失败只降级不拖垮渲染；`/render` 与异步任务同语义（`audio_path`/`audio_asset_id` → `animatic_video_path`/`audio_muxed`）。
- **分层所有权（V0.2 §14.13）**：两层锁都是结构性的——① Audio 锁：走位/运镜预设落在说话窗内时保留 talk（边走边说），应用时报告保留帧数；② Visual 锁：唇形合并继承**该帧的插值姿态**（与预览同一语义），重新应用唇形不再把 authored 走位台阶化（此前 forward-hold 让走路变"原地站住、后半段冲刺"）。唇形应用反向只接管 action 通道。层的所有权在界面上可见（`LayerOwnershipNote`）：没人看得见的锁等于没有锁。仅剩的坦诚记录：偏航插值落在 schema 弧度盲区（0<|yaw|<=2π）时回落至 authored 值——位置永远精确，极小转身只在其起点量化。
- **LLM 的位置**：读法目录与可行性由规则层决定（`transition_proposals.py`），LLM 可重写叙事理由（`transition_narratives.py` 的 `polish_narratives`），也可**提出规则目录之外的新读法**（`propose_readings`）——但每条提案必须先过校验（id 不冒充规则读法、至少一个操作、操作词表与场景 id 逐条核对），过不了就跑掉并点名；提案带 `origin` 徽章，应用路径与规则读法同一套。多轮迭代（V0.2 §15 深化）：作者应用/驳回的读法进入保留集（`exclude_reading_ids`），prompt 与校验层双保险——LLM 被要求换个方向想，重复提议直接丢弃并点名（已知边界：记忆活在面板状态，刷新即重置）。"机器提案、人选择"的边界用代码固定，不靠提示词自律。
- **建模入口**：自然语言 / 图片（含全景切面 + MiDaS 深度）/ 参考视频 / shot 模板四通道；Blender MCP 客户端（受控白名单）+ 白模设计模式（操作批次经同一校验闸门）。
- **仍开放**：音素级唇形（启发式音节开合仍是低保真）、`render_settings` 的 Blender Converter 消费、ADR 0003 §5 的 QA registry（未建）。

## Appendix: SceneScript schema sketch (reference, not the source of truth)
The authoritative schema lives in `apps/api/app/schemas/scene_script.py`. This sketch is for readability only:

```json
{
  "scene": { "name": "teahouse-dialogue", "environment": "indoor", "lighting": "warm", "duration": 10.0 },
  "characters": [
    {
      "id": "char1", "type": "lowpoly_human", "appearance": { "color": "#8B4513" },
      "keyframes": [
        { "frame": 0, "position": [0.9, -0.9, 0], "rotation_y": 150, "action": "stand" },
        { "frame": 120, "position": [0.9, -0.9, 0], "rotation_y": -30, "action": "talk" }
      ]
    }
  ],
  "props": [{ "id": "table1", "type": "round_table", "position": [0, -1.6, 0], "scale": 1.0 }],
  "environment": [
    { "id": "wall1", "type": "wall", "position": [0, -7, 2.5] },
    { "id": "pillar1", "type": "pillar", "position": [-3.5, -6.7, 2.1] }
  ],
  "cameras": [
    {
      "id": "cam1", "shot_type": "wide",
      "keyframes": [
        { "frame": 0, "position": [12, -14, 8], "look_at": [0, -1.5, 1.3] },
        { "frame": 60, "position": [8.5, -10, 6], "look_at": [0, -1.5, 1.3] }
      ]
    }
  ],
  "shots": [
    { "id": "shot1", "camera": "cam1", "start_frame": 0, "end_frame": 60, "description": "wide establishing" }
  ],
  "speech_bindings": [{ "character": "char1", "speech_asset": "speech_audio:abc123", "mode": "bound" }]
}
```

Coordinate convention: Blender right-handed Z-up, meters. Frame rate default 30 fps. `rotation_y` is in degrees for LLM friendliness, normalized to radians internally.
