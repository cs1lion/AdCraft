import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import type { SceneEditReport } from "./shotLabels";
import { formatSegmentSeconds, shotChangeHeadline } from "./shotLabels";
import { SceneEditReportPanel } from "./SceneEditReportPanel";

afterEach(cleanup);

const LABELS: Record<string, string> = {
  camera_moved: "机位移动",
  camera_renamed: "机位改名",
  object_moved: "位置移动",
  shot_added: "新增镜头",
  shot_repointed: "镜头改绑机位",
};

function report(overrides: Partial<SceneEditReport> = {}): SceneEditReport {
  return {
    changes: { cam2: ["camera_moved"] },
    shots: [
      {
        id: "shot2",
        camera_id: "cam2",
        camera_label: "机位02 | 飞船俯瞰",
        start_seconds: 3,
        end_seconds: 6,
        changes: ["camera_moved"],
        objects_touched: ["cam2"],
      },
    ],
    shot_count: 2,
    change_count: 1,
    labels: LABELS,
    ...overrides,
  };
}

describe("SceneEditReportPanel", () => {
  it("names the shot and its span the way the reference framework does", () => {
    render(<SceneEditReportPanel report={report()} frameRate={30} />);
    const panel = screen.getByTestId("scene-edit-report");
    expect(panel.textContent).toContain("机位02 | 飞船俯瞰 的 3s–6s");
    expect(panel.textContent).toContain("机位移动");
  });

  it("says nothing changed rather than rendering an empty box", () => {
    render(
      <SceneEditReportPanel
        report={report({ changes: {}, shots: [], change_count: 0 })}
        frameRate={30}
      />,
    );
    expect(screen.getByTestId("scene-edit-report").textContent).toContain("没有改变场景内容");
  });

  it("lists objects that belong to no shot so they are not dropped", () => {
    // A prop nobody animated is still part of "what did I just do".
    render(
      <SceneEditReportPanel
        report={report({ changes: { cam2: ["camera_moved"], crate1: ["object_moved"] } })}
        frameRate={30}
      />,
    );
    expect(screen.getByTestId("scene-edit-report").textContent).toContain("crate1（位置移动）");
  });

  it("renders nothing when there is no report", () => {
    render(<SceneEditReportPanel report={null} frameRate={30} />);
    expect(screen.queryByTestId("scene-edit-report")).toBeNull();
  });

  it("survives a change code the frontend does not know yet", () => {
    // The backend owns the code list; an unknown code must degrade to its raw
    // string rather than blank the line out.
    render(
      <SceneEditReportPanel
        report={report({
          changes: { cam2: ["camera_moved", "some_future_code"] },
          shots: [
            {
              id: "shot2",
              camera_id: "cam2",
              camera_label: "机位02",
              start_seconds: 0,
              end_seconds: 3,
              changes: ["camera_moved", "some_future_code"],
              objects_touched: ["cam2"],
            },
          ],
        })}
        frameRate={30}
      />,
    );
    const panel = screen.getByTestId("scene-edit-report");
    expect(panel.textContent).toContain("机位移动");
    expect(panel.textContent).toContain("some_future_code");
  });
});

describe("shotChangeHeadline", () => {
  it("joins the camera label and the span", () => {
    expect(
      shotChangeHeadline({
        id: "s",
        camera_id: "c",
        camera_label: "机位05 | 飞船俯瞰",
        start_seconds: 4.5,
        end_seconds: 8,
        changes: [],
        objects_touched: [],
      }),
    ).toBe("机位05 | 飞船俯瞰 的 4.5s–8s");
  });
});

describe("formatSegmentSeconds", () => {
  it("keeps whole seconds clean and fractions readable", () => {
    expect(formatSegmentSeconds(3)).toBe("3s");
    expect(formatSegmentSeconds(4.5)).toBe("4.5s");
    expect(formatSegmentSeconds(Number.NaN)).toBe("0s");
  });
});
