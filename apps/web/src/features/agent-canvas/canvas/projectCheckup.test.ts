/**
 * projectCheckup 单测：锁定"缺口/静默降级/对账"三类发现的触发条件。
 *
 * 场景取自《静海攻防》v1→v6 复盘的真实形态（playbook §1 表格）：
 * 身份层被绕过、voice-cast 未配台词将回退朗读、预演片段与分镜数量不齐。
 */

import { describe, expect, it } from "vitest";

import type {
  AgentCanvasWorkflowV2,
  CanvasBindingV2,
  CanvasNodeV2,
} from "../../../types-v2.ts";
import { buildProjectCheckup } from "./projectCheckup.ts";

function node(overrides: Partial<CanvasNodeV2> & { node_id: string }): CanvasNodeV2 {
  return {
    workflow_id: "wf",
    node_type: "text",
    creative_role: "general_text",
    title: overrides.node_id,
    status: "draft",
    execution_mode: "generative",
    summary_prompt: null,
    generation_prompt: null,
    structured_content: {},
    model_id: null,
    model_selection_mode: "default",
    model_ref: null,
    model_summary: null,
    parameters: {},
    metadata: {},
    parameter_provenance: {},
    prompt_context_snapshot_id: null,
    output_asset_id: null,
    output_asset_version_id: null,
    latest_attempt: null,
    position: { x: 0, y: 0 },
    revision: 1,
    updated_at: "2026-10-05T00:00:00Z",
    created_at: "2026-10-05T00:00:00Z",
    ...overrides,
  } as CanvasNodeV2;
}

function binding(overrides: Partial<CanvasBindingV2> & { binding_id: string }): CanvasBindingV2 {
  return {
    workflow_id: "wf",
    source: { kind: "node_output", source_node_id: "node_a" },
    target_node_id: "node_b",
    input_role: "text_context",
    enabled: true,
    order: 0,
    label: null,
    metadata: {},
    created_at: "2026-10-05T00:00:00Z",
    updated_at: "2026-10-05T00:00:00Z",
    ...overrides,
  } as CanvasBindingV2;
}

function workflow(overrides: Partial<AgentCanvasWorkflowV2> = {}): AgentCanvasWorkflowV2 {
  return {
    workflow_id: "wf",
    project_id: "proj",
    workflow_schema_version: 2,
    canvas_model: "agent_canvas_v1",
    revision: 1,
    layout_revision: 1,
    nodes: [],
    bindings: [],
    assets: [],
    active_style_skill: null,
    ...overrides,
  };
}

function ids(findings: ReturnType<typeof buildProjectCheckup>): string[] {
  return findings.map((finding) => finding.id);
}

describe("buildProjectCheckup", () => {
  it("空画布给一条 info 引导", () => {
    const findings = buildProjectCheckup(workflow());
    expect(findings).toHaveLength(1);
    expect(findings[0].id).toBe("empty");
    expect(findings[0].severity).toBe("info");
  });

  it("失败节点报 fail，并给出单镜重试建议", () => {
    const findings = buildProjectCheckup(workflow({
      nodes: [node({ node_id: "n1", status: "failed", node_type: "video", creative_role: "storyboard_video" })],
    }));
    const finding = findings.find((item) => item.id === "failed-nodes");
    expect(finding?.severity).toBe("fail");
    expect(finding?.remedy).toContain("单镜重试");
  });

  it("有分镜但无三视图/场景图时报身份层缺口", () => {
    const findings = buildProjectCheckup(workflow({
      nodes: [node({ node_id: "sb1", node_type: "video", creative_role: "storyboard_video", status: "ready" })],
    }));
    expect(ids(findings)).toContain("identity-bypassed");
    expect(ids(findings)).toContain("scene-board-missing");
  });

  it("有 turnaround 与 scene 节点时不报身份层缺口", () => {
    const findings = buildProjectCheckup(workflow({
      nodes: [
        node({ node_id: "sb1", node_type: "video", creative_role: "storyboard_video", status: "ready" }),
        node({
          node_id: "ta1",
          node_type: "image",
          creative_role: "character",
          status: "ready",
          structured_content: { character_asset_kind: "turnaround" },
        }),
        node({ node_id: "scb1", node_type: "image", creative_role: "scene", status: "ready" }),
      ],
    }));
    expect(ids(findings)).not.toContain("identity-bypassed");
    expect(ids(findings)).not.toContain("scene-board-missing");
  });

  it("voice-cast 没有 audio_bed/dialogue_lines 时警告回退朗读", () => {
    const findings = buildProjectCheckup(workflow({
      nodes: [
        node({ node_id: "vc1", node_type: "voice-cast", creative_role: "voice_cast", status: "draft" }),
      ],
    }));
    const finding = findings.find((item) => item.id === "voicecast-unconfigured");
    expect(finding?.severity).toBe("warn");
    expect(finding?.detail).toContain("回退朗读");
  });

  it("voice-cast 配了台词床则不警告，QA warn 单独列出", () => {
    const findings = buildProjectCheckup(workflow({
      nodes: [
        node({
          node_id: "vc1",
          node_type: "voice-cast",
          creative_role: "voice_cast",
          status: "ready",
          structured_content: {
            audio_bed: { roles: [], scripts: [{ text: "台词" }] },
            voicecast_qa_report: { warned: ["speech_loudness_target"] },
          },
        }),
      ],
    }));
    expect(ids(findings)).not.toContain("voicecast-unconfigured");
    expect(ids(findings)).toContain("voicecast-qa");
  });

  it("剧本有对白而分镜 dialogue 全空时报台词断层", () => {
    const screenplay = JSON.stringify({
      screenplay_items: [
        { dialogue: [{ character: "甲", line: "上弹。" }] },
        { dialogue: [] },
      ],
    });
    const findings = buildProjectCheckup(workflow({
      nodes: [
        node({ node_id: "script1", node_type: "script", creative_role: "script", status: "ready", structured_content: { content: screenplay } }),
        node({ node_id: "sb1", node_type: "video", creative_role: "storyboard_video", status: "ready", structured_content: { dialogue: "" } }),
      ],
    }));
    const finding = findings.find((item) => item.id === "dialogue-not-carried");
    expect(finding?.severity).toBe("warn");
    expect(finding?.detail).toContain("1 场有对白");
  });

  it("预演片段与分镜数量不齐、分镜未连预演时都报", () => {
    const findings = buildProjectCheckup(workflow({
      nodes: [
        node({ node_id: "clip1", node_type: "video", creative_role: "scene_3d_previs_clip", status: "ready" }),
        node({ node_id: "clip2", node_type: "video", creative_role: "scene_3d_previs_clip", status: "ready" }),
        node({ node_id: "sb1", node_type: "video", creative_role: "storyboard_video", status: "ready" }),
      ],
      bindings: [
        binding({
          binding_id: "b1",
          source: { kind: "node_output", source_node_id: "clip1" },
          target_node_id: "sb1",
          input_role: "video_reference",
        }),
      ],
    }));
    expect(ids(findings)).toContain("clip-storyboard-count");
    expect(ids(findings)).toContain("identity-bypassed");
    expect(ids(findings)).not.toContain("storyboard-not-anchored");
  });

  it("分镜没连任何预演片段时报未锚定", () => {
    const findings = buildProjectCheckup(workflow({
      nodes: [
        node({ node_id: "clip1", node_type: "video", creative_role: "scene_3d_previs_clip", status: "ready" }),
        node({ node_id: "sb1", node_type: "video", creative_role: "storyboard_video", status: "ready" }),
      ],
      bindings: [],
    }));
    expect(ids(findings)).toContain("storyboard-not-anchored");
  });

  it("导演台 consistency error 报 fail，warning 报提醒", () => {
    const withIssues = (severity: string) => buildProjectCheckup(workflow({
      nodes: [
        node({
          node_id: "s3d",
          node_type: "scene-3d",
          creative_role: "scene_3d_previs",
          status: "ready",
          structured_content: {
            scene_script: { shots: [{ id: "s1" }] },
            scene3d_consistency: { issues: [{ severity, message: "角色未绑定资产" }] },
          },
        }),
      ],
    }));
    expect(withIssues("error").find((item) => item.id === "scene3d-consistency-errors")?.severity).toBe("fail");
    expect(withIssues("warning").find((item) => item.id === "scene3d-consistency-warnings")?.severity).toBe("warn");
  });

  it("导出失败与跳过输入分别报 fail/warn", () => {
    const findings = buildProjectCheckup(workflow({
      nodes: [
        node({
          node_id: "edit1",
          node_type: "editing",
          creative_role: "editing",
          status: "ready",
          structured_content: {
            last_successful_export: { status: "failed", error: "ffmpeg failed", skipped_inputs: [{ node_id: "sb9" }] },
          },
        }),
      ],
    }));
    expect(ids(findings)).toContain("export-failed");
    expect(ids(findings)).toContain("export-skipped-inputs");
  });

  it("一切正常时给一条 ok", () => {
    const findings = buildProjectCheckup(workflow({
      active_style_skill: { skill_id: "s1" } as AgentCanvasWorkflowV2["active_style_skill"],
      nodes: [node({ node_id: "t1", status: "ready" })],
    }));
    expect(findings).toHaveLength(1);
    expect(findings[0].severity).toBe("ok");
  });
});

describe("buildProjectCheckup · 导出后置验收", () => {
  const editingWith = (acceptance: unknown) =>
    node({
      node_id: "edit1",
      node_type: "editing",
      creative_role: "editing",
      status: "ready",
      structured_content: {
        last_successful_export: {
          export_id: "export_1",
          status: "completed",
          manifest_revision: 3,
          fingerprint: "sha256:" + "0".repeat(64),
          ready_video_node_ids: [],
          skipped_inputs: [],
          bgm_node_id: null,
          output_asset_id: "asset_x",
          error: null,
          started_at: null,
          finished_at: null,
          acceptance,
        },
      },
    });

  it("acceptance fail/warn 逐条上浮，pass 不上浮", () => {
    const findings = buildProjectCheckup(workflow({
      nodes: [editingWith({
        checks: [
          { check: "subtitles_burned", status: "fail", detail: "cue 3.4s 没有文字" },
          { check: "cue_windows_audible", status: "warn", detail: "7.0s 窗口接近静音" },
          { check: "cuts_vs_entries", status: "pass", detail: "全部命中" },
        ],
        ran_at: null,
      })],
    }));
    const failFinding = findings.find((item) => item.id === "acceptance-subtitles_burned");
    expect(failFinding?.severity).toBe("fail");
    expect(failFinding?.detail).toContain("没有文字");
    const warnFinding = findings.find((item) => item.id === "acceptance-cue_windows_audible");
    expect(warnFinding?.severity).toBe("warn");
    expect(findings.find((item) => item.id === "acceptance-cuts_vs_entries")).toBeUndefined();
  });

  it("验收全部 skipped 时提示媒体质量未经过检查", () => {
    const findings = buildProjectCheckup(workflow({
      nodes: [editingWith({
        checks: [
          { check: "streams", status: "skipped", detail: "ffprobe 不可用" },
          { check: "duration_alignment", status: "skipped", detail: "ffprobe 不可用" },
        ],
        ran_at: null,
      })],
    }));
    const finding = findings.find((item) => item.id === "acceptance-all-skipped");
    expect(finding?.severity).toBe("warn");
    expect(finding?.detail).toContain("未经过检查");
  });
});
