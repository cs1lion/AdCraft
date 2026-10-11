/**
 * SyncComparePanel 的纯逻辑：候选收集、默认选品、漂移阈值、B 侧偏移。
 * 与组件分离，便于单测与 fast-refresh。
 */

import type { AgentCanvasWorkflowV2, CanvasNodeV2, ProjectAssetSummaryV2 } from "../../../types-v2.ts";
import { mediaAssetContentPath } from "../../../workflow/mediaPreview.ts";

export interface SyncCompareCandidate {
  node: CanvasNodeV2;
  asset: ProjectAssetSummaryV2;
  url: string;
}

/** 漂移校正阈值（秒）：双播放器时间差超过它就把从动方拉回主动方 */
export const SYNC_DRIFT_TOLERANCE = 0.15;

/** 逐帧步进假定的帧率（预演管线 24fps） */
export const FRAME_RATE = 24;

/** B 侧偏移限幅（秒）：防止误触把对比拉得过远 */
export const SYNC_OFFSET_LIMIT = 3;

/** 偏移限幅 + 0.1s 精度取整，nudge 与手输共用 */
export function clampOffsetSeconds(value: number): number {
  const rounded = Math.round(value * 10) / 10;
  return Math.max(-SYNC_OFFSET_LIMIT, Math.min(SYNC_OFFSET_LIMIT, rounded));
}

/**
 * 区间循环的回跳判定（NLE I/O 语义）：主时钟越过出点即回入点（未设入点回 0）。
 * 返回 null 表示当前不在边界上，自然播放。轮询粒度内允许小幅越线，回跳即校正。
 */
export function loopBoundaryTime(
  currentTime: number,
  inPoint: number | null,
  outPoint: number | null,
): number | null {
  if (outPoint === null || !Number.isFinite(outPoint)) return null;
  if (currentTime < outPoint) return null;
  return inPoint ?? 0;
}

/** wipe/diff 叠加对比要求两侧画框一致：宽高比相差超 1% 视为错位 */
export function aspectMismatch(
  a: { w: number; h: number } | null,
  b: { w: number; h: number } | null,
): boolean {
  if (!a || !b || a.w <= 0 || a.h <= 0 || b.w <= 0 || b.h <= 0) return false;
  const ratioA = a.w / a.h;
  const ratioB = b.w / b.h;
  return Math.abs(ratioA - ratioB) / Math.max(ratioA, ratioB) > 0.01;
}

/** B 侧应处的媒体时间：主时钟（A）时间 + 偏移，夹在 [0, B 时长] 内 */
export function expectedRightTime(
  leftTime: number,
  offsetSeconds: number,
  rightDuration: number,
): number {
  const raw = leftTime + offsetSeconds;
  const max = Number.isFinite(rightDuration) && rightDuration > 0 ? rightDuration : raw;
  return Math.max(0, Math.min(raw, max));
}

/** 候选：有视频输出的节点（video 与 scene-3d），按标题稳定排序 */
export function collectSyncCompareCandidates(workflow: AgentCanvasWorkflowV2): SyncCompareCandidate[] {
  const assetsById = new Map(workflow.assets.map((asset) => [asset.asset_id, asset]));
  const out: SyncCompareCandidate[] = [];
  for (const node of workflow.nodes) {
    if (node.node_type !== "video" && node.node_type !== "scene-3d") continue;
    const assetId = node.output_asset_id;
    if (!assetId) continue;
    const asset = assetsById.get(assetId);
    if (!asset || asset.media_type !== "video") continue;
    out.push({ node, asset, url: mediaAssetContentPath(asset) });
  }
  return out.sort((a, b) => (a.node.title || "").localeCompare(b.node.title || "", "zh-Hans-CN"));
}

/** 默认选品：左侧优先标题含「白模」，右侧优先含「成片」且不与左侧重复；否则取前两个 */
export function pickSyncCompareDefaults(
  candidates: SyncCompareCandidate[],
): { leftId: string | null; rightId: string | null } {
  if (candidates.length === 0) return { leftId: null, rightId: null };
  const findBy = (kw: string, excludeId?: string) =>
    candidates.find((c) => c.node.node_id !== excludeId && (c.node.title || "").includes(kw));
  const left = findBy("白模") ?? candidates[0];
  const right = findBy("成片", left.node.node_id)
    ?? candidates.find((c) => c.node.node_id !== left.node.node_id)
    ?? null;
  return { leftId: left.node.node_id, rightId: right?.node.node_id ?? null };
}
