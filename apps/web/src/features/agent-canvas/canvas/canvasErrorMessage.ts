import { isV2ApiError } from "../../../api/agentCanvasApi.ts";

const FRIENDLY_ERRORS: Record<string, string> = {
  canvas_binding_cycle: "This connection would create a dependency cycle.",
  canvas_cycle_detected: "This connection would create a dependency cycle.",
  canvas_connection_cycle: "This connection would create a dependency cycle.",
  canvas_connection_not_allowed: "These node types cannot be connected.",
  canvas_connection_incompatible: "These node types cannot be connected.",
  canvas_connection_duplicate: "These nodes are already connected.",
  canvas_binding_role_invalid: "This input role is not valid for the selected nodes.",
  canvas_input_role_invalid: "This input role is not valid for the selected nodes.",
  canvas_reference_limit_exceeded: "This node has reached the provider's reference limit.",
  provider_inputs_unsupported: "The selected provider cannot use these inputs.",
  provider_reference_delivery_unavailable: "The provider cannot currently receive this reference.",
  upstream_inputs_not_ready: "Required upstream nodes must be Ready before this node can run.",
  world_setting_projection_unavailable: "World Setting context is temporarily unavailable. Retry this node.",
  model_not_configured: "No default model is configured for this node type.",
  model_default_not_configured: "No default model is configured for this node type.",
  model_not_found: "The selected model is no longer in the local catalog.",
  model_unavailable: "The selected model is currently unavailable.",
  model_capability_mismatch: "The selected model cannot run this node with its current inputs.",
  provider_credentials_missing: "This model provider has no configured credential.",
  provider_credentials_invalid: "This model provider credential is not valid.",
  agent_model_incompatible: "The Agent default cannot perform this action.",
  model_catalog_sync_failed: "The provider model catalog could not be synchronized.",
  model_selection_invalid: "Choose a valid model selection before running this node.",
  media_requires_remote_transport: "This media file needs a public URL to be sent to the provider. Upload it to the asset library or use a publicly accessible link.",
  node_prompt_preparation_incomplete: "Prompt preparation is still in progress. Try running this node again when it is ready.",
  provider_gateway_config_stale: "Provider gateway configuration is out of date. Synchronize models before retrying.",
  provider_gateway_unavailable: "The configured provider gateway is unavailable.",
  model_adapter_unavailable: "The selected model has no executable adapter.",
  model_conformance_required: "The selected model has not completed compatibility verification.",
  model_conformance_revoked: "Compatibility approval for the selected model has been revoked.",
  model_parameter_incompatible: "One or more parameters are not supported by the selected model.",
  reference_input_mode_unsupported: "The selected model cannot use the current reference input mode.",
  reference_count_exceeded: "The current references exceed the selected model's limit.",
  provider_generation_failed: "The provider rejected this generation. Check the provider credential and quota, then retry.",
  provider_quota_exceeded: "The provider account is out of quota. Top up or switch credentials in API settings, then retry.",
  // D4: 3D 线本地引擎缺失必须"看得懂 + 知道下一步"——不是"失败"两个字。
  // 后端探针（get_blender_capability）查 BLENDER_EXECUTABLE 或 PATH 上的 blender。
  scene3d_blender_unavailable:
    "Blender is not installed on the machine running the backend, so this 3D node cannot render. Install Blender (or point BLENDER_EXECUTABLE at it) and retry; on a shared server, ask your administrator.",
  // MCP 桥（BlenderMcpClient）起不来：本地服务未启动时给同等级别的可行动说明。
  mcp_unavailable:
    "The Blender MCP service could not be started, so this 3D action cannot run. Start the local Blender MCP service and retry, or run without the MCP bridge.",
  // D4: apply-operations 的 MCP 扩展操作在运行时被工具拒绝——整个批次
  // all-or-nothing 拒绝、什么都不落（不是"操作无效"的校验问题，是桥那头的事）。
  // 看得懂 + 说得出下一步。
  scene_operations_mcp_failed:
    "Some 3D scene operations were rejected by the Blender MCP service; nothing was applied. Check that the local Blender MCP service is running and healthy, then retry.",
};

export function canvasAuthoringErrorMessage(error: unknown): string {
  if (!isV2ApiError(error)) {
    // 运行期投影的错误是 normalizeRuntimeError 的普通对象 {code,message,stage}
    // （不是 V2ApiError 实例）——同一张翻译表必须也对它生效，否则节点上的
    // 红字仍会漏出后端实现细节。
    if (error && typeof error === "object") {
      const record = error as { code?: unknown; message?: unknown };
      if (typeof record.code === "string" && FRIENDLY_ERRORS[record.code]) {
        return FRIENDLY_ERRORS[record.code];
      }
      if (typeof record.message === "string" && record.message) {
        return record.message;
      }
    }
    return error instanceof Error ? error.message : "The canvas operation could not be completed.";
  }
  if (error.code === "binding_model_incompatible") {
    const models = Array.isArray(error.details.compatible_model_ids)
      ? error.details.compatible_model_ids.filter((value): value is string => typeof value === "string")
      : [];
    return models.length
      ? `The selected model cannot use this input. Choose ${models.join(", ")}.`
      : "The selected model cannot use this input. Choose a compatible model.";
  }
  return (error.code && FRIENDLY_ERRORS[error.code]) || error.message;
}
