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

## 1. 已修（5 个文件 / 5 条）

| 文件 | 条数 | 根因 | 修法 | 提交 |
|---|---|---|---|---|
| `src/api/agentCanvasClient.test.ts` | 1 | frozen 连接策略契约要求全部 9 种节点类型，fixture 停在 6 种（漏 scene-3d/voice-cast/replica） | 按后端 `agent_canvas_connection_policy` 真实值补齐 `binding_kind_by_source_type` 与 `target_node_types` | 本批 |
| `src/pages/HomeStaticBackground.asset.test.ts` | 1 | Three.js 背景移除后 `three`/`@types/three`/`@react-three/*` 依赖忘删（src 零 import） | package.json 删 4 个包 + `npm install --package-lock-only --offline` 重新生成锁 | 本批 |
| `src/features/agent-canvas/canvas/AgentCanvasNodePicker.test.tsx` | 1 | 规范节点类型扩到 9（复刻/3D/配音三线依赖），测试断言停在 6 | 更新为 9 种 + 新类型图标映射 + 标签"3D Previs" | 本批 |
| `src/pages/ProjectsPage.rename.test.tsx` | 1 | 测试硬编码 en-US 日期格式 "7/24/2026"，组件用浏览器默认 locale（zh-CN 下必挂） | 期望值改为与组件同一算法（locale 无关） | 本批 |
| `src/quality/agentCanvasRetiredRoutes.test.ts` | 1 | D7/E6 让 ReplicaBlueprintPanel 引用 final-composition 路由族，触犯"agent-canvas 不得引用退役路由"闸；同时闸的正则误伤产品文案里的术语 | ① 路径构造移到 `src/api/finalRenderPaths.ts`（路由字面量回归 api 层）；② 闸模式精确为路由段 `/\/final-composition\//`（文案不再是误报——与可达性工具"误报比没检查更糟"同教训） | 本批 |

## 2. 豁免（需设计/产品裁决，不盲修）

| 文件 | 条数 | 冲突双方 | 定责 |
|---|---|---|---|
| `src/styles/brandInteractionStyles.test.ts` | 1 | 测试锁"非聊天主操作用品牌亮底（`color: var(--text-inverse)`）"，CSS 实为暗底 `#292929/#f5f5f5`；同文件 `.agent-asset-browser__add` 仍遵守品牌亮底 | **设计裁决**：`.agent-asset-browser__upload` 是漂成 monochrome 的回归，还是 chrome monochrome 化的有意变更？定后单向修（改 CSS 或改测试），默认倾向恢复品牌亮底（与 `__add` 一致） |
| `src/typographySystem.test.ts` | 1 | 测试锁字重白名单 {400,500,600,700,800,900}，CSS 用可变字体中间字重（650/620/300）。其中 650/620 在 Manrope 可变轴 (400–800) 内合法；`projects.css` 的 300 **超出轴范围**（浏览器合成） | **设计裁决 + 一处真修**：把白名单扩为"可变轴内中间字重 + 静态档"（650/620 转正），并把 `.create-plus` 的 300 改为 400（轴外合成是无意义样式） |

## 3. 待修（73 条 / 8 文件）——按根因分类

| 文件 | 条数 | 根因类别 | 证据（代表失败） | 下一步 |
|---|---|---|---|---|
| `workbench/AgentCanvasInlineWorkbench.test.tsx` | 22 | **组件表面漂移**：按钮/标签改名或重组（"Generate audio"×8 找不到、"Duration seconds"标签×4 找不到、"Retry video node"×1） | 大量 `Unable to find role=button/label` | 逐个对齐当前 DOM（本批未动：集中了工作台最大一块 UI 漂移，需专门一轮） |
| `canvas/AgentCanvasNode.test.tsx` | 15 | **状态派生断言漂移**（"expected false to be true"/status 断言） | 15 条里 13 条 AssertionError | 逐条比对 `AgentCanvasNode` 当前状态机；注意本会话验证过其失败集与基线一致，非本次改动引入 |
| `chat/useAgentCanvasChat.test.tsx` | 12 | **hook 行为漂移**：调用序列/参数/authoring 冲突店状态断言 | "expected {scope:'timeline'} to be null"×4、call-count×3 | 逐条核对 chat hook 当前契约；冲突店断言需确认是行为变更还是测试过期 |
| `app/routeProviders.test.tsx` | 9 | **混合**：8×"API ready"等待不到（mock 就绪时序）+ 1×`spawnSync npm ENOENT` | 见证据列 | npm ENOENT 属**环境限制**（worker 内 npm 不在 PATH，ENV-SKIP 性质）；其余 8 条查 provider 就绪门 |
| `runtime/useAgentCanvasRuntime.test.tsx` | 6 | 断言漂移 + 1 条 NodeRunBlockedError | 5 Assertion + 1 抛错 | 同上，逐条定责 |
| `editing/EditingPreviewStage.test.tsx` | 4 | 断言漂移（预览产物断言） | 4 Assertion | 小批量，可直接修 |
| `AgentCanvasPage.chrome.test.ts` | 3 | chrome 结构断言漂移 | 3 Assertion | 小批量，可直接修 |
| `pages/HomePage.motion.test.tsx` | 2 | 动画偏好断言漂移 | 2 Assertion | 小批量，可直接修 |

## 4. 此后纪律（对应 P5"新增失败 = 0"）

1. 本批起，任何新增失败必须先修或先在台账登记豁免理由，再合入。
2. 每修一个文件：更新本台账 §1/§3（减账），commit message 带 `P5` 编号。
3. §2 的两项设计裁决落地后，同步删去对应豁免行。
