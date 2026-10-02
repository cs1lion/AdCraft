# P5 前端失败基线治理 — 台账（2026-09-29）

> 对应 `last-hundred-meters-plan.md` P5："前端失败基线治理：80 条失败逐条定责
> （修 / 豁免+理由），此后新增失败 = 0"。
> 本文件是**逐文件定责台账**；单条用例级的修复排期见"下一步"列。

## 0. 基线变迁

| 时点 | failed | 文件数 | 说明 |
|---|---|---|---|
| 2026-09-28（计划 §2） | 80 | 15 | D/E 工作前的实测基线 |
| 2026-09-29 D/E 完成后 | 80 | 15 | 零新增（本阶段全部新测试绿） |
| 2026-09-29 P5 首批修复后 | **75** | **10** | 修 5 个文件（见 §1） |
| 2026-09-29 P5 二批（豁免转正+小批量）后 | **64** | **9** | 修 6 个文件/11 条，含一处真 bug |
| 2026-09-29 P5 中批量后 | **49** | **5** | 修 2 个文件/15 条，含 runtime 四机制恢复 |
| 2026-09-29 P5 大批量首批后 | **38** | **3** | 修 1 个文件/11 条，含 merge 丢失 CSS 恢复 |
| 2026-10-02 Item 系列合入 main 后 | **63**（62 持续 + 1 并行调度偶发） | **6** | Item 2/7 把 ReplicaBlueprintPanel 系 24 条新债带上 main，台账失真；本轮重新定责见 §5 |
| 2026-10-02 断奶补全后 | **39**（38 持续 + 1 并行调度偶发） | **4** | BlueprintPanel 系 24 条清零（修实现非修测试，见 §5 减账） |
| 2026-10-02 富参数工作台接线后 | **17**（16 持续 + 1 并行调度偶发） | **3** | InlineWorkbench 22 条清零（测试文件零改动，纯实现补齐，见 §6 减账） |

## 1. 已修（5 个文件 / 5 条）

| 文件 | 条数 | 根因 | 修法 | 提交 |
|---|---|---|---|---|
| `src/api/agentCanvasClient.test.ts` | 1 | frozen 连接策略契约要求全部 9 种节点类型，fixture 停在 6 种（漏 scene-3d/voice-cast/replica） | 按后端 `agent_canvas_connection_policy` 真实值补齐 `binding_kind_by_source_type` 与 `target_node_types` | 本批 |
| `src/pages/HomeStaticBackground.asset.test.ts` | 1 | **误删，已恢复（订正）**：本测试断言 package.json 不得含 `three`/`@types/three`（首页 Three.js 背景移除的有意留痕）。本批据此把 `three`/`@types/three`/`@react-three/*` 4 个包删除，理由写成"依赖忘删（src 零 import）"——**该理由是误判**：`SceneScript3DPreview.tsx`（实时 3D 预览，经 `SceneScript3DEditor`/`SceneScriptPanel` 上车）一直在 import 它们。且 `--package-lock-only` 不剪枝 node_modules、测试又 `vi.mock` 掉该组件 → 本地 tsc/vitest 全绿，**干净安装（npm ci）直接断链** | 恢复 4 个依赖（package.json + 锁还原至删除前状态）；测试改锁"依赖在场"（背景资产缺席由同文件第一条测试锁）；新增 `quality/mockedModuleDependencies.test.ts` 闸：被 vi.mock 的模块，其依赖不得从 package.json 删除 | 46ec7e14（删，误）→ 订正提交（恢复） |
| `src/features/agent-canvas/canvas/AgentCanvasNodePicker.test.tsx` | 1 | 规范节点类型扩到 9（复刻/3D/配音三线依赖），测试断言停在 6 | 更新为 9 种 + 新类型图标映射 + 标签"3D Previs" | 本批 |
| `src/pages/ProjectsPage.rename.test.tsx` | 1 | 测试硬编码 en-US 日期格式 "7/24/2026"，组件用浏览器默认 locale（zh-CN 下必挂） | 期望值改为与组件同一算法（locale 无关） | 本批 |
| `src/quality/agentCanvasRetiredRoutes.test.ts` | 1 | D7/E6 让 ReplicaBlueprintPanel 引用 final-composition 路由族，触犯"agent-canvas 不得引用退役路由"闸；同时闸的正则误伤产品文案里的术语 | ① 路径构造移到 `src/api/finalRenderPaths.ts`（路由字面量回归 api 层）；② 闸模式精确为路由段 `/\/final-composition\//`（文案不再是误报——与可达性工具"误报比没检查更糟"同教训） | 本批 |

### 二批/中批/大批量首批追加已修（2026-09-29 晚）

| 文件 | 条数 | 根因 | 修法 | 提交 |
|---|---|---|---|---|
| `src/typographySystem.test.ts` | 1 | 白名单未涵盖可变字体轴内字重（650/620）；projects.css 的 300 出轴 | 300→400（轴外只能浏览器合成）；白名单纳入轴内档（豁免转正） | 61ec04f5 |
| `src/styles/brandInteractionStyles.test.ts` | 1 | 两个并列主操作一明一暗的样式漂移 | __upload 恢复品牌亮底、__add 色值换 token（豁免转正） | 61ec04f5 |
| `src/pages/HomePage.motion.test.tsx` | 2 | 观察者计数过期（Orbit 加入后 3→4）；reduced-motion 断言过宽 | 计数更新；改为"没有揭示观察者"（非动画观察者不关） | 61ec04f5 |
| `src/features/agent-canvas/AgentCanvasPage.chrome.test.ts` | 3 | 源码形状锁停在演进前实现 | 对齐语义 snap / overlay 可见性过滤口径 | 61ec04f5 |
| `editing/EditingPreviewStage.test.tsx` + `editingPlayableSequence.ts` | 4 | **真 bug**：时长口径混用（全部输入未裁切源时长 vs 可播放裁切窗）→ 尺比片段长、BGM 空舞台播放、钳位不到真实末端 | 解耦 `duration`（尺长）与新增 `playableDuration`（播放/钳位/BGM 口径）+2 锁定测试 | 61ec04f5 |
| `src/app/routeProviders.test.tsx` | 9 | fixture 未跟上 /providers 配置就绪检查；Home 路水合断言过期；**win32 真 bug**：spawn npm ENOENT | URL 分发 mock；对齐 listProjects 活行为；npm.cmd + shell:true | 40d3fdc5 |
| `runtime/useAgentCanvasRuntime.test.tsx` | 6 | 73212c76 重构连带删除四个活性机制（tests 即规格） | 恢复终态补偿 250ms / 非终态 120ms 合批 / 开流 replayChanged 门控；修 runNode 过严守卫（ready 可 Regenerate）；测试文件补 RTL cleanup（拆跨用例定时器竞态） | 40d3fdc5 |
| `canvas/AgentCanvasNode.test.tsx` | 11 | 组件演进（媒体 URL/lazy/尺寸实测/视频 poster 卡片/handle 机制）+ **merge 冲突丢失物** | 测试对齐新契约；**恢复点阵/reveal CSS 全家+keyframes**（组件在渲染但无样式）；删死 loader CSS；补 overMedia 接线 | 5b2f1f2d |

## 2. 豁免（需设计/产品裁决，不盲修）

| 文件 | 条数 | 冲突双方 | 定责 |
|---|---|---|---|
| `src/styles/brandInteractionStyles.test.ts` | 1 | 测试锁"非聊天主操作用品牌亮底（`color: var(--text-inverse)`）"，CSS 实为暗底 `#292929/#f5f5f5`；同文件 `.agent-asset-browser__add` 仍遵守品牌亮底 | **设计裁决**：`.agent-asset-browser__upload` 是漂成 monochrome 的回归，还是 chrome monochrome 化的有意变更？定后单向修（改 CSS 或改测试），默认倾向恢复品牌亮底（与 `__add` 一致） |
| `src/typographySystem.test.ts` | 1 | 测试锁字重白名单 {400,500,600,700,800,900}，CSS 用可变字体中间字重（650/620/300）。其中 650/620 在 Manrope 可变轴 (400–800) 内合法；`projects.css` 的 300 **超出轴范围**（浏览器合成） | **设计裁决 + 一处真修**：把白名单扩为"可变轴内中间字重 + 静态档"（650/620 转正），并把 `.create-plus` 的 300 改为 400（轴外合成是无意义样式） |

## 3. 待修（38 条 / 3 文件）——按根因分类（2026-09-29 晚）

| 文件 | 条数 | 根因类别 | 证据（代表失败） | 下一步 |
|---|---|---|---|---|
| `workbench/AgentCanvasInlineWorkbench.test.tsx` | 22 | **组件表面漂移**：按钮/标签改名或重组（"Generate audio"×8 找不到、"Duration seconds"标签×4 找不到、"Retry video node"×1） | 大量 `Unable to find role=button/label` | 逐个对齐当前 DOM（集中了工作台最大一块 UI 漂移，需专门一轮） |
| `chat/useAgentCanvasChat.test.tsx` | 12 | **hook 契约漂移**：调用序列/参数/authoring 冲突店状态/guidance revision 冲突文案 | "expected {scope:'timeline'} to be null"×4、call-count/args×5、conflict×1 | 逐条核对 chat hook 当前契约；无共享根因，需逐条定责 |
| `canvas/AgentCanvasNode.test.tsx` | 4 | **merge 丢失的行为重建**：① 揭示门控 trio（working→ready 后 awaiting→revealed 两段式）——节点卡的媒体门控（output_asset_id gate + CanvasMediaPreview revealToken 接线）在 33580aaf 合并时丢失，CSS 已由 5b2f1f2d 恢复但组件接线未接；② 状态优先级（persisted vs runtime.visible_status 谁赢）需产品定夺 | 见各用例 | 揭示 trio 按失败测试所锁规格重建卡片媒体门控；状态优先级需设计裁决 |

**死代码（发现，未处理）**：`CanvasMediaPreview`/`CanvasVideoPreview` 当前无产品消费方
（仅各自身测试）——揭示链的组件侧已在卡片中脱落，CSS 已恢复。按仓规"要么接上
要么删"：重建卡片门控时接上，或连同 trio 测试一并退役（需设计裁决后单向执行）。

## 4. 此后纪律（对应 P5"新增失败 = 0"）

1. 本批起，任何新增失败必须先修或先在台账登记豁免理由，再合入。
2. 每修一个文件：更新本台账 §1/§3（减账），commit message 带 `P5` 编号。
3. §2 的两项设计裁决落地后，同步删去对应豁免行。

## 5. 2026-10-02 复盘：main 基线 63 条重新定责（Item 系列之后）

> P5 台账此前的"剩 38"是 chore 分支时点；Item 1-7 提交直入 main 时带进了
> ReplicaBlueprintPanel 系新失败且未登记台账，导致账面（38）与实测（63）失真。
> 本轮用 vitest JSON 报告逐文件盘点并对账。

### 定责总表（62 持续 + 1 偶发）

| 文件 | 条数 | 归属 | 根因 | 下一步 |
|---|---|---|---|---|
| `canvas/ReplicaBlueprintPanel.test.tsx` | 22 | **Item 2/7 新债** | 概念断奶重设计（默认主路径"🎬 导演台 + 槽位替换"、高级入口收进 ⚙ 折叠、复刻改写改槽位语义）落地后，旧面板测试仍锁旧 UI（"源码 .adreplica" 页签 ×18、锚点事件 ×2 等，全部 `Unable to find` 类） | 专门一轮：以 weaning 测试的新信息架构为规格，把旧测试迁移到新 DOM（或按断奶语义降级/退役相应断言） |
| `canvas/ReplicaBlueprintPanel.weaning.test.tsx` | 2 | **Item 7 自带新债** | 断奶自己的规格测试有 2 条在 main 上红（"🎬 导演台"/"⚙ 高级"找不到）——要么 c012cf64（复刻改写）回退了断奶入口，要么测试先于实现 | 先裁决：面板当前实装 vs 断奶规格谁对；单向修（实现或测试） |
| `workbench/AgentCanvasInlineWorkbench.test.tsx` | 22 | 旧债（§3 在案）；**2026-10-02 深挖升级诊断，见 §6** | 非表面漂移：test-first 的富参数工作台规格（descriptor 门控/视频音频开关/legacy 迁移），新组件建了没接线 | 接线 MediaPromptWorkbench + 对齐 22 条规格测试（一轮） |
| `chat/useAgentCanvasChat.test.tsx` | 12 | 旧债（§3 在案） | hook 契约漂移：Turn hydration/retry 调用序列、proposal 冲突店、guidance revision 文案 | 逐条核对当前契约；无共享根因 |
| `canvas/AgentCanvasNode.test.tsx` | 4 | 旧债（§3 在案） | 揭示门控 trio（merge 丢失，CSS 已恢复但接线未接）+ 状态优先级需设计裁决 | 按失败测试所锁规格重建媒体门控 |
| `app/routeProviders.test.tsx` | 1 | **非债**（并行调度偶发） | 单独运行 15/15 全过；全量跑时偶发（memory：并行调度坑） | 重跑即可，不记账 |

### 结论

- 修复方向上没有发现新的产品 bug 线索：24 条新债全部是 **测试锁旧 UI** 型
  （重设计先于测试更新），与 Item 7"概念断奶"的提交信息一致。
- 修复排期建议：BlueprintPanel 系（24 条，同根因一起修）→ InlineWorkbench
  （22 条）→ chat hook（12 条）→ AgentCanvasNode 揭示 trio（4 条，含一项设计
  裁决）。每轮修完更新本台账减账。

### 减账（2026-10-02，a9affca8）

- **BlueprintPanel 系 24 条清零**：裁决为"实现半成品"而非"测试锁旧 UI"——
  Item 7 只建了 `showAdvanced` 状态并删除旧页签栏，折叠 UI 没建（规格测试
  与旧测试双双落空，作者也到不了锚点/镜头表/源码页）。补全实现：主路径
  「🎬 导演台」标题 + 「⚙ 高级/收起高级」开关（收起落回 slots）、展开才
  渲染页签栏、折叠态用「槽位替换」区块标题替代页签标签。
- 旧测试迁移 6 处（两处 openSourceTab helper + 4 处直接点页签）：先展开
  ⚙ 高级再进页签，断言本体未动。
- 验证：weaning 2/2 + 面板 36/36 全绿；typecheck 0 error；全量 2643 passed
  / 39 failed = 63 − 24，零新增。

## 6. InlineWorkbench 簇深挖（2026-10-02）：不是表面漂移，是先行规格未接线

> 对 22 条失败逐簇归因（Generate audio ×8、Duration seconds ×4、参数布局
> ×4、model picker ×2、Run 错误通道 ×2、Retry ×1、reference policy ×1）后的
> 结论修正。

**架构事实**：
- AgentCanvasInlineWorkbench 是 223 行的**分发器**（text/script/image/video/
  audio → 各专用 workbench）；video 节点渲染 MediaPromptWorkbench。
- 测试锁的富参数 UI 属于两个**零消费方**的新组件：`ModelParameterControls`
  （descriptor 驱动的时长/分辨率/比例控件，自带 5 条绿测试）、
  `VideoAudioToggle`（"Generate audio"，连测试都没有）——组件建了，从未
  import 进任何产品代码。
- 现行 MediaPromptWorkbench 自带一套**无条件渲染**的 duration 控件
  （aria-label "Requested video duration"，管理同一批参数键
  duration_seconds/requested_duration_seconds/effective_duration_seconds）；
  CanvasModelPicker 已接线（image/video/script/text 共用）。

**定性**：与 BlueprintPanel 断奶同型——73212c76（3D previs + provider
video/audio reference channel）以测试先行写了富参数工作台规格（1525 行
测试），子组件起了头，接线没做。22 条失败里大量断言（legacy 参数迁移、
provider 上限钳位、非整数阻塞、descriptor 门控"模型没有就别造控件"）是
**尚未实现的规格**，不是可以对着现 DOM 改改查询就绿的标签错位。

**下一轮做法（接规格补实现，不是删测试）**：
1. MediaPromptWorkbench 接入 ModelParameterControls（替换手写 duration
   控件，descriptor 驱动：模型没声明就不渲染）+ VideoAudioToggle（视频
   音频生成开关）；
2. 行为对齐四条规格线：legacy 迁移（requested/effective → duration_seconds）、
   上限钳位保 canonical key、非整数阻塞 run、descriptor 门控；
3. 逐簇跑绿 22 条；CanvasModelPicker/Run 错误通道两条线按现行 DOM 对齐。

**连带处置**：VideoAudioToggle 无测试无消费方——接线时一并补其测试；
ModelParameterControls.test 5 条保持绿的约束下动组件。

### 减账（2026-10-02，0f4bafbe）

- **InlineWorkbench 22 条清零，测试文件零改动**——22 条本就是规格测试，
  实现补齐后全部自然变绿。落地的规格线：
  ① MediaPromptWorkbench 接入 ModelParameterControls（descriptor 驱动，
  显式选择 > 安装默认 > default 档兜底，不参考 node.model_summary）；
  ② VideoAudioToggle 上车（footer 开关、默认不落盘、三态禁用带原因）；
  ③ descriptor 校验阻塞 run + legacy 参数迁移走 normalizeProviderParameters；
  ④ retry 优先级（failed+retryable 最新尝试的 ready 节点 = Retry）；
  ⑤ 错误通道 __image-feedback/__text-feedback 包裹 + 删 "Prompt ready" 噪音行。
- 验证：InlineWorkbench 83/83 + ModelParameterControls/CanvasModelPicker
  全绿；typecheck 0 error；lint 0；全量 2665/17 = 39 − 22 精确减账。
- 剩余：chat hook 12、AgentCanvasNode 揭示 trio 4（含设计裁决）。
