/**
 * previsPipelineTemplate 单测：锁定模板创建的节点/绑定形状。
 *
 * 契约（playbook §2 顺序）：5 个节点（指引/剧本/预演/配音/剪辑）、
 * 2 条 script 的 text_context 绑定；不预建预演片段与分镜节点——
 * 它们由导演台渲染后逐镜发布产生。scene-3d 的 generation_prompt 必须为空，
 * 场景描述才能落到绑定的剧本文本。
 */

import { describe, expect, it, vi } from "vitest";

import {
  createPrevisPipelineTemplate,
  PREVIS_TEMPLATE_GUIDE,
  type PrevisTemplateApi,
} from "./previsPipelineTemplate.ts";

function fakeApi() {
  let nodeSeq = 0;
  let bindingSeq = 0;
  const nodeRequests: Array<Record<string, unknown>> = [];
  const bindingRequests: Array<Record<string, unknown>> = [];
  const api = {
    createAgentCanvasNode: vi.fn(async (_workflowId: string, request: Record<string, unknown>) => {
      nodeRequests.push(request);
      nodeSeq += 1;
      return {
        value: {
          node: { node_id: `node_${nodeSeq}` },
          workflow: { revision: nodeSeq },
        },
        etag: `"workflow-wf-v${nodeSeq}"`,
      };
    }),
    createAgentCanvasBinding: vi.fn(async (_workflowId: string, request: Record<string, unknown>) => {
      bindingRequests.push(request);
      bindingSeq += 1;
      return {
        value: { binding: { binding_id: `binding_${bindingSeq}` }, workflow: { revision: 10 + bindingSeq } },
        etag: `"workflow-wf-v${10 + bindingSeq}"`,
      };
    }),
  } as unknown as PrevisTemplateApi & {
    createAgentCanvasNode: ReturnType<typeof vi.fn>;
    createAgentCanvasBinding: ReturnType<typeof vi.fn>;
  };
  return { api, nodeRequests, bindingRequests };
}

describe("createPrevisPipelineTemplate", () => {
  it("创建 5 个节点：指引/剧本/预演/配音/剪辑，不预建片段与分镜", async () => {
    const { api, nodeRequests } = fakeApi();
    const result = await createPrevisPipelineTemplate("wf", { origin: { x: 100, y: 200 } }, api);
    expect(nodeRequests).toHaveLength(5);
    expect(result.guideNodeId).toBe("node_1");
    expect(result.scriptNodeId).toBe("node_2");
    expect(result.scene3dNodeId).toBe("node_3");
    expect(result.voiceCastNodeId).toBe("node_4");
    expect(result.editingNodeId).toBe("node_5");
    const types = nodeRequests.map((request) => request.node_type);
    expect(types).toEqual(["text", "script", "scene-3d", "voice-cast", "editing"]);
    // 指引节点带六步文本
    const guide = nodeRequests[0] as { structured_content?: { content?: string } };
    expect(guide.structured_content?.content).toBe(PREVIS_TEMPLATE_GUIDE);
    // 位置按列展开
    expect((nodeRequests[0] as { position?: { x: number } }).position?.x).toBe(100);
    expect((nodeRequests[4] as { position?: { x: number } }).position?.x).toBe(100 + 4 * 280);
  });

  it("script 带剧本 schema 提示；scene-3d 的 generation_prompt 留空", async () => {
    const { api, nodeRequests } = fakeApi();
    await createPrevisPipelineTemplate("wf", {}, api);
    const script = nodeRequests[1] as { generation_prompt?: string };
    expect(script.generation_prompt).toContain("screenplay_item");
    const scene3d = nodeRequests[2] as { generation_prompt?: string | null; summary_prompt?: string };
    expect(scene3d.generation_prompt ?? null).toBeNull();
    expect(scene3d.summary_prompt).toContain("镜头表");
  });

  it("绑定两条 script 的 text_context：scene-3d 与 voice-cast", async () => {
    const { api, bindingRequests } = fakeApi();
    const result = await createPrevisPipelineTemplate("wf", {}, api);
    expect(bindingRequests).toHaveLength(2);
    for (const request of bindingRequests) {
      expect(request.input_role).toBe("text_context");
      expect((request.source as { source_node_id: string }).source_node_id).toBe(result.scriptNodeId);
    }
    expect(bindingRequests.map((request) => request.target_node_id)).toEqual([
      result.scene3dNodeId,
      result.voiceCastNodeId,
    ]);
  });

  it("节点创建失败时抛出，不继续建绑定", async () => {
    const { api } = fakeApi();
    (api.createAgentCanvasNode as ReturnType<typeof vi.fn>)
      .mockImplementationOnce(async () => {
        throw new Error("boom");
      });
    await expect(createPrevisPipelineTemplate("wf", {}, api)).rejects.toThrow("boom");
    expect(api.createAgentCanvasBinding).not.toHaveBeenCalled();
  });
});
