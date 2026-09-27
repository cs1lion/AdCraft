/**
 * White-model op log — the agent's modeling process, made visible.
 *
 * After a white-model run the node carries ``structured_content
 * ["white_model_report"]``: which ops the batch applied and what the MCP
 * extension ops returned. This panel renders it (collapsed by default — the
 * process is evidence, not the workspace). Rendered OUTSIDE the lazy 3D
 * editor chunk so it shows even before three.js loads.
 */

import "../workbench/scene-3d-workbench.css";

const OP_LABELS: Record<string, string> = {
  add_environment: "添加环境",
  add_prop: "添加道具",
  add_character: "添加角色",
  add_camera: "添加相机",
  move_object: "移动",
  rotate_object: "旋转",
  scale_object: "缩放",
  set_camera: "设置相机",
  add_keyframe: "关键帧",
  remove_object: "移除",
  mcp_request: "MCP 扩展",
};

export interface WhiteModelOpLogProps {
  /** The node's ``white_model_report`` (null = no run yet). */
  report: Record<string, unknown> | null;
}

interface AppliedOp {
  index?: number;
  op?: string;
  target?: string | null;
}

interface McpResult {
  tool?: string;
  target?: string | null;
  is_error?: boolean;
  content?: unknown;
}

export function WhiteModelOpLog({ report }: WhiteModelOpLogProps) {
  if (!report) return null;

  const applied: AppliedOp[] = Array.isArray(report.applied)
    ? (report.applied as AppliedOp[])
    : [];
  const mcpResults: McpResult[] = Array.isArray(report.mcp_results)
    ? (report.mcp_results as McpResult[])
    : [];
  const operationCount =
    typeof report.operation_count === "number" ? report.operation_count : applied.length;

  if (applied.length === 0 && mcpResults.length === 0) return null;

  return (
    <details className="white-model-op-log" data-testid="white-model-op-log">
      <summary>
        Agent 建模记录 · {applied.length}/{operationCount} 个操作
        {mcpResults.length > 0 && ` · ${mcpResults.length} 个 MCP 扩展`}
      </summary>
      {applied.length > 0 && (
        <ol className="white-model-op-log__ops">
          {applied.map((entry, index) => (
            <li key={`${entry.op ?? "op"}-${index}`} data-op={entry.op ?? undefined}>
              <span className="white-model-op-log__op">
                {OP_LABELS[entry.op ?? ""] ?? entry.op ?? "操作"}
              </span>
              {entry.target && (
                <span className="white-model-op-log__target">{entry.target}</span>
              )}
            </li>
          ))}
        </ol>
      )}
      {mcpResults.length > 0 && (
        <ul className="white-model-op-log__mcp">
          {mcpResults.map((result, index) => (
            <li key={`mcp-${index}`} data-mcp-tool={result.tool ?? undefined}>
              <span className="white-model-op-log__op">MCP</span>
              <span className="white-model-op-log__target">
                {result.tool ?? "tool"}
                {result.target ? ` → ${result.target}` : ""}
              </span>
              <span
                className={
                  result.is_error
                    ? "white-model-op-log__status is-error"
                    : "white-model-op-log__status"
                }
              >
                {result.is_error ? "失败" : "已执行"}
              </span>
            </li>
          ))}
        </ul>
      )}
    </details>
  );
}
