/**
 * Route builders for the final-composition render-state family.
 *
 * These live in the api layer on purpose: agent-canvas sources may not embed
 * route strings for this family (see `quality/agentCanvasRetiredRoutes` —
 * "cannot import the broad legacy V2 client or reference retired routes").
 * The replica workbench polls and cancels durable renders through these
 * paths; the strings are constructed here so the boundary stays honest
 * without copying the panel into the etag machinery of the v2 client.
 *
 * 本文件自身也在 `quality/agentCanvasRetiredRoutes` 闸的管辖下（46ec7e14
 * 后补的管辖）：全文件唯一允许的路由字面量就是下面 finalRenderStatePath 的
 * 那一个，多一个退役路由字面量/退役客户端方法即红——路由引用不会因为搬了
 * 家就逃出闸门。
 */

export function finalRenderStatePath(workflowId: string, renderId: string): string {
  return `/api/v2/workflows/${encodeURIComponent(workflowId)}/final-composition/renders/${encodeURIComponent(renderId)}`;
}

export function finalRenderCancelPath(workflowId: string, renderId: string): string {
  return `${finalRenderStatePath(workflowId, renderId)}/cancel`;
}
