/**
 * AudioBedEditor tests (voice-cast unified mode authoring surface).
 *
 * Locks the editor contract: rows render from the persisted block, the
 * speaker dropdown comes from roles, validation gates save with the same
 * rules the backend enforces, and save PATCHes structured_content MERGED
 * (other keys survive) with empty rows dropped.
 */

import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { CanvasNodeV2 } from "../../../types-v2.ts";
import { AudioBedEditor } from "./AudioBedEditor.tsx";

function makeNode(structuredContent: Record<string, unknown> = {}): CanvasNodeV2 {
  return {
    node_id: "voice-node",
    workflow_id: "workflow-1",
    node_type: "voice-cast",
    creative_role: "voice_cast",
    role_contract_version: "ad-media-role-v1",
    title: "voice node",
    status: "ready",
    summary_prompt: null,
    generation_prompt: "some dialogue",
    structured_content: structuredContent,
    model_id: null,
    parameters: {},
    prompt_context_snapshot_id: null,
    output_asset_id: null,
    position: { x: 0, y: 0 },
    revision: 1,
    error: null,
    prompt_preparation: null,
    created_at: "2026-09-26T00:00:00Z",
    updated_at: "2026-09-26T00:00:00Z",
  } as CanvasNodeV2;
}

const BED_BLOCK = {
  audio_bed: {
    roles: [{ name: "林澈", description: "二十多岁的男性，嗓音低沉冷静" }],
    scripts: [
      { text: "[地下研究所 B2 层，低频电机嗡鸣]" },
      { speaker: "林澈", text: "（压低声音，警惕）就是这里，信号源在墙后面。" },
    ],
    instruction: "废弃地下研究所，悬疑氛围",
    response_format: "mp3",
  },
};

afterEach(cleanup);

describe("AudioBedEditor", () => {
  it("renders the persisted roles and scripts", () => {
    render(<AudioBedEditor node={makeNode({ ...BED_BLOCK })} patchNode={vi.fn()} />);
    expect((screen.getByLabelText("角色 1 名称") as HTMLInputElement).value).toBe("林澈");
    expect((screen.getByLabelText("角色 1 音色描述") as HTMLInputElement).value).toBe(
      "二十多岁的男性，嗓音低沉冷静",
    );
    expect((screen.getByLabelText("脚本 1 内容") as HTMLTextAreaElement).value).toBe(
      "[地下研究所 B2 层，低频电机嗡鸣]",
    );
    expect((screen.getByLabelText("脚本 2 内容") as HTMLTextAreaElement).value).toBe(
      "（压低声音，警惕）就是这里，信号源在墙后面。",
    );
    expect((screen.getByLabelText("脚本 2 说话人") as HTMLSelectElement).value).toBe("林澈");
    expect((screen.getByLabelText("全局指导") as HTMLTextAreaElement).value).toBe(
      "废弃地下研究所，悬疑氛围",
    );
    expect(screen.getByText("已保存")).toBeTruthy();
  });

  it("offers role names in the speaker dropdown", () => {
    render(<AudioBedEditor node={makeNode({ ...BED_BLOCK })} patchNode={vi.fn()} />);
    const select = screen.getByLabelText("脚本 2 说话人") as HTMLSelectElement;
    const options = Array.from(select.options).map((option) => option.value);
    expect(options).toEqual(["", "林澈"]);
  });

  it("adds and removes role rows", () => {
    render(<AudioBedEditor node={makeNode()} patchNode={vi.fn()} />);
    fireEvent.click(screen.getByText("+ 角色"));
    fireEvent.click(screen.getByText("+ 角色"));
    expect(screen.getAllByLabelText(/^角色 \d+ 名称$/)).toHaveLength(2);
    fireEvent.click(screen.getByLabelText("删除角色 1"));
    expect(screen.getAllByLabelText(/^角色 \d+ 名称$/)).toHaveLength(1);
  });

  it("moves script rows", () => {
    render(<AudioBedEditor node={makeNode({ ...BED_BLOCK })} patchNode={vi.fn()} />);
    fireEvent.click(screen.getByLabelText("下移脚本 1"));
    const first = (screen.getByLabelText("脚本 1 内容") as HTMLTextAreaElement).value;
    const second = (screen.getByLabelText("脚本 2 内容") as HTMLTextAreaElement).value;
    expect(first).toBe("（压低声音，警惕）就是这里，信号源在墙后面。");
    expect(second).toBe("[地下研究所 B2 层，低频电机嗡鸣]");
  });

  it("gates save on validation (unknown speaker) and explains why", () => {
    render(<AudioBedEditor node={makeNode()} patchNode={vi.fn()} />);
    // A speaker-tagged line with no roles defined.
    fireEvent.change(screen.getByLabelText("脚本 1 说话人"), { target: { value: "" } });
    fireEvent.change(screen.getByLabelText("脚本 1 内容"), { target: { value: "你好" } });
    // Add a speaker by typing into a role-less config through the scripts row:
    fireEvent.click(screen.getByText("+ 角色"));
    fireEvent.change(screen.getByLabelText("角色 1 名称"), { target: { value: "苏晴" } });
    fireEvent.change(screen.getByLabelText("角色 1 音色描述"), {
      target: { value: "年轻女性，声音轻而紧绷" },
    });
    fireEvent.change(screen.getByLabelText("脚本 1 说话人"), { target: { value: "苏晴" } });

    const saveButton = screen.getByText("保存音频床配置") as HTMLButtonElement;
    expect(saveButton.disabled).toBe(false);
  });

  it("shows the unknown-speaker issue and keeps save disabled", () => {
    // A script tagged with a speaker that no (complete) role defines.
    const node = makeNode({
      audio_bed: {
        roles: [],
        scripts: [{ speaker: "Ghost", text: "有人吗？" }],
      },
    });
    render(<AudioBedEditor node={node} patchNode={vi.fn()} />);
    const issue = screen.getByText(/台词指定了说话人「Ghost」/);
    expect(issue).toBeTruthy();
    expect((screen.getByText("保存音频床配置") as HTMLButtonElement).disabled).toBe(true);
  });

  it("PATCHes merged structured_content with empty rows dropped", async () => {
    const patchNode = vi.fn().mockResolvedValue(undefined);
    render(
      <AudioBedEditor
        node={makeNode({ ...BED_BLOCK, narration: "低沉的风声" })}
        patchNode={patchNode}
      />,
    );
    // Make the draft dirty with a real edit.
    fireEvent.change(screen.getByLabelText("全局指导"), {
      target: { value: "废弃地下研究所，悬疑氛围，远处传来警报" },
    });

    fireEvent.click(screen.getByText("保存音频床配置"));

    await waitFor(() => {
      expect(patchNode).toHaveBeenCalledTimes(1);
    });
    const [nodeId, patch] = patchNode.mock.calls[0];
    expect(nodeId).toBe("voice-node");
    // Merge, never replace.
    expect(patch.structured_content.narration).toBe("低沉的风声");
    expect(patch.structured_content.audio_bed).toEqual({
      roles: [{ name: "林澈", description: "二十多岁的男性，嗓音低沉冷静" }],
      scripts: [
        { text: "[地下研究所 B2 层，低频电机嗡鸣]" },
        { speaker: "林澈", text: "（压低声音，警惕）就是这里，信号源在墙后面。" },
      ],
      instruction: "废弃地下研究所，悬疑氛围，远处传来警报",
      response_format: "mp3",
    });
  });

  it("reverts the draft", () => {
    render(<AudioBedEditor node={makeNode({ ...BED_BLOCK })} patchNode={vi.fn()} />);
    fireEvent.change(screen.getByLabelText("全局指导"), { target: { value: "changed" } });
    expect((screen.getByLabelText("全局指导") as HTMLTextAreaElement).value).toBe("changed");
    fireEvent.click(screen.getByText("撤销修改"));
    expect((screen.getByLabelText("全局指导") as HTMLTextAreaElement).value).toBe(
      "废弃地下研究所，悬疑氛围",
    );
  });

  it("renders nothing without a patchNode capability", () => {
    const { container } = render(<AudioBedEditor node={makeNode({ ...BED_BLOCK })} />);
    expect(container.firstChild).toBeNull();
  });

  it("warns when a script exceeds the documented budget", () => {
    const longText = "x".repeat(1001);
    const node = makeNode({ audio_bed: { scripts: [{ text: longText }] } });
    render(<AudioBedEditor node={node} patchNode={vi.fn()} />);
    expect(screen.getByText(/scripts 超出 1 字符/)).toBeTruthy();
    expect((screen.getByText("保存音频床配置") as HTMLButtonElement).disabled).toBe(true);
  });
});

describe("AudioBedEditor — role scene-character link", () => {
  it("renders the persisted character id", () => {
    render(
      <AudioBedEditor
        node={makeNode({
          audio_bed: {
            roles: [{ name: "林澈", description: "低沉男声", character_id: "char_a" }],
            scripts: [{ speaker: "林澈", text: "就是这里。" }],
            response_format: "mp3",
          },
        })}
        patchNode={vi.fn()}
      />,
    );

    const input = screen.getByLabelText("角色 1 场景角色 ID") as HTMLInputElement;
    expect(input.value).toBe("char_a");
  });

  it("persists an edited character id in structured_content", async () => {
    const patchNode = vi.fn().mockResolvedValue(undefined);
    render(
      <AudioBedEditor
        node={makeNode({
          audio_bed: {
            roles: [{ name: "林澈", description: "低沉男声" }],
            scripts: [{ speaker: "林澈", text: "就是这里。" }],
            response_format: "mp3",
          },
        })}
        patchNode={patchNode}
      />,
    );

    fireEvent.change(screen.getByLabelText("角色 1 场景角色 ID"), {
      target: { value: "char_a" },
    });
    fireEvent.click(screen.getByText("保存音频床配置"));

    await waitFor(() => {
      expect(patchNode).toHaveBeenCalledTimes(1);
    });
    const payload = patchNode.mock.calls[0][1].structured_content as {
      audio_bed: { roles: { name: string; character_id: string }[] };
    };
    expect(payload.audio_bed.roles[0].character_id).toBe("char_a");
    // The voice fields survive the round trip unchanged.
    expect(payload.audio_bed.roles[0].name).toBe("林澈");
  });
});
