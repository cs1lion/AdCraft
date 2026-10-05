/**
 * ProjectCheckupPanel — 项目体检面板（流程协同，playbook §4）。
 *
 * 只读展示 buildProjectCheckup 的发现清单：失败/缺口/静默降级/对账。
 * 不改任何节点，不参与生成链路；默认收起，工具栏按钮展开。
 */

import { useMemo } from "react";

import type { AgentCanvasWorkflowV2 } from "../../../types-v2.ts";
import {
  buildProjectCheckup,
  type CheckupSeverity,
  type ProjectCheckupFinding,
} from "./projectCheckup.ts";

const SEVERITY_ORDER: CheckupSeverity[] = ["fail", "warn", "info", "ok"];

const SEVERITY_META: Record<CheckupSeverity, { icon: string; label: string }> = {
  fail: { icon: "✕", label: "失败" },
  warn: { icon: "!", label: "注意" },
  info: { icon: "i", label: "提示" },
  ok: { icon: "✓", label: "通过" },
};

export interface ProjectCheckupPanelProps {
  workflow: AgentCanvasWorkflowV2;
  open: boolean;
  onToggle: () => void;
}

function summaryFor(findings: ProjectCheckupFinding[]): string {
  const counts = new Map<CheckupSeverity, number>();
  for (const finding of findings) {
    counts.set(finding.severity, (counts.get(finding.severity) ?? 0) + 1);
  }
  const parts: string[] = [];
  if ((counts.get("fail") ?? 0) > 0) parts.push(`${counts.get("fail")} 失败`);
  if ((counts.get("warn") ?? 0) > 0) parts.push(`${counts.get("warn")} 注意`);
  if (parts.length === 0) return "体检通过";
  return parts.join(" · ");
}

export function ProjectCheckupPanel({ workflow, open, onToggle }: ProjectCheckupPanelProps) {
  const findings = useMemo(() => buildProjectCheckup(workflow), [workflow]);
  const worst = findings.reduce<CheckupSeverity>((acc, finding) => {
    return SEVERITY_ORDER.indexOf(finding.severity) < SEVERITY_ORDER.indexOf(acc)
      ? finding.severity
      : acc;
  }, "ok");
  const blockedCount = findings.filter((finding) => finding.severity === "fail").length;
  const warnCount = findings.filter((finding) => finding.severity === "warn").length;

  return (
    <div className="project-checkup" data-testid="project-checkup">
      <button
        type="button"
        className={`project-checkup__toggle is-${worst}${open ? " is-open" : ""}`}
        aria-expanded={open}
        data-testid="project-checkup-toggle"
        onClick={onToggle}
      >
        <span aria-hidden="true">🩺</span>
        <span>项目体检</span>
        {!open && (blockedCount > 0 || warnCount > 0) ? (
          <span className="project-checkup__badge" data-testid="project-checkup-badge">
            {summaryFor(findings)}
          </span>
        ) : null}
      </button>
      {open ? (
        <div className="project-checkup__body" data-testid="project-checkup-body">
          <p className="project-checkup__summary">{summaryFor(findings)} · 共 {findings.length} 项</p>
          <ul className="project-checkup__list">
            {findings.map((finding) => (
              <li
                key={finding.id}
                className={`project-checkup__item is-${finding.severity}`}
                data-testid={`checkup-${finding.id}`}
              >
                <span className="project-checkup__icon" aria-hidden="true">
                  {SEVERITY_META[finding.severity].icon}
                </span>
                <span className="project-checkup__text">
                  <b>{finding.title}</b>
                  <span className="project-checkup__detail">{finding.detail}</span>
                  {finding.remedy ? (
                    <span className="project-checkup__remedy">建议：{finding.remedy}</span>
                  ) : null}
                </span>
              </li>
            ))}
          </ul>
          <p className="project-checkup__footnote">
            只读体检，不改节点；媒体级验收（切点/字幕烧录/音画时长）由导出后置检查承担。
          </p>
        </div>
      ) : null}
    </div>
  );
}
