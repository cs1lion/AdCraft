/**
 * 项目体检（流程协同，纯前端快照检查）。
 *
 * 动机（docs/plans/agent-autonomous-production-playbook.md §4）：真实用户会
 * 在中途发现"缺身份资产 / 配音床没配 / 静默降级没人看"，agent 一口气跑到成片
 * 才暴露。本模块把系统已经算出来、但埋在 structured_content 里的报告，加上
 * 几项跨节点对账，收敛成一张可扫读的发现清单。
 *
 * 只读快照、只给建议，不 gate 任何既有流程；媒体级验收（切点/RMS/烧录像素）
 * 需要 ffmpeg，后续由导出后置钩子承担，不在前端范围。
 */

import type { AgentCanvasWorkflowV2, CanvasNodeV2 } from "../../../types-v2.ts";

export type CheckupSeverity = "fail" | "warn" | "info" | "ok";

export interface ProjectCheckupFinding {
  id: string;
  severity: CheckupSeverity;
  title: string;
  detail: string;
  remedy?: string;
}

interface SceneScriptShots {
  shots?: Array<Record<string, unknown>>;
}

function asRecord(value: unknown): Record<string, unknown> | null {
  return value && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null;
}

function structured(node: CanvasNodeV2): Record<string, unknown> {
  return asRecord(node.structured_content) ?? {};
}

function nodeTitle(node: CanvasNodeV2): string {
  return node.title || node.node_id;
}

function parseScreenplayDialogueCount(node: CanvasNodeV2): number {
  const raw = structured(node).content;
  if (typeof raw !== "string" || !raw.trim()) return 0;
  try {
    const parsed = asRecord(JSON.parse(raw));
    const items = parsed?.screenplay_items;
    if (!Array.isArray(items)) return 0;
    return items.filter((item) => {
      const dialogues = asRecord(item)?.dialogue;
      return Array.isArray(dialogues) && dialogues.length > 0;
    }).length;
  } catch {
    return 0;
  }
}

function storyboardDialogueCount(node: CanvasNodeV2): number {
  const dialogue = structured(node).dialogue;
  return typeof dialogue === "string" && dialogue.trim() ? 1 : 0;
}

/**
 * 从工作流快照构建体检发现清单。顺序：失败 → 缺口 → 静默降级 → 对账。
 * 空画布返回一条 info，保证面板永远有可读内容。
 */
export function buildProjectCheckup(workflow: AgentCanvasWorkflowV2): ProjectCheckupFinding[] {
  const findings: ProjectCheckupFinding[] = [];
  const nodes = workflow.nodes;
  if (nodes.length === 0) {
    return [{
      id: "empty",
      severity: "info",
      title: "画布还是空的",
      detail: "可以用「分镜预演流程」模板一键搭好节点骨架，或从对话/一句话开始。",
    }];
  }

  const byRole = (role: string) => nodes.filter((node) => node.creative_role === role);
  const storyboards = byRole("storyboard_video");
  const previsClips = byRole("scene_3d_previs_clip");
  const scene3d = nodes.find((node) => node.node_type === "scene-3d");
  const script = nodes.find((node) => node.node_type === "script");
  const voiceCast = nodes.find((node) => node.node_type === "voice-cast");
  const editing = nodes.find((node) => node.node_type === "editing");

  // ---- 1. 失败节点 ------------------------------------------------------
  const failed = nodes.filter((node) => node.status === "failed");
  if (failed.length > 0) {
    findings.push({
      id: "failed-nodes",
      severity: "fail",
      title: `${failed.length} 个节点生成失败`,
      detail: failed.map(nodeTitle).join("、"),
      remedy: "看节点错误详情；provider 限流（429）等 1-2 分钟单镜重试，不要整批并发。",
    });
  }

  // ---- 2. 流程缺口（playbook §2 身份层）---------------------------------
  if (!workflow.active_style_skill) {
    findings.push({
      id: "style-skill",
      severity: "warn",
      title: "风格技能未锁定",
      detail: "项目还没选定风格参考，各节点会各按各的默认风格生成。",
      remedy: "先锁定风格技能，再开始素材生成。",
    });
  }
  const identityKinds = new Set(["storyboard_video", "scene_3d_previs_clip"]);
  const producesFootage = nodes.some((node) => identityKinds.has(node.creative_role));
  const hasTurnaround = nodes.some(
    (node) => node.creative_role === "character"
      && structured(node).character_asset_kind === "turnaround",
  );
  const hasSceneBoard = nodes.some((node) => node.creative_role === "scene");
  if (producesFootage && !hasTurnaround) {
    findings.push({
      id: "identity-bypassed",
      severity: "warn",
      title: "身份层被绕过：没有人物三视图",
      detail: "已有分镜/预演片段节点，但没有 character 节点（turnaround）。角色一致性只剩预演剪影级，换镜会漂。",
      remedy: "补 character_main → character_turnaround，再把它绑进分镜节点。",
    });
  }
  if (producesFootage && !hasSceneBoard) {
    findings.push({
      id: "scene-board-missing",
      severity: "warn",
      title: "场景图缺失",
      detail: "storyboard_video 的参考策略要求 scene_board（3x3 环境板）；缺它时空间/光照锚点缺失。",
      remedy: "补 scene 节点（环境板）并绑入分镜节点。",
    });
  }

  // ---- 3. 导演台与静默降级 ------------------------------------------------
  if (scene3d) {
    const sc = structured(scene3d);
    if (!sc.scene_script) {
      findings.push({
        id: "scene-script-missing",
        severity: "warn",
        title: "导演台还没有 SceneScript",
        detail: `${nodeTitle(scene3d)} 上没有 scene_script；没有它就无法渲染 animatic、无法发布预演片段。`,
        remedy: "在导演台用喊话台/语言搭建搭场景，或运行节点让 LLM 从描述生成。",
      });
    }
    const consistency = asRecord(sc.scene3d_consistency);
    const issues = Array.isArray(consistency?.issues) ? consistency.issues : [];
    const errors = issues.filter((issue) => asRecord(issue)?.severity === "error");
    const warnings = issues.filter((issue) => asRecord(issue)?.severity === "warning");
    if (errors.length > 0) {
      findings.push({
        id: "scene3d-consistency-errors",
        severity: "fail",
        title: `导演台一致性错误 ×${errors.length}`,
        detail: issues
          .filter((issue) => asRecord(issue)?.severity === "error")
          .map((issue) => String(asRecord(issue)?.message ?? ""))
          .join("；"),
        remedy: "按 remedy 修复后再发布预演片段。",
      });
    } else if (warnings.length > 0) {
      findings.push({
        id: "scene3d-consistency-warnings",
        severity: "warn",
        title: `导演台一致性提醒 ×${warnings.length}`,
        detail: warnings.map((issue) => String(asRecord(issue)?.message ?? "")).join("；"),
      });
    }
    const blocking = Array.isArray(sc.scene3d_blocking_continuity)
      ? sc.scene3d_blocking_continuity
      : [];
    if (blocking.length > 0) {
      findings.push({
        id: "blocking-continuity",
        severity: "warn",
        title: `走位连续性问题 ×${blocking.length}`,
        detail: "存在跨切点的姿态/朝向断档；镜头切换会显得跳。",
        remedy: "按报告调整角色 keyframe 或声明 transition intent。",
      });
    }
    const animaticAudio = asRecord(sc.animatic_audio);
    if (animaticAudio && animaticAudio.muxed !== true) {
      const reason = typeof animaticAudio.reason === "string" ? animaticAudio.reason : "";
      if (reason && reason !== "no_speech_binding" && reason !== "keyframes_only_render") {
        findings.push({
          id: "animatic-audio",
          severity: "warn",
          title: "预演音频床没有混入",
          detail: `animatic_audio.reason = ${reason}`,
          remedy: "检查台词资产绑定后重新渲染。",
        });
      }
    }
  }

  // ---- 4. 预演片段 ↔ 分镜 对账 -------------------------------------------
  if (previsClips.length > 0 && storyboards.length !== previsClips.length) {
    findings.push({
      id: "clip-storyboard-count",
      severity: "warn",
      title: `预演片段 ${previsClips.length} 个 / 分镜 ${storyboards.length} 个`,
      detail: "数量不一致：有的镜头还没从预演片段建分镜，或分镜还挂着旧片段。",
      remedy: "每个预演片段建一个分镜节点并连 video_reference。",
    });
  }
  if (storyboards.length > 0) {
    const clipIds = new Set(previsClips.map((node) => node.node_id));
    const unbound = storyboards.filter((node) => {
      const incoming = workflow.bindings.filter(
        (binding) => binding.target_node_id === node.node_id && binding.input_role === "video_reference",
      );
      return !incoming.some((binding) => {
        const source = asRecord(binding.source);
        return typeof source?.source_node_id === "string" && clipIds.has(source.source_node_id);
      });
    });
    if (unbound.length > 0 && previsClips.length > 0) {
      findings.push({
        id: "storyboard-not-anchored",
        severity: "warn",
        title: `${unbound.length} 个分镜没连预演片段`,
        detail: `${unbound.map(nodeTitle).join("、")} 没有 video_reference 指向预演片段，构图将不受预演约束。`,
      });
    }
  }

  // ---- 5. 台词与配音对账 --------------------------------------------------
  const scriptDialogues = script ? parseScreenplayDialogueCount(script) : 0;
  const storyboardDialogues = storyboards.reduce((sum, node) => sum + storyboardDialogueCount(node), 0);
  if (scriptDialogues > 0 && storyboardDialogues === 0 && storyboards.length > 0) {
    findings.push({
      id: "dialogue-not-carried",
      severity: "warn",
      title: "剧本有台词，分镜没挂台词",
      detail: `剧本里 ${scriptDialogues} 场有对白，但分镜节点的 dialogue 字段全空——台词不会进入视频提示词，配音容易另起炉灶。`,
      remedy: "把每场对白填进对应分镜节点的 dialogue 字段。",
    });
  }
  if (voiceCast) {
    const vc = structured(voiceCast);
    const hasBed = Boolean(vc.audio_bed);
    const hasLines = Array.isArray(vc.dialogue_lines) && vc.dialogue_lines.length > 0;
    if (!hasBed && !hasLines) {
      findings.push({
        id: "voicecast-unconfigured",
        severity: "warn",
        title: "Voice Cast 未配置台词",
        detail: "节点上没有 audio_bed / dialogue_lines；直接运行会回退朗读绑定的剧本文本（连动作描述一起读出来）。",
        remedy: "在台词床里配 roles + scripts（或逐行 dialogue_lines），再运行。",
      });
    }
    const qa = asRecord(vc.voicecast_qa_report);
    const warned = Array.isArray(qa?.warned) ? qa.warned : [];
    if (warned.length > 0) {
      findings.push({
        id: "voicecast-qa",
        severity: "warn",
        title: `Voice Cast QA 提醒 ×${warned.length}`,
        detail: warned.join("、"),
      });
    }
  } else if (scriptDialogues > 0) {
    findings.push({
      id: "voicecast-missing",
      severity: "warn",
      title: "没有 Voice Cast 节点",
      detail: "剧本有对白但画布上没有配音节点。",
      remedy: "添加 Voice Cast 并配置台词床。",
    });
  }

  // ---- 6. 成片导出 --------------------------------------------------------
  if (editing) {
    const ec = structured(editing);
    const lastExport = asRecord(ec.last_successful_export);
    if (lastExport?.status === "failed") {
      findings.push({
        id: "export-failed",
        severity: "fail",
        title: "上次成片导出失败",
        detail: String(lastExport.error ?? "未知错误"),
      });
    }
    const skipped = Array.isArray(lastExport?.skipped_inputs) ? lastExport.skipped_inputs : [];
    if (skipped.length > 0) {
      findings.push({
        id: "export-skipped-inputs",
        severity: "warn",
        title: `导出跳过了 ${skipped.length} 个输入`,
        detail: "成片缺素材：被跳过的输入没有进入成片。",
        remedy: "补齐对应节点后重新导出。",
      });
    }
    // 后置验收报告（媒体半场）：fail/warn 逐条上浮，skipped 只在全部被跳过时提示。
    const acceptance = asRecord(lastExport?.acceptance);
    const acceptanceChecks = Array.isArray(acceptance?.checks) ? acceptance.checks : [];
    for (const raw of acceptanceChecks) {
      const check = asRecord(raw);
      if (!check) continue;
      const status = String(check.status);
      const label = String(check.check);
      const detail = String(check.detail ?? "");
      if (status === "fail") {
        findings.push({
          id: `acceptance-${label}`,
          severity: "fail",
          title: `成片验收失败：${label}`,
          detail,
          remedy: "修复后重新导出（验收只记录，不改变导出结果）。",
        });
      } else if (status === "warn") {
        findings.push({
          id: `acceptance-${label}`,
          severity: "warn",
          title: `成片验收提醒：${label}`,
          detail,
        });
      }
    }
    if (
      acceptanceChecks.length > 0
      && acceptanceChecks.every((raw) => asRecord(raw)?.status === "skipped")
    ) {
      findings.push({
        id: "acceptance-all-skipped",
        severity: "warn",
        title: "成片验收全部被跳过",
        detail: "ffmpeg/ffprobe 不可用或输出异常，媒体质量未经过检查。",
        remedy: "确认本机 ffmpeg 可用后重新导出。",
      });
    }
  }

  if (findings.length === 0) {
    findings.push({
      id: "all-clear",
      severity: "ok",
      title: "未发现流程缺口",
      detail: "身份层/台词对账/静默降级检查均通过。媒体级验收（切点/字幕烧录/音画时长）在导出后由后置检查承担。",
    });
  }
  return findings;
}

/** 镜头表的镜头数（scene_script.shots），供体检摘要展示。 */
export function sceneScriptShotCount(node: CanvasNodeV2 | undefined): number {
  if (!node) return 0;
  const script = asRecord(structured(node).scene_script) as SceneScriptShots | null;
  return Array.isArray(script?.shots) ? script.shots.length : 0;
}
