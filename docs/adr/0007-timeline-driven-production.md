# ADR 0007: 时间线驱动的制片工作流（Timeline-Driven Production）

## Status

Proposed（2026-09-16）→ **Phase 1–4 落地（2026-09-26 回填）**。扩展见 [ADR 0008](./0008-timeline-two-phase-directing-and-assembly.md)（双相：生成前指导 + 生成后组装）。本节回填与下方原「Phase 1 待启动」表述的关系：原决策逐条不变，落地证据列在文末「实施状态」。

## Context

### 问题陈述

当前 Agent Canvas 是**"节点数据流"**架构，每个节点独立生成素材，但缺少**"时间流"**的精确编排能力。当 TTS 语音、3D 预演运镜、视频生成同时参与时，产生以下核心问题：

1. **时长不一致**：voice-cast 生成 4.1 秒音频，scene-3d 生成 6 秒预演，video 节点输出 5 秒——三者没有显式的时间对齐关系。
2. **起点不确定**：视频模型收到 audio_reference 和 video_reference 时，不知道语音应该从第 0 秒还是第 1 秒开始，BGM 何时淡入。
3. **多段顺序混乱**：角色 A 说 3 秒、角色 B 说 2 秒，多段语音的时间顺序和重叠关系没有约束。
4. **运镜与语音脱节**：3D 运镜的关键帧切换可能发生在角色说话中间，而不是语音停顿处，导致观感不专业。
5. **音频冲突**：语音和 BGM 同时播放时没有音量控制，BGM 可能盖过人声。

### 用户诉求

> "tts语音和3D粗建模运镜一起参与视频生成，视频模型如何判断语音或bgm何时开始和结束，会不会产生冲突，有没有一个设计方向是能像专业工作台导演和剪辑那样，能控制视频输出达到预期的？"

核心诉求：**从"AI黑盒生成"走向"专业级精确可控"**。

### 约束

- V2 画布是 canonical 的执行边界，时间线不能替代节点执行，而是**补充编排层**。
- 必须向后兼容：现有节点（text/script/image/video/audio/editing/scene-3d/voice-cast）不需要改动就能在时间线中工作。
- 时间线是**视图层 + 元数据层**的概念，不改变底层的节点执行调度机制。

## 现有代码事实（扩展点，必须复用）

| 概念 | 现有实现 | 位置 |
|---|---|---|
| 节点执行调度 | `DynamicCanvasScheduler`，按 node_type 限制并发 | `app/services/agent_canvas_runtime.py:31-39` |
| 节点状态 | `CanvasNodeStatusV2 = draft \| working \| ready \| failed` + `visible_status` | `app/schemas/agent_canvas.py:25`；`web/src/types-v2.ts:1474` |
| 连接策略 | `AgentCanvasConnectionPolicyService`，定义节点间输入输出角色 | `app/services/agent_canvas_connection_policy.py` |
| voice-cast 节点 | 已实现 TTS 生成，输出 audio_reference（WAV），duration_seconds 已记录 | `app/services/agent_canvas_node_execution.py:1140` |
| scene-3d 节点 | 已实现 Blender headless 渲染，输出 video_reference，有关键帧和相机轨迹 | `app/services/agent_canvas_node_execution.py:1296` |
| video 节点输入 | `SeedanceInputManifestV1` 已有 `audio_inputs` / `video_inputs` / `image_inputs` | `app/schemas/seedance_inputs.py:59-73` |
| editing 节点 | `AgentCanvasCompositionRenderer` 用 ffmpeg 拼接视频 + 混合 BGM | `app/services/agent_canvas_composition_renderer.py:40` |
| 前端音频播放器 | `AgentCanvasAudioPlayer` 已接入 voice-cast 节点 | `web/src/features/agent-canvas/canvas/AgentCanvasAudioPlayer.tsx` |
| 前端 editing 预览 | `EditingPreviewStage` 支持 BGM 音频预览 | `web/src/features/agent-canvas/editing/EditingPreviewStage.tsx` |
| 资产时长元数据 | `asset_versions.duration_seconds` 已记录音频/视频时长 | `app/persistence/models.py` |

## 设计决策

### 1. 核心原则：时间线是编排层，不是执行层

```
节点图（Node Graph）= 素材生成器（"生成什么"）
时间线（Timeline）  = 素材编排器（"什么时候播放、如何混合"）
```

- **节点负责生成**：每个 video/voice/scene-3d 节点独立执行，和现在完全一样。
- **时间线负责编排**：将节点产出的资产（asset）放到时间线上的精确位置，定义开始时间、持续时长、裁剪范围、转场效果、音量曲线。
- **editing 节点负责渲染**：消费时间线上的所有素材，用 ffmpeg 精确拼接+混音，输出最终成片。

**关键洞察**：不是把音频和 3D 预演"一起扔给视频模型"，而是用时间线把大问题拆成小问题——每个分镜独立生成、精确对齐、最后拼接。

### 2. 分镜在画布上的体现方式：独立节点 + 视觉分组 + 时间线视图

**不采用**主节点+子节点（复合节点）方案，因为：
- 需要实现复合节点/Group Node 机制，改动大
- 子节点的执行调度、状态管理、错误处理都要特殊处理
- 与现有"每个节点独立执行"的架构冲突

**采用**三层结构：

```
┌─────────────────────────────────────────────────────────┐
│  节点图视图（上半部分）                                      │
│  ┌─────────────────────────────────────────────────────┐ │
│  │  ╔═══════════ 分镜组: 赌场入场 ═════════════════╗  │ │
│  │  ║ [text]→[voice-cast]→[video1]←[scene-3d]   ║  │ │
│  │  ║                                              ║  │ │
│  │  ║ [text]→[voice-cast]→[video2]←[scene-3d]   ║  │ │
│  │  ╚══════════════════════════════════════════════╝  │ │
│  │                                                       │ │
│  │  [video1] [video2] [video3] → [editing] → 成片     │ │
│  └─────────────────────────────────────────────────────┘ │
├─────────────────────────────────────────────────────────┤
│  时间线视图（下半部分，可折叠/展开）                          │
│  ┌─────────────────────────────────────────────────────┐ │
│  │ video │[shot1 0-3s]│[shot2 3-5s]│[shot3 5-7s]   │ │
│  │ voice │[A说话]     │[B说话]      │                │ │
│  │ bgm   │[背景音乐 0-7s, 自动闪避]                   │ │
│  └─────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────┘
```

**三层说明**：

1. **独立节点**：每个分镜是一个独立的 video 节点，执行机制和现在完全一样。voice-cast、scene-3d 也都是独立节点。
2. **视觉分组（Shot Group）**：用背景框将相关节点（同一场景的分镜）视觉上框在一起，类似 Figma 的 Group。**纯视觉，不影响执行**。分组有名称（如"赌场入场"），可折叠/展开。
3. **时间线视图**：画布下方的独立面板，显示所有视频/音频节点产出的资产按时间排列。可折叠/展开，不占用户不需要时的空间。

**双向同步**：
- 节点图选中节点 ↔ 时间线高亮对应的 clip
- 时间线拖动 clip ↔ 节点的 `timeline_metadata`（start_time/duration）更新
- 时间线播放头移动 ↔ 3D 视图跳转到对应帧（Phase 4）

### 3. 时间线数据模型

```typescript
// 时间线（一个 workflow 对应一个 timeline）
interface Timeline {
  id: string;
  workflow_id: string;
  duration_seconds: number;  // 总时长（自动计算，也可手动设置）
  fps: number;  // 24 / 30，默认 30
  tracks: TimelineTrack[];
  created_at: string;
  updated_at: string;
}

// 轨道
interface TimelineTrack {
  id: string;
  type: 'video' | 'voice' | 'bgm' | 'sfx' | 'camera' | 'subtitle';
  name: string;  // 可自定义，如"角色A语音"、"主视频"
  clips: TimelineClip[];
  muted: boolean;  // 静音（音频轨道）
  volume: number;  // 0-1，默认 1.0
  locked: boolean;  // 锁定后不可编辑
  display_order: number;  // 轨道显示顺序
}

// 片段（一个 clip 引用一个节点产出的资产）
interface TimelineClip {
  id: string;
  track_id: string;
  // 资产引用
  asset_id: string;
  asset_version_id: string;
  source_node_id: string;  // 产出这个资产的节点
  // 时间线位置（秒，帧级精度）
  start_time: number;  // 在时间线上的开始时间
  duration: number;    // 在时间线上的持续时间（可裁剪）
  // 素材裁剪（入点出点）
  source_start: number;     // 从素材的哪个时间点开始（默认 0）
  source_duration: number;  // 使用素材的多长时间（默认素材总时长）
  // 音频控制
  fade_in?: number;   // 淡入时长（秒）
  fade_out?: number;  // 淡出时长（秒）
  // 视频转场
  transition_in?: { type: 'fade' | 'dissolve' | 'wipe'; duration: number };
  transition_out?: { type: 'fade' | 'dissolve' | 'wipe'; duration: number };
  // 绑定关系
  bound_character_id?: string;  // 语音绑定的 3D 角色 ID（Phase 4）
  // 元数据
  label?: string;  // 显示名称，如"角色A：你好"
  color?: string;  // 自定义颜色标记
}
```

**存储方式**：
- `timelines` 表：时间线元数据
- `timeline_tracks` 表：轨道
- `timeline_clips` 表：片段（关联 asset_id + source_node_id）
- 节点表增加 `timeline_metadata` JSON 列：存储节点在时间线上的位置（start_time/duration/track_id），方便节点图和时间线双向同步

### 4. 时间线驱动的视频生成流程

```
Step 1: 导演规划（时间线）
  用户在时间线上规划：
  - 0-3秒：角色A近景，说"你好"
  - 3-5秒：角色B中景，说"好久不见"
  - 5-7秒：两人全景，沉默对视
  - BGM：0-7秒，轻柔背景音乐

Step 2: 自动创建节点（节点图）
  时间线根据规划自动创建对应的节点：
  - voice-cast节点A：生成角色A"你好"(3秒)
  - voice-cast节点B：生成角色B"好久不见"(2秒)
  - scene-3d节点：生成7秒3D预演（包含3个镜头的运镜）
  - video节点1：参考3D预演0-3秒 + 角色A语音 → 生成3秒近景
  - video节点2：参考3D预演3-5秒 + 角色B语音 → 生成2秒中景
  - video节点3：参考3D预演5-7秒 + 无语音 → 生成2秒全景

Step 3: 素材生成（节点执行）
  每个节点独立执行，和现在完全一样：
  - voice-cast → TTS生成WAV音频
  - scene-3d → Blender渲染MP4预演
  - video → 视频模型生成MP4
  执行顺序由调度器控制（video_limit=1，逐个执行）

Step 4: 自动对齐（时间线）
  节点生成完成后，资产自动放到时间线的对应位置：
  - video1 → video轨道 0-3秒
  - video2 → video轨道 3-5秒
  - video3 → video轨道 5-7秒
  - 角色A语音 → voice轨道 0-3秒
  - 角色B语音 → voice轨道 3-5秒
  - BGM → bgm轨道 0-7秒

Step 5: 精细剪辑（时间线，用户可选）
  用户可以：
  - 拖动clip调整位置（帧级精度）
  - 裁剪素材（拖动clip边缘设置入点出点）
  - 添加转场（clip之间的fade/dissolve）
  - 调整音量（voice/bgm独立控制，关键帧音量曲线）
  - 添加字幕（自动从语音生成，可编辑）

Step 6: 最终输出（editing节点渲染）
  editing节点消费时间线上的所有素材，用ffmpeg精确渲染：
  - 视频拼接（带转场）
  - 音频混音（voice + bgm，自动闪避ducking）
  - 字幕烧录（可选）
  - 输出最终MP4
```

**为什么这样不会冲突？**

| 冲突点 | 解决方式 |
|--------|----------|
| 语音和视频时长不一致 | 时间线精确定义每个clip的start_time和duration，视频按分镜独立生成 |
| BGM盖过人声 | 多轨道音量控制 + 自动闪避（ducking）：有人声时BGM音量自动降低30-50% |
| 运镜在说话中间切换 | 语音节拍检测 + 分镜边界对齐到语音停顿处 |
| 多角色对话顺序混乱 | 时间线voice轨道可视化，自动避让/交替排列 |
| 3D预演和实际视频不同步 | 每个分镜用对应时间段的3D预演做参考，生成后自动对齐 |

### 5. 冲突解决机制

#### 5.1 语音与BGM的冲突 → 多轨道音量 + 自动闪避

```
voice轨道:  │[A说话 0-3s]│[B说话 3-5s]│
bgm轨道:    │[背景音乐 0-7s, 音量自动闪避]│
                ↓ 有人声时BGM自动降低40%
            音量: 100% → 60% → 100% → 60% → 100%
```

- voice 轨道优先级高于 bgm 轨道
- 自动闪避（ducking）：检测到 voice 轨道有音频时，bgm 音量自动降低 30-50%
- 用户可以手动调整每条轨道的音量曲线（关键帧）
- ffmpeg 实现：`sidechaincompress` 滤镜，用 voice 轨道做 sidechain 控制 bgm 轨道

#### 5.2 多语音重叠的冲突 → 时间线可视化 + 自动避让

```
时间线显示重叠（红色高亮）：
voice轨道A: │[说话 0-3s]│
voice轨道B:      │[说话 2-5s]│  ← 2-3秒重叠，红色高亮
```

- 时间线可视化显示重叠区域（红色高亮）
- 提供"自动避让"按钮：将重叠的语音片段自动错开
- 支持"同时说话"模式（多人嘈杂场景），但自动降低非主要语音的音量
- 支持"对话交替"模式：自动将多人对话排成 A→B→A→B 的顺序

#### 5.3 3D运镜与语音节奏的冲突 → 时间线驱动分镜 + 节拍检测

**核心原则：运镜切换应该在语音的停顿处，而不是说话中间。**

```
语音波形:  ──///───///──────///───  (///=说话, ──=停顿)
运镜切换:        ↑       ↑        ↑  (在停顿处切换)
分镜:      [shot1] [shot2]  [shot3]
```

- **语音节拍检测**：用 Web Audio API 或 librosa 分析语音的停顿、重音，生成"建议切换点"
- **时间线驱动分镜**：每个时间线片段对应一个分镜（shot），独立生成视频
- **3D运镜对齐**：3D预演的相机关键帧自动对齐到分镜边界
- **用户可锁定**："运镜跟随语音节奏"开关，开启后自动对齐

### 6. 专业工作台的核心能力（路线图）

| 能力 | 实现方式 | Phase |
|------|----------|-------|
| 多轨道时间线 | video/voice/bgm/sfx/camera/subtitle 6条轨道 | Phase 1 |
| 帧级精度 | 时间以帧为单位，clip可拖动到任意帧 | Phase 1 |
| 素材裁剪 | source_start/source_duration，入点出点 | Phase 3 |
| 转场效果 | fade/dissolve/wipe等转场 | Phase 3 |
| 音频混音 | 每条轨道独立音量，voice优先，bgm自动闪避 | Phase 2 |
| 关键帧动画 | 位置/缩放/旋转的关键帧插值 | Phase 5 |
| 字幕轨道 | 时间线对齐的字幕，自动从语音生成 | Phase 3 |
| 3D双向同步 | 时间线播放头 ↔ 3D视图帧同步 | Phase 4 |
| 语音绑定角色 | voice clip绑定character_id，3D高亮说话角色 | Phase 4 |
| 节拍检测 | 自动分析语音停顿/重音，建议运镜切换点 | Phase 4 |

## 实施路径（分阶段）

### Phase 1：时间线基础（P0，预计2-3周）

**目标**：时间线数据模型 + 基础可视化 + 节点输出自动创建clip

**后端**：
- [ ] `timelines` / `timeline_tracks` / `timeline_clips` 表 + SQLAlchemy models
- [ ] `Timeline` / `TimelineTrack` / `TimelineClip` Pydantic schemas
- [ ] `GET /workflows/{id}/timeline`：获取工作流的时间线（不存在则自动创建）
- [ ] `PATCH /workflows/{id}/timeline/clips/{clip_id}`：更新clip位置/时长/裁剪
- [ ] `POST /workflows/{id}/timeline/clips`：手动添加clip
- [ ] `DELETE /workflows/{id}/timeline/clips/{clip_id}`：删除clip
- [ ] 节点执行完成后，自动创建对应的timeline clip（video节点→video轨道，voice-cast→voice轨道）
- [ ] 节点表增加 `timeline_metadata` JSON 列（start_time/duration/track_id）

**前端**：
- [ ] 时间线组件（横向轨道，可拖动clip，播放头）
- [ ] 画布下方可折叠/展开的时间线面板
- [ ] 基本播放/暂停/拖动播放头
- [ ] 节点图选中节点 ↔ 时间线高亮clip（双向同步）
- [ ] 时间线拖动clip ↔ 节点timeline_metadata更新

**验收标准**：
- 创建一个workflow，自动生成空时间线（6条轨道）
- 运行一个video节点，完成后自动在video轨道创建clip
- 运行一个voice-cast节点，完成后自动在voice轨道创建clip
- 时间线上可以看到clip，能拖动调整位置
- 拖动clip后，节点的timeline_metadata更新

### Phase 2：时间线驱动分镜生成 + 基础混音（P0，预计2-3周）

**目标**：时间线片段→分镜映射，每个分镜独立生成视频，ffmpeg精确拼接+基础混音

**后端**：
- [ ] `TimelineShot` 概念：时间线上video轨道的每个clip对应一个分镜
- [ ] "从时间线创建分镜节点"功能：根据时间线上的规划，自动创建对应的video/voice/scene-3d节点
- [ ] video节点执行时，根据timeline_metadata的时间段，从scene-3d预演中提取对应时间段的参考帧
- [ ] video节点执行时，将对应时间段的语音作为audio_reference传入
- [ ] editing节点消费时间线：读取所有clip，按时间顺序拼接视频，混合voice+bgm音频
- [ ] 自动闪避（ducking）：ffmpeg sidechaincompress，有人声时BGM降低
- [ ] `POST /workflows/{id}/timeline/render`：触发时间线渲染（调用editing节点）

**前端**：
- [ ] "从时间线生成节点"按钮：根据时间线规划自动创建节点
- [ ] 时间线clip显示对应的节点状态（draft/working/ready/failed）
- [ ] 点击时间线clip跳转到对应的节点（节点图定位）
- [ -editing节点预览时间线渲染结果

**验收标准**：
- 用户在时间线上规划3个分镜（0-3s, 3-5s, 5-7s）
- 点击"生成节点"，自动创建3个video节点 + 对应的voice-cast + scene-3d
- 运行所有节点，每个video节点用对应时间段的3D预演+语音做参考
- 生成完成后，自动对齐到时间线
- 点击"渲染成片"，editing节点消费时间线，输出带语音+BGM的最终MP4
- 语音和BGM混音正确，BGM在有人声时自动降低

### Phase 3：专业剪辑能力（P1，预计2周）

**目标**：素材裁剪、转场效果、字幕轨道、音量曲线

**后端**：
- [ ] clip的source_start/source_duration生效（素材裁剪）
- [ ] 转场效果：fade/dissolve，clip之间的过渡
- [ ] 字幕轨道：subtitle类型，clip包含文本+时间
- [ ] 自动从语音生成字幕（用Whisper或语音时间戳）
- [ ] 音量曲线关键帧（clip级别的volume automation）
- [ ] ffmpeg渲染支持转场+字幕+音量曲线

**前端**：
- [ ] 拖动clip边缘裁剪素材（入点出点）
- [ ] clip之间添加转场（下拉选择fade/dissolve）
- [ ] 字幕轨道编辑（点击添加字幕，编辑文本）
- [ ] 音量曲线编辑（clip上的音量控制点）
- [ ] 时间线缩放（帧级到秒级，滚轮缩放）

### Phase 4：3D与时间线双向同步（P1，预计2周）

**目标**：3D视图与时间线播放头同步，语音绑定3D角色，节拍检测

**后端**：
- [ ] 时间线播放头位置 → 3D场景对应帧的查询API
- [ ] voice clip绑定character_id（3D角色ID）
- [ ] 语音节拍检测API（分析语音停顿/重音，返回建议切换点）
- [ ] 相机关键帧记录到camera轨道（从scene-3d的scene_script中提取）

**前端**：
- [ ] 3D视图与时间线播放头同步（拖动时间线，3D跳转到对应帧）
- [ ] 选中voice clip，3D视图高亮绑定的角色
- [ ] "节拍检测"按钮：分析语音，在时间线上标记建议的运镜切换点
- [ ] camera轨道显示3D运镜关键帧

### Phase 5：高级导演工具（P2，按需）

- [ ] 关键帧动画（位置/缩放/旋转的时间线动画）
- [ ] 代理剪辑（低分辨率代理，流畅编辑）
- [ ] 颜色校正/滤镜
- [ ] 多版本对比（A/B roll）
- [ ] 音效库（sfx轨道）

## 与现有架构的兼容性

| 现有功能 | 兼容性 | 说明 |
|----------|--------|------|
| 现有节点类型 | ✅ 完全兼容 | 所有节点不需要改动，执行完成后自动创建timeline clip |
| 现有连接策略 | ✅ 完全兼容 | 节点间的连接关系不变，时间线是额外的编排层 |
| 现有执行调度 | ✅ 完全兼容 | DynamicCanvasScheduler 不需要改动，每个节点还是独立执行 |
| 现有editing节点 | ⚠️ 需要扩展 | editing节点需要增加"消费时间线"的模式，但现有"手动选择视频"模式保留 |
| 现有引导流程 | ✅ 完全兼容 | 引导流程创建的节点自动进入时间线，用户可以后续在时间线上微调 |
| 自由创作模式 | ✅ 完全兼容 | 用户自由添加的节点也自动进入时间线，时间线不阻塞节点执行 |

## 风险与缓解

| 风险 | 缓解措施 |
|------|----------|
| 时间线和节点图的双向同步可能复杂 | Phase 1 只做单向（节点→时间线自动创建clip），Phase 2 再做双向（时间线拖动→节点metadata更新） |
| ffmpeg渲染时间线可能很慢 | 用代理剪辑（低分辨率预览），最终输出时用高分辨率；Phase 5 实现 |
| 用户可能觉得时间线太复杂 | 时间线面板默认折叠，高级用户展开；引导流程自动处理时间线，新手不需要手动操作 |
| 视频模型不消费audio_reference | Phase 2 先做"时间线拆分镜独立生成"，audio_reference作为可选输入；即使模型不消费，时间线的精确对齐+混音仍然有价值 |

## 关键决策总结

1. **时间线是编排层，不是执行层**：节点负责生成，时间线负责编排，editing负责渲染。
2. **分镜用独立节点+视觉分组+时间线视图**，不采用主节点+子节点的复合节点方案。
3. **大问题拆成小问题**：不让视频模型一次性理解复杂的时间关系，而是用时间线拆成独立的分镜逐个生成。
4. **向后兼容优先**：所有现有节点不需要改动，时间线是增量的视图层+元数据层。
5. **分阶段交付**：Phase 1 基础时间线 → Phase 2 时间线驱动分镜+混音 → Phase 3 专业剪辑 → Phase 4 3D同步 → Phase 5 高级工具。

## 实施状态（2026-09-26 回填，对照上方 Phase 表）

| Phase | 状态 | 证据 |
|---|---|---|
| Phase 1 多轨时间线 + 帧级精度 | ✅ | `alembic/versions/20260917_01_create_timelines.py`（timelines/tracks/clips 三表）+ `app/services/timeline_editing_integration.py` + `GlobalTimelinePanel`；节点产出经 auto-creator 自动建 clip |
| Phase 2 混音 / 闪避 | ✅ | `20260917_02_add_timeline_ducking.py` + ffmpeg 侧链闪避混音（sidechain ducking） |
| Phase 3 专业剪辑 | ✅ | 源链接边缘裁剪、可吸附网格 + 同轨重叠拒绝、跨轨拖拽、keyframed 音量包络、clip 转场编辑器（dissolve/wipe/slide，xfade 渲染）、手动/孤儿 clip 提升为视频节点、字幕 clip（SRT/ASS 导出 + ASS 烧录入成片） |
| Phase 4 3D 同步 / 语音绑定 / 节拍 | ✅ | 播放头同步（3D 视口 ↔ 时间线）、`bound_character_id` 语音→角色绑定、BGM 节拍检测（`timeline_beat_analysis.py`）；对话唇形关键帧与台词上字幕轨由 scene-3d 侧闭环（ADR 0003/0005 线） |
| 双栈收敛（§5.1 方案 A） | ✅ | `app/api/v2/endpoints/final_composition.py` 作为 ADR-0007 时间线的兼容投影（8 路由），v2 final-composition 路由不再 404 |
| 场景操作批次 / 白模模式 | ✅（另一线） | `scene_script_tool_service.py` + 白模设计模式（见 `docs/plans/blender-mcp-white-model-mode-and-audio-collaboration.md`） |

仍开放：§4.3 camera 轨从 scene-3d 导入运镜关键帧的**拖拽源**（自动映射已在）、ADR 0008 之后的声音事件→必要镜头检查（QA registry 形态，未建）。
