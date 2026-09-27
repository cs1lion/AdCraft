/**
 * Semantic snap for canvas node drags (V0.2 §2.2).
 *
 * The research is explicit that snapping must not be geometric convenience:
 * "吸附不是纯视觉，而是语义吸附——左右可表达前后镜头，上下可表达素材/参考
 * 关系". Canvas node drags previously snapped to NOTHING (free-floating), so
 * the author's placement carried no meaning and every layout drifted.
 *
 * The first rule, implemented here:
 *
 * - **Row snap (左右 = 前后/同阶段)** — dropping near a sibling's vertical
 *   centre aligns the row: same row reads as "same narrative stage".
 * - **Gap insertion** — releasing just past a sibling's right (left) edge
 *   snaps the node to the canonical horizontal gap AFTER (BEFORE) it: the
 *   gesture reads as "place this next to / after that", and the result is the
 *   same spacing the auto-layout produces.
 * - **Column snap (上下 = 并列/备选)** — aligning a column reads as a
 *   parallel or alternative branch, which is how the canvas already draws
 *   stacks.
 *
 * Two deliberate restraints, both from the research's own warning ("语义过多
 * 会让用户不知道拖到哪里做什么"):
 *
 * 1. Only THREE meanings ship in this rule. Card-internal ownership and
 *    between-shot transitions are recorded as open — they need richer drop
 *    targets than "near a node edge".
 * 2. A snap that would OVERLAP a sibling is refused: alignment is not worth a
 *    stack of coincident cards.
 */

import { AGENT_CANVAS_NODE_HORIZONTAL_GAP } from "./nodeGeometry.ts";

export interface SnapBox {
  id: string;
  /** Top-left in canvas coordinates (React Flow's node position). */
  position: { x: number; y: number };
  size: { width: number; height: number };
}

export type CanvasSnapKind = "row" | "row_gap_after" | "row_gap_before" | "column";

export interface CanvasSnapResult {
  position: { x: number; y: number };
  snap: CanvasSnapKind | null;
  anchorId: string | null;
}

/** Vertical-centre slack (px) that still reads as "same row". */
export const CANVAS_SNAP_ROW_THRESHOLD = 26;
/** Horizontal-centre slack (px) that still reads as "same column". */
export const CANVAS_SNAP_COLUMN_THRESHOLD = 26;
/** How close to a sibling's edge (px) reads as "place beside it". */
export const CANVAS_SNAP_GAP_ENGAGE = 110;
/** A hair of visual overlap still counts as "beside" (px). */
const CANVAS_SNAP_EDGE_SLACK = 8;

interface BoxGeom {
  left: number;
  right: number;
  top: number;
  bottom: number;
  centerX: number;
  centerY: number;
}

function geometry(box: SnapBox): BoxGeom {
  const left = box.position.x;
  const top = box.position.y;
  return {
    left,
    top,
    right: left + box.size.width,
    bottom: top + box.size.height,
    centerX: left + box.size.width / 2,
    centerY: top + box.size.height / 2,
  };
}

function intersects(a: BoxGeom, b: BoxGeom): boolean {
  const overlapX = Math.min(a.right, b.right) - Math.max(a.left, b.left);
  const overlapY = Math.min(a.bottom, b.bottom) - Math.max(a.top, b.top);
  // A hair of contact is not an overlap; a card sitting on another is.
  return overlapX > 1 && overlapY > 1;
}

/**
 * Where a dragged node should land, given the boxes it was dropped among.
 * Returns the original position when nothing snaps.
 */
export function snapDraggedNode(
  dragged: SnapBox,
  siblings: readonly SnapBox[],
  options: { horizontalGap?: number } = {},
): CanvasSnapResult {
  const gap = options.horizontalGap ?? AGENT_CANVAS_NODE_HORIZONTAL_GAP;
  const here = geometry(dragged);
  const others = siblings.filter((sibling) => sibling.id !== dragged.id);

  let best: { kind: CanvasSnapKind; anchor: SnapBox; x: number; y: number; distance: number } | null =
    null;

  for (const sibling of others) {
    const there: BoxGeom = geometry(sibling);
    const dy = Math.abs(here.centerY - there.centerY);
    const dx = Math.abs(here.centerX - there.centerX);

    if (dy <= CANVAS_SNAP_ROW_THRESHOLD) {
      // Same row: align it...
      const y = there.top;
      // ...and, when the card is released BESIDE the sibling's edge (its left
      // edge at or just past the sibling's right edge), insert at the
      // canonical gap so the gesture reads as "next in sequence".
      if (
        here.centerX > there.centerX
        && here.left >= there.right - CANVAS_SNAP_EDGE_SLACK
        && here.left - there.right <= CANVAS_SNAP_GAP_ENGAGE
      ) {
        const candidate = {
          kind: "row_gap_after" as CanvasSnapKind,
          anchor: sibling,
          x: there.right + gap,
          y,
          distance: dy + Math.abs(here.centerX - there.centerX) * 0.1,
        };
        if (!best || candidate.distance < best.distance) best = candidate;
      } else if (
        here.centerX < there.centerX
        && there.left >= here.right - CANVAS_SNAP_EDGE_SLACK
        && there.left - here.right <= CANVAS_SNAP_GAP_ENGAGE
      ) {
        const candidate = {
          kind: "row_gap_before" as CanvasSnapKind,
          anchor: sibling,
          x: there.left - dragged.size.width - gap,
          y,
          distance: dy + Math.abs(here.centerX - there.centerX) * 0.1,
        };
        if (!best || candidate.distance < best.distance) best = candidate;
      } else {
        const candidate = {
          kind: "row" as CanvasSnapKind,
          anchor: sibling,
          x: dragged.position.x,
          y,
          distance: dy + Math.abs(here.centerX - there.centerX) * 0.1,
        };
        if (!best || candidate.distance < best.distance) best = candidate;
      }
      continue;
    }

    if (dx <= CANVAS_SNAP_COLUMN_THRESHOLD) {
      const candidate = {
        kind: "column" as CanvasSnapKind,
        anchor: sibling,
        x: there.left,
        y: dragged.position.y,
        distance: dx,
      };
      if (!best || candidate.distance < best.distance) best = candidate;
    }
  }

  if (!best) {
    return { position: dragged.position, snap: null, anchorId: null };
  }

  const snapped: SnapBox = {
    id: dragged.id,
    position: { x: best.x, y: best.y },
    size: dragged.size,
  };
  // Alignment is never worth a stack of coincident cards.
  for (const sibling of others) {
    if (intersects(geometry(snapped), geometry(sibling))) {
      return { position: dragged.position, snap: null, anchorId: null };
    }
  }

  return { position: snapped.position, snap: best.kind, anchorId: best.anchor.id };
}

/**
 * Where a pane DROP should land (V0.2 §2.2: 两个镜头之间 = 新镜头插入).
 *
 * A drag has a card that already exists; a drop only has a point and the
 * size the new node will have. This wraps the same rule: the drop point is
 * treated as the would-be card's position, so releasing an asset between
 * two cards inserts it into that row at the canonical gap — the same
 * semantic landing a card drag gets, instead of "first free spot".
 */
export function snapCanvasDropPosition(
  point: { x: number; y: number },
  siblings: readonly SnapBox[],
  size: { width: number; height: number },
): CanvasSnapResult {
  return snapDraggedNode({ id: "", position: point, size }, siblings);
}

// ---------------------------------------------------------------------------
// Reflow insert: drop into a narrow gap and the neighbours make room
// ---------------------------------------------------------------------------

export interface RowInsertShift {
  id: string;
  x: number;
  y: number;
}

export interface RowInsertPlan {
  /** Where the new card lands (the canonical gap after the left neighbour). */
  insertAt: { x: number; y: number };
  /** The neighbours that must move right, and where they land. */
  shifts: RowInsertShift[];
}

/**
 * Plan a real INSERT: the drop point sits in the gap of a row that cannot
 * hold the card (V0.2 §2.2: 两个镜头之间 = 新镜头插入).
 *
 * A snap refuses that case — it will not stack cards — but refusing throws
 * away a gesture the research explicitly names. This planner finishes it:
 * the card takes the canonical gap after its left neighbour, and every
 * sibling to its right in that row shifts by one card + one gap. That is
 * what "insert" means; a drop position alone cannot move anyone, so the
 * caller creates the node and persists the shifts.
 *
 * The caller tries the plain snap FIRST and consults this planner only when
 * the snap refuses, so the "gap already has room" case never reaches here.
 * Returns null when the gesture is not an insert-between: the point is ON a
 * card (the card's own drop handler owns that) or shares no row with any
 * card (a free-spot drop).
 */
export function planRowGapInsert(
  point: { x: number; y: number },
  siblings: readonly SnapBox[],
  size: { width: number; height: number },
  options: { horizontalGap?: number } = {},
): RowInsertPlan | null {
  const gap = options.horizontalGap ?? AGENT_CANVAS_NODE_HORIZONTAL_GAP;
  const pointCenterY = point.y + size.height / 2;

  // The row: siblings whose vertical span contains the drop's centre (with
  // the same slack a row snap uses, so a slightly high release still reads
  // as "this row").
  const row = siblings
    .filter((sibling) => {
      const top = sibling.position.y;
      const bottom = top + sibling.size.height;
      return (
        pointCenterY >= top - CANVAS_SNAP_ROW_THRESHOLD
        && pointCenterY <= bottom + CANVAS_SNAP_ROW_THRESHOLD
      );
    })
    .sort((left, right) => left.position.x - right.position.x);
  if (row.length === 0) return null;

  // The horizontal logic reads the CURSOR, not the would-be card: a 272px
  // card centred on a 68px gap overlaps both neighbours by construction, so
  // card-centred tests would read every real insert as "on a card".
  const pointX = point.x;

  // A release ON a card is not an insert-between: the card's own handler
  // owns it (and refusing here keeps the two gestures from double-firing).
  if (
    row.some(
      (sibling) =>
        pointX >= sibling.position.x
        && pointX <= sibling.position.x + sibling.size.width,
    )
  ) {
    return null;
  }

  // The left neighbour: the last card whose right edge is left of the point.
  const leftIndex = row.reduce(
    (found, sibling, index) =>
      sibling.position.x + sibling.size.width <= pointX ? index : found,
    -1,
  );
  const left = leftIndex >= 0 ? row[leftIndex] : null;
  const right = leftIndex + 1 < row.length ? row[leftIndex + 1] : null;

  // The caller tries the plain snap first; this planner is the fallback for
  // the gap that cannot hold the card, so it always plans a real insert.
  const insertAtX = left
    ? left.position.x + left.size.width + gap
    : row[0].position.x - size.width - gap;

  const insertAtY = (left ?? row[0]).position.y;
  const shift = size.width + gap;
  // Everyone in this row to the right of the insert point moves over.
  const shifts: RowInsertShift[] = row
    .filter((sibling) => sibling.position.x >= insertAtX - 1)
    .map((sibling) => ({
      id: sibling.id,
      x: sibling.position.x + shift,
      y: sibling.position.y,
    }));

  return { insertAt: { x: insertAtX, y: insertAtY }, shifts };
}
