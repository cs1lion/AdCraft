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
- **源码 tab 增强 + ADR 0010**（同日追加）：`ReplicaSourceEditor.tsx`（四类词汇表着色 underlay 编辑器 + 行内锚点击）、锚点行「📍 源码定位」反向跳转；direct-execute 渲染器归属剪辑域的决策与分期见 [ADR 0010](../adr/0010-direct-execute-renderer-in-editing-domain.md)

## 11. 已知限制与后续迭代（对齐调研档 P2/P3）

| 优先级 | 方向 | 说明 |
|---|---|---|
| P2 | WhisperX 词级对齐 | **已交付（见 §9）**：whisperX 词流 → 锚点事件绑定具体词 → `.adreplica` 行内 `@{id}词@{/id}`；启用 `SPEECH_ALIGNMENT_ENGINE=whisperx` + 安装 whisperx |
| P2 | `.adreplica` 源码编辑器增强 | **已交付（2026-09-27）**：原位高亮编辑（四类词汇表着色 underlay 编辑器）+ 行内锚↔锚点行双向跳转；导出/导入重编译闭环此前已就绪 |
| P2 | 实例化扩展 | **已交付（见 §10）**：绑定自动创建 + 指针写回；storyboard/image 节点组由既有生成流承接 |
| P2 | 风格混搭变体引擎 | **已交付（见 §10）**：确定性风格导演 + 单风格应用；多风格一键混搭应用待"多风格并行激活"改造（调研 §5 风险 4） |
| P3 | 参考片链接下载 | **已交付（见 §10）**；yt-dlp 未安装时显式降级提示 |
| P3 | direct-execute 快车道 | **可行性门已交付（见 §10）**；渲染器归属与接口已决策——[ADR 0010](../adr/0010-direct-execute-renderer-in-editing-domain.md)（Proposed，待剪辑域确认排期） |

## 12. 测试与验证

- 后端：`tests/test_replica_teardown.py` **15 passed**（LLM 边界整体 monkeypatch，无网络/无 ffmpeg 依赖）；`app.api.v1.router` 导入通过；全量套件 1738 passed（5 个失败为沙箱预存环境问题：缺 torch/ffmpeg，与本次无关）；ruff 默认规则集（E4/E7/E9/F）0 error
- 前端：`ReplicaTeardown.test.tsx` **5 passed**；`tsc --noEmit` 0 error；eslint 0 error
- 前端画布目录全量：622 passed / 16 failed（失败集中于工作树在途改动 `AgentCanvasNode*`，与本次无关）
