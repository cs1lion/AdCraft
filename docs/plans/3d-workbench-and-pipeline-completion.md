# 3D 导演工作台 × 视频制作流水线补全 — 需求拆解与设计方案

> **Status**: Proposed（2026-09-25）
> **触发**: 借鉴 Dramagic（BytePlus 企业级 AI 短剧工作台）的设计思想，补齐 AdCraft 视频制作流水线，设计 3D 工作台。
> **关联 ADR**: [0005 3D 低保真预演](./adr/0005-3d-low-fidelity-previs.md) · [0007 时间线驱动制片](./adr/0007-timeline-driven-production.md) · [0003 对白/语音轨](./adr/0003-dialogue-speech-track.md)
> **纪律**: 本文所有"现状"结论均在 2026-09-25 工作树上逐条核对过代码；每条补全建议标注对应的现有文件/扩展点。

---

## 0. TL;DR — 五个问题的代码级答案

| # | 问题 | 结论 | 关键证据 |
|---|------|------|----------|
| Q1 | 生成全景图，直接给视频模型是否识别？还是必须 3D 建模？ | **直接喂图不可行**（视频模型把全景图当成一张扭曲的普通图片，无空间理解、无运镜控制）。有三档可行路径：**① MiDaS 深度白模（2.5D 重投影）② SceneScript 3D 预演（全可控）③ NeRF/3DGS 真重建（P6+ 研究线）**。当前仓库已实现 ①②的基础设施 | `scene3d/depth_estimator.py`（MiDaS 已在）、`scene3d/blender_renderer.py` + ADR 0005 全链路已验证（`docs/3d-previs-to-photoreal-video-workflow.md`） |
| Q2 | 拖入图片直接做建模怎么实现？ | 仓库已有 **参考视频 → SceneScript** 的多模态 LLM 分析器（`reference_video_analyzer.py`）。图片建模 = **同一架构的图片版**：等距柱状全景图先裁剪成透视立方体面图 → 多模态 LLM 逐帧分析 → 合成合法 SceneScript（Pydantic 校验，fail closed）→ 3D 工作台可编辑。**前后端全通**（2026-09-26）：后端 `scene3d/image_analyzer.py` + `POST /scene-3d/analyze-image`；前端 scene-3d 工作台「🖼 从图片生成场景」拖放区 → 返回脚本直接成为草稿，视口即时预览 + 全部编辑工具可用，全景切面 warning 上屏 | `reference_video_analyzer.py` 的 `_analyze_frame` / `_SCENE_SCRIPT_SYSTEM_PROMPT` / `SceneScriptRoot` 校验 |
| Q3 | 用建模放置镜头、操作人物运动，如何更可控？ | SceneScript 的 `cameras[].keyframes`（position + look_at）与 `characters[].keyframes` 已是结构化可控载体，shot 模板 7 套已就绪。缺的是**前端可交互化**：当前 `SceneScript3DPreview.tsx` 是只读回放。补一个**交互视口（选择-变换-关键帧-相机放置）**，经 `PATCH /api/v2/workflows/{id}/nodes/{id}`（scene-3d 节点为 freeform 角色，已验证可写入）持久化 | `SceneScript3DPreview.tsx`（只读）、`agent_canvas.py:2398 patch_node`、`agent_canvas_ad_media.py:146`（scene_3d_previs = freeform） |
| Q4 | timeline 目前还不能用？ | **一半对**。ADR 0007 全局时间线 Phase 1–3 已基本完工（拖拽/裁剪/转场/音量曲线/字幕/闪避/节拍检测）。真正不能用的有三处：**① 前端在调的 `/api/v2/workflows/{id}/final-composition/*` 路由根本不存在（404）**；**② 资产库素材不能直接拖入轨道**（目前只能靠节点产出自动建 clip）；**③ camera 轨道不能从 scene-3d 导入运镜、不能拖入"参考运镜"**（ADR 0007 §4.3 未做）；**④ 语音→口型关键帧未自动生成**（§4.2 只做了角色绑定） | `v2Client.ts:1776-1828` vs `app/api/v2/endpoints/` 无 final-composition 路由；`timeline-implementation-plan.md` 状态行 |

> **2026-09-25 更新（P0 部分落地）**：① 已修复——新增 `app/api/v2/endpoints/final_composition.py` 并挂载，8 条路由（GET/PATCH timeline、POST/DELETE clips、POST sources、POST render、GET render state、POST cancel）全部就绪，15 项测试通过（含真实服务生命周期）；裁决采用 §5.1 方案 A 的服务直介（前端 normalizer 期望的响应形状与既有 schemas 完全一致）。②③④ 仍开放，见 §6 P4。

> **2026-09-26 更新（②③ 落地）**
> **2026-09-26 二次更新（运镜可控性）**
> **2026-09-26 三次更新（角色调度）**：`characterMotionPresets.ts`——走到/转身面向/靠近至/标记说话。朝向随行（行走面朝行进方向、转身走最短弧），action 语义对齐后端合并（走停落 stand、转身不覆盖 talk）。角色从手算向量变成走位词汇表：相机从手算向量变成可编排——`cameraMotionPresets.ts` 8 种运镜预设（推近/拉远/左右环绕/左右摇/升臂/降臂），沿真实路径 15 帧采样（渲染器线性插值，两点式会切和弦横穿圆弧），预设只替换自身窗口内关键帧（重应用=扩展不堆叠），相机检查器一键应用到播放头所在帧：**拖入式装载已实现**——`timeline/timelineDropPayload.ts`（单一拖拽契约：自定义 MIME `application/x-adcraft-timeline-drop`、外/损坏载荷拒收、媒体类型→轨道兼容矩阵、落点→吸附量化、hovered 兼容优先否则首个兼容轨）+ `AgentAssetBrowser` 卡片可拖（仅 ready 资产）+ scene-3d 节点卡可拖（**camera 载荷**，即"参考运镜拖入"）+ `GlobalTimelinePanel` 轨道落点（dragover 合法/非法高亮 `data-drop-hover`、drop→`createClip`→resync、无兼容轨/创建失败有错误横幅）。23 项新测试（17 契约 + 6 面板）。
| Q5 | 最终目标：台词驱动视频 | 架构上已经铺好：voice-cast → speech_audio → 时间线 voice 轨（`bound_character_id` 已实现）→ speech_orchestration 唇形关键帧 → 3D 预演 → 视频模型参考。**缺的三块**：真·音素级唇形（当前是启发式）、语音拖入时间线的拖拽交互、台词驱动的**镜头/分镜自动编排**（说多久 → 分镜多长） | `speech_orchestration.py`（LipSyncGenerator 启发式，注释自述"生产级应换音素分析器"）、`timeline_clips.bound_character_id` |

---

## 1. 背景：Dramagic 的设计思想与 AdCraft 的对应关系

### 1.1 Dramagic 是什么（2026-09 公开信息）

BytePlus 面向企业团队的 AI 短剧生产工作台，四步流程：**剧本分析 → 素材设定（角色/场景/道具资产表）→ 分镜 → 视频预览**。公开报道中反复强调的三个支柱：

1. **角色/场景一致性锁**：剧本拆出人物后，每个角色建立一套多角度设定；几十个镜头生成前**先核验一致性，形象跑偏的画面被拦在成片之外**（不允许崩坏流出）。
2. **资产表驱动分镜**：分镜不是自由文本，而是"镜头表 × 角色表 × 场景表"的绑定关系；改剧本后下游分镜可联动更新。
3. **工作台而非生成按钮**：把"生成一个镜头"的问题升级为"组织几十个镜头之间关系"的问题；外加多人协作与重制（换语言翻拍）。

同期可参考的还有 Pixmax 3D 导演台：**场景/人物/机位放进可视化 3D 空间，空间搭建、站位姿势调度、多机位构图、参考图一键输出，再接 AI 视频生成**——这正是本设计 §4 "3D 导演工作台"的产品原型。

### 1.2 映射到 AdCraft：已有的 vs 缺的

| Dramagic 支柱 | AdCraft 现状（已核对） | 差距 |
|---|---|---|
| 剧本分析 | `script` 节点 + `front_desk.py` 意图分类 + v2 脚本写作专家 | 基本对齐 |
| 角色资产表 + 多角度设定 | 角色资产库（三视图/面部/服装/配饰，README §6）+ `LibraryEntity` | 资产本身齐；**缺"资产生成时的一致性锁"** |
| 场景资产表 | 场景资产库 + `WorldSettingCoreV2.owned_scene_ids`（2026-09-15 协作公告已加） | 缺场景资产 → 3D 场景的绑定校验 |
| 分镜 = 镜头表×角色表×场景表绑定 | `StoryboardPanelV2` 已带 `scene_id / character_ids / prop_ids / shot_type / camera_move / duration_seconds`（P0 完成）+ `PanelAssetBindingService` | 绑定校验有了；**缺可视化 3D 排练层** |
| 一致性检查（生成前拦截） | QA registry（ADR 0003 §5）+ 资产绑定校验 `validate_binding_consistency` | 缺**渲染前 SceneScript↔资产一致性闸门**（本设计 §5.3） |
| 3D 可视化导演台 | scene-3d 节点 + Three.js **只读**预览 + Blender 渲染 + 控制通道 | **缺交互编辑**（本设计 §4，核心补全） |
| 时间线编排 | ADR 0007 全局时间线（Phase 1–3 完工） | 拖入式素材装载、camera 轨导入、唇形、单时间线收敛（§5.1） |

**一句话**：AdCraft 的"素材生成"和"时间线编排"两层都已存在，Dramagic 式的"**把角色/场景/道具用资产表锁死、在 3D 空间里排练镜头、用时间线精确对白**"的中间层——3D 导演工作台——正是最大的缺口。

---

## 2. Q1 深答：全景图能不能直接喂视频模型？

### 2.1 为什么不能

1. **形态不匹配**：全景图是等距柱状投影（equirectangular，2:1），边缘被极度拉伸；视频模型（Seedance/Agnes/Hailuo）在训练中见到的是普通透视影像，会把全景图当"一张奇怪的照片"去续写，产出不可预测。
2. **无空间理解**：模型没有从全景图重建 3D 场景的能力，"镜头往左移 2 米应该看到什么"无法回答——而这恰恰是导演要的控制。
3. **无相机参数**：视频模型的相机控制通道（如 Agnes 的 `videos` 运动参考、Seedance 的 `camera_fixed`）都需要一个**已知相机的参考视频/图序列**，一张静态全景图不构成运动参考。

### 2.2 三档可行路径（按可控性排序）

```
可控性/工作量
  高 │ ② SceneScript 3D 预演（Blender 渲染运镜参考）
     │    NL/图片/视频 → SceneScript → 运镜关键帧 → 渲染低清预演
     │    → depth/normal/flow 控制通道 + 运动参考视频 → 照片级视频模型
     │ ① MiDaS 深度白模（2.5D 重投影）
     │    全景图/视频 → 逐帧深度图 → 把像素投影到深度网格 → 有限视差内自由运镜
  低 │ ③ NeRF / 3D Gaussian Splatting（真自由视角，P6+ 研究线）
```

| 路径 | 适用场景 | 仓库现状 | 局限 |
|---|---|---|---|
| ② 3D 预演 | 有角色表演、多机位、精确运镜的分镜 | **全链路已验证**（ADR 0005 + `docs/3d-previs-to-photoreal-video-workflow.md`：长廊→赌场案例，照片级成片） | 场景要"重建"成低模，资产偏白模；需 LLM 参与 |
| ① 深度白模 | 空场景漫游、缓慢推拉升 orbit；已有现成视频想改运镜 | **半成品**：`depth_estimator.py` 只做了"视频→深度图视频"（可视化输出），**没做深度重投影/视差运镜**；MiDaS 依赖（torch/timm/opencv）未装时 `check_dependencies()` 可查询降级 | 单视深度有洞、大视差处撕裂；只能小幅运动 |
| ③ 真重建 | 高保真环绕、复杂几何 | ADR 0005 明确 **Deferred**（"requires a separate research track"） | GPU 训练重、时延长 |

### 2.3 针对"地下研究所全景图"的推荐流水线（本设计拍板）

```
全景图（等距柱状）
  │ ① 等距柱状 → 6 面立方体裁剪（4 水平面 + 顶/底），LLM 看到不失真内容
  ▼
② 多模态 LLM 分析（= image_analyzer，Q2 的实现）
  ▼
SceneScript blockout（墙/门/桌/柜 + 角色 + 相机关键帧）← 全景图同时作为场景风格/材质参考
  ▼
③ Blender 预演渲染（可选叠加全景图 MiDaS 深度图作为"白模贴图"保持结构忠实）
  ▼
④ 视频模型：Agnes 运动参考视频通道（SEEDANCE_SEGMENT_MOTION_ROLE=motion_reference）
   或 Seedance 直喂参考视频；不支持时降级 5 关键帧（ADR 0005 §4a，previs_control_level 可查询）
  ▼
照片级成片 + 台词语音轨（Q5）
```

**全景图的正确定位是"场景资产与构图/风格参考"，而不是"视频模型的直接输入"。** 这一点与已验证案例的经验一致：参考图只保留构图/空间关系，材质光照靠强风格提示词压过参考图风格（`docs/3d-previs-to-photoreal-video-workflow.md` 第一节）。

---

## 3. Q2 深答：拖入图片直接做建模 — 实现方案

### 3.1 架构：复用参考视频分析器的三阶段模式

```
[拖入图片]                       （新增）image_analyzer.py
   │ 单图 / 多图 / 全景图
   ▼
阶段 A：预处理
   ├─ 全景图判定（2:1 等距柱状特征）→ equirect→cubemap 6 面裁剪（ffmpeg v360/transpose 或纯 numpy）
   └─ 普通多图：保持原样（如一体化生成软件的"前/后/侧"设定图）
   ▼
阶段 B：多模态 LLM 逐图分析（复用 _call_multimodal_llm）
   ├─ 画面类型/环境/光照/机位建议/景别/运镜暗示
   ├─ 可见物体枚举（墙、门、桌、机器、通道…）
   └─ 人物（外观、站位、朝向）
   ▼
阶段 C：SceneScript 合成（复用 _SCENE_SCRIPT_SYSTEM_PROMPT + SceneScriptRoot 校验）
   ▼
SceneScript JSON → 落入 scene-3d 节点 structured_content → 3D 工作台打开即可编辑
```

### 3.2 关键设计决策

1. **不是"图片 → 网格"而是"图片 → LLM → SceneScript"**。直接 CV 重建（单图深度→网格）质量不可控且不可编辑；LLM 语义重建产出的是**带业务语义的领域对象**（墙就是 `wall` 类型、门就是 `door`），可在 3D 工作台里继续拖拽、绑资产、K 帧。深度估计退居为**辅助控制信号**（白模贴图/构图保真），不是主路径。
2. **全景图必须切面**：LLM 对拉伸边缘的解析很差；切成 4 张 90° 水平透视面后，结构与墙面关系恢复可读。
3. **校验前置**：LLM 输出必须过 `SceneScriptRoot` Pydantic 校验（`extra="forbid"`），失败走 `AnalysisError`，绝不静默通过（工程标准 §4）。
4. **依赖可查询**：LLM 未配置（`LLM_API_KEY/LLM_BASE_URL`）返回 `configuration` 错误类型，前端提示去配置中心；图片处理失败有明确 error_type。
5. **不引入新依赖**：图片分析只用 httpx（已在依赖里）；全景切面用 ffmpeg（已在媒体工具链里）。

### 3.3 前端交互（归属 §4 工作台）

资产库/上传的图片 → 拖到 scene-3d 节点或工作台资产托盘 → `POST /scene-3d/analyze-image` → 返回 `{scene_script, frame_analyses, warnings}` → 工作台加载 SceneScript → 用户微调 → `PATCH` 节点落库。**"拖入即建模"的体验闭环 = 本文件 §4.2 + §4.4 + §5.2。**

---

## 4. Q3 + 3D 工作台设计：用建模放置镜头、操作人物运动

### 4.1 形态：scene-3d 节点的"导演工作台"（全屏覆盖层）

沿用现有 workbench 模式（`features/agent-canvas/workbench/NodeWorkbenchShell.tsx` 已存在），scene-3d 节点从"节点内小预览"升级为**可全屏展开的导演工作台**。这是整个设计里最"惊艳"的一张牌。

> **✅ 已落地（2026-09-26）**：全屏模式以「⤢ 全屏导演台」开关实现——portal 到 document.body 的 fixed inset-0 覆盖层，托盘/视口/检查器三列加宽（200px/1fr/280px），视口高度 360→620，Esc 收起。设计文档全部阶段（P0–P5）至此落地。

```
┌───────────────────────────────────────────────────────────────────────┐
│ 3D 导演工作台 — 场景「地下研究所 B2 走廊」        [渲染预演] [生成视频提示词] [保存] │
├───────────┬───────────────────────────────────────────┬───────────────┤
│ 场景大纲    │                                           │ 检查器          │
│ ▼ scene   │           视口（Three.js r3f）              │ 位置 [x y z]    │
│  ▼ 角色(2) │      选择 / 平移 / 旋转 / 放置相机          │ 旋转_y [ ]     │
│  ▼ 道具(5) │      · 地栅格 + 坐标轴 + 安全框            │ 缩放 [ ]       │
│  ▼ 环境(8) │      · 角色位移轨迹线 / 相机轨迹线          │ ── 关键帧 ──    │
│  ▼ 相机(2) │      · 当前 shot 取景框（frustum 线框）     │ f0  pos… rot…  │
│  ▼ 镜头(3) │      · 说话角色高亮（voice clip 绑定）      │ f120 pos… rot… │
│           │                                           │ [+ 在当前帧记录] │
│ 资产托盘    │      ▶ 播放条：frame 0 ──●──── 480        │ ── 镜头 ──      │
│ ┌───┐┌───┐│                                           │ shot_type 景别  │
│ │墙 ││门 │ │                                           │ 起止帧 [ ][ ]   │
│ └───┘└───┘│                                           │ 运镜模板 ▾       │
│ [拖入添加] │                                           │ 台词绑定 ▾       │
├───────────┴───────────────────────────────────────────┴───────────────┤
│ 迷你时间线：镜头条 ▮▮▮ | 关键帧菱形 ◆     | 帧标尺，与全局时间线播放头联动    │
└───────────────────────────────────────────────────────────────────────┘
```

### 4.2 视口交互（核心增量，P1/P2 落地）

| 能力 | 交互 | 落地的数据变更 |
|---|---|---|
| 选择 | 点击物体 → 高亮描边 + 大纲联动 | 本地 state `selectedId` |
| 平移 | 选中后拖拽 → 限制在地面平面（射线求交） | 写 `position`（对角色：写当前帧的 keyframe 或新建） |
| 旋转 | 选中后拖拽旋转环 | 写 `rotation_y`（度） |
| 缩放 | inspector 数值输入（props/environment 有 `scale`） | 写 `scale` |
| 放置相机 | 相机模式：第一次点击设 `position`，第二次点击设 `look_at` | 新建/更新 `SceneCamera.keyframes` |
| 关键帧捕获 | "在当前帧记录"按钮：把角色当前 transform 写入该帧 keyframe | `CharacterKeyframe` |
| 轨迹可视化 | 相机/角色 ≥2 关键帧时画折线（catmangrom 平滑） | 纯渲染层，`Line` + `BufferGeometry` |
| 帧步进 | 播放条逐帧/区间循环；帧切换时角色按插值移动（已有） | 复用 `SceneScriptPlaybackContext` |
| 镜头取景框 | 当前 shot 的相机画 frustum 线框 + shot 切换跟随 | 扩展 `CameraGizmo` |

**持久化路径（已验证存在）**：工作台"保存"→ `PATCH /api/v2/workflows/{workflow_id}/nodes/{node_id}`，body `structured_content.scene_script = <sceneScript>`。scene-3d 的 semantic role 是 `scene_3d_previs`（`agent_canvas_ad_media.py:146`，content_model=None → freeform），不受 DesignAsset 之类的 schema 约束，场景脚本原样落库；执行渲染时 `_scene_script_from_node()` 读回（`agent_canvas_node_execution.py:1168`）。

### 4.3 放置镜头与人物运动的"可控性"阶梯

| 层级 | 手段 | 状态 |
|---|---|---|
| L1 模板化 | 7 套 shot 模板（`shot_templates.py`）+ camera_move 7 型映射（`scenescript_derivation.py`） | ✅ 已有 |
| L2 关键帧 | 相机 position/look_at K 帧；角色 position/rotation_y/action K 帧 | ✅ 数据层已有；⬜ 前端交互（P2） |
| L3 运镜对齐台词 | 语音停顿检测 → 建议切换点（beat analysis 已有 BGM 版，`timeline_beat_analysis.py`）→ 分镜边界吸附 | ⬜ P4 |
| L4 控制通道 | Blender depth/normal/flow pass（`control_passes.py`）+ Agnes 运动参考视频 + 5 关键帧降级 + `previs_control_level` 标记 | ✅ 已有（ADR 0005 §4/§4a） |
| L5 资产一致性 | 角色绑 `character_asset_id` → 工作台显示三视图参考 + 渲染前一致性闸门（§5.3） | ⬜ P3 |

### 4.4 场景的四个来源通道（工作台"新建场景"入口）

1. **自然语言**（已有）：`scene_script_generator.py` NL → SceneScript。
2. **拖入图片**（P0 已实现后端，`scene3d/image_analyzer.py` + `POST /scene-3d/analyze-image`）：§3。
3. **上传参考视频**（已有）：`reference_video_analyzer.py` + `POST /scene-3d/analyze-reference`。
4. **shot 模板**（已有）：`POST /scene-3d/template`。

### 4.5 全景图专用通道（P5）

- 上传全景图 → 前端标记 `projection: equirectangular` → 后端 `equirect→cubemap` 6 面裁剪 → 走 image_analyzer。
- 同时跑一次 MiDaS 单图深度 → 灰度深度图作为**构图保真参考**（白模贴图或视频模型 control 输入），并在工作台提供"深度白模快速环绕"预览（2.5D 重投影，extend `depth_estimator.py` 加单图入口 + 简化重投影渲染）。
- 降级链可查询：全景识别失败 → 按普通图片分析；MiDaS 依赖缺失 → `depth_unavailable` 标记（`check_dependencies()` 已有）。

---

## 5. Q4 + Q5 深答：Timeline 补全与台词驱动视频

### 5.1 Timeline 现状裁决（先收敛，再扩展）

**事实**（2026-09-25 核对）：
- ADR 0007 全局时间线（`/api/v2/workflows/{id}/timeline`）：Phase 1–3 完工 + Phase 4 部分（播放头同步、voice→角色绑定、节拍检测已交付）。
- v2 final-composition 时间线：**service/schemas 齐全但 HTTP 路由不存在**；前端 `v2Client.ts:1776-1828` 调的 6 组路由全部 404。
- 两套 editing 栈并存（ADR 0007 时间线 → `timeline_editing_integration` → EditingManifestV2 ↔ editing 节点渲染）。

**裁决：保留 ADR 0007 时间线为唯一编排层**，对 v2 final-composition 路由二选一：
- **方案 A（推荐）**：把 v2 final-composition 路由补成 ADR-0007 时间线的**兼容投影**（读时间线 → 转 `WorkflowV2Timeline`；写操作转回 timeline API），让老前端调用不 404 且语义统一；
- 方案 B：删掉前端对 final-composition 路由的调用，统一走 timeline API。
（决策矩阵：A 保留兼容面但多一层转换；B 干净但有一处前端改动。倾向 A，因为 `WorkflowV2Timeline` schema 已经在别的测试里被引用。）

**在此之上补三块"拖入式"能力**（对应用户原话"视频音频和参考运镜能直接拖入"）：
1. **资产拖入轨道**：资产库/节点媒体预览 → HTML5 drag → timeline track drop zone → `POST /timeline/clips`（已存在，补前端拖拽源 + 落地反馈：吸附最近轨道、自动避让重叠提示）。
2. **参考运镜拖入**：外部参考视频/3D 预演 → camera 轨：`TimelineClipAutoCreator` 已把 scene-3d → camera 轨（映射在），补"从 scene-3d 节点导入运镜关键帧到 camera clip"（ADR 0007 §4.3）+ 拖拽落 camera 轨。
3. **音频拖入**：voice-cast 产物/上传音频 → voice/bgm/sfx 轨（auto-creator 已映射 voice-cast→voice，补任意资产拖拽源）。

### 5.2 台词驱动视频：目标架构（Q5）

```
剧本台词（script 节点 dialogue）
   ▼ voice-cast 节点（TTS：stepfun/fish_audio 已完成引擎）
   ▼ speech_audio 资产（duration_seconds 已记录）
   ▼ 时间线 voice 轨（bound_character_id 绑定角色 — 已实现）
   ▼ speech_orchestration：SpeechTimeline 排版 + 唇形关键帧（当前启发式 → P6 升级音素级）
   ▼ SceneScript 角色嘴部/微动作 K 帧 → 3D 预演（口型随台词动）
   ▼ 视频模型参考（运动参考视频带上口型 + audio_inputs 通道 / Seedance generate_audio）
   ▼ editing 节点：视频拼接 + voice/bgm 混音闪避（已实现）+ 字幕烧录（已实现）
   ▼ 成片
```

**三条唇形控制路线（按优先级）**：
1. **视频模型原生音频驱动**（最省事）：Agnes 的 `audios` 输入通道 + `<Audio N>` 占位（`seedance_adapter.py` 已注册该能力）、Seedance `generate_audio`。台词音频直接进生成，模型自带动口型。
2. **3D 预演唇形驱动**（最可控）：`speech_orchestration.LipSyncGenerator` 已有启发式实现；升级为音素级（WhisperX 强制对齐或 Rhubarb）→ 写 SceneScript 嘴部 action K 帧 → 预演渲染 → 运动参考通道进视频模型。适合特写对话镜头。
3. **后处理唇形替换**（留给专业管线）：最终成片级的口型替换工具链（本版本不做，记录为 P6+）。

**台词 → 分镜时长的闭环**（"bound" 模式，ADR 0003）：TTS 实测时长反推分镜长度与时间线 clip 位置——ADR 0007 §2.5 冲突解决表已设计，落地点是 `TimelineShot` 概念 + video 节点按时间段从预演提取参考帧（Phase 2 已部分接线）。

### 5.3 Dramagic 式"一致性闸门"（P3，把角色崩坏拦在成片外）

在 scene-3d 节点渲染前增加 QA 检查（复用 ADR 0003 QA registry 模式）：
- 场景中每个 `SceneCharacter` 若绑定了 `character_asset_id` → 校验资产存在且在库；未绑定角色在多镜头场景 → warning（提示去绑）。
- 同一 workflow 内多 scene-3d 节点的角色色板冲突 → warning（跨场景角色漂移预警）。
- 资产绑定变更 → 标记下游 shot stale（复用现有 `stale/stale_reason` 机制，`final_composition.py` 已有先例）。

---

## 6. 分阶段实施计划

> 原则：每阶段独立可验收；不动的文件不动（复用优先）；每阶段跑工程标准 §1 自检阶梯。

### P0 — 设计定稿 + 图片建模后端 ✅（本轮完成）
- [x] 本设计文档
- [x] `apps/api/app/services/scene3d/image_analyzer.py`（图片 → SceneScript）
- [x] `POST /scene-3d/analyze-image` 端点 + pytest（含 mutation 检查）

### P1 — 3D 工作台骨架 + 视口编辑（前端） ✅ 主体完成（2026-09-26）
- [x] 轴系转换单一来源：`web/src/features/agent-canvas/canvas/sceneScriptAxes.ts`（SceneScript Blender Z-up ↔ three.js Y-up，双边断言+不变量测试）。**顺带修复既有 bug**：预览此前不转换轴系，相机 z=7 会渲染到地下 12 米
- [x] 纯编辑模型：`sceneScriptEditModel.ts`（角色/相机按当前帧写关键帧：同帧更新、异帧有序插入、朝向/动作继承最近帧；道具/环境静态 position/rotation/scale；全不可变；not-found 抛码）
- [x] 交互视口：`SceneScript3DPreview.tsx` 增加 editMode（点击选中、地面平面拖拽且保持高度、选中环、相机/角色轨迹线、拖拽时 OrbitControls 让位、拖拽幽灵位）
- [x] 检查器 + 保存条：`SceneScript3DEditor.tsx`（位置/朝向/缩放/注视点/景别数值编辑、关键帧条、保存/撤销）
- [x] 工作台接线：`LocalEngineWorkbench.tsx`（scene-3d 节点）；保存走 `patchNode`，structured_content **合并**保留 narration；three.js 保持 lazy（编辑器 chunk 6.3 KiB）
- 测试：34 项新测试（axes 3 / editModel 16 / editor 9 / workbench 6）；全量 1983 项零新增失败；tsc + eslint 干净；bundle 预算基线不变（既有超支非本改动引入）
- 遗留：节点卡内嵌面板未同步编辑入口（符合设计）；ETag 409 冲突仅错误文案
- **验收**：拖角色 → 保存 → PATCH 合并落库链路已由单测锁定；浏览器端到端人眼验收留待手工

### P2 — 相机放置 + 关键帧 + 轨迹 ✅ 主体完成（2026-09-26）
- [x] **相机放置模式**：视口第一次点击设机位、第二次点击设注视点（window 级指针捕获的模态手势——放置时不会被物体选中/拖拽抢事件）；金色锚点 gizmo 落在 1.6m 视平线 + 实时预览连线；Esc 取消
- [x] 放置的两种语义：**选中相机时 = 重设该相机机位/注视点（保留各自高度）**；未选中 = **`addCameraAtFrame` 新建相机 + 不重叠 shot**（接在最后一个 shot 之后，最短 1 秒，不够则自动延长场景时长——schema 禁止 shot 重叠与时越界），并自动选中新相机
- [x] 关键帧捕获按钮：把选中角色/相机在当前播放头的插值状态固化为关键帧（该帧已是关键帧时为恒等 no-op，不搅动 React 状态）
- [x] 轨迹折线可视化 + 相机 gizmo 跟帧插值（P1 已交付）
- 模型新增 11 项测试（`addCameraAtFrame` 4 + capture 4 + interpolate 3），编辑器新增 5 项（编辑器 14 项、模型 27 项全绿）；全量 1999 项零新增失败；编辑器 chunk 7.68 KiB
- 遗留：shot 起止帧无专用编辑器；frustum 取景框留 P3
- **验收**：空白处点击两次 → 新相机+新镜头生成并自动选中；选中相机再点两次 → 机位/注视点更新且高度保留（均有单测锁定）

> **2026-09-26 补**：§5.3 列出的「同一 workflow 内多 scene-3d 节点的角色色板冲突 → warning（跨场景角色漂移预警）」已由 `scene3d/wardrobe_drift.py` 落地（执行器发布 `scene3d_wardrobe_drift`，前端编辑器渲染发现与补救）。

### P3 — 资产托盘 + 一致性闸门 ✅ 一致性闸门已落地（2026-09-26）
- [x] **一致性闸门**：`app/services/scene3d/scene_consistency.py`（Dramagic 式"把崩坏拦在成片外"）+ `POST /scene-3d/consistency-check` + Scene3DNodeExecutor 每次渲染后把报告发布到节点 `structured_content["scene3d_consistency"]`（可查询，工程标准 §4）。检查项：`character_unbound`（多镜头场景里未绑 `character_asset_id` 的角色——预演里角色只是颜色，没有身份契约）、`character_color_collision`（两个角色同色——低保真场景里颜色就是身份通道，审查者与视频模型的参考映射都无法区分）、`camera_unused`（没有 shot 引用的相机）、`shot_coverage_gap`（shot 没覆盖全时间线）、`scene_empty`。**全部 warning 级**：报告可查询、工作台可作为渲染前门，但任何以前能渲染的场景照样渲染（门不是新的阻断器）
- [x] **一致性闸门前端**（2026-09-26）：`canvas/sceneScriptConsistency.ts` 是后端五检查的实时镜像（codes 与后端锁步，8 项测试锁定触发/静默与码表对齐）；编辑器在工具条上方渲染警告横幅，**点击警告选中对应对象**（character → 角色，camera_unused → 相机），remedy 一步可达；角色检查器新增**「角色资产绑定」下拉**（候选来自 workflow.assets 中 `character_*` semantic_type 的图片资产，经 AgentCanvasInlineWorkbench → LocalEngineWorkbench → SceneScript3DEditor 三级线程）——`character_unbound` 的 remedy 从“知道有问题”变成“两下点击就修好”
- [x] **资产托盘**（2026-09-26）：`canvas/SceneAssetTray.tsx`——低模词汇调色板（环境 13 种 + 道具 12 种，直接取生成枚举，后端加类型前端立刻可加），色块用 `SCENE_SCRIPT_ASSET_COLORS`（托盘承诺的与预览/Blender 显示的一致）；**点击添加**到确定性螺旋位（重复点击不堆叠），再由视口拖拽定位（拖拽是精度工具）。编辑模型新增 `addEnvironmentObject`/`addPropObject`（id 防碰撞、显式 id/scale、原地不变性）。编辑器布局改三列：托盘 | 视口 | 检查器
- [x] **绑定后显示参考图**（2026-09-26）：`CharacterAssetOption` 携带 `preview_url`（经 `AgentCanvasInlineWorkbench` 从 `workflow.assets` 用共享的 `mediaAssetPreviewPath` 解析——优先后端派生预览）；检查器在绑定下拉下方渲染 `<figure data-testid="character-reference">`（缩略图 + 资产名），无预览 URL 时显示"无参考图"占位。Dramagic 的锁只有**看得见**才是真的：作者绑完必须能看到自己绑的是谁
- **验收**：未绑定角色触发 warning ✅（15 项测试锁定：触发/静默条件、报告形状、remedy 必有、warning 不阻断）；绑定后工作台显示参考图（随资产托盘落地）

### P4 — 时间线收敛与"拖入式"装载
- [ ] 时间线路线裁决（§5.1 方案 A）
- [ ] 资产库 → 轨道拖拽（视频/音频/图片）
- [ ] camera 轨导入 scene-3d 运镜（§5.2）
- [ ] 语音 → 唇形关键帧接线（speech_orchestration → SceneScript）
- **验收**：从资产库拖 3 段素材到时间线 → editing 渲染成片；scene-3d 运镜出现在 camera 轨；voice clip 重跑后角色口型 K 帧更新

### P5 — 全景图通道 + 深度白模 ✅ 主体完成（2026-09-26）
- [x] equirect→cubemap 裁剪 + 全景标志透传（image_analyzer.py，测试锁定方向）
- [x] **MiDaS 单图深度**（2026-09-26）：`depth_estimator.estimate_depth_from_image`（全景超长边自动降采样到 1280 推理，结果复用 DepthEstimationResult 语义）+ `POST /scene-3d/extract-depth-image`（multipart 上传、依赖缺失 400 带报告、深度图存 media 目录经 /media 服务）；前端 intake 的可选「同时提取深度白模」开关 → 结果横幅内联灰度深度图；深度失败是 warning 不是失败（blockout 已可用）
- [x] **2.5D 重投影环绕预览**（2026-09-26）：`depth_reprojection.py`——图片+深度图反向投影成点云，虚拟相机绕焦点视差环绕；**零扫幅 = 精确恒等**（投影管线正确性锁定）、near 特征比 far 特征位移大（深度视差锁定）、空洞经 inpaint 填充且逐帧比例**上报**（不静默）；`POST /scene-3d/render-depth-orbit`（multipart，可带深度图，产物经 /media 服务）；前端 intake 的「🎥 生成深度环绕预览」→ 结果横幅内联播放
- [ ] MiDaS 单图入口 + 2.5D 重投影环绕预览
- [ ] 深度图作为 control 输入接入视频模型（`control_signals` 已在 schema 预留）
- **验收**：上传地下研究所全景 → 工作台出现 blockout 场景 → 相机推拉正常 → 预演渲染

### P6 — 音素级唇形 + 台词驱动分镜（研究线）
- [ ] WhisperX/Rhubarb 音素对齐替换启发式 LipSyncGenerator
- [ ] 语音停顿 → 分镜边界自动吸附（ADR 0007 §5.3 的"运镜跟随语音节奏"开关）
- [ ] "换语言重制"（Dramagic 的翻拍链路）评估：台词替换 → 唇形/时长重排 → 重渲染

---

## 7. 与现有 ADR / 计划的兼容性声明

- 本设计**不新增节点类型**：全部能力挂在既有 `scene-3d` 节点与 ADR 0007 时间线上，遵守 ADR 0005 §3"3D 预演是新节点不是 storyboard 替代"的边界。
- 对 ADR 0005  withdrawn 的"NeRF/3DGS"仍维持 Deferred，本设计 P6 只是评估不改状态。
- 对 ADR 0007：Phase 4.3（camera 轨）与 4.2 的唇形部分被本设计 P4 提前具体化，不冲突；§5.1 的"单时间线收敛"是对 ADR 0007 执行中出现的双栈事实的补丁，须同步更新 ADR 0007 状态行。
- 术语遵循 `CONTEXT.md` 词汇表：Workflow/Node/Asset/Asset Version/Timeline（ADR 0007）/SceneScript（ADR 0005）/Speech Audio（ADR 0003）/Shot Group 等，不造同义词。

## 8. 风险

| 风险 | 缓解 |
|---|---|
| LLM 生成的 SceneScript 结构臆测（墙的位置/尺寸） | 校验失败即拒；工作台人工微调是正式路径而非兜底；全景切面提高解析质量 |
| 前端 r3f 交互改造成本 | 只扩 `SceneScript3DPreview.tsx` 的交互层，渲染层/播放 context 不动；工作台按 P1/P2 拆两步 |
| 双时间线并存继续漂移 | P4 先裁决再扩展；`timeline_editing_integration.py` 保持唯一转换点 |
| MiDaS 依赖未安装导致全景深度不可用 | `check_dependencies()` 查询式降级 + 前端 capability 提示，静默失败禁止 |
| 工作台保存与节点执行的竞态 | 保存走 ETag `If-Match` 乐观锁（端点已实现）；渲染读最新落库脚本 |
