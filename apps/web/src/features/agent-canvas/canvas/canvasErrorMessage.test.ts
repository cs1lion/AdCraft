import { describe, expect, it } from "vitest";

import { V2ApiError } from "../../../api/v2Client.ts";
import { canvasAuthoringErrorMessage } from "./canvasErrorMessage.ts";

describe("canvasAuthoringErrorMessage", () => {
  it("explains rate limiting without misdiagnosing credentials or automatically retrying", () => {
    const message = canvasAuthoringErrorMessage({ code: "provider_rate_limited", message: "media_api_failed: status=429", retryable: true });
    expect(message).toContain("rate limiting");
    expect(message).toContain("manually retrying this node");
    expect(message).toContain("completed media is preserved");
    expect(message).not.toContain("credential");
  });
  it("explains a retryable World Setting projection failure", () => {
    expect(canvasAuthoringErrorMessage(new V2ApiError({
      status: 409,
      code: "world_setting_projection_unavailable",
      message: "Projection service unavailable.",
      details: { retryable: true },
    }))).toBe("World Setting context is temporarily unavailable. Retry this node.");
  });

  it("turns cycle and capability failures into actionable canvas messages", () => {
    expect(canvasAuthoringErrorMessage(new V2ApiError({
      status: 409,
      code: "canvas_binding_cycle",
      message: "Cycle",
      details: {},
      violations: [],
      suggestedActions: [],
      payload: null,
    }))).toContain("cycle");

    expect(canvasAuthoringErrorMessage(new V2ApiError({
      status: 422,
      code: "binding_model_incompatible",
      message: "Unsupported",
      details: { compatible_model_ids: ["seedance-1.0", "seedance-lite"] },
      violations: [],
      suggestedActions: [],
      payload: null,
    }))).toContain("seedance-1.0");
  });

  it("preserves an unknown backend message", () => {
    expect(canvasAuthoringErrorMessage(new Error("Connection failed."))).toBe("Connection failed.");
  });

  it("maps model failures without exposing backend implementation details", () => {
    expect(canvasAuthoringErrorMessage(new V2ApiError({
      status: 409,
      code: "provider_credentials_missing",
      message: "missing provider key",
      details: {},
      violations: [],
      suggestedActions: [],
      payload: null,
    }))).toBe("This model provider has no configured credential.");

    expect(canvasAuthoringErrorMessage(new V2ApiError({
      status: 409,
      code: "model_unavailable",
      message: "unavailable",
      details: {},
      violations: [],
      suggestedActions: [],
      payload: null,
    }))).toBe("The selected model is currently unavailable.");
  });

  it("explains that incomplete prompt preparation blocks Run admission", () => {
    expect(canvasAuthoringErrorMessage(new V2ApiError({
      status: 409,
      code: "node_prompt_preparation_incomplete",
      message: "Prompt preparation is incomplete.",
      details: {},
      violations: [],
      suggestedActions: [],
      payload: null,
    }))).toBe("Prompt preparation is still in progress. Try running this node again when it is ready.");
  });

  it.each([
    ["provider_gateway_config_stale", "Provider gateway configuration is out of date. Synchronize models before retrying."],
    ["provider_gateway_unavailable", "The configured provider gateway is unavailable."],
    ["model_adapter_unavailable", "The selected model has no executable adapter."],
    ["model_conformance_required", "The selected model has not completed compatibility verification."],
    ["model_conformance_revoked", "Compatibility approval for the selected model has been revoked."],
    ["model_parameter_incompatible", "One or more parameters are not supported by the selected model."],
    ["reference_input_mode_unsupported", "The selected model cannot use the current reference input mode."],
    ["reference_count_exceeded", "The current references exceed the selected model's limit."],
  ])("maps provider-neutral failure %s", (code, message) => {
    expect(canvasAuthoringErrorMessage(new V2ApiError({
      status: 422,
      code,
      message: "backend implementation detail",
      details: {},
      violations: [],
      suggestedActions: [],
      payload: null,
    }))).toBe(message);
  });

  // D4: 3D 线本地引擎缺失必须"看得懂 + 有下一步"。
  it("explains a missing Blender install with the next step (D4)", () => {
    const message = canvasAuthoringErrorMessage(new V2ApiError({
      status: 409,
      code: "scene3d_blender_unavailable",
      message: "Blender is not available: [Errno 2] No such file or directory: 'blender'",
      details: {},
      violations: [],
      suggestedActions: [],
      payload: null,
    }));
    expect(message).toContain("Blender is not installed");
    // 可行动：说得出下一步（安装 / BLENDER_EXECUTABLE / 找管理员），不是"失败"
    expect(message).toContain("BLENDER_EXECUTABLE");
    expect(message).toContain("administrator");
  });

  it("explains an unreachable Blender MCP bridge with the next step (D4)", () => {
    const message = canvasAuthoringErrorMessage(new V2ApiError({
      status: 503,
      code: "mcp_unavailable",
      message: "Blender MCP server unavailable: spawn failed",
      details: {},
      violations: [],
      suggestedActions: [],
      payload: null,
    }));
    expect(message).toContain("Blender MCP service could not be started");
    expect(message).toContain("without the MCP bridge");
  });

  // D4: apply-operations 的 MCP 扩展操作运行时被拒——all-or-nothing 批次拒绝、
  // 什么都不落。要翻译成"看得懂 + 有下一步"，不能漏后端原文。
  it("explains rejected MCP scene operations with the next step (D4)", () => {
    const message = canvasAuthoringErrorMessage(new V2ApiError({
      status: 400,
      code: "scene_operations_mcp_failed",
      message: "1 MCP extension op(s) failed; nothing was applied.",
      details: {},
      violations: [],
      suggestedActions: [],
      payload: null,
    }));
    expect(message).toContain("rejected by the Blender MCP service");
    expect(message).toContain("nothing was applied");
    expect(message).not.toContain("MCP extension op(s) failed");
  });

  // 运行期投影错误是 normalizeRuntimeError 的普通对象（非 V2ApiError 实例），
  // 同一张表必须也对它生效——否则节点上的红字仍漏出后端原始 message。
  it("maps a normalized runtime error object (node failure surface)", () => {
    expect(
      canvasAuthoringErrorMessage({
        code: "scene3d_blender_unavailable",
        message: "Blender is not available: probe failed",
        stage: "execute",
      }),
    ).toContain("Blender is not installed");

    // 未知 code 保留原始 message 可查询，不吞掉
    expect(canvasAuthoringErrorMessage({ code: "some_new_code", message: "backend said why" })).toBe(
      "backend said why",
    );
  });
});
