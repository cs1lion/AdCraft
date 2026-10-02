/** 草稿历史 hook 测试（F1 单步撤销）。 */

import { useState } from "react";
import { act, cleanup, render } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import type { SceneScriptRoot } from "../../../types/scene-script";
import { useScene3dDraftHistory, type Scene3dDraftHistory } from "./scene3dDraftHistory";

afterEach(cleanup);

let counter = 0;
function makeScript(): SceneScriptRoot {
  counter += 1;
  return {
    scene: { name: `s${counter}`, environment: "indoor", duration: 4, frame_rate: 30 },
    characters: [],
    props: [],
    environment: [],
    cameras: [],
    shots: [],
  } as SceneScriptRoot;
}

interface Probe {
  history: Scene3dDraftHistory;
  raw: (script: SceneScriptRoot | null) => void;
}

function Harness({ initial, probe }: { initial: SceneScriptRoot | null; probe: (api: Probe) => void }) {
  const [draft, setDraft] = useState<SceneScriptRoot | null>(initial);
  const history = useScene3dDraftHistory(draft, setDraft);
  probe({ history, raw: setDraft });
  return null;
}

describe("useScene3dDraftHistory", () => {
  it("commit applies the next draft and records the pre-edit one", () => {
    const A = makeScript();
    const B = makeScript();
    let api!: Probe;
    render(<Harness initial={A} probe={(value) => (api = value)} />);

    expect(api.history.canUndo).toBe(false);
    act(() => api.history.commit(B));

    expect(api.history.canUndo).toBe(true);
    expect(api.history.depth).toBe(1);
  });

  it("undo walks back through the chain in order and stops when empty", () => {
    const A = makeScript();
    const B = makeScript();
    const C = makeScript();
    let api!: Probe;
    render(<Harness initial={A} probe={(value) => (api = value)} />);

    act(() => {
      api.history.commit(B);
      api.history.commit(C);
    });
    expect(api.history.depth).toBe(2);

    act(() => api.history.undo());
    expect(api.history.depth).toBe(1);
    act(() => api.history.undo());
    expect(api.history.depth).toBe(0);
    expect(api.history.canUndo).toBe(false);
    // 空栈上再撤销是无害的 no-op
    act(() => api.history.undo());
    expect(api.history.depth).toBe(0);
  });

  it("an external draft change invalidates the recorded history", () => {
    const A = makeScript();
    const B = makeScript();
    const external = makeScript();
    let api!: Probe;
    render(<Harness initial={A} probe={(value) => (api = value)} />);

    act(() => api.history.commit(B));
    expect(api.history.canUndo).toBe(true);

    // 节点重跑/恢复草稿/revert 等外部通道直接改 state
    act(() => api.raw(external));
    expect(api.history.canUndo).toBe(false);
  });

  it("caps the history depth", () => {
    let api!: Probe;
    render(<Harness initial={makeScript()} probe={(value) => (api = value)} />);

    act(() => {
      for (let step = 0; step < 25; step += 1) {
        api.history.commit(makeScript());
      }
    });
    expect(api.history.depth).toBe(20);
  });

  it("committing from a null draft starts no history", () => {
    const B = makeScript();
    let api!: Probe;
    render(<Harness initial={null} probe={(value) => (api = value)} />);

    act(() => api.history.commit(B));
    expect(api.history.canUndo).toBe(false);
  });
});
