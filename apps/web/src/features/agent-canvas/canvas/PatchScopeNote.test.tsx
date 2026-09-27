/**
 * PatchScopeNote / patchScopeReport store tests (ADR 0009 决策 2 / V0.2 §10).
 *
 * The point of the whole surface: an unspoken "no neighbours affected" reads
 * as "the system didn't check". These tests lock that the empty case is the
 * LOUD one, that an affected case names its neighbours, and that a report for
 * another node does not narrate itself here.
 */

import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import {
  lastPatchScopeReport,
  patchScopeReportStore,
  publishPatchScopeReport,
  scopeSummary,
  type PatchScopeRecord,
} from "./patchScopeReport.ts";
import { PatchScopeNote } from "./PatchScopeNote.tsx";

afterEach(cleanup);

function record(overrides: Partial<PatchScopeRecord> = {}): PatchScopeRecord {
  return {
    nonce: 1,
    nodeId: "node-a",
    report: {
      edited_keys: ["structured_content"],
      content_areas: ["场景脚本"],
      affected_neighbours: [],
      dirty_reasons: ["场景脚本有未提交的作者修改"],
      notes: ["本次编辑不影响任何已绑定节点（下游只消费本节点的产物，不读取作者态）。"],
    },
    ...overrides,
  };
}

// Must run FIRST: the store is module-level state, and this file's other
// tests publish reports. Vitest isolates modules per file, so "before the
// first patch" is truthful exactly once — here.
describe("PatchScopeNote before any patch", () => {
  it("stays quiet before the first patch", () => {
    render(<PatchScopeNote />);
    expect(screen.queryByTestId("patch-scope-note")).toBeNull();
  });
});

describe("patchScopeReport store", () => {
  it("publishes and re-publishes with a fresh nonce", () => {
    publishPatchScopeReport("node-a", record().report);
    const first = lastPatchScopeReport();
    expect(first?.nodeId).toBe("node-a");

    publishPatchScopeReport("node-a", record().report);
    const second = lastPatchScopeReport();
    // A repeat patch of the same node must still re-render subscribers.
    expect(second?.nonce).toBe((first?.nonce ?? 0) + 1);
  });

  it("ignores an absent report", () => {
    publishPatchScopeReport("node-a", record().report);
    publishPatchScopeReport("node-a", null);
    expect(lastPatchScopeReport()?.nodeId).toBe("node-a");
  });

  it("exposes a useSyncExternalStore-compatible store", () => {
    expect(typeof patchScopeReportStore.subscribe).toBe("function");
    expect(typeof patchScopeReportStore.getSnapshot).toBe("function");
  });
});

describe("scopeSummary", () => {
  it("says the quiet case OUT LOUD (the ADR's whole point)", () => {
    const summary = scopeSummary(record());
    expect(summary.headline).toBe("未影响其他节点");
    expect(summary.detail).toContain("不影响任何已绑定节点");
  });

  it("names the affected neighbours when there are any", () => {
    const summary = scopeSummary(
      record({
        report: {
          affected_neighbours: [
            { node_id: "video-1", relation: "video_reference" },
            { node_id: "video-2", relation: "video_reference" },
          ],
          notes: ["下游将消费新产物。"],
        },
      }),
    );
    expect(summary.headline).toBe("影响 2 个关联节点");
    expect(summary.detail).toContain("video-1");
    expect(summary.detail).toContain("video-2");
  });
});

describe("PatchScopeNote", () => {
  it("renders the last report and its verdict", () => {
    publishPatchScopeReport("node-a", record().report);
    render(<PatchScopeNote nodeId="node-a" />);

    const note = screen.getByTestId("patch-scope-note");
    expect(note.getAttribute("data-affected")).toBe("false");
    expect(note.textContent).toContain("未影响其他节点");
  });

  it("does not narrate another node's patch", () => {
    publishPatchScopeReport("node-b", record().report);
    render(<PatchScopeNote nodeId="node-a" />);
    expect(screen.queryByTestId("patch-scope-note")).toBeNull();
  });

  it("marks an affected case", () => {
    publishPatchScopeReport(
      "node-a",
      record({
        report: { affected_neighbours: [{ node_id: "video-1" }], notes: [] },
      }).report,
    );
    render(<PatchScopeNote nodeId="node-a" />);
    expect(
      screen.getByTestId("patch-scope-note").getAttribute("data-affected"),
    ).toBe("true");
  });
});
