# 拉片复刻 vs hypit 代码级对照：改进方向

> 方法：不靠调研文档转述，直接读 hypit 一手源码（`D:\project\hypit\hypit-main`，
> packages/narrative、core、caption-fine、markup、whisperx、estimate 等），逐机制
> 对照本仓库现状（`apps/api/app/services/replica/*`），给出有证据的改进方向与优先级。
> 关联：`docs/plans/replica-teardown.md`、`docs/adr/0010`、`docs/plans/hypit-replica-research.md`。

## 1. 一手证据清单（已读代码）

| hypit 位置 | 机制 |
|---|---|
| `packages/narrative/src/types.ts` | NarrativeToken（id/segmentId/startAnchorId/endAnchorId/text/**normalized**）、NarrativeTurn（role + token 区间）、Anchor 6 种 kind |
| `packages/narrative/src/selection.ts` | **selection = 两个 anchor 间的 token 区间**，"independent of material placement and frame timing"；`narrativeTokensForSelection` 不查时间线 |
| `packages/caption-fine/src/schedule.ts` | 语义帧 vs 可见帧分离（leadFrames/tailFrames 加宽可见窗）、同角色 `cut` handoff 裁切、Use 窗口可见性掩码 |
| `examples/podcast/recipes.svs` | 风格 = 语义维度 token 集（framing/edit-language/pacing/performance/reaction/gesture） |
| `packages/core/src/machine.ts` | BuildMachine：Definition+Facts 持久、机器是临时视图、evaluate→持久→commit 两段提交 |
| `packages/whisperx/src/manifest.ts` | 词对齐用 **normalized** 授权词 vs 同步媒体，产出 local frame anchors |
| `docs/quickstart/script.md` | 亲和锚语法精确语义：`@{id}` 右吸收 / `@{~id}` 左吸收 / `@{/id~}` 右吸收闭合 / `@{id!}` Moment 点锚；`||` = Caption Cue Break；`<spoken\|display>` N:M 对齐单元；标记不产文本不产空格 |
| `examples/podcast/swap-host.svml` | swap 与 reference 的 diff = 346 行，但**骨架（轨道/段落/锚点拓扑）不变**，变的是说话人/文本/配方引用 |

## 2. 机制对照与改进方向

### P1 · Narrative token 层：把"锚定在词上"升级为"锚定在授权序上"

**hypit 机制**：每个词是一个 token（带授权顺序、所属 segment、前后 anchor id、`normalized` 拼写）；selection 是 anchor 对之间的 **token 区间**，与帧时间解耦——时间只是投影。改台词/重转写/重配音后 selection 天然存活。

**我们现状**：beats 存绝对秒；锚点事件存词文本 + 已解析秒数（`resolve_word_anchors` 从词流拼接文本做子串匹配，`direct_execute_render.py` 的 cue 用词窗优先）。时间与锚定耦合：重转写后锚点要重新解析，且子串匹配对重复子串脆弱。

**改进方向（P1）**：在复刻域新增 `narrative.py`——beats/lines → token 序列（含 `normalized`）+ 6 种 anchor；锚点事件改引用 **token 区间**；时间（transcript 词流）降级为**投影**（可重算），`.adreplica` 的 `<line>` 文本仍是授权真相源（向后兼容：无 token 层的旧文档照常解析）。这一步把"改一句台词全片重排"从口号变成结构保证。

**P1 子项（同批）**：
- **亲和边界语义**：采用 `@{id}`/`@{~id}`/`@{/id}`/`@{/id~}` 吸收规则 + `@{id!}` **Moment 点锚**（我们目前表达不了"第 3 秒落版"这种点事件）。`.adreplica` 解析器（`adreplica.py`）与 `resolve_word_anchors` 同步升级。
- **normalized 匹配**：词对齐用规范化文本（去标点/大小写/空白），替换脆弱的原始子串匹配。

### P2 · 字幕的语义/可见时间分离 + handoff

**hypit 机制**：`scheduleFineCaption` 把 cue 分成语义窗（口播时间，神圣不可动）与可见窗（`leadFrames`/`tailFrames` 样式参数加宽）；同角色相邻 cue 用 `handoff: "cut"` 裁前一条可见尾、不切口播时间。

**我们现状**：`_merge_adjacent_cues` 用 0.4s 间隔合并、clamp 到内容末端——显示时间与口播时间混为一谈，没有样式化的提前/延后。

**改进方向（P2）**：`direct_execute_render.py` 的 cue 模型加 `lead/tail/handoff` 三参数（纯函数，正是我们编译层的风格）；顺手打通**词级 karaoke**——我们已有词级 transcript（`transcribe.py`），hypit 证明这是 caption-fine 的标准形态。

### P2 · recipes 风格维度表 → `.adrecipe`

**hypit 机制**：风格不是整包 skill，而是**语义维度 token 集**（framing/pacing/performance/…），组件按名引用。

**我们现状**：`variants.py` 只挑整包 skill_id；R1 字幕样式硬编码（42/白/底部）；D 端点的变体渲染计划除槽位外无真实差异。

**改进方向（P2）**：为 direct-execute 引入一个小维度词汇表（字幕族：font/color/position/lead/tail/handoff；后续 motion 预设），落成 `.adrecipe` 文件（调研档 §3.5 本来就规划了这个家族成员）；`variants.py` 的变体 = skill × recipe 组合——变体渲染计划从此有真实的样式差异。

### P3 · 直出链的 fact log（事件溯源）

**hypit 机制**：BuildMachine——Definition+Facts 持久化、机器是临时视图、`evaluate()`（验证）与 `commit()`（确认持久化后）两段提交；重放 facts 即恢复状态。这就是"失败不重复花钱"的实现方式。

**我们现状**：渲染服务有 render state，但编译/解析/回填是即时的、无账本。

**改进方向（P3）**：直出链追加 fact log（plan_compiled / clip_resolved / render_completed 三种 fact 起步），崩溃恢复 + 审计 + 省钱语义。中等工作量，先只覆盖渲染与解析两步。

### P3 · swap 骨架恒等断言（最便宜的先做）

**hypit 机制**：swap 与 reference 的 diff 346 行，但轨道/段落/锚点**拓扑恒等**。

**我们现状**：D 端点变体重编译后没有任何"复刻关系未破坏"的检查。

**改进方向（P3，半天）**：写 `assert_same_structure(a, b)`——比较两份 `.adreplica` 的轨道/段落/镜头骨架，仅允许槽位/风格字段差异；挂进变体渲染计划端点与导入路径。把"复刻结构不复刻像素"变成可执行断言。

### P4 · estimate 语音时长预估 / N:M 双文本 / 发音对

- `packages/estimate`：TTS 前按语言/语速预估口播时长——我们的可行性门可加"台词预估时长 vs 段落窗"校验（零成本预检）。
- `<spoken|display>` N:M 对齐单元与 `<2012 | twenty twelve>` 发音对：TTS 阶段（R2+）的输入形态，记录待用。

### 公平对照：我们已有、hypit 没有的

真实 E2E + media 级测试纪律、多 provider 抽象（hypit 把 provider 焊在包名里）、显式降级纪律（§4）、画布/资产库集成。这些不追。

## 3. 落地映射（改我们哪些文件）

| 方向 | 我们的位置 |
|---|---|
| P1 token 层 | 新增 `services/replica/narrative.py`；`adreplica.py` 行内锚 v2；`blueprint.py` 锚点事件引用 token 区间 |
| P2 cue 时间 | `direct_execute_render.py` cue 模型 + 样式参数 |
| P2 recipes | 新增 `.adrecipe` 读取；`variants.py` 变体=skill×recipe；渲染计划携带样式参数 |
| P3 fact log | 渲染服务 + resolve 流程 |
| P3 骨架断言 | `adreplica.py` 或新 util + 变体端点挂断言 |

## 4. 不抄清单（防语言蔓延）

- hypit 的 provider 专属包（gpt-image/seedance/fishaudio…包名即厂商）——我们走角色契约；
- Studio Companion 全套投影机制——我们画布即投影，无第二编辑器；
- 100+ 包的粒度——我们单仓分层，词汇表按 §3.4 封顶（每个新元素必须有编译目标）。

## 5. 落地状态更新（2026-09-28，与 CHANGELOG 对应）

| 差距分析项 | 状态 |
|---|---|
| P1 子项：亲和边界（left/right 吸收） | ✅ 已落地（adreplica 序列化 + 匹配） |
| P2：语义/可见时间分离 + handoff | ✅ **已交付（2026-09-28）**：`WorkflowV2TimelineSubtitleStyle` += lead_seconds/tail_seconds/handoff；`schedule_caption_cues` 语义窗不动、可见窗加宽钳位、同轨 cut 交接；渲染器 `_subtitle_filter` enable 窗读可见窗元数据。**词级可见窗/karaoke 未做**——v2 路径每 cue 一个 drawtext 无法逐词换色，ASS writer 无词级时间；下一片需蓝图词流保留 + ASS `{\k}`（见 `replica-teardown.md` §14） |
| P1 主项：narrative token 层 | 未启动 |
| P1 子项：normalized 匹配 | 未启动（现为原始子串匹配） |
| P2：recipes/.adrecipe | 未启动 |
| P3：fact log | 部分（渲染有 state；编译/解析无账本） |
| P3：swap 骨架恒等断言 | 未启动（半天工作量） |
