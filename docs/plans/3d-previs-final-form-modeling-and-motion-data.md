# 3D 预演的最终形态：建模文件 × 运行数据 × 中性参考视频

> **Status**: Proposed（2026-09-26 研究轮）
> **触发**: 用户原则原话——"提示词和图片都是手段，但最终要落到**建模文件**和**运行数据**上；本着最终能建模、能根据运动数据生成参考视频的原则，查一些好的设计，探索一条适合本项目的方案"。
> **关联**: [ADR 0005 3D 低保真预演](../adr/0005-3d-low-fidelity-previs.md) · [ADR 0007 时间线](../adr/0007-timeline-driven-production.md) · [ADR 0008 双相导演](../adr/0008-timeline-two-phase-directing-and-assembly.md) · [3D 工作台补全](./3d-workbench-and-pipeline-completion.md) · [Blender MCP 白模方案](./blender-mcp-white-model-mode-and-audio-collaboration.md) · [已验证案例](../3d-previs-to-photoreal-video-workflow.md)
> **纪律**: 所有"现状"结论均在 2026-09-26 工作树核对过代码/文档；引用具体文件与行号；外部调研附来源链接；建议与事实分开陈述。

---

## 0. TL;DR

| # | 问题 | 结论 |
|---|---|---|
| 1 | 最终形态是什么？ | **一份可带走的建模文件（`.blend`/GLB）+ 一份可编辑的运行数据（motion JSON）+ 三种渲染人格之一的中性参考视频**。SceneScript 保持唯一规范状态不变（ADR 0005 §1），建模文件是它的**几何实现缓存**，运行数据是它的**时序投影**——两者都可由 SceneScript 重建，因此不破坏"单一事实来源" |
| 2 | 现在缺什么？ | **建模文件根本不存在**（Blender 场景每次从基本体重推、MCP 高级几何即弃、无真模型导入）；**运行数据只有相机一半**（`previs_trajectory`）且不可回流；**参考视频的生成原则是"提示词+单图"，不是"运动数据"**——已验证案例为躲避低模风格泄漏只能弃用关键帧模式 |
| 3 | 运动数据怎么进视频模型？ | 各家视频模型（Seedance/Kling/Agnes）的运动通道都吃**参考视频**而不是相机 JSON，而参考视频会**把低模风格带进成片**（案例实证）。解法：新增**中性渲染人格**（黏土/无材质白模），让"运动保真、风格绝缘" |
| 4 | "上传图片出建模"怎么落地？ | **本地 Blender 三档路线**（用户 2026-09-26 拍板：不用外部 SaaS、初期"能用就行"）：T1 深度浮雕网格（场景/空间，零新依赖秒级）+ T2 TripoSR 单图重建（用户指定物体，MIT，CPU 分钟级）+ T3 检索胜过重建（可替换道具走词表/资产库）。GLB/网格进 SceneScript 已有的 `scene_asset_id`/`prop_asset_id` 字段，再进建模文件 |
| 5 | 与已确认范围怎么拼？ | 单屏 → 不开新窗口（全屏 portal 已覆盖）；最终范围 = 上一轮 W0–W3（图片语义闸、导演台信任件、指令可见层、并排评审、一键交接）**并入**本文的 W0–W4 重新排序，编号以本文为准 |
| 6 | "聊天逐轮出场景"+“改角度”+“动起来”现成吗？ | **动起来的地基已在**（add_keyframe op、相机/角色 K 帧、rAF 播放循环、按帧插值），断的是环：`execute_canvas_white_model` 契约已注册但无任何 UI 调用；聊天面板与 scene-3d 零耦合。补环 + 三个结构缺口（add_camera 不建 shot、ops 只写 frame-0、环境道具无 K 帧）即可，见 §4.6/§6a |

---

## 1. 把用户原则拆成可施工的命题

用户原话包含三个可独立验证的命题，本设计逐一对应：

| 命题 | 工程含义 | 验收表现 |
|---|---|---|
| 提示词和图片都是**手段** | 自然语言 / 图片都只是**建模文件与运行数据的生产者**，不是交付物本身 | scene-3d 节点的首个产物应含"建模文件引用 + 运动数据"，而不是只有一个 MP4 |
| 最终要落到**建模文件** | 场景必须有持久化的几何文件（`.blend` 权威工作文件 + GLB 交换文件），可被重渲染、被外部工具打开、被用户带走 | 上传图片生成的 blockout，导出的 `.blend` 在 Blender 里打开就是视口里那面墙 |
| 能根据**运行数据**生成参考视频 | 相机轨迹 + 角色 blocking 是一等数据（可编辑、可回流、可导出），参考视频是 `f(建模文件, 运行数据, 渲染人格)` 的**纯函数** | 只改运动数据不动 SceneScript，重渲染出的参考视频运动随之改变；反过来从时间线拖入的运镜能写回运动数据 |

---

## 2. 现状事实（代码级）

### 2.1 建模文件：不存在

| 事实 | 证据 |
|---|---|
| Blender 每次以 `--background --python <临时脚本>` 运行，**脚本末尾从不 `save_as_mainfile`**，会话即弃 | `app/services/scene3d/blender_renderer.py:178`（`cmd = [exe, "--background", "--python", script_path]`） |
| 几何**每次从 SceneScript 基本体全量重建**（`_ASSET_BUILDERS` 拼立方体/球/圆柱） | `app/services/scene3d/blender_converter.py`（`_build_asset` / `_ASSET_BUILDERS`） |
| MCP 高级几何（bevel/subdivide/boolean）执行后**只上报不回流**：SceneScript `extra="forbid"` 装不下厂商几何，视频提示词管线必须继续消费 SceneScript 一种格式 | `app/services/scene3d/scene_script_tool_service.py:16-21`（模块 docstring 明确记录） |
| SceneScript 词汇表 = 13 环境 + 12 道具基本体，**无法引用外部模型文件** | `white_model_generator.py:53-73` 的系统提示词枚举 |
| 上传图片只产出 SceneScript blockout（基本体），**没有 GLB 资产落盘环节** | `app/services/scene3d/image_analyzer.py`（产物是 `SceneScriptRoot`） |

**后果**：① MCP 白模模式的"高级几何"每次渲染都丢；② 用户上传的"地下研究所"永远是一堆方块而不是模型；③ "最终能建模"没有兑现路径；④ 一致性闸门只能靠颜色辨身份（`scene_consistency.py`）。

### 2.2 运行数据：只有相机一半，且不可回流

| 事实 | 证据 |
|---|---|
| 节点发布 `previs_trajectory`：每 shot 的相机关键帧、帧/秒区间、实际渲染帧——**只有相机** | `app/services/scene3d/previs_trajectory.py:33-107`；发布点 `agent_canvas_node_execution.py:2006-2015` |
| 角色运动埋在 SceneScript 的 `characters[].keyframes` 里，**没有独立的逐帧运行数据产物**，也没有按帧采样的 transform | `app/schemas/scene_script.py`（`CharacterKeyframe`） |
| **环境/道具没有 keyframes**（schema `extra="forbid"`），只有角色和相机能动——门扇开启这类动作做不了 | `docs/3d-previs-to-photoreal-video-workflow.md:136-144` |
| 运行数据不可回流：时间线 camera 轨无法从 scene-3d 导入运镜（ADR 0007 §4.3 未做），stated as open in `3d-workbench-and-pipeline-completion.md:17`（Q4 ③） | 同上 |
| 运动数据没有标准导出格式（BVH/FBX），专业用户带不走 | 全仓无导出实现 |

### 2.3 参考视频：今天是"提示词+单图"，不是"运动数据驱动"

这是**最重要的现状发现**，来自已验证案例文档：

| 事实 | 证据 |
|---|---|
| Agnes `keyframes` 模式（3 张关键帧）会**忠实保留关键帧的视觉风格**——3D 低保真几何进、低保真风格出，不会自动转照片级 | `docs/3d-previs-to-photoreal-video-workflow.md:27-36` |
| 因此案例 deliberately 弃用运动参考/keyframes 模式，改用**单图参考 + 极强风格转换提示词**（negative 强排 3D/CGI），让提示词权重压过参考图风格 | 同上 :33-47 |
| 也就是说：**当前链路刻意牺牲了运动控制**——视频模型只继承了构图/空间关系，运镜靠提示词描述（`prompt_builder.py:76-99` 把相机位移翻译成 "camera dollies forward" 之类文本） | `prompt_builder.py` |
| 几何控制通道在 Blender 5.x 已残：compositor 的 Z/Normal/Vector pass 被移除，只剩 **Cycles ray-depth 单通道、仅 5 关键帧采样**（慢）；normal/flow 明确降级 unavailable | `blender_converter.py:810-826`（docstring 记录 Blender 5.2.1 实测） |
| 渲染信封：960×540 Eevee ≈ 2s/帧，6 秒镜头 ≈ 6 分钟；同步端点 >60 帧易超时 | `docs/3d-previs-to-photoreal-video-workflow.md:150-156`；`agent_canvas_node_execution.py:1727-1761`（超时按 `startup + per_frame × frames` 推导） |

### 2.4 两个工程约束（影响设计选型）

- **单产物通道**：`NodeExecutionOutcome` 一次只携带一个 `media`（MP4 或单张静帧）。建模文件要落盘需要第二个 artifact 通道，或采用仓库已有的"文件写 media 数据目录 + `/media` 服务 + structured_content 记引用"模式（深度白模已用此模式：`SceneImageIntake.tsx:129-135`）。
- **ASCII 路径**：ffmpeg/Blender 在中文路径下失败，渲染产物路径必须纯 ASCII（`docs/3d-previs-to-photoreal-video-workflow.md:145-151`）；端点保存上传时也已按 ASCII 临时路径处理（`scene_3d.py:1116-1134`）。

### 2.5 上传图片的硬条件与判别（上一轮结论，本文承接）

`image_analyzer.py:54-66` 定义现状硬条件（1–6 张、≤20MB、5 种扩展名、全景 ≥1024 宽且 1.9–2.1）。四个缺口：普通照片无分辨率下限、扩展名≠内容（端点静默改后缀 `.png`，`scene_3d.py:1129-1131`）、HEIC 不在白名单、**语义合法性零判别**（`_FRAME_ANALYSIS_SYSTEM_PROMPT` 明写 "If unsure, make your best guess"，`FrameAnalysis` 全字段有默认值 → 任何图都会被硬编成场景）。四层判别闸（魔数/几何+EXIF/LLM 语义闸/本地启发式）设计见对话记录，本文 W0 收纳。

---

## 3. 外部好设计调研（2026-09-26）

### 3.1 图生3D：本地 Blender 路线（已决策不用外部 SaaS；**2026-09-26 随图片上传功能整体暂缓**）

> 本节保留为设计储备：图片上传建模解冻时直接启用，无需重新调研。

**先看约束，再看选型**：部署无 GPU（`compose.yaml` 无 nvidia runtime），API 容器纯 CPU；但 `torch`/`timm` 已是硬依赖，MiDaS 单张 CPU 推理可行（DPT_Hybrid ~0.2–0.5s/张）。许可红线：可商用是前提。

| 候选 | 许可 | CPU 现实 | 结论 |
|---|---|---|---|
| [TripoSR](https://triposr.org/download)（VAST/Stability，HF: stabilityai/TripoSR） | **MIT** | GPU 4–6GB/<0.5s；**CPU 可跑但慢（约 30–60s/物体）**；权重 ~1GB；自动抠图+主体裁到 85%；输出 OBJ/GLB | ✅ **T2 选定**：唯一"可商用 + CPU 能跑 + 单图出网格"的交集 |
| Depth Anything V2 Small | Apache-2.0 | 轻量，CPU 友好，精度显著优于 MiDaS | ✅ **T1 可选升级**（保持 MiDaS 为默认，模型可配） |
| MiDaS（仓库已接入） | MIT | 已跑通 | ✅ T1 默认深度源 |
| Hunyuan3D-2 | Tencent 社区许可（商用条款需审） | 仓库 56GB、shape-only 10GB VRAM | ❌ CPU 无望，出局 |
| MASt3R（多图 SfM） | CC BY-NC-SA | — | ❌ 不可商用，出局 |
| InstantMesh / MIDI-3D | Apache-2.0 | 10–30GB VRAM | ❌ 出局 |
| Meshy/Tripo SaaS | 付费+署名等条款 | — | ⚠️ 降级为备选参考，本期不做（授权与外部依赖，违背 native-fusion 纪律） |

**三档路线（按"场景 vs 物体"分开——这是本设计最关键的技术判断）**：

单图重建对**场景**（"地下研究所"这种空间）本质只能给出 2.5D 浮雕，不可能给出可走进去的场景；对**物体**（一个控制台、一个箱子）才是真三维。所以分轨，不混谈：

| 档 | 对象 | 方法 | 新增依赖 | CPU 现实 | 产物 |
|---|---|---|---|---|---|
| **T1 深度浮雕** | 场景/空间 | MiDaS/DA-V2 深度 → 反投影网格三角化 → 写进 blend；顶点色=原图像素 | 零（反投影网格数学已在 `depth_reprojection.py`） | 秒级 | blend 中 `photo_relief_*` 物体；视差 ±20° 诚实边界 + 空洞率上报（沿用既有纪律） |
| **T2 单图重建** | 用户/agent 指定的道具、角色 | TripoSR → GLB → 进 blend 并按 target 名替换 | TripoSR 权重+依赖（torch 版本冲突风险 → 子进程/独立 venv 隔离） | ~30–60s/物体 → 异步 job | blend 中该 id 的真网格 |
| **T3 检索胜过重建** | 可替换道具 | 检测物 → 25 种低模词表 / LibraryEntity 资产匹配 | 零 | 零 | 基本体或库资产（干净、正确缩放、可替换） |

外部调研的一条关键判断（[《图片转3D：开源模型探索》](https://m.toutiao.com/article/7682743336394605071/)）：*生成的家具网格凹凸不平且难以编辑；把检测到的物体与 CAD 库匹配而不是重建它，会得到干净、正确缩放、可替换的东西——重建给你布局，检索给你质量*。落到本项目：**T1 给结构保真，LLM 布局给语义，T3 给干净几何，T2 只用于"词表表达不了且会上镜"的少数物体**——这与"初期能用就行、精细化要求不高"完全对齐，也把 CPU 成本压在可接受范围。

### 3.2 Agent 场景生成的研究与产品方向

- **SceneSmith（ICML 2026）/ Agentic Generation of Simulation-Ready Indoor Scenes（[arXiv:2602.09153](https://arxiv.org/html/2602.09153v2)）**：分层 VLM 代理生成可分离、带物理属性、可用于仿真的室内场景——"先建可用的资产组合，再检查"。
- [36kr《AI 造世界，难在第二步》](https://www.36kr.com/p/3939149915946376)：系统梳理 Holodeck、LayoutGPT、RoomCraft、Code-as-Room 等语言生成场景路线；核心判断与本项目 ADR 0005 一致：**稀缺的不是几何而是可信的场景状态**。
- **BlenderAlchemy（ECCV 2024）**：VLM 直接生成/修改 Blender Python——本项目已用"确定性 converter + 受控 MCP 白名单"替代此路线（任意 bpy = 任意代码执行）。
- **Hyper3D Agentic Mode + MCP**（[报道](https://www.163.com/dy/article/L7FB2MCP052682V2.html)、[新浪](https://k.sina.cn/article_5952915705_162d248f906703p0ke.html)）：通用大模型走进 Blender/引擎后，3D 工具的新定位是"被 agent 完整地用起来"。

**可复用思想**：① 分层（布局层/资产层/物理层）而不是一个平铺场景；② 生成后必有检查闸门；③ 真几何来自生成模型，agent 负责编排与校验，不负责手写几何。

### 3.3 视频模型的运动通道：都吃参考视频，不吃相机 JSON

- **[Seedance 2.5](https://jimeng.jianying.com/tools/seedance-2-5)**：R2V 参考视频控制动作；@ 标签给多模态参考分配角色（character / **camera motion** / soundtrack）；30s 原生、50 个参考素材——**"相机运动"是一个可引用的输入角色**。
- **[Kling 3.0 Motion Control 3.0](https://kling3.io/)**：从参考视频迁移运动到角色；导演级控制。
- **[Agnes keyframes 模式](https://docs/3d-previs-to-photoreal-video-workflow.md)**：参考帧风格会被忠实保留（本项目实证的低模泄漏根因）。

**结论**：运动数据的出口 = **一段风格中性的参考视频**；"相机 JSON 直传"在本期可对接的视频模型上不存在通道。所以渲染人格的"中性化"不是审美选择，是**让运动数据可用的必要条件**。

### 3.4 角色运动数据的第三来源：视频动捕

[Plask](https://plask.ai/)、[DeepMotion](https://www.deepmotion.com/)、Move.ai、Rokoko Vision、DiMocap：视频 → BVH/FBX 骨骼动画，可导出到 Blender/UE/Maya。对本项目的意义：运行数据里"角色动作"除了 5 个枚举动作（stand/talk/walk/sit/gesture）之外，远期可接受外部动作数据（P4+，本期只留数据契约的扩展位）。

### 3.5 文件格式定位

- **OpenUSD**（[组合/版本层的定位讨论](https://zhuanlan.zhihu.com/p/2079171724466308010)、[USD→glTF 转换实践](https://m.blog.csdn.net/gitblog_00425/article/details/156017102)）：references/payloads/variants/非破坏性覆盖是 Agent 时代的场景组合答案，但 web 侧实时渲染生态在 glTF。
- **本项目的选择**：`.blend` = 权威工作文件（后端 Blender 管线原生、可带回用户机器）；**GLB = 交换与预览格式**（three.js 前端可直接加载，"建模文件"对用户可见可带走）；USD 记为远期研究线，不进入本期（与 ADR 0005 对 NeRF/3DGS 的 Deferred 处置一致）。

---

## 4. 提议的最终形态

### 4.1 三层架构（SceneScript 仍是唯一规范状态）

```
┌─────────────────────────────────────────────────────────────┐
│ 规范层 SceneScript（不变，ADR 0005 §1）                          │
│  场景语义 + 词汇表 + 引用：characters/cameras/props/…/shots    │
│  · agent ops（SceneScriptToolService 单闸门）                  │
│  · 用户手势/数值（同一闸门）                                    │
│  · 资产引用 scene_asset_id / prop_asset_id / character_asset_id│
├─────────────────────────────────────────────────────────────┤
│ 几何层 建模文件（新增，可缓存可重建）                             │
│  scene.blend：基本体词汇 + MCP 高级几何 + 导入的 GLB 真模型      │
│  · 渲染前：有 blend 且版本匹配 → 直接加载；否则从 SceneScript 重建│
│  · 保存为节点产物资产；GLB 由 blend 导出（交换/预览/带走）        │
├─────────────────────────────────────────────────────────────┤
│ 时序层 运行数据（新增，可编辑可回流）                             │
│  motion.json：逐帧采样的 camera transform(FOV) + character    │
│  transform/action + 环境道具轨（schema 扩展后） + 语音绑定区间   │
│  · 出口 A：中性渲染人格 → 参考视频（运动数据 → 视频模型）        │
│  · 出口 B：回流 SceneScript（改运动 = 改关键帧）                 │
│  · 出口 C：时间线 camera 轨导入（关闭 ADR 0007 §4.3 开放项）     │
│  · 出口 D：BVH/FBX 导出（专业用户带走，P3）                     │
└─────────────────────────────────────────────────────────────┘
```

**为什么不违反"单一事实来源"**：SceneScript 仍是唯一规范；建模文件与运行数据都是它的**派生缓存**——可由 SceneScript 完整重建、可随时丢弃、可版本校验失效（blend 记录生成它的 SceneScript 版本号，不匹配即重建）。派生品被持久化只为省算力与承接"SceneScript 装不下的东西"（MCP 几何、GLB 网格）。

### 4.2 id 空间对齐（地基已在，剩两处缺口）

SceneScript id ↔ blend 物体名 ↔ motion track id 三者同一空间。**地基已在代码里**：converter 生成的物体本来就以 SceneScript id 命名——相机 `cam.id`（`blender_converter.py:716-720`）、角色 `char.id`（:707）、环境/道具 `obj_id`（:84/130/138…）。这把"agent 说 door_1"、"用户在视口点那扇门"、"运动数据里 door_1 的轨迹"三件事先天焊在一起。

剩两个缺口：

1. **导入的 GLB 物体**带着自己的名字，需按 `scene_asset_id`/`prop_asset_id` 重命名并保留原资产引用（`scene_script.py` 已有这两个字段，语义正好）。
2. **MCP op 的 `target` → 物体名需要显式桥接**：`blender-mcp` server 是**独立进程、独立 Blender 会话**（stdio spawn，`blender_mcp_client.py` 的 `StdioMcpTransport`），它建的几何不在我们的渲染会话里。"MCP 写 blend"因此不是附贴，而是**跨会话几何转移**——务实路线是让 MCP 会话把 op 的结果网格（修改器求值后的 mesh，正是 SceneScript 装不下的那部分）按 target 名导出 GLB，我们的渲染会话加载自身 blend 后导入该 GLB 并替换同名物体（`mcp_results` 已记录 tool/target/状态，转移产物同样要上报，工程标准 §4）。另一条路是让我们的常驻会话托管 MCP addon（单会话），改动大得多，记 W4 评估。

### 4.3 三种渲染人格（同一 (blend, motion) 的纯函数）

| 人格 | 外观 | 音频 | 消费者 | 现状 |
|---|---|---|---|---|
| `animatic` | 低模配色（现有） | 床音混流（已实现） | 人（审片） | ✅ 已有 |
| `motion_reference` | **中性**：白/灰无材质 clay 或线框，去掉色板与装饰 | 无 | 视频模型（运动/构图继承，风格绝缘） | ❌ 新增，**核心** |
| `stills` | 同 animatic 的单帧 | 无 | 人 + 视频模型单图模式 | ✅ 已有（ establishing frame） |

`motion_reference` 的关键性质：**风格绝缘 + 运动保真**。它直接回答案例文档记录的两难（keyframes 模式泄漏低模风格 vs 单图模式丢运动）——中性参考视频走 Seedance R2V / Kling Motion Control / Agnes 视频参考通道时，模型继承的是相机与 blocking 运动，不是低模配色。灰度黏土渲染在 VFX 预演里是标准做法（layout/blocking pass），不是发明。

兼容与降级（工程标准 §4）：provider 不吃视频参考 → 回落 5 关键帧（`previs_control_level` 可查询）；即使落回单图模式，`motion_reference` 的静帧也比低模配色帧更适合当构图参考。**中性人格的引入不改变任何现有 provider 调用路径**，只是多一种可选的参考产物。

### 4.4 "上传图片 → 建模"的完整链路（本地 Blender 三档路线）

```
上传图片（四层判别闸：魔数/几何+EXIF/语义/本地启发式）
   ↓ ① LLM 布局：SceneScript blockout（已有 image_analyzer，语义层，秒级）
   ↓ ② 场景结构保真：T1 深度浮雕网格 → 写进 scene.blend（photo_relief_*，秒级）
   ↓ ③ 用户/agent 指定"这个物体要按图建" → T2 TripoSR → GLB → 进 blend 按 target 名替换
   ↓ ④ 其余可替换物体走 T3 检索（低模词表 / 资产库），不重建
   ↓ ⑤ 重渲染直接用 blend（真几何+浮雕）——"先 blocking 后精修"两段式兑现
```

- T1/T3 零新依赖、CPU 秒级，是"能用就行"的默认路径；T2 是**显式触发的加重通道**（异步、许可与来源进 metadata、失败降级为该物体继续用基本体）。
- 环境变量与依赖纪律沿用既有模式：深度模型可配（`MiDaS` 默认 / DA-V2 Small 可选）；TripoSR 权重懒加载（同 MiDaS 的 `torch.hub` 模式）+ `check_dependencies()` 能力闸 + 缺失时 coded 失败，绝不静默。
- Meshy/Tripo SaaS 保留为备选调研结论（授权、链接 3 天过期、异步契约同构），本期不做。
- 用户自带 `.blend`/GLB 导入（反向）仍记 W4——导入=解析/对齐/合并语义，工作量等于再做一个 converter 反向。

### 4.5 交付包（一键导出）

`scene.blend` + `scene.glb` + `motion.json`（+ BVH/FBX） + 三种人格的参考视频 + prompt bundle + 一致性/降级报告。把案例文档 §五"保留全部中间产物"的手工清单自动化，且每项带溯源（哪个 SceneScript 版本、哪次渲染、哪个 provider）。

### 4.6 聊天驱动的逐轮场景与"动起来"（2026-09-26 新重心，图片建模暂缓）

> **范围变更（用户二次拍板）**：图片上传建模暂缓（T1/T2/T3 冻结为设计储备，见 §3.1）；当前重心 = 聊天逐轮驱动场景 + 聊天改角度 + 动画。约束：**颜色和形状即可、不需要渲染**——即前端 Three.js 预览，Blender 完全不参与。

**先回答"能否动起来"：能，而且地基已经在代码里。** 这不是新能力，是一个没被点亮的能力：

| 层 | 已存在 | 证据 |
|---|---|---|
| 数据 | `add_keyframe` op（character/camera，带 `frame`）、相机 `position/look_at` K 帧、角色 `position/rotation_y/action` K 帧、shots 帧区间 | `scene_script_tool_service.py:51-63`（OP_KINDS）、SKILL.md op 表 |
| 前端 | 播放上下文（rAF 帧循环、play/pause/seek/帧步进）、相机关键帧插值、角色按帧动作（前向继承）、手势轨迹、台词浮层随播放头 | `SceneScriptPlaybackContext.tsx`（:158-198 rAF）、`SceneScript3DPreview.tsx:91-165` |
| 消费 | 预览即动画：Three.js 实时，**不需要 Blender、不需要渲染队列** | ADR 0005 §2 双引擎的前端一半 |

**断掉的是环，不是能力**（核心发现）：

- 聊天面板与 scene-3d **零耦合**——`chat/` 下无任何 scene-3d 引用；
- `execute_canvas_white_model` 操作**已注册**（契约 `AgentCanvasWhiteModelOutput` + skill `video_agent_3d_white_model` + registry 元数据齐全）但**没有任何 UI 调用它**；内部 router 无白模分发；
- 唯一活着的白模路径是 scene-3d 节点的 Run 按钮（`white_model_generator`，prompt-per-run），不是 chat-per-round。

**所以"每轮聊天分析出场景"= 把已注册未接线的四件套连起来**：chat 轮 → runtime 白模 capability → ops 批次 → `SceneScriptToolService` 同一道闸 → PATCH 节点（合并写）→ SSE → 预览。契约/skill/闸门/预览四件都在，缺的就是这根线（含会话↔节点绑定，`conversationCanvasLinks.ts` 的 `navigableNodeIds` 是可坐的种子）。

**三个结构性缺口（不补会咬人）**：

1. **`add_camera` 不建 shot**：新相机只有 frame-0 关键帧、没有 shot 引用它 → 播放里这台相机不存在（`camera_unused` 一致性警告正是抓这个）。多角度聊天前必须有 shot 概念（新增 `add_shot`/`set_shot_camera` op，或显式"当前 shot"模型）。
2. **move/rotate/scale/set_camera 全部只写 `keyframes[0]`**（`scene_script_tool_service.py:446-500`）→ "把角色挪到门边"只能重排第 0 帧。运动表达只能走 `add_keyframe`（带 frame），而 skill 没教这个模式。要么给这些 op 加 `frame` 参数（推荐：同一 op 带帧即写该帧 K 帧），要么在 skill 里把 add_keyframe 提为一等手法。
3. **环境/道具 schema 无 keyframes** → 门开不了、道具动不了。**诚实边界：能动的是角色与相机**，产品话术不得承诺门扇/道具动画（案例文档已记录此限制）。

**两个设计洞察（省钱且直接提体验）**：

1. **"改变角度"是单路径双结果，前期不省**（2026-09-26 用户拍板：前期效果优先，不做调用经济优化）：
   - 用户一切输入都过 agent，由 agent 判断并回显理解，不在前端做意图猜测；
   - agent 的答复分两种结果：**`view_command`（观察角度——"转过去看看背面"）**：纯前端 OrbitControls 应用，**不落盘、不进 SceneScript、不消耗节点修订号**；**`scene_ops`（镜头角度——"这场戏从侧面拍"）**：走 `set_camera`/`add_keyframe` 过闸门落盘；
   - 两者都经**指令可见层**回显（"理解为：观察角度-绕到背面" / "理解为：把 cam_1 机位移到场景西侧 3.2m、注视桌边"），用户可改可撤；
   - 前一轮设计的"规则先行分流以省 LLM 调用"**显式撤回**：省调用会让体验分裂（同一句话两种路径两种延迟），前期要的是连贯与可解释；`view_command` 仍然便宜（前端本地），省钱的自然结果保留，但不作为设计目标。
2. **每轮 diff 必须带时间维度**：否则"她走到桌边"和"墙加高了"在用户眼里长得一样（都是场景变了）。设计：本轮 ops 若含关键帧 → 自动播放受影响的 shot（或最低限度：高亮新关键帧 + 帧位标记）。**"什么时候发生"必须成为可见事实**，这是聊天驱动动画的体验核心，也是"能分析每一轮聊的内容"的验收标准。

**契约短板（prompt 工程，非架构）**：白模 skill 教"建造"不教"调度"。要补：时长一等公民（默认 6s/30fps）、节拍→帧映射（"第 0 秒站在门口、第 2 秒走到桌前"）、镜头运动与 blocking 作为成组关键帧下发、一次一个镜头的纪律。

---

## 5. 与 V0.2 / ADR 的对账

| 主张/开放项 | 本文如何处置 |
|---|---|
| ADR 0005 §1 SceneScript 唯一规范 | **不违反**：blend/motion 均为派生缓存（§4.1） |
| ADR 0005 §4/§4a 可查询降级 | motion 数据出口与人格降级沿用 `previs_control_level` + 新 markers，不新增静默路径 |
| ADR 0007 §4.3 camera 轨从 scene-3d 导入（开放） | **由运行数据出口 C 关闭** |
| V0.2 §8.3 画箭头表达镜头运动 | 手势已落地；升级为运动数据里的一条可编辑轨（§4.3 出口 B） |
| V0.2 §14.3 Timing 锚点（Audio Event） | 语音绑定区间进 motion.json，与角色/相机轨同时间轴 |
| V0.2 §5 Continuity State | 一致性闸门从"颜色即身份"升级为 blend 级（绑定的真模型存在性） |
| 白模方案 §1.2 "MCP 是扩展词汇" | **升级兑现**：MCP 几何写入 blend 后不再即弃，SceneScript 仍持引用（§4.1） |
| 工作台方案 Q3 "缺前端可交互化" | 已实现大半（上一轮对账），本文补运动轨编辑器 |
| 上一轮 W0–W3（图片语义闸/信任件/指令可见层/并排评审/一键交接） | **编号并入本文 W0–W4**（下表），内容不变 |
| 2026-09-26 新重心：聊天逐轮驱动场景 + 改角度 + 动起来 | §4.6 + §6a：四件套已注册未接线（契 约/skill/闸门/预览），缺环与三结构缺口列明；动起来的地基（数据+播放）已在代码里 |

---

## 6. 分阶段施工（W0–W4，每阶段独立可验收、可回滚）

### §6a — 新重心：聊天驱动的逐轮场景 + "动起来"（当前优先，~3 周）

> 图片上传建模（T1/T2/T3）与下列 W0–W4 冻结为设计储备，本阶段完成后解冻。

- [ ] **接线（一周）**：chat 轮 → `execute_canvas_white_model` capability → ops 批次 → SceneScriptToolService 闸门 → PATCH 节点合并写 → SSE → 预览刷新；会话↔scene-3d 节点绑定（坐 `conversationCanvasLinks` 的种子）；无节点时首轮自动建（starter 脚本 = 相机+shot）
- [ ] **角度双结果**（先不省）：一切输入过 agent；`view_command`（观察角度→前端 OrbitControls，不落盘不耗修订号）与 `scene_ops`（镜头角度→`set_camera`/`add_keyframe` 过闸门）两种结果都经指令可见层回显；撤回"规则先行省调用"方案
- [ ] **每轮时间 diff**：ops 含关键帧 → 自动播放受影响 shot；无关键帧 → 静态刷新；白模 op 日志面板扩展时间列（帧/秒）
- [x] **结构缺口（2026-09-27 已落地）**：`add_shot` / `set_shot_camera` op + `add_camera` 的 `frame` 参数 + `move_object`/`rotate_object`/`set_camera` 的可选 `frame` 参数（带帧=该帧 upsert 关键帧，不带帧=原 frame-0 语义，向后兼容）；顺手修掉 `rotate_object` 作用相机上的静默失真（写不存在的 `rotation_y`、报成功不改任何东西，现 coded 拒绝）。验收：`scene_script_tool_service.py` + 其测试 48 项全绿；相关 931 passed（4 个失败为本机缺 torch 的 depth 预存在失败，与本改动无关）；变异检查锁定 upsert 不复制
  - **两个设计发现（施工中浮出）**：① schema 有"相机关键帧必须落在使用它的 shot 内"校验（`_validate_camera_keyframes_in_shots`）——所以"从第 60 帧起用侧机位"必须表达为相机 K 帧@60 + shot 覆盖 60，`add_camera` 因此获得 `frame` 参数；② 闸门上限必须与 schema 一致（`end_frame ≤ total_frames`），严于 schema 的闸门会拒掉合法脚本
- [ ] **契约升级**：白模 skill 增加"调度"教学（时长一等公民、节拍→帧映射、成组关键帧、一次一镜）；生成器提示词同步
- [ ] **验收**：纯聊天 5 轮建出"走廊+门+两个角色+一相机一shot"，视口每轮可见更新；说"她走到桌边再抬头看门"→ 播放可见位移与转身（角色关键帧，帧级）；说"转过去看看背面"→ 前端即时环绕、**零 LLM 调用**；说"这场戏从侧面拍"→ set_camera 生效且回显理解；改台词时口型/浮层随播放头（已有能力不回归）

### W0 — 建模文件落盘 + 中性渲染人格（后端为主，~2 周）
- [ ] 渲染脚本末尾 `save_as_mainfile` 落 `.blend` 到 media 数据目录（ASCII 路径），structured_content 记录 `scene_blend` 引用（沿用深度白模"文件+/media+引用"模式；资产库正式通道记 P3）。物体命名无需改动——converter 本就以 SceneScript id 命名（§4.2）
- [ ] `render_scene_script` 支持 `persona` 参数：`animatic`（现状）/`motion_reference`（中性黏土：统一灰白自发光材质、去色板、去灯光装饰，保留几何与运动）/`stills`
- [ ] blend 版本闸：记录生成 blend 的 SceneScript 哈希；SceneScript 变更则不匹配 → 重建并覆盖（可查询，不静默用旧几何）
- [ ] 验收：白模模式跑一轮 → 节点带 `.blend`；用 Blender 打开是同一场景；同一 SceneScript 两种人格渲染，运动逐帧一致、外观不同；改 SceneScript 后 blend 被标记重建
- [ ] 收纳上一轮 W0 的图片四层判别闸（魔数/几何+EXIF/语义/本地启发），作为建模链路的输入质量前置

### W1 — 运行数据完整化（~2 周）
- [ ] `previs_trajectory` → `motion_data`：逐帧采样 camera(position/look_at/fov) + character(position/rotation/action) + shots + speech bindings 区间 + blend 物体引用表；保持 `coordinate_system: blender_z_up` 与单一坐标约定（现有纪律）
- [ ] 回流：motion.json → SceneScript 关键帧合并（复用 `sceneScriptEditModel` 的"同帧更新/异帧插入/继承"语义，TS 侧已有同构实现）
- [ ] 出口 C：时间线 camera 轨导入 scene-3d 运镜（关闭 ADR 0007 §4.3）
- [ ] 验收：只改 motion.json 重渲染 → 参考视频运动变、SceneScript 语义不变；从时间线拖入运镜 → 节点运动数据更新；导出 motion.json 在另一节点重放一致

### W2 — 真几何接入：深度浮雕 + TripoSR + MCP 写 blend（~2–3 周）
- [ ] **T1 深度浮雕网格**：把 `depth_reprojection.py` 的反投影网格抽成可复用函数（规则网格 → 每格 2 三角形 → `mesh.from_pydata`，按需降采样至 ~10 万顶点）；converter 增加 `photo_relief` 物体（SceneScript 持 `scene_asset_id` 引用，记录源图资产与深度模型来源）；顶点色=原图（或按渲染人格着黏土灰）；视差 ±20° 与空洞率上报沿用 `depth_reprojection` 既有纪律
- [ ] **T2 TripoSR 通道**（`triposr_service.py`）：懒加载 + `check_dependencies()` 闸 + **子进程/独立 venv 隔离**（TripoSR 的 torch/依赖版本与 API 主环境有冲突风险，不能 in-process）+ HF 权重缓存（~1GB，同 MiDaS 懒加载模式）+ OBJ/GLB 产物即时落盘 + 许可与来源进 metadata + 异步 job（照 `render_job_manager` 模式，CPU ~30–60s/物体）+ 失败全 coded 并降级"该物体继续用基本体"
- [ ] **工作台入口**："把这个物体按参考图建成真模型"——选中物体 → 从已上传图裁剪或补传一张 → 触发 T2 → blend 中该 id 出现真网格
- [ ] **T3 检索**：`image_analyzer` 已识别的 props 显式走一层"词表/资产库匹配"（本就要做的枚举匹配，补成显式步骤 + 测试：匹配不上才提示可 T2）
- [ ] MCP op 从"执行并上报"升级为"执行并写入 blend"：跨会话转移采用 §4.2-2 的 GLB 路线（MCP 会话导出结果网格 → 渲染会话导入并按 target 名替换）；无 blend 或转移失败 → 保持现有"执行并上报"语义并 coded 降级（链路本就完整，不新增阻断）
- [ ] 一致性闸门 blend 级：绑定的 `character_asset_id` 有真模型 vs 只有颜色，分开报
- [ ] 验收：上传航天基地照片 → blockout + 背景浮雕同屏呈现；指定一个箱子走 T2 → blend 出现真网格并替换该 id；MCP bevel 后重渲染几何仍在（不再即弃）；TripoSR 依赖缺失时 coded 失败且场景仍可用

### W3 — 导演台 + 指令可见层 + 并排评审（前端，~2 周）
- [ ] 收纳上一轮 W1/W2：单步 undo/redo、ETag 冲突重读合并、镜头起止帧+frustum、`render_settings` 消费（`blender_converter.py:744` 硬编码 960×540）、视口旋转/缩放 gizmo
- [ ] 运动轨编辑器：camera/character 轨可拖、与台词浮层同轴对齐（V0.2 §14.3 Timing 落到数据层）
- [ ] 指令可见层组件（全剧组共用）：手势/agent 操作回显"系统理解…"可改可撤
- [ ] 并排评审：一次描述 N 个运镜版本（分叉）+ 一键交接 video 节点 + 参考账本上屏（`previs_control_level`/`degraded_assets`）

### W4 — 带走与生态（P2/P3，按需）
- [ ] 交付包一键导出（blend/GLB/motion/prompt/报告 + 溯源）
- [ ] BVH/FBX 运动导出；外部动作数据导入契约（只留 schema 扩展位，不接服务）
- [ ] 用户自带 blend/GLB 导入（反向 converter，工作量最大，独立立项评估）
- [ ] USD 组合层研究线（与 NeRF/3DGS 同列 Deferred）

---

## 7. 风险与缓解

| 风险 | 缓解 |
|---|---|
| blend 与 SceneScript 双向漂移（用户改了 blend 里的墙） | 本期纪律：**blend 是单向派生**（SceneScript → blend）；用户在 blend 里的手改不被读回，工作台明示"外部修改不回流"；读回能力记 W4 专项 |
| TripoSR 的依赖/权重/CPU 成本 | 子进程+独立 venv 隔离（避 torch 版本冲突）；权重懒加载（同 MiDaS 模式）+ `check_dependencies()` 闸；异步 job；失败 coded 降级"该物体继续用基本体"；文档明示 CPU 量级（~30–60s/物体）管理预期 |
| 用户对"上传场景图=得到可走进去的场景"预期落空 | 产品话术与文档统一按 T1 浮雕 + LLM 布局表述，不承诺可漫游场景；多图 SfM（COLMAP/Meshroom，许可干净）记 W4 研究线；MASt3R 因 CC BY-NC-SA 不可商用已排除 |
| 中性渲染=丑，用户不想看 | 人格是**给模型看的**，不是给人看的；审片用 animatic 人格不变；入口文案区分"给视频模型的运动参考"与"给我看的预演" |
| 渲染算力（中性人格又多一遍渲染） | keyframes-only 已是默认（5 帧/镜）；中性人格默认只渲 5 关键帧 + 低分辨率；与并发闸（`scene3d_max_concurrent_renders=1`）共存 |
| 图生3D/动捕是外部依赖，违反"native fusion"？ | ADR 0005 §withdrawn 反对的是"引入外部预演工具作为服务"；图生3D 与视频/TTS 同级——都是**素材生成 provider**，不进领域代码、可查询降级，纪律同构 |
| 运行数据 schema 膨胀 | 只存"事实"（帧、transform、引用），不存"解释"；解释留在 SceneScript |

## 8. 术语提议（进 `CONTEXT.md` 词汇表前需评审）

**Scene File（建模文件）** · **Motion Data（运行数据）** · **Render Persona（渲染人格）** · **Clay Reference（黏土参考）**。避免与既有 SceneScript / Previs Trajectory 造同义词：`previs_trajectory` 改名 `motion_data` 属同一概念扩展（相机半成品→全量），迁移时保留旧键一个版本的读取兼容。

## 9. 暂不做 / Open

- 用户自带 `.blend`/GLB 导入读回（W4）；USD 组合层（Deferred）；真音素级唇形以外的动捕接入（只留契约位）；引擎内实时预演（ADR 0005 withdrawn 维持）。
- **已决策（2026-09-26 用户拍板，两轮合并）**：真实设施照片的合规审核**不上**；图生3D 走本地 Blender 路线（T1/T2/T3）**但随图片上传功能整体暂缓**；单屏形态（不开新窗口/PiP）；新重心 = 聊天逐轮场景 + 聊天改角度 + 动画（§6a）；**前期效果优先、不做调用经济优化**（角度走单路径双结果，§4.6）。
- **仍开放**：① HEIC 支持与否（要支持需加转码依赖，随图片功能暂缓后优先级下降）；② 图片语义闸严格度（默认"宁松不紧+黄标"）；③ 深度模型默认值（MiDaS vs DA-V2 Small）；④ 与 replica/timeline 并行流的共享文件分界是否需要在 issue 里正式互告（§10.2）。

## 10. 并发施工与冲突处理预案（2026-09-26 新增）

> **2026-09-27 施工首日备注**：`git stash list` 可见 `stash@{0}: On main: timeline-feature-work-in-progress`（timeline 流 WIP 被 stash 过）——并行流真实存在，预案按 §10.4 执行。

> 前提：仓库是**共享主干（当前 `main`）**、多施工方并行（近期并行流：timeline/ADR 0007 线、replica 节点线、本功能线；工作树常年 ~2000 个未暂存改动）。冲突不是异常，是常态，按预案处理而不是按惊喜处理。

### 10.1 仓库已有的冲突范式（照抄，不发明）

来自 `CHANGELOG.md` 最新条目的实录——上一回合与并行的 replica 工作流改同一批共享文件（`types-v2.ts` 多 `replica` 节点类型、`nodeDefaults.ts` 可见类型表多一行），**其未暂存改动把全量基线从 77 → 80 失败并产生 2 处 tsc 错误，均非本改动引入**，用 `git stash` 对照 + 逐条 diff 归因后在 CHANGELOG 显式声明。由此固化四条：

1. **基线归因**：每次汇报前跑全量，把失败数与改动前基线比对；**别人的 WIP 失败必须点名"非本改动引入"并附证据**（stash 对照 / 逐条 diff）。不允许把别人的失败算自己头上，也不允许悄悄无视。
2. **CHANGELOG 是协作面**：每条条目写清"改了什么、没改什么、哪些失败是别人 WIP、bundle 增量里含谁的 WIP"。
3. **"会压到别人的一律拒绝"**：canvasSnap 的产品级冲突规则（snap 后与兄弟相交即放弃）——本功能同样适用：**不得让他人的节点/轨道/吸附/播放头因我们的自动行为失效**。
4. **纪律来源**：`docs/agents/engineering-standards.md`（自检阶梯/契约同步/可查询降级/ADR 边界）+ `docs/agents/issue-tracker.md`（`gh issue` 跟踪；本会话无 gh CLI，用文档+CHANGELOG 公告代替，事后补 issue）。

### 10.2 本功能的冲突地图（按风险排序）

> **2026-09-26 预检**：下表每个文件当前均带未提交改动（多条流 WIP 混合）。`nodeDefaults.ts` 暂为干净（replica 流的相关改动已提交）。施工第一步前先重跑预检，把它当作"当前是否有别人正在动这里"的探针。

| 文件/面 | 谁在碰 | 风险 | 处理 |
|---|---|---|---|
| `apps/web/src/types-v2.ts`、`nodeDefaults.ts` | **replica 流正在改**（实证） | 高 | 本功能**不加节点类型、原则上不碰**；scene-3d 已存在，新能力挂 workbench/chat 不挂 catalog |
| `CHANGELOG.md`、`README*.md`、`AGENTS.md` | 全员追加 | 高 | 追加式编辑；冲突时 take theirs + 重新贴我们的段 |
| `apps/api/app/services/agent_canvas_node_execution.py` | timeline 自动建 clip、voice-cast QA 钩子 | 高 | 只**合并写新键**（`white_model_*`/`scene3d_*` 前缀），不重构既有键；`publish_node_output` 的合并语义即是共生契约 |
| `apps/api/agent/src/registry.ts` + `src/generated/*`（agent-runtime.schema.json/.ts、agent-capabilities） | agent 契约面（MCP 方案期间已踩坑） | 高 | 一次性命令重新生成（`generate_agent_contracts`），**已知 OneDrive+WSL 会把生成文件回退**——生成后立即 `verify` 再提交，绝不手改；与并行的契约改动冲突时重跑生成+取并集 |
| `apps/api/app/schemas/scene_script.py` | prompt_builder / control_passes / consistency / timeline camera 导入线都消费它 | 中高 | `add_shot`、env/prop keyframes 等 schema 变更是**跨流事件**：改前在 issue/CHANGELOG 点名，改后双侧重新生成 + `check:agent-canvas-contract`，旧键读兼容一期 |
| `canvas/SceneScript3DPreview.tsx`、`SceneScriptPlaybackContext.tsx` | timeline 的 `PlayheadSyncContext` 与编辑时间线消费它们 | 中 | 播放上下文正是为跨面板同步而存在；本功能只加消费不加破坏，改动前跑 timeline 相关测试 |
| `apps/api/app/services/scene3d/*`、`video_agent_operation_registry.py` | 主要本功能 | 低 | 正常施工；registry 追加不动既有条目 |

### 10.3 运行时冲突（产品内多方同时编辑同一 workflow）

- **节点写用 ETag 乐观锁**（`If-Match: "workflow-{id}-v{rev}"` 字面量，读 revision 或写整数都会 412）。聊天环的每轮 ops 写节点必然撞锁：**412/409 → 重读节点 → 在新版本上重放 ops**。白模 ops 是**相对增量**，天然适合重放；若 target 已不存在（别人删了那面墙）， coded 失败并列出 violations，由用户决定，绝不静默丢弃。
- **锁只用 `v2_workflow_lock`**（`final_composition`/render/recovery 已在用的 per-workflow 文件锁）。**严禁自造第二套锁**——两个锁腹死锁是真实风险。本功能聊天环默认不加锁（写路径短、有乐观锁兜底）；若未来要加，坐这把。
- **渲染闸不碰**：`_shared_scene3d_render_slot()` 是别人的渲染并发设施；本功能聊天环不渲染（无 Blender），零交互。
- **structured_content 只合并**：与他人流的键（`previs_trajectory`、`scene3d_consistency`、timeline 自动建的键）共存；新增键全部带前缀并在 CHANGELOG 登记。
- **SSE 事件加法式**：本功能推送"ops 已应用/版本+1"事件；不得吞掉或改写他人事件；前端刷新策略跟随既有 `timelineMutationRefresh` 式 store bump，不新造刷新通道。

### 10.4 施工规矩（本功能执行期）

1. 开工先立 issue（本会话无 `gh`，先在本文档+CHANGELOG 公告范围，事后补 `gh issue create`）；
2. 优先新文件；必须动共享文件时小步、早提交、CHANGELOG 点名；
3. **提交纪律（2026-09-26 预检发现，必守）**：冲突地图上的文件当前全部带未提交改动（`types-v2.ts`/`scene_script.py`/`SceneScript3DPreview.tsx` 均为 `MM` 暂存+未暂存混合态），工作树约 2000 个脏文件混有多条流的 WIP——**严禁 `git add -A` / `git commit -a`**，只按路径逐个 `git add <我们的文件>`；提交前 `git status --short` 核对清单，`git diff --cached --stat` 确认只含本功能文件；发现误暂存别人的文件立即 `git restore --staged <file>`；
3. 每次汇报带全量基线归因（§10.1-1）；
4. schema/契约/manifest 任何变更 → 双侧重新生成 + 契约检查 + 在稳定文件系统验证（绕开 OneDrive+WSL 回退坑）；
5. 与 replica 流的分界写死：不加节点类型、不碰 `types-v2.ts`/`nodeDefaults.ts`；
6. 产品级"不压别人"：自动播放/高亮只作用于本 scene-3d 节点的 shot，不动全局播放头与他人 clip（除非用户显式操作）。

