# Blender MCP 白模设计模式 × StepAudio 3 Gen 音频协作 — 设计与落地方案

> **Status**: Proposed（2026-09-25）
> **触发**: (1) 在画布场景中加入 Blender MCP 与"白模设计模式"入口：用户意图进入白模设计工作时，界面与功能随之跟上；用户描述想法，agent 通过 Blender MCP 建模并生成参考视频，建模与参考视频均可预览，建模预览可开放手动编辑高级功能。(2) 接入 StepAudio 3 Gen（`stepaudio-3-gen-preview`，`POST /v1/audio/generate`）：一次调用统一生成多角色对白、音效、环境音与 BGM。(3) 从创作者视角重构音频×视频协作方式：让创作体验轻松、酷炫、能完整交付；工作模式创新；音频设计与分镜相辅相成；分镜与剧情设计借协作摆脱死板。
> **关联**: [ADR 0005 3D 预演](./adr/0005-3d-low-fidelity-previs.md) · [ADR 0003 对白/语音轨](./adr/0003-dialogue-speech-track.md) · [ADR 0007 时间线](./adr/0007-timeline-driven-production.md) · [3D 工作台方案](./plans/3d-workbench-and-pipeline-completion.md)
> **纪律**: 所有"现状"结论均在 2026-09-25 工作树核对；引用具体文件与行号。

---

## 0. TL;DR

| 诉求 | 结论 |
|---|---|
| Blender MCP 接入 | **后端拥有 MCP 客户端**（`scene3d/blender_mcp_client.py`，stdio JSON-RPC），SceneScript 保持唯一规范状态；MCP 工具集是"扩展建模词汇"，Agent 通过结构化提交驱动，不直接裸操 Blender。pi-coding-agent 运行时本身**没有**内置 MCP 客户端（已核查 node_modules），故不存在"前端直连 MCP"架构 |
| 白模设计模式 | scene-3d 节点升级为**模式化入口**：意图识别（front_desk）→ 画布切换为"导演工作台"全屏 → 左 Agent 对话 / 中实时 3D 视口 / 右 MCP 操作日志与检查器 / 底帧轨。描述→建模→参考视频→预览→手动编辑，全闭环 |
| StepAudio 3 Gen | **客户端已落地**（`app/tools/step_audio_gen.py`，28 项单测）。一次调用 = roles（音色）+ scripts（带 speaker 与`(情绪)`/`[]`音效标记的剧本）+ instruction（全局基调）→ 一整段编排好的音频床 |
| 音频×分镜协作 | **音频先行工作流**：台词/音效实测时长与停顿 → 分镜边界（ADR 0003 bound 模式 + ADR 0007 §5.3 已铺路）；声音事件 → 镜头建议；氛围 → 景别/光线建议。分镜表从"拍脑袋定时长"变成"被声音牵引的动态编排" |
| 工作模式创新 | 双模式：**音频先行**（对白驱动的短片/微电影）与**画面先行**（视觉驱动的广告）；同一时间线编排层收敛两种模式，editing 节点统一交付 |

---

## 1. Blender MCP × 白模设计模式

### 1.1 代码事实（已核对）

| 事实 | 证据 |
|---|---|
| Agent 运行时是 pi-coding-agent 0.81.1，**无内置 MCP 客户端** | `apps/api/agent/node_modules/@earendil-works/pi-coding-agent/dist/` 全树无 mcp 引用；依赖列表无 MCP SDK |
| Agent 通过 **skill（SKILL.md + manifest）+ 结构化提交**工作，后端校验后落地 | `agent/skills/video_agent_3d_storyboard/SKILL.md`（SceneScript 契约）；`app/api/internal/router.py:349` `/agent-tools/execute` 结构化校验 |
| Blender headless 渲染基建完整 | `app/services/scene3d/blender_renderer.py`（subprocess/超时/产物收集）、`blender_converter.py`（SceneScript→bpy 脚本） |
| SceneScript 是唯一规范格式，前端 Three.js 实时预览已存在 | ADR 0005 §1；`web/src/features/agent-canvas/canvas/SceneScript3DPreview.tsx` |
| 异步渲染任务管理已存在（长超时） | `scene3d/render_job_manager.py`；`/scene-3d/render/async` 端点 |
| scene-3d 节点内容是 freeform，PATCH 可持久化 SceneScript | `agent_canvas_ad_media.py:146`；`agent_canvas.py:2398 patch_node` |

### 1.2 架构决策：三层，而不是"Agent 裸操 Blender"

```
┌──────────────────────────────────────────────────────────────┐
│ Agent 层（Node runtime，不动）                                    │
│  新 skill: video_agent_3d_white_model                          │
│  输出结构化"场景操作序列"（SceneScript 增量 patch + 可选的      │
│  MCP 高级操作请求），经 /internal/v1/agent-tools/execute 校验    │
├──────────────────────────────────────────────────────────────┤
│ 后端领域层（Python，SceneScript 唯一规范状态）                     │
│  SceneScriptToolService：校验操作 → 应用 → 版本+1 → 事件         │
│  BlenderMcpClient：按需调 MCP 扩展词汇（倒角/细分/布尔…）        │
│  BlenderRenderer：既有 SceneScript→MP4 渲染                     │
├──────────────────────────────────────────────────────────────┤
│ 进程层                                                          │
│  blender --background（既有） ＋ blender-mcp server（子进程 stdio）│
└──────────────────────────────────────────────────────────────┘
```

**为什么不让 Agent 直接驱动 Blender MCP 做自由建模？**

1. SceneScript 是前端预览、JSON 页签、视频提示词管线（`prompt_builder.py`）、控制通道（`control_passes.py`）的共同输入。自由建模产生的 .blend 场景无法回流这些链路 → 预览与最终渲染会分叉。
2. 版本与冲突：SceneScript 有乐观锁（节点 ETag）；.blend 二进制没有可合并的版本语义。
3. 安全：任意 Blender Python 执行 = 任意代码执行。必须收窄为**受控工具集**。

**MCP 的正确定位：扩展建模词汇表。** SceneScript 的 13 种环境 + 12 种道具类型覆盖 90% 的 blockout；当用户描述超出词汇表（"门要有金属包边和铆钉"、"桌面要开槽"），Agent 发出 MCP 高级操作请求，由后端 `BlenderMcpClient` 执行，执行结果以**几何参数**形式回写 SceneScript 的扩展字段（或生成白模变体资产）。回写不了的，明确降级并告知用户（工程标准 §4，可查询降级）。

**撤回方案（如实记录）**：
- *前端直连 Blender MCP（浏览器 WebSocket 到本地 MCP server）*：违背"后端拥有 provider/工具"的分层（ provider 名词不进领域代码，CONTEXT.md 纪律）；浏览器无法安全持有 Blender 进程句柄；部署形态（Blender 在容器）不支持。
- *用 MCP 替代既有 BlenderRenderer*：MCP 的 render 工具与 `render_job_manager` 的异步/超时/能力指纹体系重复，且成熟度不如既有链路；MCP 只做 Renderer 不覆盖的高级几何。

### 1.3 白模设计模式：意图 → 界面跟随

**入口（三处触发，互为补充）**：
1. scene-3d 节点上的 **「白模设计」模式按钮**（明确意图）。
2. 对话意图识别：`front_desk.py` 分类扩展"white_model_intent"——用户说"我想做个白模"/"先摆个 blocking 看看" → 系统建议切换到白模设计模式（确认制，不劫持）。
3. 资产拖入：图片/全景图拖到 scene-3d 节点（Q2 已实现 `analyze-image`）→ 生成 blockout 后自动进入工作台。

**模式化的界面（模式 = 画布进入"导演工作台"全屏，复用既有 workbench 外壳理念）**：

```
┌─────────────────────────────────────────────────────────────────────┐
│ 白模设计模式 — 场景「地下研究所 B2」    [退出] [生成参考视频] [手动编辑] │
├──────────────┬──────────────────────────────────────┬───────────────┤
│ Agent 对话    │                                      │ 检查器          │
│ ┌──────────┐ │      实时 3D 视口（Three.js）          │ 选中物体 transform│
│ │你: 先搭一 │ │      · 灰白模材质（模式切换）          │ MCP 操作日志     │
│ │个 8×6 的 │ │      · 选择高亮 / 坐标轴 / 地栅格       │ · 14:02 created │
│ │走廊，尽  │ │      · Agent 每步操作即时反映           │   wall_4        │
│ │头一道铁门│ │      · 播放/帧步进/相机轨迹线           │ · 14:02 bevel   │
│ │          │ │                                      │   door_1 (MCP)  │
│ │Agent: 好 │ │                                      │ SceneScript 版本 │
│ │的，我先… │ │      ▶ 播放条 frame 0 ──●── 180       │ v7 · 已保存      │
│ └──────────┘ │                                      │               │
│ [描述你的想法]│                                      │               │
├──────────────┴──────────────────────────────────────┴───────────────┤
│ 参考视频预览条：[预演 MP4 v3 ▸] [关键帧 1/2/3]       帧轨 ◆关键帧      │
└─────────────────────────────────────────────────────────────────────┘
```

**Agent 建模循环（核心体验）**：
1. 用户描述（自然语言，可迭代多轮："墙再高一点""加两个储物柜"）。
2. Agent 输出**结构化操作序列**（不是一整包 SceneScript 重生成——增量才可预览、可回放、可撤销）：`{ops: [{op: "add_environment", type: "wall", ...}, {op: "mcp_request", tool: "bevel", target: "door_1", params: {...}}]}`。
3. 后端逐个校验应用 → SceneScript 版本+1 → SSE 推给前端 → **视口实时反映每一步**（用户看到"墙在长高"的过程，而不是黑盒等待）。
4. MCP 类操作的进度/结果在右栏日志可见（含降级标记）。
5. 满意后 **「生成参考视频」** → 既有 `/scene-3d/render/async` → 预演 MP4 + 关键帧落入预览条与时间线 camera 轨。
6. **「手动编辑」** → 视口切到编辑模式（复用 3D 工作台方案的 P1/P2：选择-变换-关键帧-相机放置），Agent 操作与手动操作共用同一 SceneScript 版本线，互不覆盖（版本冲突走乐观锁提示）。

### 1.4 MCP 工具集与安全边界

**v1 工具集（受控白名单）**：
- `scene_info` / `list_objects`（只读）
- `add_primitive`（box/sphere/cylinder/cone，位置+尺寸，映射 SceneScript 类型）
- `transform_object`（move/rotate/scale，带边界盒约束：坐标 |x,y|≤30m，z≥0）
- `set_camera`（position + look_at + shot_type）
- `add_keyframe` / `remove_keyframe`
- `bevel` / `subdivide` / `boolean_union` / `boolean_difference`（高级几何，**仅这些**是 MCP 执行；结果回写为 SceneScript 扩展字段 `geometry_hints`）
- `render_preview`（单帧，快速验证用）
- **禁止**：任意 Python 执行、文件系统访问、外部网络。

**安全与韧性**：
- MCP server 以子进程 stdio 启动，每调用超时（默认 30s，可配）；崩溃 → 标记 `mcp_unavailable`，场景操作降级为纯 SceneScript（可查询降级事件，不静默）。
- 所有 MCP 调用在工作流锁（`v2_workflow_lock` 既有模式）内串行，避免与手动编辑竞争。
- 二进制/几何产物落在 `validate_v2_data_path` 校验的数据目录内。

### 1.5 预览策略（建模 + 参考视频双预览）

| 预览对象 | 载体 | 更新时机 |
|---|---|---|
| 建模（实时） | Three.js 视口，白模模式下强制灰白材质 + 边线，突出结构而非材质 | 每个 op 应用后（SSE 推送，帧级节流） |
| 参考视频（渲染） | 既有 media 预览播放器 + 预览条缩略 | 异步渲染完成后（render job 事件） |
| 手动编辑 | 视口切编辑模式（见 3D 工作台方案 P1/P2） | 用户操作即时本地 + 保存时 PATCH 节点 |

"建模预览开放手动编辑"= 同一视口的两种模式（回放/编辑），共享 SceneScript 状态；**不需要第二套编辑器**。这是"惊艳且不分裂"的关键：用户看见 Agent 建的墙，可以直接上手拖动它。

---

## 2. StepAudio 3 Gen × 音频制作协作

### 2.1 已落地（本轮）

`app/tools/step_audio_gen.py`：完整客户端（roles/scripts/instruction、response_format 五种、speed/volume/sample_rate、pronunciation_map、text_normalization、return_url、URL/base64/raw 三种响应形态、HTTP 错误映射、ffprobe 落盘校验、`per_element_timing_available: False` 显式标记）。配置项 `STEP_AUDIO_GEN_*` 已入 `Settings`。28 项单测 + mutation 检查通过。

### 2.2 音频节点改造：从"voice-cast 单台词"到"音频床（Audio Bed）"

**现状**：voice-cast 节点逐句 TTS（stepaudio-2.5-tts），输出 speech_audio 资产，`speech_orchestration` 做启发式唇形。

**改造**：voice-cast 节点增加 **unified 模式**（或新的 `audio-bed` 语义角色，遵循 glossary 纪律一次只加一个词）：

```
输入（节点结构化内容）:
  roles:      [{name, description}]        # 音色设定，可引用角色资产描述
  scripts:    [{speaker?, text}]            # 台词(带speaker) / [音效·环境音·BGM](无speaker)
  instruction: "废弃地下研究所，悬疑氛围"      # 全局基调
  per_line_fallback: bool                   # 关键特写是否补逐句 TTS

执行：
  StepAudioGenAdapter.generate_unified_audio(...)
  → speech_audio 资产（一整段音频床，duration_seconds 来自 ffprobe 实测）
  → 资产 metadata 记录 per_element_timing_available=False + 原始 scripts/roles 快照
```

**前端音频工作台**（EditingWorkbench 旁的新面板或 voice-cast 节点工作台）：
- 剧本表格编辑器：每行一个 script —— speaker 下拉（来自 roles）、text 输入（`()`情绪与`[]`音效有语法高亮提示）、上/下移、删除。
- roles 编辑器：姓名 + 音色描述（提供"从角色资产导入"按钮，把角色设定里的外观/性格描述转写为音色描述——Dramagic 式资产复用到声音）。
- 播放器 + 波形（既有 `AudioWaveformTrack` 能力可复用）。
- **一键分镜建议**：见 §3.2。

### 2.3 时序缺口与三种对齐模式（诚实的工程答案）

StepAudio 3 Gen **不返回时间戳**（模型文档明确不支持 `timestamp`）。台词驱动视频需要"谁在第几秒说什么"。三种模式，按镜头重要性选择：

| 模式 | 做法 | 适用 | 时序精度 |
|---|---|---|---|
| **A. 音频床主导** | 整段床音作为主音频轨；分镜按视觉节奏剪辑；对白口型后期用强制对齐补 | 环境叙事、旁白型短片、氛围广告 | 秒级（对齐后~100ms） |
| **B. 逐句精确** | 每句单独 TTS（既有链路），实测时长入时间线；3D 唇形关键帧精确生成 | 对白特写、双人对话戏 | 帧级 |
| **C. 床音 + 强制对齐** | 生成床音 → WhisperX/中文对齐模型跑一遍 → 恢复每句起止 → 自动落字幕 + 唇形关键帧 + 分镜边界建议 | **默认推荐**：质量与效率的平衡点 | ~100–200ms |

模式 C 是对白驱动短片的"甜点"：一次生成获得收音质感的统一床音（语气衔接、环境融合是逐句拼接做不到的），再用对齐把时间结构补回来。**C 的分词对齐结果必须带置信度**，低置信句自动降级为该句的 B 模式重生成（可查询降级，工程标准 §4）。

---

## 3. 音频 × 分镜：相辅相成的协作设计

### 3.1 传统模式 vs 新模式

| 维度 | 传统流水线 | AdCraft 新模式（本方案） |
|---|---|---|
| 起点 | 剧本 → 分镜表（时长导演拍脑袋：这个镜头 3 秒） | 剧本 → **音频先行**：台词/音效的真实时长成为分镜的第一份数据 |
| 时长依据 | 经验值，后期配音才发现装不下/对不上 | TTS/床音实测时长（ADR 0003 `bound` 模式已有此语义） |
| 运镜切换点 | 均分或感觉 | **贴着语音停顿与声音事件切**（ADR 0007 §5.3 设计 + beat 检测已实现 BGM 版，语音停顿检测是缺口） |
| 对白口型 | 后期配音演员对口型（人工） | 语音 → 唇形关键帧 → 3D 预演 → 视频模型运动参考（链路已铺，缺对齐精度） |
| 音效/环境 | 后期找素材库试听粘贴 | `[]` 描述进 scripts，与对白**同一语境**生成，天然融合 |
| 分镜灵活性 | 分镜表是死的，改一句台词全线返工 | 分镜表是声音时间线的**投影**：改台词 → 时长/边界自动重排，下游 staleness 标记传播（既有 stale 机制） |
| 一致性 | 每集换配音演员，角色声音漂移 | roles 绑定角色资产，跨集同音色（Dramagic 式一致性锁延伸到声音） |

### 3.2 声音事件 → 镜头：一键分镜建议

音频床（模式 C）对齐后，时间线上出现两类事件：**语音段**（谁、说什么）与**声音事件**（`[金属门撞响]`、`[警报渐起]`）。分镜生成的规则：

1. 每个语音段 ≥1 个镜头（景别由情绪与台词内容建议：特写对话 / 中景互动）。
2. 每个声音事件 = 一个**必要镜头**：`[金属门撞响]` 必须有一个画面承载它（门、或角色的反应）——这是"声音牵引画面"的关键创新：传统是画面定声音，现在是**声音事件暴露被漏掉的画面**。
3. 停顿 ≥0.8s 的区间 → 建议"呼吸镜头"（空镜/反应镜头/环境细节）。
4. 语音段之间的情绪反差 → 建议景别跳切（推近/拉远）。

产物：分镜建议表（可编辑）→ 一键生成 video/scene-3d 节点（复用 ADR 0007 §2.4 "从时间线创建分镜节点"的既有能力）。**分镜表从此是动态的**：音频改 → 建议表重算 → 用户确认增量。

### 3.3 氛围音频 → 景别与光线建议

床音的 `instruction`（"悬疑"、"温暖怀旧"、"压迫"）与音频特征（响度、频谱、节拍）映射为视觉预设建议：
- 悬疑/压迫 → 冷光 preset + 缓推 + 浅景别
- 温暖/怀旧 → 暖光 + 固定机位 + 柔焦
- 节拍明显（BGM bed）→ 切点吸附节拍（`timeline_beat_analysis.py` 已有）

音频不再只是"配乐"，而是**视觉风格的另一份输入**。

### 3.4 角色音色资产化与跨集一致性（Dramagic 式一致性锁 §5.3 的声音版）

- `roles` 的 name 绑定角色资产（`character_asset_id` 同源思想），音色描述进角色资产的扩展字段。
- 多场景/多集复用同一角色时，音色描述自动带出；QA registry 增加"同角色跨 scene-3d 音色一致性"检查（warning 级）。
- 重制/换语言（Dramagic 的翻拍链路）：剧本换语言 → roles 描述重写 → 新床音 → 对齐 → 唇形/时长重排。

---

## 4. 创作者工作模式：轻松、酷炫、完整交付

### 4.1 两种工作模式，一个编排层

```
模式一：音频先行（对白驱动：微电影、短剧、广播剧式广告）
  剧本台词+音效描述 → StepAudio 3 Gen 床音 → 对齐恢复时序 →
  分镜建议（声音牵引）→ 3D 预演/白模设计（Blender MCP）→ 视频生成 → 时间线精修 → 成片

模式二：画面先行（视觉驱动：产品广告、氛围片）
  产品/角色/场景 → 分镜 → 视频生成 → 音频床按成片时长生成（instruction 描述氛围）
  → 时间线混音（闪避已有）→ 成片
```

两种模式在**时间线编排层收敛**（ADR 0007 原则不变）：节点负责生成，时间线负责编排，editing 负责渲染。工作模式只是"先生成谁"的顺序选择，不是两套管线。

### 4.2 "酷炫"的三个瞬间

1. **一句话出一床音频**：粘贴剧本片段 → 选角色音色 → 一段带环境音、音效、多角色情绪对白的完整床音诞生（对比传统：找配音、找素材、对时间轴）。
2. **Agent 搭白模的过程可见**：描述想法，视口里墙一堵立起来、门装上、相机摆好——建模从黑盒变成"看着它发生"，且随时可以抢过鼠标自己拖。
3. **改一句台词，全线跟着动**：分镜边界、唇形关键帧、字幕自动重排，用户只确认增量。

### 4.3 完整交付闭环（不丢东西）

成片 = 视频拼接（时间线）+ 床音/语音轨（闪避混音，已有）+ 字幕（对齐结果自动生成，已有 SRT/ASS 管线）+ 参考溯源（SceneScript 版本、音频生成参数、MCP 操作日志全部随资产沉淀）。每一步可解释、可回放、可重生成。

---

## 5. 落地方案

### P1 — 音频床节点（P0，2 周）
- [x] `step_audio_gen.py` 客户端 + 配置 + 单测
- [x] **voice-cast 节点 unified 模式**（2026-09-26）：节点 `structured_content.audio_bed` 携带 roles/scripts/instruction 时走 `StepAudioGenAdapter.generate_unified_audio`（real 模式）；mock 模式写确定性 WAV（近静音 220Hz，时长按脚本估算 1–60s）保证全链路离线可跑。资产 metadata 固定记录 `audio_bed: true`、`per_element_timing_available: False`（模型不给每句时间戳，对齐决策必须显式）、`duration_source`（mock/measured）、脚本与 roles 快照。失败全 coded：scripts 缺失/非对象/roles 非列表、provider 失败（带 error_code + retryable）、未配置 key（`external/revise/no-retry` 可执派，与逐句 TTS 同款语义）。无 audio_bed 块时逐句 TTS 路径原样不动
- [x] **前端音频工作台**（2026-09-26）：`workbench/AudioBedEditor.tsx` + `workbench/audioBedConfig.ts`（纯契约：解析/序列化/校验与后端同规则——至少一条脚本、speaker 必须有对应且完整的 role、role 名唯一；空行序列化时丢弃；1000/500/500 字符预算实时显示）。voice-cast 节点工作台渲染编辑器；保存走 `patchNode` **合并** structured_content（narration 等键保留）；`LocalEngineWorkbench` 的 run 门在有 `audio_bed` 块时不再要求 prompt 非空（unified 路径不读 prompt）。10 项组件测试 + 14 项契约测试
- [x] **床音预览**（2026-09-26）：`AgentCanvasInlineWorkbench` 从 `workflow.assets` 解析 `node.output_asset_id` 得到输出资产，经 LocalEngineWorkbench 传给 voice-cast 工作台，渲染现成的 `AgentCanvasAudioPlayer`（标题=节点提示词摘录、content 端点播放、收藏/进度都在）；**没有输出资产时整个播放区不渲染**；scene-3d 节点不渲染（画布节点卡拥有那个展示面）
- [ ] 时间线：床音作为单 clip 落 audio 轨（auto-creator 扩展），subtitle 轨占位
- **验收**：粘贴一段三角色对白+音效 → 一键生成床音 → 时间线播放 → 导出成片带音频；参数越界/未配置时错误可见（工程标准 §4）——后端已就绪，前端工作台是剩余项

### P2 — Blender MCP 集成 + 白模设计模式（P0，3–4 周）
- [x] `scene3d/blender_mcp_client.py`（2026-09-26）：stdio JSON-RPC 2.0 客户端。**Transport 是 Protocol**（默认 `StdioMcpTransport` 子进程；测试注入脚本化 fake，不 spawn Blender）。握手 initialize → notifications/initialized → tools/list 发现；`call_tool` 只接受白名单工具（scene_info/list_objects/add_primitive/transform_object/set_camera/add_keyframe/remove_keyframe/bevel/subdivide/boolean_union/boolean_difference/render_preview——**render_video 故意不在内**，渲染链路保持 SceneScript→BlenderRenderer  canonical）；**transform 类操作客户端 bbox 强制**（|x,y|≤50m、0≤z≤30m）防 agent 把几何体扔到 10km 外或地板下；能力指纹 ready/degraded（缺工具逐一列出，不静默）/unsupported；错误全 coded（mcp_tool_not_allowed / mcp_tool_unavailable / mcp_tool_error / mcp_transform_out_of_bounds / mcp_protocol_error / mcp_server_spawn_failed）。配置 `BLENDER_MCP_COMMAND`/`BLENDER_MCP_TIMEOUT_SECONDS`
- [x] **`scene_script_tool_service.py`**（2026-09-26）：agent 输出**操作序列**（add_environment/add_prop/add_character/add_camera/move_object/rotate_object/scale_object/set_camera/add_keyframe/remove_object/mcp_request）而非整包 SceneScript。**对进行中的脚本校验**——批次内可引用自己前面的 op 创建的对象（"加角色再移它"），原子性由工作副本保证（任一违规全批丢弃，violations 逐条列出供 repair）；枚举经 `typing.get_args` 从 schema 取（新类型零改动）；bbox/move/frame 边界同 MCP 客户端；`mcp_request` 是扩展词汇——执行并**上报**（几何留在 Blender，SceneScript `extra="forbid"` 带不了厂商几何，视频提示词管线必须继续消费一种格式），无客户端时整批拒绝并给出 `mcp_unavailable`（可查询降级）。`POST /scene-3d/apply-operations` 暴露；use_mcp 且 spawn 失败 → 503 mcp_unavailable
- [x] agent skill `video_agent_3d_white_model`（2026-09-26）：SKILL.md（7752 字节，在 8192 上下文预算内）+ skills/manifest.json 重新生成 + `verify:skills` 通过。**操作批次契约**：输出 `{"operations": [...]}`（一次响应=一批 2–10 个 op）、11 种 op 字段表、枚举表（从 schema 现取，零漂移）、批次语义（全有或全无、批内前向引用、bbox/frame 边界、按区域分块）、MCP 扩展 op 使用规则（target 必须存在、只做精修不做基础阻挡、非白名单不过线）、空间推理规则、迭代流（每轮一批）。Python 侧新增 `AgentCanvasWhiteModelOutput` 契约 + `execute_canvas_white_model` 操作（55 个操作，contract/registry 146 项测试通过）；TS 侧 registry 注册 + `contracts/agent-capabilities.json` 加操作。**已知环境问题**：`src/generated/agent-runtime.schema.json`/`.ts` 两个派生文件在本机（OneDrive+WSL）被反复回退——生成命令本身验证可用（临时目录证明），需要在稳定文件系统上重跑 `python -m app.cli.generate_agent_contracts --output ../agent/src/generated`
- [x] **白模生成链路 + 模式入口**（2026-09-26）：`white_model_generator.py`——LLM 按 skill 契约输出操作批次，经 SceneScriptToolService **同一道闸门**应用（agent 输出永远不是被信任的脚本；base_script 支持增量编辑，提示词带现有对象 id 清单；新场景从带相机+shot 的 starter 脚本起步；失败全 coded 且闸门拒绝带逐条 violations）；Scene3DNodeExecutor `white_model` 分支（无注入 generator 时 `white_model_generator_missing` 响亮失败，不静默回退；`white_model_report` 发布到节点）；前端 scene-3d 工作台模式开关（PATCH 合并写 flag，两态说明文案）
- [x] **操作日志面板**（2026-09-26）：`canvas/WhiteModelOpLog.tsx`——渲染节点 `structured_content.white_model_report`：`applied` 操作列表（中文标签映射，永不向用户展示原始 op code）+ target、`mcp_results`（工具 → target + 已执行/失败状态）、`applied/total` 诚实话计数（部分应用不虚报）；`<details>` 折叠（过程是证据不是工作区）；渲染在 **lazy 编辑器 chunk 之外**——不等 three.js 加载也能看日志
- [ ] 前端剩余：工作台全屏化
- **验收**：对话描述走廊+铁门 → 视口分步呈现建模 → 生成参考视频 → 切换手动编辑拖动一面墙 → 保存 → 刷新后位置保持；MCP 不可用时降级为纯 SceneScript 且有标记

### P3 — 床音对齐与台词驱动闭环（P1，2–3 周）
- [x] **台词驱动最后一步的 UI（场景侧唇形面板）**（2026-09-26）：`DialogueLipSyncPanel.tsx`——scene-3d 工作台里编辑台词行（说话人下拉来自场景角色+台词输入）→「👄 应用唇形到场景」POST 当前草稿 → 返回的新脚本成为草稿：**视口、Blender 渲染、视频提示词全部反映唇形**；summary 如实显示时长来源（TTS 实测/强制对齐/文本估算）与重叠提示；后端拒绝（如未定义角色）原样透传。此前 `/scene-3d/dialogue-lipsync` 只有端点没有调用方——现在"台词进、唇形场景出"在 UI 上闭环
- [x] **E2E 台词驱动链路验证 + 两个真 bug 修复**（2026-09-26）：`tests/test_dialogue_driven_previs_e2e.py`（integration 标记）把真实服务串成链：blockout → dialogue+measured TTS → 唇形关键帧合并 → 一致性闸门 → 视频提示词包，锁定不变量（talk 帧落在语音处、台词交错而非分块、Blocking 保留、bound 绑定存活、提示词携带 speaking）。**测试捕获并修复两个预存在 bug**：① 唇形帧与已有关键帧同帧时更新写进旁路 dict 而输出列表是循环前拷贝的——frame-0 关键帧（最普遍！）的嘴永远打不开；② 合并重建 SceneCharacter 时丢失 `character_asset_id`——跑一次唇形就把 Dramagic 身份绑定静默剥离
- [x] **台词驱动唇形接线（B 模式地基）**：`app/services/scene3d/dialogue_lipsync_service.py`（`apply_dialogue_lip_sync`）+ `POST /scene-3d/dialogue-lipsync`。链路：dialogue_lines → `build_timeline_from_script`（有 TTS 引擎=measured，否则 estimated 且在 summary 声明来源）→ `LipSyncGenerator.merge_into_scene_script`（唇形关键帧前向继承位置/朝向）→ SceneScriptRoot 重新校验 + 合并后关键帧越界断言。重叠/越界以 advisory issue 上报不静默；**未定义角色 fail closed 并列出可用角色 id**（schema 拒绝幽灵 SpeechBinding，静默丢台词违背完整交付）
- [x] **强制对齐 UI 触发**（2026-09-26）：`POST /align-speech` 支持按 `asset_id` 解析节点输出资产（timeline 同款 asset→storage_key→本地路径模式，免上传）；voice-cast 工作台的「🎯 台词对齐」面板——有输出资产且有带 speaker 的台词时才出现，调对齐后逐行展示（角色/台词/起止/置信度），**引擎名称诚实显示**（"确定性估算铺排（未实测）"），低置信句黄色点名；SFX 行（无 speaker）自动排除
- [x] **强制对齐服务（C 模式地基）**（2026-09-26）
- [x] **C 模式 UI 闭环：对齐结果直达唇形面板**（2026-09-26）
- [x] **台词上字幕轨：唇形同一边界驱动字幕 cues**（2026-09-26）
- [x] **字幕上轨幂等**（2026-09-26）
- [x] **台词驱动→视频模型参考链路验证**（2026-09-26）
- [x] **客户端时间线变更信号**（2026-09-26）
- [x] **3D 视口可见唇形**（2026-09-26）
- [x] **3D 视口台词浮层**（2026-09-26）：`activeDialogueLineAtFrame` 纯函数（该句持续到**同一说话人的下一句**而非自己的估算 end——床音无逐句结束时间，估算会与字幕 cues 漂移）+ drei Html DOM 浮层（避开 troika -109 KiB）；持久化 dialogue_lines 单一数据源驱动 嘴/浮层/字幕轨 三表面：`characterActionAtFrame`（最近关键帧 action、与后端合并一致的继承语义）+ 嘴部网格（talk 帧张开、确定性于帧）；此前视口是木头人——台词驱动在 3D 工作台上无视觉确认：`timelineMutationRefresh` 外部 store + `useSyncExternalStore`；字幕上轨是跨面板的客户端直写，SSE 听不到——发布成功后 bump，时间线面板即时刷新：床音绑给视频节点（audio_reference）→ seedance 编译器输出 audio_url → 时间窗切片器按镜头窗切片——视频模型拿这一镜的台词片段；锁定测试防音频引用被静默丢弃：发布 clip 带 `source_node_id` 溯源，重发布=替换本节点旧 cues（别人的与 unowned 不动）；旧集读不到仍写新 cues——陈旧重复可见可手删，不静默失败；结果消息含替换计数
- [x] **编排提示：speaker 与角色 id 失配预警**（2026-09-26）
- [x] **bed 角色绑定场景角色 ID**（2026-09-26）
- [x] **台词行持久化 + 床音节点可拖入时间线**（2026-09-26）：唇形面板台词行落 `structured_content.dialogue_lines`（600ms 去抖 coalesce PATCH、merge 不替换、unmount flush、值等跳过；失败 best-effort 不阻塞编辑）——修复刷新即丢失对齐工件的缺口；voice-cast 节点成为拖源，clip label 带说话人名单（多说话人床音刻意不绑角色 id，名单走 label）：`AudioBedRole.character_id`（可选）——StepAudio 线上契约无此字段、provider payload builder 天然丢弃，**桥本地、线上零成本**；对齐面板 `speakerCharacterMap` 在交接时把展示名映射为角色 id 并显示 `林澈 → char_a` 芯片。修复的真实缺口：此前作者只能靠把场景角色改名成 speaker 名来绕过：`creation_flow_guidance` 跨阶段警告（失配 speaker 点名 + 可用角色 id 列表）——唇形对未知 speaker fail closed 是对的，但首作者不应写完整个床音才知情；画布级提示把话说在动手之前。前端警告截断改为 3 条+「还有 N 条」计数（截断必须可见）：`dialogue_lipsync_service` summary 新增 `segments` 每句起止（曾考虑前端按字速率重新估算——否决，字幕与口型必须同源否则必然分叉）；前端 `dialogueSubtitleCues.ts`（纯函数：跨话抢白按下一句起点钳制、零时长/空文本带理由跳过）+ `publishSubtitleCues.ts`（字幕轨缺失即抛错、逐条 createClip 部分失败按 cue 上报）+ 唇形面板「🗎 台词上字幕轨」按钮（仅应用唇形后出现）。字幕 cues 正式落到 ADR 0007/0008 双相时间线的剪辑面：`DialogueAlignmentPanel` 的 `onLinesAligned` 把每句起止上交页面级状态（`AgentCanvasPageSurface`——对齐面板与唇形编辑器在不同节点工作台、单选切换，状态必须活过切换），scene-3d 工作台播种给 `DialogueLipSyncPanel.initialLines`；唇形面板新增**起句时间输入**（对齐实测值可见可改、留空回落估算）——此前 start_time 只存在于模型、UI 无处编辑（测试发现的缺口）。至此 C 模式：床音 → 对齐 → （跨节点）→ 口型关键帧，产品表层无断点：`app/services/scene3d/speech_alignment.py`——`SpeechAligner` 契约 + 两个引擎：`WhisperXAligner`（真强制对齐，torch 依赖**惰性导入**，模块本身零重依赖；词级概率平均为句级置信度）+ `EstimatedSpeechAligner`（确定性回退：按估计时长顺序铺排、缩放到实测床长、显式 cue 锚点优先、未锚句只填到下一个 cue；`align_source="estimated"`、置信度 0.4 保守带）。`build_speech_aligner` 按 `SPEECH_ALIGNMENT_ENGINE` 选择，whisperX 缺失时回落且**报告里说明**。`POST /scene-3d/align-speech`：床音 + 已知台词 → 每句起止 + 置信度 + `low_confidence_ids`（低于 0.6 的片段点名，调用方决定重生成或显式接受）+ `to_dialogue_lines` 把对齐结果喂给唇形服务（C 模式闭环：对齐 → 唇形关键帧 → 字幕 cues）。唇形服务 summary 新增 `pretimed_line_count` 与 `duration_source: "aligned"`
- [x] **低置信句自动 B 模式重生成**（2026-09-26）：`regenerate_low_confidence_segments`——保留对齐起句、逐句重测时长（真实 TTS=measured，占位估算=estimated，来源如实报告）、超长钳制到下一句/床末尾并点名、置信度保持低位（长度可信≠位置可信）；端点 `regenerate_low_confidence` 默认 true 可 opt-out；对齐面板有汇总行与逐句「B 模式重测」徽章
- [x] **词级唇形**（2026-09-26）：whisperX 的词级时间戳经 `word_timings` 贯通到唇形关键帧（`word_mouth_frames`：词开嘴、词闭幕），嘴跟着词动而非按节拍器抖；无词级数据（估算对齐/畸形时间戳）时保持原音节节拍器——严格增量。真音素级 viseme 形状键仍开放。上一条「音素级唇形（启发式）」由此升级
- [x] **字幕自动生成**（2026-09-26）：应用唇形的同一手势内发布字幕 cues（`publishCues` 抽成复用回调；幂等替换带 `sourceNodeId`，应用两次不堆叠）；无 workflowId 不写时间线；发布失败不拖垮 apply；「🗎 台词上字幕轨」按钮保留供改后重发。C 模式链（床音 → 对齐 → 唇形 → 字幕）收为一个作者行为
- [ ] 前端接线：3D 编辑台「台词驱动」面板调用该端点（对白表 → 唇形预览）
- **验收**：床音 → 对齐 → 每句起止误差 <200ms（抽样 20 句）→ 字幕轨自动填充 → 特写镜头唇形关键帧可见

### P4 — 声音牵引分镜（P1，2 周）
- [ ] 语音停顿检测（ADR 0007 §5.3 的"运镜跟随语音节奏"开关）
- [ ] 声音事件 → 必要镜头检查（QA registry：床音含 `[x]` 事件但分镜无承载镜头 → warning）
- [ ] 一键分镜建议表（可编辑）→ 生成节点（复用时间线→节点能力）
- **验收**：改一句台词 → 分镜建议重排 → 确认增量 → 下游 shot stale 标记正确传播

### P5 — 音色资产化与重制（P2，按需）
- [ ] roles 绑定角色资产 + 音色描述字段 + 跨场景一致性 warning
- [ ] 换语言重制链路评估（Dramagic 翻拍）：剧本替换 → roles 重写 → 新床音 → 对齐 → 重排
- **验收**：同一角色在两集工作流中音色描述一致；一集床音换语言重生成后时间结构保持

### 风险与缓解

| 风险 | 缓解 |
|---|---|
| Blender MCP server 成熟度/稳定性未知 | 受控白名单 + 每调用超时 + `mcp_unavailable` 降级为纯 SceneScript（链路本就完整）；MCP 只做增强几何 |
| 强制对齐模型中文精度/依赖重量 | 模型可插拔；失败降级逐句 TTS（B 模式）；对齐置信度驱动降级决策 |
| 床音时长不可控（文档称 1–3 分钟级输出可能超视频长度） | 时间线裁剪既有（trim）；长床音拆段；duration 元数据记录请求值 |
| Agent 结构化操作的校验成本 | 操作是 SceneScript 增量而非全文，校验便宜；非法 op 逐条拒绝并可修复（既有 repair_allowed 机制） |
| 音频先行改变用户习惯 | 两种模式都保留，引导流程按内容类型推荐（对白密度高的默认音频先行） |

### 术语与 ADR 关系

- 新词进入 `CONTEXT.md` 词汇表：**Audio Bed（音频床）**、**White-Model Design Mode（白模设计模式）**、**Sound Event（声音事件）**、**Scene Operation（场景操作）**。避免同义词漂移。
- 本方案扩展 ADR 0003（语音轨：unified 生成 + 对齐）、ADR 0005（预演：MCP 扩展建模）、ADR 0007（时间线：声音事件/语音停顿）；不修改三者核心决策。合并前升为 ADR 0008 草案（跨上下文决策，工程标准 §6）。
