# 拉片复刻完成度研究（2026-09-28）

> 方法：代码级盘点当前仓库的真实状态（`apps/api/app/services/replica/*` 9 个服务
> 3171 行、11 条 POST 路由、10 个测试文件 132 条用例；前端 `Replica*` 4 组件 2521 行；
> `e2e_output/replica_e2e/` E2E 11 步运行记录），对照路线图（`replica-teardown.md`
> §11）、ADR 0010 与 hypit 差距分析（`replica-hypit-gap-analysis.md`）。
> 本文回答三个问题：**现在到底有什么、缺什么、下一步先做什么。**

> **2026-09-28 晚更新（R3 增量已落地，逐条核对后）**：**G1 已闭合**——渲染桥
> `POST /replica/blueprint/direct-execute/render` + 工作台「⚡ 零模型费直出」+
> 轮询 + 成片预览均已交付并通过测试（详见 CHANGELOG 顶部条目与
> `replica-teardown.md` §13）；**G7 已闭合**——补了"resolve-library→渲染→成片
> 有音轨"的 media 测试，且静态核查抓到并修掉一个真 bug（BGM/SFX 意图 clip 缺
> `role` 标记，bgm_only 模式下被音频图静默跳过）；**G2 已修**（§11 路线表与
> ADR 0010 同步）；**G3 的语义/可见时间分离 + handoff 已闭合**（schema +3 字段、
> `schedule_caption_cues` 纯函数、渲染器 visible 窗落地；词级 karaoke 烧录作为
> 下一片，边界已明——需要蓝图词流保留 + ASS `{\k}`）。仍开放：词级 karaoke、
> G4 narrative token 层、G5 `.adrecipe`、G6 teardown 缓存。下文矩阵与缺口清单
> 为当日快照，保留作历史记录。

> **2026-09-28 第五更（G5 增量）**：**G5 `.adrecipe` 已闭合**——六维词汇表（与样式 schema 同口径）+ `.adrecipe` 文档层 + 5 个内置配方 + 变体 = skill × recipe（确定性轮换）+ 编译层真实消费 + 工作台点选器；代表变体的字幕样式签名互不相同（测试断言）。至此 gap 分析的 P1 主项/normalized/P2 cue 时间/P2 recipes **全部落地**；仍开放：P3 fact log、P3 swap 骨架恒等断言、P4 estimate 语音时长预估、词级 karaoke 烧录（生成通道 + ASS `{\k}`）、G4 的"重新对齐"生产触发点。

> **2026-09-28 第四更（G4 增量）**：**G4 narrative token 层已闭合**——`services/replica/narrative.py`（normalize/tokenize/6 种 anchor/selection 与帧时间解耦/投影）+ 锚点 token 区间绑定 + `reproject_anchor_seconds`（秒数降级为投影）；实现中修掉"token 源不一致导致 binding 必丢"的真缺陷。至此 gap 分析的 P1 主项落地；仍开放：**G5 `.adrecipe`**（风格维度表）、P1 子项 normalized匹配已随 narrative 落地、词级 karaoke 烧录（生成通道 + ASS `{\k}`）、G4 的"重新对齐"生产触发点。

> **2026-09-28 第三更（G3 后半增量）**：**词级数据层已闭合**——`ReplicaBeatV2.words`（转录词窗，单归宿归属）+ 工作台词流展示；**词级 karaoke 在零模型通道被证伪**（有台词必 TTS → 不可行，通道内不存在词级对齐内容），死分支已撤、决策已记录（`replica-teardown.md` §16）；karaoke 真实归属 = 生成通道 + 剪辑域 ASS `{\k}`（需 `SubtitleCue` 词级时间，后续片）。仍开放：G4 narrative token 层、G5 `.adrecipe`。

> **2026-09-28 深夜更新（G6 增量）**：**G6 已闭合**——teardown 拆解缓存（内容 hash + 参数 + 模型 + 转录状态派生键，命中跳过全部 LLM，损坏按 miss 自愈），端点 `use_cache` 开关 + `cached`/`cache_key` 溯源 + 前端徽标；**G3 的语义/可见时间分离也已闭合**（见 CHANGELOG）。仍开放：词级 karaoke 烧录（G3 后半，需 ASS `{\k}` + 蓝图词流保留）、G4 narrative token 层、G5 `.adrecipe`。下文为当日快照。## 1. 完成度矩阵

| 子系统 | 状态 | 证据 |
|---|---|---|
| 拆解（teardown：抽帧→多模态 LLM→综合报告） | ✅ | `teardown.py`（716 行）；E2E 步 2 真实跑通 4 次（74-97s）；LLM 429 时显式降级地面真值 fixture |
| 词级转录（whisperX） | ✅（默认关闭） | `transcribe.py`（263 行）；`SPEECH_ALIGNMENT_ENGINE=whisperx` 启用；四条降级路径显式 |
| 复刻蓝图（槽位/锚点/词解析） | ✅ | `blueprint.py`（611 行）；affinity（left/right 吸收）已进词匹配与序列化 |
| `.adreplica` 文档层 | ✅ | `adreplica.py`（564 行）；行内 `@{id}词@{/id}` + `affinity` 属性 + 往返锁定 |
| 风格导演/变体 | ✅ | `variants.py`（295 行）；37 Skill 打分混搭；变体重编译计划端点 |
| 链接下载 | ✅ | `ingest.py`；yt-dlp 显式降级 |
| 直出可行性门 | ✅ | `direct_execute.py`（114 行） |
| **R1 编译层（字幕轨时间线）** | ✅ | `direct_execute_render.py`（443 行）：词窗优先 cue、合并、BGM/SFX 意图 clip、unresolved 透出 |
| **R1 渲染（剪辑域）** | ✅ | `V2FinalCompositionRenderer`：`needs_placeholder_video` → 自动纯色占位 clip；E2E 步 7.5 成片落盘（2.6s）；media 测试 2 条 |
| **库素材解析** | ⚠️ v1 | 人工回填端点通（`resolve-library`）；**无渲染侧 media 测试**（启用 BGM 需真实音频资产）；自动匹配未做 |
| **R3 用户入口（工作台直出按钮/成片预览）** | ❌ | `apps/web` 对 direct-execute 端点**零引用**（grep 证实）；工作台 4 tab（槽位/锚点/镜头/源码）无渲染入口 |
| **工作流桥接（时间线保存 → start_render）** | ❌ | E2E 步 7.5 是进程内渲染器验收；复刻时间线进工作流 final-composition 的保存桥未建 |
| 变体 × 渲染计划 | ✅（计划层） | `/blueprint/variant-render-plans`（前 2 代表携带时间线）；但变体间无真实样式差异（见缺口 G5） |
| 实例化/绑定/指针 | ✅ | E2E 步 10-11 校验通过；迁移 `20260927_01` 补 replica CHECK |

测试基线：replica 套件 132 条（含 2 条真实 ffmpeg 渲染 media 测试）；ruff 0 error；
`check:agent-canvas-contract` 通过。

## 2. 自上次研究（2026-09-27）以来的变化

1. **affinity 落地**（hypit 差距分析 P1 子项）：`.adreplica` 事件序列化带 `affinity`
   属性（默认 right 省略），`_match_word_span` 按 left/right 吸收语义取词窗端点——
   词锚边界歧义已按 hypit 语义解决；
2. **R1 渲染全链落盘**：编译端点、占位画面、resolve-library、变体重编译计划、
   `ck_agent_canvas_nodes_type` 迁移（20260927_01）——渲染器侧从"待排期"变为
   "已实现并 E2E 验收"；
3. **E2E 固化为 12 步**（含渲染验收 + 429 降级 fixture），样例库 4 件（多镜头广告/
   纯字幕/商品图/人物图）+ 手写 `.adreplica`。

## 3. 缺口清单（按用户价值排序）

**G1 · 最后一公里：用户入口 + 工作流桥接（最大缺口）**
后端编译→渲染→占位→解析全通，但用户在 UI 上无任何入口；且 E2E 的渲染是进程内
验收，正式链路缺"复刻时间线写回工作流 final-composition → `start_render` → 轮询
状态 → 取成片"的保存桥。这是 R3 的后端半边 + 前端半边，也是唯一挡住"用户真正
用上直出"的事。
**建议拆法**：① 后端桥（`POST /workflows/{id}/final-composition/replica-render`：
编译时间线写入 timeline service → 复用 `start_render`）；② 工作台源码 tab 旁加
「零模型费直出」按钮（仅 `feasible=true` 可点）+ 渲染状态轮询 + 成片预览。

**G2 · 文档腐化（最低成本，先修）**
`replica-teardown.md` §11 路线表 P3 行仍写"可行性门已交付…待排期"——落后实现
两拍（R1/占位/解析/变体计划均已落地）。"文档即真相源"原则下，下一次接手的人会
被误导。5 分钟修复 + ADR 0010 状态行同步。

**G3 · 词级 karaoke（P2，素材已齐）**
词级 transcript + affinity 都在，但 cue 模型只有行级 + 0.4s 合并；缺
`lead/tail/handoff` 语义/可见时间分离与词级可见窗（hypit caption-fine 的标准
形态）。`WorkflowV2TimelineSubtitleStyle` schema（font_size/color/position）需要
扩展。

**G4 · narrative token 层未启动（P1 主项，最大件）**
锚点仍锚在"词文本 + 已解析秒"；token 序列/6 种 anchor/selection 区间语义未建。
重转写/改词后的锚点存活依赖文本匹配而非结构保证。

**G5 · 变体无样式差异**
`.adrecipe` 风格维度表未启动：变体重编译计划之间除 style 槽位值外完全相同
（R1 字幕样式硬编码 42/白/底部）。变体审片的"看得见差异"依赖此项。

**G6 · teardown 无缓存（LLM 额度强依赖）**
同一 asset 重复拆解每次全量重付 LLM 费用；429 时只能 fixture 降级。按
asset+content hash 缓存拆解报告可省额度且加速 E2E。

**G7 · resolve→渲染音频路径无测试**
resolve-library 启用 BGM 后的渲染需要真实音频资产文件——现有 media 测试只覆盖
占位画面 + 字幕（BGM clip 保持 disabled）。补一条带真实音频资产的渲染 media 测试。

## 4. 优先级建议

1. **G2 文档修复**（5 分钟，先做——防误导）；
2. **G1 R3 用户入口 + 工作流桥接**（最大价值：把已建成的后端能力交到用户手上）；
3. **G7 音频渲染 media 测试**（随 G1 一起，锁 resolve→渲染链）；
4. **G3 karaoke cue 模型**（词级素材已齐，schema 扩展 + 纯函数）；
5. **G6 teardown 缓存**（省额度，E2E 提速）；
6. **G4 narrative token 层 / G5 .adrecipe**（大件，等 G1 落地后按 hypit 差距分析
   的设计推进）。

## 5. 与 hypit 差距分析的映射更新

| 差距分析项 | 状态 |
|---|---|
| P1 子项：亲和边界（left/right 吸收） | ✅ 并行会话已落地（adreplica 序列化 + 匹配） |
| P1 主项：narrative token 层 | 未启动 |
| P1 子项：normalized 匹配 | 未启动（现为原始子串匹配） |
| P2：语义/可见时间分离 + handoff | 未启动（schema 无 lead/tail） |
| P2：recipes/.adrecipe | 未启动 |
| P3：fact log | 部分（渲染有 state；编译/解析无账本） |
| P3：swap 骨架恒等断言 | 未启动（半天工作量） |
