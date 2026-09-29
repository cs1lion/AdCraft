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

## 1. 已修（5 个文件 / 5 条）

| 文件 | 条数 | 根因 | 修法 | 提交 |
|---|---|---|---|---|
| `src/api/agentCanvasClient.test.ts` | 1 | frozen 连接策略契约要求全部 9 种节点类型，fixture 停在 6 种（漏 scene-3d/voice-cast/replica） | 按后端 `agent_canvas_connection_policy` 真实值补齐 `binding_kind_by_source_type` 与 `target_node_types` | 本批 |
| `src/pages/HomeStaticBackground.asset.test.ts` | 1 | Three.js 背景移除后 `three`/`@types/three`/`@react-three/*` 依赖忘删（src 零 import） | package.json 删 4 个包 + `npm install --package-lock-only --offline` 重新生成锁 | 本批 |
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
