# 拉片复刻 · 参考片拆解（Replica Teardown）

> 功能：上传一条参考视频，系统像专业创作者"拉片"一样逐镜头拆解它——整片解读、结构 Beats、镜头表（景别/运镜/屏上文字/转场）、节奏、视觉系统——并生成一份**复刻分镜草稿**，可直接粘贴进 Script 节点或 Agent 对话，带着原片的结构进入正常创作流。
>
> 设计理念借鉴 hypit（`github.com/hypit-ai/hypit`）：视频是可拆解、可复刻的工程；复刻的是**关系**不是像素。完整调研与方案论证见 [`docs/plans/hypit-replica-research.md`](./plans/hypit-replica-research.md)（本文件是其落地记录：**P0 拉片拆解 + P1 复刻半场 + `.adreplica` 文档层均已完成**）。

## 1. 功能概述

### 解决的问题

创作者看到一条好的参考片（竞品广告、爆款短视频），想"照着它的结构拍一条自己的"，但只能凭感觉描述。拉片复刻把这件事变成结构化产出：**先拆解，再复刻**。

### 与现有能力的关系（刻意不冲突）

| 现有能力 | 关系 |
|---|---|
| `scene-3d/analyze-reference`（参考视频 → SceneScript → 3D 预演） | 并行不悖：那边回答"这个场景的空间/运镜怎么重建成 3D"，这边回答"这条片子的**叙事结构**怎么复刻" |
| ReferenceVideoPanel（scene-3d 节点的 Reference 页） | **入口宿主**：拉片复刻作为该面板的第三个动作（上传/白模/拉片），不新增节点类型、不改画布协议 |
| Script 节点 / Agent 对话 | **下游**：复刻分镜草稿的消费方，产物是文本，天然融入现有创作流 |

## 2. 数据流

```
用户上传参考视频（ReferenceVideoPanel，已有上传端点）
    ↓  asset_id
POST /api/v1/replica/teardown
    ↓
[teardown.py] analyze_reference_teardown()
    ├─ extract_metadata()            → ffprobe 元数据；>60s 拒绝（拉片面向短片）
    ├─ extract_keyframes_from_video()→ 均匀抽帧（默认 8 帧，clamp [4,16]，复用 scene3d 基建）
    ├─ _analyze_teardown_frame() ×N  → 多模态 LLM 逐帧分析（新增 on_screen_text 维度）
    ├─ _synthesize_teardown()        → LLM 综合拆解（整片解读/Beats/镜头表/节奏/系统）
    ├─ _normalize_* + pydantic 校验   → LLM 输出兜底（钳制/默认值/派生，HTML schema 严校验）
    └─ build_replica_draft()         → 确定性生成复刻分镜草稿（不再调 LLM）
    ↓
TeardownResponse{report, frame_analyses, video_metadata}
    ↓
前端 ReplicaTeardown 面板：报告可视化 + 一键复制草稿 → 粘贴到 Script 节点/对话继续创作
```

## 3. API 端点

### POST /api/v1/replica/teardown

**请求**（multipart/form-data）：

| 字段 | 必填 | 说明 |
|---|---|---|
| `asset_id` | 二选一 | 已上传参考视频的 asset_id（走 `get_reference_video_path` 安全解析，防路径穿越） |
| `file` | 二选一 | 直接上传视频文件（MP4/WebM/MOV/M4V，≤60s） |
| `user_description` | ○ | 复刻目标（换商品/换人物/换台词/换风格/整片复刻），引导 LLM 读片侧重 |
| `num_frames` | ○ | 抽帧数，默认 8，clamp [4,16] |

**响应**：

```json
{
  "success": true,
  "report": {
    "whole_piece_reading": "前3秒用错误示范制造焦虑，中段产品证明，结尾CTA。",
    "format_name": "product-comparison",
    "shots": [{"index": 1, "start_seconds": 0.0, "end_seconds": 2.1, "shot_size": "closeup", "camera_motion": "static", "subject_action": "唇部特写", "on_screen_text": "别再这样洗脸", "transition_to_next": "cut", "note": ""}],
    "beats": [{"role": "hook", "description": "...", "start_seconds": 0.0, "end_seconds": 3.0}],
    "rhythm": {"avg_shot_seconds": 2.4, "cut_points_seconds": [0.0, 2.1], "energy_curve": "前快后缓"},
    "systems": {"captions": "...", "music": "...", "graphics": ["..."], "sfx": ["..."]},
    "replica_storyboard_draft": "# 复刻分镜草稿…",
    "constraints": ["镜头边界与运动为 LLM 基于稀疏抽帧的推断值，非帧级测量；…"]
  },
  "frame_analyses": ["…"],
  "video_metadata": {"…"},
  "num_frames_analyzed": 8,
  "user_description": "换商品，保留人物与台词结构"
}
```

**错误**：400（无输入源 / 视频超长 / LLM 失败 / 报告校验失败，带 `error_type`）；404（asset_id 不存在）；500（内部错误）。

**性能**：N 帧逐帧分析 + 1 次综合，共 N+1 次 LLM 调用（默认 9 次），约 1-3 分钟；端点用 `asyncio.to_thread` 避免阻塞事件循环。

## 4. 产品边界（对用户诚实，写入 report.constraints）

1. **镜头边界与运动轨迹是 LLM 基于稀疏抽帧的推断值**，不是帧级测量——LLM 从不连续看片；
2. **复刻目标是结构与关系**（镜头顺序/节奏/转场/系统），不是像素还原；
3. 帧数不足时明确告知（<8 帧追加提示）。
4. 屏上文字来自逐帧 `on_screen_text` 字段，未检测到即为空——词级字幕锚定（WhisperX）是后续迭代，不在本切片。

## 5. 文件清单

| 文件 | 类型 | 说明 |
|---|---|---|
| `apps/api/app/services/replica/teardown.py` | 新增 | 核心服务：抽帧→读片→拆解→normalize→草稿（约 600 行） |
| `apps/api/app/api/v1/endpoints/replica.py` | 新增 | `POST /replica/teardown` 端点 |
| `apps/api/app/api/v1/router.py` | 修改 | 注册 replica router |
| `apps/web/src/features/agent-canvas/canvas/ReplicaTeardown.tsx` | 新增 | 拉片面版：复刻目标选择、报告可视化、草稿复制 |
| `apps/web/src/features/agent-canvas/canvas/ReferenceVideoPanel.tsx` | 修改 | Reference 页嵌入拉片入口（上传后可用） |
| `apps/api/tests/test_replica_teardown.py` | 新增 | 15 项：mocked-LLM 全链路/normalize 兜底/草稿确定性/失败路径/端点契约 |
| `apps/web/src/features/agent-canvas/canvas/ReplicaTeardown.test.tsx` | 新增 | 7 项：禁用态/fetch 契约/报告渲染/复制草稿/错误面/创建蓝图节点/无 workflow 禁用 |
| `apps/api/app/services/replica/blueprint.py` | 新增 | 蓝图服务：报告→蓝图、槽位应用、锚点增删、复刻脚本渲染、实例化计划（纯函数） |
| `apps/api/app/api/v1/endpoints/replica.py` | 修改 | 新增 `POST /replica/blueprint`、`POST /replica/instantiate` |
| `apps/api/app/schemas/agent_canvas.py`、`agent_canvas_ad_media.py`、`agent_canvas_ad_media`(service)、`agent_canvas_connection_policy.py`、`agent_canvas_authoring_validation.py`、`agent_canvas_runtime.py` | 修改 | `replica` 节点类型 + `replica_blueprint` 角色注册（连接策略/校验/调度限额） |
| `apps/web/src/features/agent-canvas/canvas/ReplicaBlueprintPanel.tsx` | 新增 | 复刻工作台（槽位/锚点/镜头表/保存/一键生成） |
| `apps/web/src/features/agent-canvas/canvas/ReplicaBlueprintPanel.test.tsx` | 新增 | 5 项：空蓝图/三 tab/保存 patch/实例化全链路/错误面 |
| `apps/web/src/types-v2.ts`、`model/nodeDefaults.ts`、`model/normalizers.ts`、`canvas/AgentCanvasNode.tsx`、`canvas/AgentCanvasNodeIcon.tsx`、`canvas/SceneScriptPanel.tsx`、`canvas/ReferenceVideoPanel.tsx` | 修改 | replica 节点前后端接线（类型/默认值/图标/面板/workflowId 穿层） |
| `apps/api/app/services/replica/adreplica.py` | 新增 | `.adreplica` 文档层：蓝图 ↔ 标记文本双向转换（纯函数，词汇表见 §7） |
| `apps/api/tests/test_replica_adreplica.py` | 新增 | 26 项：语法形态/往返锁定/逃逸/结构拒绝/normalize/手改重编译/端点契约/全链闭环 |

## 6. 已交付：复刻半场（2026-09-27）

**闭环**：拉片报告 → 复刻蓝图（`replica` 画布节点）→ 槽位编辑 → 一键生成复刻工作流（script 节点）。

- **蓝图即节点内容**：新增画布节点类型 `replica`（角色 `replica_blueprint`，内容模型 `ReplicaBlueprintContentV2`）。蓝图是单一真相源，不新开存储；连接策略限定 replica 只以 `text_context` 流向 script
- **槽位与锚点**：五槽（人物/商品/台词/风格/声音，留空=保留原片值）；锚点事件挂在结构段落上（caption/broll，复刻时可整体移除）；两者都经 `POST /api/v1/replica/instantiate` 的 `slot_updates` 进入复刻脚本
- **实例化**：蓝图经 `AgentCanvasNodeService.create` 编译为 script 节点（既有画布生命周期，`expected_revision` 防并发覆盖），script 节点带 `replica_source_node_id` 反向引用；执行仍走既有工作流引擎
- **端点**：`POST /api/v1/replica/blueprint`（报告→蓝图）、`POST /api/v1/replica/instantiate`（蓝图→script 节点）
- **前端**：replica 节点面板 = 复刻工作台（槽位编辑/锚点勾选/镜头表/保存/一键生成/脚本展示）；3D Previs 节点 Reference 页的「🎬 拉片复刻」新增「🧬 创建复刻蓝图」
- **测试**：后端 +19、前端 +12；全量 backend 1803 passed；tsc/eslint 0 error

## 7. 已交付：`.adreplica` 文档层（2026-09-27）

**闭环**：复刻蓝图（结构化 JSON，"SVML 的思想"）↔ `.adreplica` 标记文本（标记语言的"载体"）双向转换——hypit **"文件即真相源"** 思想的落地形态。

- **词汇表**（调研档 §3.5 AdSVML 草案的最小实现，语法基因取自 hypit 一手样例）：`<advideo>`（语法版本/画幅/时长）→ `<meta>`（来源/格式/复刻目标/整片解读）→ `<cast><slot kind>`（槽位统一为 kind 属性，非 hypit 的 provider 焊死元素）→ `<script><beat id role dur>`（段落+时窗）→ `<timeline><shot>`（start/dur 双记 + `during=` 结构锚定）→ `<events>`（元素名即事件类型 broll/caption/sfx/mg/transition，`during` 指向段落）→ `<rhythm>/<systems>/<constraints>`
- **`during=` 引用锚定**（hypit "structural span, no timeline drag"）：事件/镜头引用段落 id 而非绝对秒数，结构重排时锚点自动跟随；`@{id}词@{/id}` 行内词锚已实现（P2，见 §9）：`<line>` 段落台词里绑定具体词，时间为词流的派生数据
- **派生状态不落盘**：`applied`（= `replace_with` 非空）与段落→锚点联动（= keep=true 且 during 指向该段落）都在解析端重导出。文档是唯一真相源：手改 `replace-with`、删一行 `<caption>`、加一行 `<sfx>` 直接生效——hypit "swap = 改几行"的数据层等价物
- **normalize 兜底 + 结构性显式报错**：数字/布尔容忍、未知子元素忽略（向前兼容未来语法位）；根元素/语法版本/文档 kind 不符、未知槽位或事件类型（含 hypit 原生词汇，如 `kind="host"`）、重复/缺失 id 一律 422（`error_type: adreplica_parse`）——静默降级禁止
- **端点**：`POST /api/v1/replica/blueprint/export`（蓝图→文本+建议文件名）、`POST /api/v1/replica/blueprint/import`（文本→蓝图，响应与 `/blueprint` 同形，返回的 blueprint 可直接 patch 回 replica 节点完成回写闭环）
- **刻意边界**：不导出 hypit 原生 `.svml`（修改版 Apache-2.0 + provider 焊死词汇表，见调研档 §2.2/§6.1）；`instantiated_script_node_id` 属画布运行时状态，不进文档（导入后复位为 null）
- **测试**：`tests/test_replica_adreplica.py` +26（语法形态/往返锁定/文本幂等/XML 逃逸/结构拒绝/normalize 兜底/手改重编译/端点契约/报告→蓝图→导出→手改→导入全链闭环）；开发中测试抓住两处设计失真并已修正：相对 `dur` 丢失镜头绝对起点（补 `start` 属性）、手改替换值后 `applied` 仍为 false（改为派生）

## 8. 已交付：前端流畅性与使用引导（2026-09-27）

**方法**：先调研（逐组件读 ReplicaTeardown / ReplicaBlueprintPanel / ReferenceVideoPanel 的交互与数据流）再优化；抓到的头号卡点不在 UI，而在**上传关卡**。

- **上传时长上限 10s→60s**（前后端同步）：参考片上传是共用入口，旧上限把 15-30s 的核心场景（调研档 P0 验收视频）挡在第一步；拆解成本由抽帧数决定而非时长，60s 与 teardown 上界对齐
- **拉片进行时可感知、可退出**：1-3 分钟的读片期间显示秒级已进行计时 + 阶段说明 + 「⏹ 取消等待」（AbortController；诚实提示后端可能仍在完成，可重新发起）；组件卸载自动断开
- **元数据透传**：teardown 返回的 `video_metadata` 不再被丢弃——真实时长 + 分辨率推导画幅（gcd 整数比，超 32 吸附常见画幅）进蓝图与 `.adreplica` 导出，报告头部可见（`12.0s · 9:16`）
- **下一步引导**：蓝图创建成功显示引导卡（打开 replica 节点 → 编辑槽位/锚点 → 生成工作流）；Reference 页 HOW IT WORKS 增补拉片复刻路径
- **工作台「源码 .adreplica」tab**：导出"生效内容"（含未保存编辑）→ 复制给 Agent/自己改 → 粘贴导入重编译 → 自动写回节点——文档即真相源的前端闭环
- **状态同步修复**：槽位/锚点编辑态改为内容签名同步——外部更新（导入重编译/协同 patch）面板跟得上，打字途中不被无关渲染清掉；配套两向锁定测试
- **未保存指示**：槽位/锚点有改动时保存按钮高亮加 ●
- **测试**：+9（Teardown 7→11、BlueprintPanel 5→10）；`check:quality` 通过（tsc/eslint 0 error；vitest 80 failed 为既有基线零新增）；`build` 通过；`perf:bundle` 失败为仓库级既有状态（core JS 2061 KiB vs 1281 KiB 限额，先于此工作已失败，本切片增量约 250 行同风格 JSX）

## 9. 已交付：词级锚定（whisperX "时间脊柱"，2026-09-27）

**闭环**：参考视频 → ffmpeg 抽音轨 → whisperX 词流 → 锚点事件绑定具体词 → `.adreplica` 行内 `@{id}词@{/id}`——hypit "改台词锚点跟随" 的数据层落地。

- **transcribe.py**（新增）：whisperX 懒加载可选依赖（与 scene3d `speech_alignment` 同款纪律）；降级显式可查询——`source="unavailable"` + 结构化原因（engine_disabled / no_audio_track / engine_unavailable / failed）写进报告 transcript 块与用户 constraints；默认关闭，`SPEECH_ALIGNMENT_ENGINE=whisperx` 启用
- **teardown 接线**：词流进综合拆解 prompt（时间脊柱），LLM 被要求逐段引用台词原文（`beats[].line`）并在系统条目点名触发词；`StructureBeat.line` 一路进蓝图
- **词锚解析**（`resolve_word_anchors`，确定性）：触发文本在所属段落窗内的词流拼接文本上子串匹配（字符→词边界映射），锚不出段落；字幕锚点未命中时兜底绑定整句台词；无词流原样返回（旧蓝图零影响）
- **`.adreplica` 行内锚**：beat 新增 `<line>` 子元素；词锚以 `@{id}词@{/id}` 行内表达；**时间为派生数据不落盘**（词文本是绑定，时间跨度由词流解析——与 hypit "文档存词、编译对时"同构）；词不在台词里时 `word` 属性兜底；幽灵锚（引用未声明事件）显式报错
- **schema**（加法、向后兼容）：`ReplicaAnchorEventV2` += `word/word_start_seconds/word_end_seconds`；`ReplicaBeatV2` += `line`；前端类型同步
- **前端**：报告转录徽标（`词级转录 N 句`）+ 段落台词原文展示；工作台锚点词 chip（含时间或"待转录解析"）
- **测试**：后端 +22（transcribe 9 含真实 ffmpeg 抽轨 media 测试；teardown 3；blueprint 6；adreplica 4）

## 10. 已交付：路线图收尾——实例化扩展 / 风格导演 / 链接下载 / 直出可行性门（2026-09-27）

- **实例化扩展**：`/replica/instantiate` 三步生命周期——创建 script 节点 → **自动创建 replica→script 绑定**（`text_context`，响应含 `binding_id`）→ **写回 `instantiated_script_node_id`**（指针进单一真相源）；前端 notice 同步。storyboard/image 节点组的创建仍由既有生成流承担（蓝图不携带像素源，诚实不编造 9 格 storyboard 合同）
- **风格导演/变体引擎**（Jev 式，确定性实现）：`variants.py` 扫描真实风格库（37 Skill）→ CJK 二元组+拉丁词打分 → 单风格排名推荐 / 组合加权随机（seed 可复现）；`/replica/blueprint/style-variants` + 工作台「🎲 风格推荐」picker（组合候选标注不可应用——多风格激活未支持，调研档 §5 风险 4）
- **链接下载**：`/replica/ingest-link`——yt-dlp 下载后走**与本地上传同一套校验/存储**（≤60s/抽帧/asset_id），链接不是旁路；四条结构化降级（ytdlp_missing / download_failed / invalid_url / invalid_download_*）；前端拉片入口加链接行（无上传可用）
- **direct-execute 可行性门**：`/replica/blueprint/direct-execute-plan`——确定性分类零模型费环节（纯屏上文字镜头/音效/音乐库/剪辑）与必须生成环节（动作镜头/TTS/已应用主体），`feasible` 门 + 成本清单喂给既有工作流。**边界**：直出渲染器属剪辑域（ADR 0008），不建第二执行链
- **测试**：后端 +31、前端 +4；replica 全套 110 passed
- **direct-execute 收尾四件（同日追加，C'→A→F→B→D 顺序）**：占位画面（needs_placeholder_video → 渲染器自动补纯色 clip，`__placeholder_video__` 溯源）；纯字幕样片 `sample_caption_only.mp4` + E2E「7.5 渲染验收」步（成片落盘，LLM 429 时拆解显式降级为地面真值 fixture）；库素材人解析（render 响应 `unresolved_assets` + `/blueprint/direct-execute/resolve-library` 回填端点，自动匹配 v2）；变体重编译计划端点（`/blueprint/variant-render-plans`，前 2 个代表携带时间线）。E2E 抓到并修复第四个真实缺陷：`ck_agent_canvas_nodes_type` 漏 replica（迁移 20260927_01）。E2E 11 步全通，replica 全套 147 passed
- **源码 tab 增强 + ADR 0010**（同日追加）：`ReplicaSourceEditor.tsx`（四类词汇表着色 underlay 编辑器 + 行内锚点击）、锚点行「📍 源码定位」反向跳转；direct-execute 渲染器归属剪辑域的决策与分期见 [ADR 0010](../adr/0010-direct-execute-renderer-in-editing-domain.md)

## 11. 已知限制与后续迭代（对齐调研档 P2/P3）

| 优先级 | 方向 | 说明 |
|---|---|---|
| P2 | WhisperX 词级对齐 | **已交付（见 §9）**：whisperX 词流 → 锚点事件绑定具体词 → `.adreplica` 行内 `@{id}词@{/id}`；启用 `SPEECH_ALIGNMENT_ENGINE=whisperx` + 安装 whisperx |
| P2 | `.adreplica` 源码编辑器增强 | **已交付（2026-09-27）**：原位高亮编辑（四类词汇表着色 underlay 编辑器）+ 行内锚↔锚点行双向跳转；导出/导入重编译闭环此前已就绪 |
| P2 | 实例化扩展 | **已交付（见 §10）**：绑定自动创建 + 指针写回；storyboard/image 节点组由既有生成流承接 |
| P2 | 风格混搭变体引擎 | **已交付（见 §10）**：确定性风格导演 + 单风格应用；多风格一键混搭应用待"多风格并行激活"改造（调研 §5 风险 4） |
| P3 | 参考片链接下载 | **已交付（见 §10）**；yt-dlp 未安装时显式降级提示 |
| P3 | direct-execute 快车道 | **R1+R3 已交付（见 §10 与 §13）**：可行性门 → 编译 → 渲染桥（`/replica/blueprint/direct-execute/render` 写进工作流 final 时间线并复用剪辑域 `start_render`）→ 工作台「⚡ 零模型费直出」入口 + 轮询 + 成片预览；ADR 0010 Partially Accepted——R2（MG 组件）仍待剪辑域排期 |
| P3 | R2 MG 组件直出 | 未启动：`screen_overlay`/MG 类组件的编译目标与素材来源未定（ADR 0010 R2，待剪辑域排期） |
| P2 | karaoke cue 模型 / narrative token 层 / `.adrecipe` | 未启动：hypit 差距分析（`replica-hypit-gap-analysis.md`）的 P1 主项（token 层）与 P2（caption 语义/可见时间分离、recipes 维度表）——按完成度研究（`replica-completion-research.md`）优先级排在 R3 之后 |

## 12. 测试与验证

- 后端：`tests/test_replica_teardown.py` **15 passed**（LLM 边界整体 monkeypatch，无网络/无 ffmpeg 依赖）；`app.api.v1.router` 导入通过；全量套件 1738 passed（5 个失败为沙箱预存环境问题：缺 torch/ffmpeg，与本次无关）；ruff 默认规则集（E4/E7/E9/F）0 error
- 前端：`ReplicaTeardown.test.tsx` **5 passed**；`tsc --noEmit` 0 error；eslint 0 error
- 前端画布目录全量：622 passed / 16 failed（失败集中于工作树在途改动 `AgentCanvasNode*`，与本次无关）

## 13. 已交付：R3 渲染桥 + 工作台直出入口 + G7 音频渲染测试（2026-09-28）

**闭环**：复刻蓝图（replica 节点）→ 工作台「⚡ 零模型费直出」→ 可行性门 → 编译
→ 写进工作流 final-composition 时间线 → 复用剪辑域 `start_render` 耐久渲染 →
轮询 → 成片预览。此前"后端编译→渲染→占位→解析全通"但用户无入口、渲染只是
进程内验收（完成度研究 G1）；本节把最后一公里接上。

- **渲染桥**（`services/replica/direct_execute_bridge.py`，纯编排、服务注入）：
  门 → 编译 → 可选 `library_resolutions` 回填 → **剥未解析哨兵 clip**（哨兵不是
  真实资产，写进 v2 时间线会被 `_validate_clip_source` 404 拒；被剥 clip id 随
  响应透出）→ `save_timeline`（`expected_version` 取自当前时间线）→ `start_render`。
  **不建第二执行链**（ADR 0010）。
- **端点**：`POST /replica/blueprint/direct-execute/render`——非可行返回 422 +
  `rejected` 缺失清单（不渲染）；时间线服务错误按 v2 约定映射（code/message）；
  响应透出 `previous_timeline_version`（写盘替换用户此前的 final 时间线，不隐瞒）。
- **前端**：`ReplicaBlueprintPanel` 源码 tab 顶部直出区——发起前先落盘（节点是
  真相源）；409/422 拒绝清单逐条展示；轮询 `/api/v2/workflows/{id}/final-
  composition/renders/{render_id}`（卸载停、~5 分钟超时明确失败）；成片 `<video>`
  预览；替换版本与未解析库素材两件事以备注说出口。
- **G7（抓到真 bug）**：补 `test_resolved_bgm_renders_real_audio_into_final_video`
  （真实音频资产 → resolve-library → 渲染 → 断言成片有音轨；无 ffmpeg 环境 skip）。
  静态核查该路径时发现：剪辑域 `build_audio_filter_graph` 按 `metadata.role`
  识别 BGM，而编译层的 BGM/SFX 意图 clip 没打 role——bgm_only 模式下 BGM 会被
  音频图静默跳过（"启用 BGM"只在文本上成立）。已修编译层（`role: bgm/sfx`），
  并补两条常驻守护：role 标记断言 + 音频图集成断言（后者不依赖 ffmpeg，处处可跑）。
- **测试**：后端 +14（桥 11 含端点契约 5、render role 1、音频图 1、media 1）；
  replica 全套 **146 collected**（本机无 ffmpeg：140 passed / 6 skipped，skip 全为
  media 与 transcribe 的 ffmpeg 依赖项；有 ffmpeg 的机器上全跑）；  `ruff`（E4/E7/E9/F）全绿；`check:agent-canvas-contract` 对导出 OpenAPI 通过
  （185 paths）；全量后端 1968 passed（4 失败 = depth-image 既有基线，零新增）。
  前端 +2（桥端点请求体/成片预览/门拒绝清单）；`ReplicaBlueprintPanel` 17 passed；
  tsc/eslint 0 error；canvas 目录全量零新增失败（既有基线 AgentCanvasNode 15 /
  Picker 1）。
- **E2E 跟进（未做，诚实记录）**：`replica_e2e_run.py` 尚未加"渲染桥"步（HTTP 调
  `/replica/blueprint/direct-execute/render` → 断言 render_id → 轮询到终态）。本
  增量开发环境无 ffmpeg/后端服务/LLM 额度，按"未跑过不写已验证"的纪律留到完整
  栈机器上补；端点逻辑已由 11 条单测（含 dependency_overrides 契约测试）覆盖。

## 14. 已交付：G3 字幕语义/可见时间分离 + handoff（hypit caption-fine 移植，2026-09-28）

**动机**：完成度研究 G3——cue 模型只有行级 + 0.4s 合并，显示时间与口播时间混为
一谈；hypit `scheduleFineCaption` 的标准形态是语义窗（口播，神圣不可动）与可见
窗（lead/tail 加宽 + handoff 裁切）分离。

- **schema（加法）**：`WorkflowV2TimelineSubtitleStyle` += `lead_seconds`/
  `tail_seconds`/`handoff`（cut/overlap），默认 0/0/overlap——旧时间线与编辑器
  手排 clip 逐字节不变；前端 `V2TimelineSubtitleStyle` 镜像同步（可选字段）。
- **`schedule_caption_cues`**（纯函数）：可见窗 = 语义窗 ± lead/tail，钳
  `[0, total]`；同轨相邻 cue 且 cut：前可见尾裁到不超过后语义起点（≥自己的
  语义尾），后可见头推到不早于裁点（≤自己的语义起点）。**语义窗一律不动**。
  跨轨不交接（hypit 按 role 分组；单条 subtitle 轨的对应物是同轨）。
- **编译层默认**：复刻 cue 0.1s lead / 0.2s tail / cut。0.4s 合并不闪跳规则
  保留（合并防"闪"、handoff 防"抢"，两者并存——hypit 不合并是其台词语句
  形态差异，中文短句连读下合并是可读性规则）。
- **渲染器**：`_subtitle_filter` 的 drawtext `enable` 窗读 clip metadata
  `visible_start_seconds`/`visible_end_seconds`（缺失回落 clip 窗）——调度
  真的改变成片，不是文本上的成立。
- **词级 karaoke（下一片，边界已明）**：v2 路径每 cue 一个 drawtext，无法
  同元素逐词换色；ASS writer 的 cue 模型无词级时间。需要：蓝图侧词流保留
  （`ReplicaBeatV2` 词列，schema 加法）+ ASS `{\k}` 发射 + 媒体验收。
- **测试**：+9（见 CHANGELOG 顶部条目）；replica 全套 167 passed / 3 skip
  （skip = 本机无 ffmpeg）；契约检查 185 paths 通过（style +3 字段）。

## 15. 已交付：G6 teardown 拆解缓存（2026-09-28）

**动机**：完成度研究 G6——同一 asset 重复拆解每次全量重付 LLM 费用（N+1 次
多模态调用），429 时只能 fixture 降级。

- **键**（`teardown_cache.py`，纯函数）：schema 版本 + 视频内容 sha256 +
  num_frames + user_description（归一化）+ 模型名 + 转录 (source, reason)。
  内容 hash 而非 asset_id——同一资产重上传/替换字节都会换键；参数/模型/
  转录状态任何变化都换键（缓存能造的最坏事故是张冠李戴，结构上排除）。
- **只缓存完整成功的分析**；失败/校验失败不写盘。命中跳过抽帧 + 全部 LLM。
- **诚实边界**：命中在 `report.constraints` 追加可见标注（只进内存、不回写，
  不叠加）；`cached`/`cache_key` 透出到端点与前端徽标；损坏/漂移/键不匹配
  一律按 miss 并自愈重写。whisperx 启用时命中仍先跑转录（键精确性优先），
  引擎默认关闭时零成本。
- **端点**：`use_cache`（默认 true，false 强制重算）。E2E 第二次起命中。
- **测试抓到的真耦合**：默认缓存目录是共享 media_data_dir——不隔离的话同
  会话先跑的测试写缓存、后跑的测试命中，"LLM 失败应抛出"被缓存命中悄悄
  抵消。既有 fixture 已加 tmp 缓存目录隔离（教训：有状态优化的默认值必须
  在测试里显式隔离）。

## 16. G3 后半：词级数据层落地 + 一条死路的证伪（2026-09-28）

- **数据层**：`ReplicaBeatV2.words`（词面 + 转录实测时间）；`resolve_word_anchors`
  按段落窗归集，单归宿规则 `[start, end)`（边界词不双算）。工作台锚点 tab
  展示段落词流（"时间脊柱"对人可见）。
- **证伪的死路（记录决策，比留死代码有价值）**：direct-execute 编译层做逐词
  cue 在结构上不成立——可行性门规定有台词的 beat 必须 TTS（生成步骤），而
  词级对齐内容只随台词存在：零模型费通道里没有词级对齐内容可渲染。三处
  尝试性改动（style 字段/逐词 cue/渲染器定位）已全部撤回。
- **词级 karaoke 的真实归属（后续片，前提已明）**：① 生成通道——TTS 落音
  后词窗与口播对齐（蓝图 `words` 即其数据源，本轮已备好）；② 剪辑域 ASS
  writer（`timeline_subtitle_writer.cues_to_ass`）发射 `{\k}` 高亮——需要
  cue 模型带词级时间（`SubtitleCue` 当前无此字段），是编辑域 schema 的
  加法变更。两条都未启动，不做浑水摸鱼的中间态。

## 17. 已交付：G4 narrative token 层——锚定从时间上移到授权序（hypit P1 主项，2026-09-28）

- **`narrative.py`（纯函数层）**：normalize + tokenize（CJK 字符级/拉丁词级）+
  Narrative（segments/tokens）+ 6 种 anchor（program/segment/token 起止）+
  selection（anchor 对 → token 区间，不查时间线）+ 投影（token 区间 → 秒数）。
- **接线**：锚点 += `start_token_id`/`end_token_id`；`resolve_word_anchors`
  记录 binding；`reproject_anchor_seconds` 把秒数降级为投影；teardown 全链
  以它做不变量强制。
- **实现中修掉的真缺陷**：token 源"词流优先"造成解析/重投影两套 id 空间，
  binding 必丢——改为 token 只来自授权文本（line），词流仅作对齐源
  （hypit Script↔media 模型）。纯字幕片（无 line）不进授权序，走兼容路径。
- **标志性性质（测试锁定）**：秒数全改脏 → selection 不变；重配音后 binding
  存活、秒数重投影；投不出时间 → 清除绑定（不保留过期秒数）。
- **边界**：token id 不进 `.adreplica`（派生数据）；reproject 的生产触发
  （"重新对齐"入口）留给生成通道/TTS 片——语义与纯函数本增量已交付。
