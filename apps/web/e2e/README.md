# V0.2 E2E 旅程 harness（asset-to-canvas · dialogue-to-proposal）

`docs/plans/infinite_canvas_ai_short_video_research_v0.2.md` §15 审计表宣布 v0.2
施工目标已完成，但审计表是**主张清单**：本目录是两条最小用户旅程的**证明**。
配套组件全部为仓库既有前端逻辑——Meshy/外部 3D 服务经检索确认 0 命中、不在关键
路径上；两层 LLM 默认关闭。因此整套 harness 跑在"本地逻辑 + 既有 mock"上。

模式沿用仓库既有的 `tests/browser` mock：dev server 提供挂载**真实组件**的页面，
只有 HTTP 由 `page.route`  mock（ playwright 的浏览器内路由），不启动后端、
不构建、不引入任何新依赖。

## 如何运行

```bash
cd apps/web
# 一次性：若尚未安装浏览器
npx playwright install chromium

# 跑两条旅程
npm run test:e2e:v02-journeys
# 等价于
npx playwright test --config=e2e/playwright.config.ts
```

- `e2e/playwright.config.ts` 会自动起 `npm run dev -- --port 5198`（webServer），
  端口 5198 与既有 5197 套件互不冲突。若已有服务器在跑，设
  `PLAYWRIGHT_BASE_URL=http://127.0.0.1:5198` 即跳过 webServer。
- 只做类型检查（不跑浏览器）：`npm run typecheck:e2e:v02-journeys`
  （即 `tsc -p e2e/tsconfig.json`）。
- `vitest` 已排除 `e2e/**`：Playwright spec 不是 vitest 测试，`npm test` 不会
  误拾取。

## 目录

| 文件 | 作用 |
|---|---|
| `v02-journeys.spec.ts` | 两条旅程的 spec（断言 + mock HTTP） |
| `harness/v02-j1-asset-to-canvas.mock.{html,tsx}` | J1 页面：真实资产浏览器 + 真实 ReactFlow 画布 + 真实 scene-3d 工作台 |
| `harness/v02-j2-dialogue-to-proposal.mock.{html,tsx}` | J2 页面：真实 `LocalEngineWorkbench`（唇形面板 + SceneScript3DEditor） |
| `harness/v02-scene-workbench.tsx` | 两个页面共享的工作台挂载点（真实组件，无复制） |
| `harness/v02-journeys.fixtures.ts` | 页面种子与 spec 响应共用同一份 fixture（纯数据，无 React） |

## 证明了什么

### J1 · asset-to-canvas（§2.1 拖拽第一语言 / §2.2 语义吸附 + 卡内归属）

1. 从资产浏览器拖一个 ready 素材到画布 pane → `POST /api/v2/workflows/:id/nodes`
   携带 `node_type == media_type` 与 `source_asset_id`（镜像后端
   `validate_asset_backed_node`）→ 画布上出现资产背书节点卡
   （`agent-canvas-node-image-still-1`）。
2. 把场景板图片拖到 scene-3d 卡片上 → `POST .../bindings`
   `input_role: "image_reference"`（`image_asset` 源 + 不可变版本）→ 3D 编辑器
   出现「⇢ 参考输入」行（`scene-script-3d-reference-0`），点名角色
   （场景设计板）与资产。
3. 卡片上的 drop 归属卡片：pane handler 被 `stopPropagation`，全程只创建了
   一个节点。

### J2 · dialogue-to-proposal（§14.3/§14.5 timing / §15 把顾问接到提案）

1. 唇形面板写入一行台词并应用 → summary 报告实测段数；同一 run 的分镜提示
   （`line_crosses_cut`，话音跨切点）出现在「分镜提示（不自动修改）」下；
   作者写的原文逐字上车。
2. C-mode 链（床 → 对齐 → 唇形 → 字幕）：应用即把 cues 发上字幕轨，
   `source_node_id` 可追溯（与嘴同一边界，不重新估算）。
3. 点提示行里的「🎬 看看怎么接」→ 播放头落入边界镜头 → picker **自动取回**
   该镜对的读法：请求体 `shot_a_id=shot1 / shot_b_id=shot2`，且 segments 是
   应用唇形时实测的同一条时间线；两个 LLM 复选框保持未勾选，无「LLM 补充」
   徽章，`narrative_source` 为 rules；不可行读法（时间跳跃）带理由保持可见。
4. 应用**声音桥**（0 操作读法）→ 读法被登记为 shot2 的入镜读法
   （note 明说"已登记"）→ 镜头条边界显示关系标签
   （`shot-strip-intent-shot2` / `shot-strip-relation-shot1-shot2` = 声音桥）
   ——是标签，不是连线（§13 第 5 问）。

## 选择器政策

- spec 只使用产品组件里**已存在**的 `data-testid`（`src/features/agent-canvas/**`
  内 grep 可得）：`agent-asset-*`、`agent-canvas-node-*`、
  `scene-script-3d-reference-*`、`dialogue-lipsync*`、`dialogue-shot-advisories`、
  `dialogue-advisory-transitions-*`、`transition-proposals*`、`shot-strip*`。
- harness 自己的页面只新增两个测试点：`canvas-pane`（drop 适配器所在 div）与
  `scene-workbench`（挂载点），均在 `e2e/harness` 内，未改动任何产品选择器。
- 诚实边界：pane 的 drop 适配器镜像 `AgentCanvasPageSurface.handleCanvasDrop`，
  复用同一批纯函数（`canvasDrop.ts` / `canvasSnap.ts` / `canvasGraphModel.ts`）
  与同一 API client；没有整册挂载 Surface，是因为它的 session/SSE 引导依赖后端
  实时端点，超出"本地逻辑 + 既有 mock"的范围（纯函数的 drop 决策由既有单测
  锁定，本 harness 证明的是从手势到节点卡的整条接线）。

## 推迟的三条旅程（及理由）

1. **跨场景 Continuity State（§5）**：有意义的旅程是"同一角色/道具/走向跨两个
   scene-3d 节点保持一致，看门（blocking_continuity / held_items / emotion /
   wardrobe / palette drift）报警"。这些 findings 由**后端执行器**发布
   （`structured_content.scene3d_*`），纯前端 harness 无法诚实产出；用 fixture
   渲染只能证明 fixture 自己。待可执行后端（或录制的执行器 fixture 集）就位后再补。
2. **LLM gates（§6.2/§15）**：`polish_narratives` / `propose_readings` 两层需要
   LLM provider gateway，按定义不在"本地逻辑"约束内。已覆盖的部分：两层默认关闭、
   无 LLM 来源读法到达面板、`narrative_source` 保持 rules（J2 中断言）。
3. **Layer locks（§14.13 锁一层，重做另一层）**：Audio 锁（说话窗内保留 talk）与
   Visual 锁（唇形合并继承该帧插值姿态）位于 scene-3d 执行器的关键帧合并
   （apps/api，由 python 测试覆盖）；前端面板（`LayerOwnershipNote`、
   "🔒 N 帧在说话"报告）只是展示执行器结论。前端 harness 到不了那里——推迟到
   API 套件。

## 本次刻意不做

- 不新增任何依赖：playwright 运行器（`@playwright/test`）本就是 apps/web 的
  devDependency，这里只加 config 与 spec。
- 不启动 dev server、不 build（config 里的 webServer 只在**运行**套件时拉起，
  与 `tests/browser` 同规）。
