# ADR 0006: 自由创作 + 创作引导（可观测性 / 状态可见 / 重试 / 进度）

## Status

Proposed → **P0/P1 implemented in the working tree (2026-09-15)**; P2 pending.

## 实施进度（审计 2026-09-15）

- **P0 已完成**：
  - `authoring_origin` / `intent_hint` 入 `CanvasNodeCreateRequestV2` / `CanvasNodeV2` schema（`schemas/agent_canvas.py`），并持久化到 `agent_canvas_nodes` 表（列 + CHECK 约束，迁移 `20260915_02`；`_node_values` / `_node_from_row` 双向接线；`agent_canvas_nodes.py:67-95` 创建时携带）。
  - `runNode` 结构化阻塞原因：`useAgentCanvasRuntime.ts` 抛 `NodeRunBlockedError`（`no_workflow` / `unsupported_node_type` / `source_only_node` / `not_runnable_status`，带 `suggestedNext`）；`AgentCanvasNode.tsx` 把每个失败节点接到重试 CTA。
  - `GET /workflows/{id}/progress` 端点（`agent_canvas.py:1811`）返回图计数 + `blocked_nodes[].next_action`（按 `authoring_origin` / `intent_hint` 生成文案）；前端进度面板消费。
- **P1 部分完成**：
  - `GuidanceAwaitingV2.kind` 增加 `free_node_advisory`，`resume_policy` 增加 `free_node_completed`；`GuidanceAwaitingService.enter_free_node_advisory` 已加。
  - `retryAllFailed` 批量重试已实现（`useAgentCanvasRuntime.ts`）。
  - 未完成：`free_node_advisory` 的生成/消费路径（引导层何时对自由节点产出 advisory next_action）尚未接入 journey 状态机。
- **P2 未做**：依赖拓扑排序执行；"卡住诊断"聚合面板（图 + journey + provider 健康）；`intent_hint` 驱动的 LLM 推荐话术。

> **2026-09-26 复审**：以上结论仍成立——`enter_free_node_advisory` 仍无调用方（advisory 的生成/消费路径未接 journey 状态机）；P0 的 progress 端点仍在（`agent_canvas.py:2096`）。本文不因周边功能（时间线、3D 工作台）落地而改判。

## Context

用户诉求：当前 Agent Canvas（V2）是"固定的广告生产引导流程"，新手想自由添加节点（哪怕不合逻辑）也会被卡住，且：

1. 点"小飞机"执行后看不到节点是否在跑（状态不可见）。
2. 失败/卡住时没有重试提示。
3. 没有整体进度，系统各部分工作状态不透明，"经常卡住不知道接下来该做什么"。

约束：V2 画布是 canonical 的执行边界，引导（guided journey）与自由节点（free authoring）不能互相限制；引导要能"引导"自由节点而不是"锁死"它。

## 现有代码事实（扩展点，必须复用）

| 概念 | 现有实现 | 位置 |
|---|---|---|
| 用户自由添加节点 | `POST /workflows/{id}/nodes` → `create_canvas_node`，picker 仅按 node_type 选，无"来源"标记 | `apps/api/app/api/v2/endpoints/agent_canvas.py:1942`；`apps/web/src/features/agent-canvas/AgentCanvasPageSurface.tsx:774-798` |
| 节点状态枚举 | `CanvasNodeStatusV2 = draft \| working \| ready \| failed` + `visible_status` | `apps/web/src/types-v2.ts:1474,2214` |
| 运行门禁 | `require_node_runnable`（仅拦 `source_only`）；前端镜像 `isSourceOnlyNode` | `app/services/agent_canvas_authoring_validation.py:18-26`；`apps/web/src/features/agent-canvas/model/nodeExecutionMode.ts:3` |
| 小飞机运行 | `runNode` 静默 early-return（editing/source-only/ready 无反馈）；`start_canvas_run` 需 Idempotency-Key | `apps/web/src/features/agent-canvas/runtime/useAgentCanvasRuntime.ts:485-515`；`agent_canvas.py:3261` |
| 引导 awaiting | `GuidanceAwaitingV2.kind`（clarification/concept_selection/media_review/manual_node_run/milestone_idle）+ `resume_policy` | `app/schemas/agent_canvas_guided_interactions.py:293-313` |
| 整体进度 | `GuidanceSessionProgress` 仅按 `journey.stage` 静态列，**不算图进度、不算 free 节点** | `apps/web/src/features/agent-canvas/chat/GuidanceSessionProgress.tsx` |
| prompt 准备 | `prompt_preparation.status ∈ queued/ready/not_applicable/superseded` | `app/persistence/agent_canvas_repository.py:792,1368` |

## 设计决策

### 1. 边界原则：引导是"顾问"，不是"门禁"

- **自由创作永不失败到不可用**：任何 `draft` 用户节点都必须可被"尝试执行"；执行前用 `require_node_runnable` + 输入就绪检查给出**可操作的缺失提示**（缺哪个上游、为什么），而不是 `node_not_runnable` 黑洞。
- **引导 = 推荐层（advisory）**：引导对自由节点只输出"下一步建议 + 可执行的修复动作"，不删除/不阻塞节点。引导能"吸收"用户已添加的自由节点进入 journey，但不能反向锁死它。
- **状态可见性**是一等公民：任何 `working`/`failed` 节点 + 每个 awaiting 都必须有**机器可读的"下一步"**（`next_action`），供 UI 渲染与"接下来该做什么"查询。

### 2. 节点来源与模式（schema 扩展）

在 `CanvasNodeCreateRequestV2` 增加：

- `authoring_origin: "user_free" | "agent_guided" | "template" = "user_free"`（缺省视为自由）。
- `intent_hint: str | None`（可选，自由节点上用户写的"这个节点想干什么"，供引导层生成推荐）。

不新增独立状态机——复用 `CanvasNodeStatusV2`；"可引导/不可引导"由 `authoring_origin` + `execution_mode` 推导，避免与现有 awaiting 冲突。

### 3. 运行反馈（小飞机不静默）

`runNode` 的每个 early-return 分支都改为返回**结构化原因**（`RunBlockedReason = { code, message, missing_inputs[], suggested_next }`）而非 `undefined`：

- `editing` / `source_only` → 提示"该节点是素材源，请用编辑模式"。
- 上游未就绪 → 列出缺失的 `input_slot` + 对应上游节点 id，并给"先跑上游 X"的 CTA。
- 执行中 → 显示 `working` 进度（复用 `visible_status` + 一条 `prompt_preparation.status`）。
- 失败 → 显示 `failed` + `error_code` + **重试按钮**（`runNodeById(nodeId, retryFailed=true)` 已存在，缺的是把它接到每个 failed 节点）。

### 4. 整体进度（图感知，非仅 stage 列表）

`GuidanceSessionProgress` 升级为**双轨**：

- **图进度**：`{ total_nodes, ready, working, failed, draft }` 的实时计数（来自一次 `GET` 画布投影，前端聚合），带"卡在 X"提示。
- **Journey 进度**：现有 stage 列表保留，但每个 stage 暴露 `next_action`（当 stage `waiting_user`/`blocked_external`/`failed` 时）——回答"接下来该做什么"。

新增一个只读端点（v2）`GET /workflows/{id}/progress`：返回图计数 + 当前 awaiting + 每个 `failed`/`working` 节点的 `next_action`，供进度条与"卡住诊断"面板消费。

### 5. 重试（一等可观测）

- 每个 `failed` 节点带 `error_code` + `last_run` + 显式 **retry**（Idempotency-Key 换发即可，复用 `start_canvas_run`）。
- `prompt_preparation` 侧沿用 ADR 0004 的修复语义：`queued` 可重入，`superseded` 自动重算，`not_applicable` 说明原因；不再"整套流程坏掉"。
- 顶层"重试卡住的节点"批量动作：对 `failed` 节点一次性重新派发（受并发上限约束），失败逐个报因。

## 实施分期（最小可用 → 完整）

- **P0（本次可做）**：`authoring_origin`/`intent_hint` 入 schema；`runNode` 结构化阻塞原因 + failed 节点重试 CTA；`GET /progress` 端点 + 前端进度条（图计数 + next_action）。
- **P1**：引导"吸收"自由节点（`GuidanceAwaitingService` 对 `user_free` 节点生成 advisory `next_action` 而非拒绝）；`intent_hint` 驱动推荐话术。
- **P2**：多节点批量重试/依赖拓扑排序执行；"卡住诊断"面板（聚合图 + journey + provider 健康）。

## 与既有 ADR 的关系

- 不改动 `require_node_runnable` 的 source_only 语义（仍拦），只补"为什么 + 下一步"。
- 引导层复用 `GuidanceAwaitingV2`，新增 `resume_policy` 值 `free_node_completed`（P1）：自由节点 terminal 时引导可被驱动续行。
- 进度端点是只读投影，不写节点状态，与 ADR 0004 的 outbox 修复解耦。

## 后果

- 自由创作不被门禁；引导对自由节点是顾问式。
- 状态/进度/重试全部机器可读，可观测性提升，"卡住"可定位到具体 next_action。
- 代价：`GET /progress` 需一次画布投影扫描；P1 的 advisory 逻辑需与 journey 状态机小心耦合，避免"引导反向锁死自由节点"。

## 风险 / 开放问题

- 批量重试的并发上限与 provider 配额（step/fish TTS、Agnes video）需对齐 pool 限制（ADR 0003 §4）。
- `intent_hint` 的自由文本到"推荐话术"映射需要一个轻量 LLM pass（Agnes 3.0 Flash），需定失败降级（无 LLM 时只给静态 checklist）。
