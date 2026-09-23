# 待实现：Agent Canvas 前端 UX 改进（暂不实施）

> 记录于 2026-09-13。以下两项是已调查清楚但暂缓的 UI 改进，
> 调查结论与实施落点已锁定，实施时直接照此执行。

## 1. "Conversation could not be refreshed" 自动重试

- **问题**：`useAgentCanvasChat.ts` 的 `runRefresh()` catch 分支（约 :607-609）设置
  banner 后没有自动重试。后端数据实际完好（creative-session 404 已被
  `.catch(() => null)` 吞掉），典型失败是瞬时 503/网络抖动，但 banner 会一直
  挂在屏幕上直到下一次 chatRevision 变化或用户手动点 Refresh。
- **实施落点（纯前端）**：
  - `apps/web/src/features/agent-canvas/chat/useAgentCanvasChat.ts`
    - catch 分支加退避重试：`REFRESH_RETRY_DELAYS_MS = [1_000, 3_000, 10_000]`，
      模块级 `refreshFailureCountRef` 计数；4xx（401/403/422/404-workflow）豁免；
      成功路径（:602）把计数归零；上限 3 次。
  - `apps/web/src/features/agent-canvas/chat/AgentCanvasChatPanel.tsx`
    - `useEffect` 监听 `chat.state.timelineRecovery` + `loading`：recovery 存在
      且 5 秒后仍非 null → 自动 dismiss。保留手动 Refresh 按钮。
  - 测试：`useAgentCanvasChat.test.tsx`（fake timers 锁退避序列/上限/4xx 豁免/归零）
    + `AgentCanvasChatPanel.test.tsx`（5s 自动消失）。
  - 验证：`cd apps/web && npm run check:quality`。

## 2. 节点连接端点可发现性（"点 node 端点没提示"）

- **根因**（三个叠加）：
  1. `AgentCanvasNode.css:758-798` — handle 平时 `opacity:0; pointer-events:none`，
     只有 hover 节点卡片才浮现，从未 hover 的用户看不见端口。
  2. `AgentCanvasNode.tsx:307-316 / 349-358` — `<Handle>` 只传了 `aria-label`，
     没有 `title` tooltip，也不知道"要拖出去"。
  3. `onOpenConnectedNodeMenu`（"添加输入/输出节点"菜单）在
     `AgentCanvasNode.tsx:61-66` 与 `AgentCanvasPageSurface.tsx:510` 都声明了，
     但全仓库**没有任何按钮触发它**——菜单是死代码，节点 Header 也没有连接入口。
- **正确的连接操作模型**：hover 节点 → 左右浮现 14px 圆点 → 按住拖到另一个
  节点松手 → `connect()`（`AgentCanvasPageSurface.tsx:689-715`）自动建 binding。
  类型不兼容才有兜底提示。
- **实施落点（纯前端）**：
  - `AgentCanvasNode.css`：handle 默认透明度提到 ~0.55，hover 时 1.0。
  - `AgentCanvasNode.tsx`：两个 `<Handle>` 加 `title="拖到另一个节点可建立连接"`。
  - `AgentCanvasNodeHeader.tsx`：加"添加输入 / 添加输出"按钮，调
    `onOpenConnectedNodeMenu(node.node_id, "upstream"|"downstream", point)`，
    把死代码菜单救活（`AgentCanvasPageSurface.tsx:1344-1353` 的渲染点已就绪）。
  - `AgentCanvasPageSurface.tsx:699`：连接失败文案细化为
    "Node X 不能连到 Node Y"。
  - 后端策略表 `agent_canvas_connection_policy.py` 本身正确，无需改。
  - 验证：`cd apps/web && npm run check:quality`。

## 两者共同约束

- 都只动 `apps/web`，不碰后端契约（跳过 `check:agent-canvas-contract`）。
- 无 UI 布局大改，bundle 预算大概率不触发；实施时用 `npm run check` 复核。
