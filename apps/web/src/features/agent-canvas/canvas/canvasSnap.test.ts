/**
 * canvasSnap tests (V0.2 §2.2: 吸附是语义吸附).
 *
 * Locks the three meanings that ship (row = same stage, gap = next/previous
 * in sequence, column = parallel/alternative), the research's own restraint
 * (a snap that would overlap is refused), and the no-snap default — snapping
 * that fires everywhere is the failure mode the doc warns about.
 */

import { describe, expect, it } from "vitest";

import {
  CANVAS_SNAP_GAP_ENGAGE,
  CANVAS_SNAP_ROW_THRESHOLD,
  planRowGapInsert,
  snapCanvasDropPosition,
  snapDraggedNode,
  type SnapBox,
} from "./canvasSnap.ts";
import { AGENT_CANVAS_NODE_HORIZONTAL_GAP } from "./nodeGeometry.ts";

const SIZE = { width: 272, height: 184 };

function box(id: string, x: number, y: number, size = SIZE): SnapBox {
  return { id, position: { x, y }, size };
}

describe("snapDraggedNode — row semantics (左右 = 前后/同阶段)", () => {
  it("aligns the row when dropped near a sibling's vertical centre", () => {
    const dragged = box("dragged", 900, 300 + 10);
    const sibling = box("anchor", 300, 300);
    const result = snapDraggedNode(dragged, [sibling]);
    expect(result.snap).toBe("row");
    expect(result.anchorId).toBe("anchor");
    expect(result.position.y).toBe(300);
    // A plain row snap does not move x.
    expect(result.position.x).toBe(900);
  });

  it("ignores a drop far from any row", () => {
    const dragged = box("dragged", 900, 800);
    const sibling = box("anchor", 300, 300);
    expect(snapDraggedNode(dragged, [sibling]).snap).toBeNull();
  });

  it("lives on the documented threshold", () => {
    const sibling = box("anchor", 300, 300);
    const inside = box("dragged", 900, 300 + CANVAS_SNAP_ROW_THRESHOLD - 1);
    const outside = box("dragged", 900, 300 + CANVAS_SNAP_ROW_THRESHOLD + 1);
    expect(snapDraggedNode(inside, [sibling]).snap).not.toBeNull();
    expect(snapDraggedNode(outside, [sibling]).snap).toBeNull();
  });
});

describe("snapDraggedNode — gap insertion (落在边旁 = 排到它后面/前面)", () => {
  it("inserts at the canonical gap when released just past the right edge", () => {
    const sibling = box("anchor", 300, 300);
    const dragged = box("dragged", 300 + SIZE.width + 20, 300 + 10);
    const result = snapDraggedNode(dragged, [sibling]);
    expect(result.snap).toBe("row_gap_after");
    expect(result.position.x).toBe(300 + SIZE.width + AGENT_CANVAS_NODE_HORIZONTAL_GAP);
    expect(result.position.y).toBe(300);
  });

  it("inserts before the sibling when released just left of it", () => {
    const sibling = box("anchor", 600, 300);
    // The card's RIGHT edge sits 20px left of the sibling's left edge.
    const dragged = box("dragged", 600 - SIZE.width - 20, 300 + 10);
    const result = snapDraggedNode(dragged, [sibling]);
    expect(result.snap).toBe("row_gap_before");
    expect(result.position.x).toBe(600 - SIZE.width - AGENT_CANVAS_NODE_HORIZONTAL_GAP);
  });

  it("does not gap-insert a drop released far from the edge", () => {
    const sibling = box("anchor", 300, 300);
    const dragged = box(
      "dragged",
      300 + SIZE.width + CANVAS_SNAP_GAP_ENGAGE + 60,
      300 + 10,
    );
    const result = snapDraggedNode(dragged, [sibling]);
    // Still the same row (so the row snap applies), but no gap move.
    expect(result.snap).toBe("row");
    expect(result.position.x).toBe(dragged.position.x);
  });
});

describe("snapDraggedNode — column semantics (上下 = 并列/备选)", () => {
  it("aligns the column when the centres line up but not the row", () => {
    const sibling = box("anchor", 300, 300);
    const dragged = box("dragged", 300 + 10, 300 + SIZE.height + 80);
    const result = snapDraggedNode(dragged, [sibling]);
    expect(result.snap).toBe("column");
    expect(result.position.x).toBe(300);
    // A column snap does not move y.
    expect(result.position.y).toBe(dragged.position.y);
  });
});

describe("snapDraggedNode — restraints", () => {
  it("refuses a snap that would overlap a sibling", () => {
    // Dropped into the crowded middle of a row: every candidate landing
    // (row-align onto the anchor, gap before the far card) sits on another
    // card, so the honest answer is NO snap at all.
    const anchor = box("anchor", 300, 300);
    const far = box("far", 900, 300);
    const dragged = box("dragged", 700, 310);
    const result = snapDraggedNode(dragged, [anchor, far]);
    expect(result.snap).toBeNull();
    expect(result.position).toEqual(dragged.position);
  });

  it("returns the original position with no siblings at all", () => {
    const dragged = box("dragged", 100, 100);
    expect(snapDraggedNode(dragged, [])).toEqual({
      position: dragged.position,
      snap: null,
      anchorId: null,
    });
  });

  it("picks the nearest candidate among several siblings", () => {
    const near = box("near", 300, 300);
    const far = box("far", 700, 300);
    const dragged = box("dragged", 1000, 300 + 6);
    const result = snapDraggedNode(dragged, [near, far]);
    expect(result.anchorId).toBe("far");
  });

  it("never counts the dragged node as its own sibling", () => {
    const dragged = box("dragged", 100, 100);
    const result = snapDraggedNode(dragged, [box("dragged", 900, 900)]);
    expect(result.snap).toBeNull();
  });
});

describe("snapCanvasDropPosition — a pane drop lands on the meaning of its spot (V0.2 §2.2)", () => {
  it("inserts a dropped asset into a row gap that has room for it", () => {
    const left = box("left", 300, 300);
    // A wide gap (400px): wide enough for the dropped card plus both gaps.
    const right = box("right", 300 + SIZE.width + 400, 300);
    const result = snapCanvasDropPosition(
      { x: 300 + SIZE.width + 10, y: 300 + 8 },
      [left, right],
      SIZE,
    );
    expect(result.snap).toBe("row_gap_after");
    expect(result.anchorId).toBe("left");
    expect(result.position.x).toBe(300 + SIZE.width + AGENT_CANVAS_NODE_HORIZONTAL_GAP);
  });

  it("refuses — and reports no snap — when the row gap cannot hold the card", () => {
    // Cards one canonical gap apart: the dropped card would overlap the
    // right neighbour, so the honest answer is NO snap (the caller falls
    // back to first-free-spot). True "insert between" would have to reflow
    // the neighbours, which a drop position cannot do.
    const left = box("left", 300, 300);
    const right = box("right", 300 + SIZE.width + AGENT_CANVAS_NODE_HORIZONTAL_GAP, 300);
    const result = snapCanvasDropPosition(
      { x: 300 + SIZE.width + 10, y: 300 + 8 },
      [left, right],
      SIZE,
    );
    expect(result.snap).toBeNull();
    expect(result.position).toEqual({ x: 300 + SIZE.width + 10, y: 300 + 8 });
  });

  it("falls back to the raw point when nothing semantic is nearby", () => {
    const sibling = box("sibling", 300, 300);
    const point = { x: 2000, y: 1500 };
    const result = snapCanvasDropPosition(point, [sibling], SIZE);
    expect(result.snap).toBeNull();
    expect(result.position).toBe(point);
  });

  it("refuses a landing that would overlap the neighbour it snapped to", () => {
    // Dropped straight onto a card's centre: the row snap would stack them.
    const sibling = box("sibling", 300, 300);
    const result = snapCanvasDropPosition({ x: 400, y: 390 }, [sibling], SIZE);
    expect(result.snap).toBeNull();
  });
});

describe("planRowGapInsert — a narrow gap inserts by moving the neighbours (V0.2 §2.2)", () => {
  const LEFT = box("left", 300, 300);
  const RIGHT = box("right", 300 + SIZE.width + AGENT_CANVAS_NODE_HORIZONTAL_GAP, 300);

  it("inserts into a one-gap row and pushes the right neighbour over", () => {
    const plan = planRowGapInsert(
      { x: 300 + SIZE.width + 10, y: 300 + 8 },
      [LEFT, RIGHT],
      SIZE,
    );
    expect(plan).not.toBeNull();
    // The new card takes the canonical gap after the left neighbour...
    expect(plan?.insertAt).toEqual({
      x: 300 + SIZE.width + AGENT_CANVAS_NODE_HORIZONTAL_GAP,
      y: 300,
    });
    // ...and the neighbour to its right moves over by one card + one gap.
    expect(plan?.shifts).toEqual([
      { id: "right", x: 300 + SIZE.width + AGENT_CANVAS_NODE_HORIZONTAL_GAP * 2 + SIZE.width, y: 300 },
    ]);
  });

  it("shifts every neighbour to the right, not just the closest one", () => {
    const far = box("far", 300 + (SIZE.width + AGENT_CANVAS_NODE_HORIZONTAL_GAP) * 2, 300);
    const plan = planRowGapInsert(
      { x: 300 + SIZE.width + 10, y: 300 + 8 },
      [LEFT, RIGHT, far],
      SIZE,
    );
    expect(plan?.shifts.map((shift) => shift.id)).toEqual(["right", "far"]);
    const right = plan?.shifts.find((shift) => shift.id === "right");
    const farShift = plan?.shifts.find((shift) => shift.id === "far");
    expect(right?.x).toBe(300 + SIZE.width + AGENT_CANVAS_NODE_HORIZONTAL_GAP * 2 + SIZE.width);
    // Everyone to the right shifts by exactly one card + one gap — one
    // insert, one shift, however many neighbours follow.
    const farOriginalX = 300 + (SIZE.width + AGENT_CANVAS_NODE_HORIZONTAL_GAP) * 2;
    expect(farShift?.x).toBe(farOriginalX + SIZE.width + AGENT_CANVAS_NODE_HORIZONTAL_GAP);
  });

  it("leaves rows that are not the target row alone", () => {
    const other = box("other", 640, 800); // a different row entirely
    const plan = planRowGapInsert(
      { x: 300 + SIZE.width + 10, y: 300 + 8 },
      [LEFT, RIGHT, other],
      SIZE,
    );
    expect(plan?.shifts.some((shift) => shift.id === "other")).toBe(false);
  });

  it("inserts before the first card of a row and pushes the whole row", () => {
    const first = box("first", 900, 300);
    const second = box("second", 900 + SIZE.width + AGENT_CANVAS_NODE_HORIZONTAL_GAP, 300);
    const plan = planRowGapInsert({ x: 800, y: 390 }, [first, second], SIZE);
    expect(plan?.insertAt.x).toBe(900 - SIZE.width - AGENT_CANVAS_NODE_HORIZONTAL_GAP);
    expect(plan?.shifts.map((shift) => shift.id)).toEqual(["first", "second"]);
  });

  it("the caller's precedence: a roomy gap is the snap's, never this planner's", () => {
    // Documented contract: the drop handler tries the snap first, so the
    // roomy-gap case lands there and this planner is never consulted.
    const roomy = box("roomy", 300 + SIZE.width + 400, 300);
    expect(
      snapCanvasDropPosition({ x: 300 + SIZE.width + 10, y: 300 + 8 }, [LEFT, roomy], SIZE).snap,
    ).toBe("row_gap_after");
  });

  it("refuses a release ON a card (the card's own handler owns it)", () => {
    const plan = planRowGapInsert({ x: 400, y: 390 }, [LEFT, RIGHT], SIZE);
    expect(plan).toBeNull();
  });

  it("refuses a drop that shares no row with any card", () => {
    const plan = planRowGapInsert({ x: 2000, y: 1500 }, [LEFT, RIGHT], SIZE);
    expect(plan).toBeNull();
  });

  it("refuses an empty canvas", () => {
    expect(planRowGapInsert({ x: 100, y: 100 }, [], SIZE)).toBeNull();
  });
});
