/**
 * 分镜预演流程模板（playbook §2 的标准顺序，一键搭骨架）。
 *
 * 一次创建：流程指引(text) → Script → 3D Previs(scene-3d) → Voice Cast →
 * Editing，并把 Script 的文本上下文绑到 scene-3d（LLM 场景生成的描述来源）
 * 与 voice-cast（台词来源）。预演片段/分镜节点不预建——它们由导演台渲染后
 * 逐镜发布产生，数量由剧本决定。
 *
 * 只用既有 REST 能力边界（agentCanvasApi），不改后端；每个创建都带幂等键。
 */

import { agentCanvasApi } from "../../../api/agentCanvasApi.ts";
import { createOperationKey } from "../../../api/operationKey.ts";
import type { CanvasNodeCreateRequestV2, CanvasPositionV2 } from "../../../types-v2.ts";

export const PREVIS_TEMPLATE_GUIDE = [
  "分镜预演流程（六步，对应 docs/plans/agent-autonomous-production-playbook.md §2）：",
  "1. 运行 Script 节点，让 LLM 写出 5-6 场戏的剧本（每场含 camera_atmosphere/action/dialogue/sfx/estimated_sec）。",
  "2. 运行 3D Previs：从剧本派生镜头表与走位（每镜角色要有位移），渲染 animatic。",
  "3. 在导演台逐镜「发布预演片段」——每个片段带 5 张关键帧上画布。",
  "4. 从每个预演片段建分镜节点（video_reference），把该场对白填进 dialogue 字段。",
  "5. 把剧本台词填进 Voice Cast 的台词床（roles + scripts），运行生成配音。",
  "6. 时间线排布镜头/字幕/配音后，在 Editing 节点导出成片。",
  "提示：先用项目体检面板确认没有缺口，再批量生成；flash 限免期一次只跑一个视频任务。",
].join("\n");

const SCREENPLAY_PROMPT_GUIDANCE = [
  "写一个 5-6 场戏的短剧剧本（schema_version=adc_v2, node_type=Script）。",
  "每场 screenplay_item 必须含：scene_heading、location、time、camera_atmosphere（镜头与氛围，",
  "可引用影视参考）、action（具体动作与调度）、dialogue（角色名+台词，至少两场有对白）、",
  "sfx（音效清单）、estimated_sec（8-20 秒）。总时长控制在 30-60 秒。",
].join("");

const SCENE3D_SUMMARY =
  "根据剧本搭建 3D 场景与镜头表：外景/走廊两级空间，每镜角色有位移与朝向变化，切点空间锚衔接。";

function guideNode(position: CanvasPositionV2): CanvasNodeCreateRequestV2 {
  return {
    node_type: "text",
    creative_role: "general_text",
    title: "流程指引 · 分镜预演",
    structured_content: { content: PREVIS_TEMPLATE_GUIDE },
    position,
  };
}

function scriptNode(position: CanvasPositionV2): CanvasNodeCreateRequestV2 {
  return {
    node_type: "script",
    creative_role: "script",
    title: "Script · 剧本",
    generation_prompt: SCREENPLAY_PROMPT_GUIDANCE,
    position,
  };
}

function scene3dNode(position: CanvasPositionV2): CanvasNodeCreateRequestV2 {
  return {
    node_type: "scene-3d",
    creative_role: "scene_3d_previs",
    title: "3D Previs · 分镜预演",
    summary_prompt: SCENE3D_SUMMARY,
    // generation_prompt 留空：scene-3d 的场景描述优先读节点自身提示词，
    // 留空才能落到绑定的剧本文本（script → scene-3d text_context）。
    generation_prompt: null,
    position,
  };
}

function voiceCastNode(position: CanvasPositionV2): CanvasNodeCreateRequestV2 {
  return {
    node_type: "voice-cast",
    creative_role: "voice_cast",
    title: "Voice Cast · 台词床",
    // 台词床留空待填：空床运行会显式失败，好过回退朗读整份剧本。
    // 剧本 ready 后配 roles + scripts（逐句台词），项目体检会持续提醒。
    position,
  };
}

function editingNode(position: CanvasPositionV2): CanvasNodeCreateRequestV2 {
  return {
    node_type: "editing",
    creative_role: "editing",
    title: "成片剪辑",
    position,
  };
}

export interface PrevisTemplateOptions {
  origin?: { x: number; y: number };
}

export interface PrevisTemplateResult {
  guideNodeId: string;
  scriptNodeId: string;
  scene3dNodeId: string;
  voiceCastNodeId: string;
  editingNodeId: string;
  bindingIds: string[];
}

export interface PrevisTemplateApi {
  createAgentCanvasNode: typeof agentCanvasApi.createAgentCanvasNode;
  createAgentCanvasBinding: typeof agentCanvasApi.createAgentCanvasBinding;
}

const COLUMN_GAP = 280;

/**
 * 搭建分镜预演流程骨架。任一步失败即抛出（调用方展示错误）；
 * 已创建的节点保留——重试前先删掉半成品，或直接在画布上补齐。
 */
export async function createPrevisPipelineTemplate(
  workflowId: string,
  options: PrevisTemplateOptions = {},
  api: PrevisTemplateApi = agentCanvasApi,
): Promise<PrevisTemplateResult> {
  const origin = options.origin ?? { x: 80, y: 120 };
  const at = (index: number): CanvasPositionV2 => ({
    x: origin.x + index * COLUMN_GAP,
    y: origin.y,
  });

  const created: string[] = [];
  const create = async (request: CanvasNodeCreateRequestV2): Promise<string> => {
    const response = await api.createAgentCanvasNode(workflowId, request);
    const nodeId = response.value.node?.node_id;
    if (!nodeId) throw new Error(`节点创建失败：${request.title ?? request.node_type}`);
    created.push(nodeId);
    return nodeId;
  };

  const guideNodeId = await create(guideNode(at(0)));
  const scriptNodeId = await create(scriptNode(at(1)));
  const scene3dNodeId = await create(scene3dNode(at(2)));
  const voiceCastNodeId = await create(voiceCastNode(at(3)));
  const editingNodeId = await create(editingNode(at(4)));

  const bindingIds: string[] = [];
  const bindTextContext = async (targetNodeId: string): Promise<void> => {
    const response = await api.createAgentCanvasBinding(workflowId, {
      source: { kind: "node_output", source_node_id: scriptNodeId },
      target_node_id: targetNodeId,
      input_role: "text_context",
      enabled: true,
      order: 0,
    });
    const bindingId = response.value.binding?.binding_id;
    if (!bindingId) throw new Error(`绑定创建失败：script → ${targetNodeId}`);
    bindingIds.push(bindingId);
  };
  await bindTextContext(scene3dNodeId);
  await bindTextContext(voiceCastNodeId);

  return {
    guideNodeId,
    scriptNodeId,
    scene3dNodeId,
    voiceCastNodeId,
    editingNodeId,
    bindingIds,
  };
}

/** 幂等键前缀，供调用方在重试场景使用。 */
export const PREVIS_TEMPLATE_OPERATION_PREFIX = "previs-template";
export { createOperationKey as previsTemplateOperationKey };
