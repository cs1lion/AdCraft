/**
 * V0.2 minimum user journeys — the E2E harness that proves them.
 *
 * The v0.2 construction goal is complete per its §15 audit table
 * (docs/plans/infinite_canvas_ai_short_video_research_v0.2.md), but the audit
 * is a claim list: this spec is the proof. Two minimum journeys run end to
 * end against the REAL components on local logic (no Meshy / external 3D
 * service is in the critical path — verified 0 hits — and no dev-time build:
 * the harness pages are served by the vite dev server exactly like the
 * existing tests/browser mocks).
 *
 *   J1 asset-to-canvas (§2.1/§2.2)
 *     drag a ready asset from the asset browser onto the canvas pane → an
 *     asset-backed node is created (media type IS the node type — the
 *     backend's validate_asset_backed_node rule mirrored by canvasDrop.ts);
 *     drag the scene board onto the scene-3d card → an image_reference
 *     binding is written → the 3D editor's 「⇢ 参考输入」 line appears. A card
 *     drop belongs to the card: no second node is created from it.
 *
 *   J2 dialogue-to-proposal (§14.3/§14.5/§15)
 *     type a line in the lip-sync panel and apply → the shot advisory
 *     (line crosses a cut) appears under 「分镜提示（不自动修改）」 → click its
 *     「🎬 看看怎么接」 → the playhead lands in the boundary shot and the
 *     transition picker auto-fetches the readings for THAT pair, priced
 *     against the segments the applied run measured (never a re-estimate) →
 *     apply 声音桥 (the zero-operation reading) → the reading is recorded as
 *     the shot's entry and the shot strip shows the relation on the boundary.
 *
 * Every selector below already exists in the product components
 * (grep data-testid): agent-asset-*, agent-canvas-node-*, scene-script-3d-reference-*,
 * dialogue-lipsync*, dialogue-shot-advisories, dialogue-advisory-transitions-*,
 * transition-proposals*, shot-strip*. The harness's own surfaces add only
 * `canvas-pane` (the drop adapter's div) and `scene-workbench` (its mount
 * point) — both in e2e/harness, never in product code.
 */

import { expect, test, type Page } from "@playwright/test";

import {
  DIALOGUE_CHARACTER_ID,
  DIALOGUE_LINE,
  J1_WORKFLOW_ID,
  J2_WORKFLOW_ID,
  SCENE_BOARD_ASSET_ID,
  SCENE_NODE_ID,
  SCENE_STILL_ASSET_ID,
  SHOT_1_ID,
  SHOT_2_ID,
  TIMESTAMP,
  assetBackedImageNode,
  j1Workflow,
  j2Workflow,
  sceneBoardBinding,
  sceneNode,
  sceneScript,
} from "./harness/v02-journeys.fixtures.ts";

// ---------------------------------------------------------------------------
// J1 — asset-to-canvas
// ---------------------------------------------------------------------------

test("J1 asset-to-canvas: drag creates an asset-backed node; binding the scene board shows the reference-input line", async ({
  page,
}) => {
  const nodeCreates: Array<{ headers: Record<string, string>; body: Record<string, unknown> }> = [];
  const bindingCreates: Array<{ headers: Record<string, string>; body: Record<string, unknown> }> = [];

  await page.route("**/api/**", async (route) => {
    const request = route.request();
    const url = new URL(request.url());

    // The authoring ETag bootstrap: the v2 client reads the workflow ETag
    // before any mutation (If-Match precondition).
    if (request.method() === "GET" && url.pathname === `/api/v2/workflows/${J1_WORKFLOW_ID}`) {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        headers: { ETag: '"workflow:workflow-j1:revision:1"' },
        body: JSON.stringify(j1Workflow()),
      });
      return;
    }

    if (request.method() === "GET" && url.pathname === `/api/v2/workflows/${J1_WORKFLOW_ID}/assets`) {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ workflow_id: J1_WORKFLOW_ID, assets: j1Workflow().assets }),
      });
      return;
    }

    if (url.pathname === "/api/v2/assets/mine" || url.pathname === "/api/v2/assets/recommended") {
      await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ items: [] }) });
      return;
    }

    // 素材 → 拖到画布 → 创建镜头: the create request the pane drop built from
    // the drag payload (canvasDropCreateRequest).
    if (request.method() === "POST" && url.pathname === `/api/v2/workflows/${J1_WORKFLOW_ID}/nodes`) {
      nodeCreates.push({ headers: request.headers(), body: request.postDataJSON() });
      const created = assetBackedImageNode(J1_WORKFLOW_ID);
      await route.fulfill({
        status: 201,
        contentType: "application/json",
        headers: { ETag: '"workflow:workflow-j1:revision:2"' },
        body: JSON.stringify({
          workflow: j1Workflow({
            revision: 2,
            nodes: [sceneNode(J1_WORKFLOW_ID), created],
          }),
          node: created,
          binding: null,
        }),
      });
      return;
    }

    // 卡片内部 = 素材归属: the image → image_reference binding the card drop
    // writes through the shared createBinding client.
    if (request.method() === "POST" && url.pathname === `/api/v2/workflows/${J1_WORKFLOW_ID}/bindings`) {
      bindingCreates.push({ headers: request.headers(), body: request.postDataJSON() });
      const binding = sceneBoardBinding(J1_WORKFLOW_ID);
      // The executor publishes what the node was FED: the scene-3d node now
      // carries the reference binding, which is what the editor renders.
      const sceneWithReference = sceneNode(J1_WORKFLOW_ID, {
        revision: 2,
        structured_content: {
          scene_script: sceneScript(),
          scene3d_reference_bindings: [
            {
              asset_id: SCENE_BOARD_ASSET_ID,
              semantic_role: "scene_board",
              recorded_on: null,
              media_type: "image",
            },
          ],
        },
      });
      await route.fulfill({
        status: 201,
        contentType: "application/json",
        headers: { ETag: '"workflow:workflow-j1:revision:3"' },
        body: JSON.stringify({
          workflow: j1Workflow({
            revision: 3,
            nodes: [sceneWithReference],
            bindings: [binding],
          }),
          node: sceneWithReference,
          binding,
        }),
      });
      return;
    }

    await route.fulfill({
      status: 404,
      contentType: "application/json",
      body: JSON.stringify({ code: "mock_route_not_found", message: url.pathname }),
    });
  });

  await page.goto("/e2e/harness/v02-j1-asset-to-canvas.mock.html");

  // The browser lists the workflow's ready media (draggable cards).
  await expect(page.getByTestId(`agent-asset-project:${SCENE_STILL_ASSET_ID}`)).toBeVisible();
  await expect(page.getByTestId(`agent-asset-project:${SCENE_BOARD_ASSET_ID}`)).toBeVisible();

  // ① Drag the still onto the canvas pane: one asset-backed node appears.
  await page.getByTestId(`agent-asset-project:${SCENE_STILL_ASSET_ID}`)
    .dragTo(page.getByTestId("canvas-pane"));
  await expect(page.getByTestId("agent-canvas-node-image-still-1")).toBeVisible();

  expect(nodeCreates).toHaveLength(1);
  // The media type IS the node type (the backend's validate_asset_backed_node
  // rule), and the node remembers the asset it was created from.
  expect(nodeCreates[0]?.body).toMatchObject({
    node_type: "image",
    source_asset_id: SCENE_STILL_ASSET_ID,
  });
  expect(nodeCreates[0]?.headers["if-match"]).toBeTruthy();

  // ② Drag the scene board onto the scene-3d card: an image_reference
  // binding is written, and the 3D editor shows the delivery.
  await page.getByTestId(`agent-asset-project:${SCENE_BOARD_ASSET_ID}`)
    .dragTo(page.getByTestId(`agent-canvas-node-${SCENE_NODE_ID}`));
  const referenceLine = page.getByTestId("scene-script-3d-reference-0");
  await expect(referenceLine).toBeVisible();
  await expect(referenceLine).toContainText("场景设计板");
  await expect(referenceLine).toContainText(SCENE_BOARD_ASSET_ID);

  expect(bindingCreates).toHaveLength(1);
  expect(bindingCreates[0]?.body).toMatchObject({
    target_node_id: SCENE_NODE_ID,
    input_role: "image_reference",
    source: {
      kind: "image_asset",
      source_asset_id: SCENE_BOARD_ASSET_ID,
      source_asset_version_id: `version-${SCENE_BOARD_ASSET_ID}`,
    },
  });
  // A drop on a card belongs to the card: the pane handler was stopped, so the
  // gesture created exactly one node in total.
  expect(nodeCreates).toHaveLength(1);
});

// ---------------------------------------------------------------------------
// J2 — dialogue-to-proposal
// ---------------------------------------------------------------------------

test("J2 dialogue-to-proposal: lip-sync advisory jumps to the picker; the sound-bridge reading labels the shot strip", async ({
  page,
}) => {
  const lipsyncRequests: Array<{ body: Record<string, unknown> }> = [];
  const transitionRequests: Array<{ body: Record<string, unknown> }> = [];
  const clipCreates: Array<{ body: Record<string, unknown> }> = [];

  await page.route("**/api/**", async (route) => {
    const request = route.request();
    const url = new URL(request.url());

    // 唇形应用: one measured segment that crosses shot1's cut — the rule
    // advisor's finding, with the readings that execute its remedy.
    if (request.method() === "POST" && url.pathname === "/api/v1/scene-3d/dialogue-lipsync") {
      lipsyncRequests.push({ body: request.postDataJSON() });
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          success: true,
          scene_script: sceneScript(),
          summary: {
            segment_count: 1,
            duration_source: "aligned",
            segments: [
              {
                segment_id: "s0",
                character_id: DIALOGUE_CHARACTER_ID,
                text: DIALOGUE_LINE,
                start_time: 0.5,
                end_time: 2,
              },
            ],
            shot_advisories: [
              {
                code: "line_crosses_cut",
                shot_id: SHOT_1_ID,
                message: `台词「${DIALOGUE_LINE}」跨过镜头 ${SHOT_1_ID} 的剪切点 1.5s。`,
                remedy: "有意保留就是 L-cut（声音桥）；或把剪切点移到 2.0s 附近的停顿里。",
                severity: "warning",
                proposal_ids: ["sound_bridge", "cut_after_line"],
              },
            ],
          },
        }),
      });
      return;
    }

    // The C-mode chain (bed → align → lip-sync → subtitles): applying the
    // lip-sync automatically publishes this node's cues on the same timeline
    // the mouths ride on.
    if (request.method() === "GET" && url.pathname === `/api/v2/workflows/${J2_WORKFLOW_ID}/timeline/tracks`) {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify([
          {
            track_id: "track-subtitle",
            timeline_id: "timeline-j2",
            type: "subtitle",
            name: "字幕",
            muted: false,
            volume: 1,
            locked: false,
            display_order: 0,
            clips: [],
            created_at: TIMESTAMP,
            updated_at: TIMESTAMP,
          },
        ]),
      });
      return;
    }
    if (request.method() === "GET" && url.pathname === `/api/v2/workflows/${J2_WORKFLOW_ID}/timeline`) {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          timeline_id: "timeline-j2",
          workflow_id: J2_WORKFLOW_ID,
          duration_seconds: 6,
          fps: 30,
          subtitle_burn_in: true,
          tracks: [],
          created_at: TIMESTAMP,
          updated_at: TIMESTAMP,
        }),
      });
      return;
    }
    if (request.method() === "POST" && url.pathname === `/api/v2/workflows/${J2_WORKFLOW_ID}/timeline/clips`) {
      const body = request.postDataJSON();
      clipCreates.push({ body });
      await route.fulfill({
        status: 201,
        contentType: "application/json",
        body: JSON.stringify({
          clip_id: "clip-subtitle-1",
          track_id: body.track_id,
          start_time: body.start_time,
          duration: body.duration,
          source_start: null,
          source_duration: null,
          asset_id: null,
          asset_version_id: null,
          source_node_id: SCENE_NODE_ID,
          fade_in: null,
          fade_out: null,
          transition_in_type: null,
          transition_in_duration: null,
          transition_out_type: null,
          transition_out_duration: null,
          bound_character_id: null,
          label: body.label ?? null,
          color: null,
          subtitle_text: body.subtitle_text ?? null,
          subtitle_style: null,
          created_at: TIMESTAMP,
          updated_at: TIMESTAMP,
        }),
      });
      return;
    }

    // 衔接方案: the six-reading catalogue, priced against the speech
    // timeline the picker forwarded. 声音桥 is the zero-operation reading
    // (§14.13 「声音先到」); time_jump stays visible WITH its reason.
    if (request.method() === "POST" && url.pathname === "/api/v1/scene-3d/transition-proposals") {
      transitionRequests.push({ body: request.postDataJSON() });
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          success: true,
          narrative_source: "rules",
          proposals: [
            {
              id: "continuous_motion",
              label: "连续运动",
              narrative: "人物穿过空间，摄影机跟随。",
              feasible: true,
              origin: "rules",
              operations: [
                {
                  kind: "character_preset",
                  rationale: "走向下一镜主体",
                  preset_id: "walk_to",
                  character_id: DIALOGUE_CHARACTER_ID,
                  start_frame: 0,
                  duration_frames: 45,
                },
              ],
            },
            {
              id: "sound_bridge",
              label: "声音桥",
              narrative: "话音先于画面切换落地，声音桥是有意的选择。",
              feasible: true,
              origin: "rules",
              operations: [],
            },
            {
              id: "time_jump",
              label: "时间/空间跳跃",
              narrative: "本段缺少可用的时间跳跃停顿。",
              feasible: false,
              infeasible_reason: "没有可用停顿",
              origin: "rules",
              operations: [],
            },
          ],
        }),
      });
      return;
    }

    await route.fulfill({
      status: 404,
      contentType: "application/json",
      body: JSON.stringify({ code: "mock_route_not_found", message: url.pathname }),
    });
  });

  await page.goto("/e2e/harness/v02-j2-dialogue-to-proposal.mock.html");

  // The lip-sync panel is the scene side of 台词驱动.
  await expect(page.getByTestId("dialogue-lipsync")).toBeVisible();
  const relationBefore = page.getByTestId(`shot-strip-relation-${SHOT_1_ID}-${SHOT_2_ID}`);
  await expect(relationBefore).toContainText("未登记");

  // ① Add the line and apply it to the scene.
  await page.getByLabel("第 1 行台词").fill(DIALOGUE_LINE);
  await page.getByLabel("第 1 行说话人").selectOption(DIALOGUE_CHARACTER_ID);
  await page.getByRole("button", { name: "👄 应用唇形到场景" }).click();

  // The run reports what it measured …
  await expect(page.getByTestId("dialogue-lipsync-summary")).toBeVisible();
  await expect(page.getByTestId("dialogue-lipsync-summary")).toContainText("1 句");
  // … and the same run's shot advisories appear — advisory, never blocking.
  const advisories = page.getByTestId("dialogue-shot-advisories");
  await expect(advisories).toBeVisible();
  await expect(advisories).toContainText("话音跨切点");
  await expect(advisories).toContainText("不自动修改");
  // The lipsync request carried the authored line, unchanged.
  expect(lipsyncRequests).toHaveLength(1);
  const lipsyncBody = lipsyncRequests[0]?.body as {
    dialogue_lines?: Array<{ text: string; character_id: string }>;
  };
  expect(lipsyncBody.dialogue_lines?.[0]).toMatchObject({
    text: DIALOGUE_LINE,
    character_id: DIALOGUE_CHARACTER_ID,
  });
  // The C-mode chain: the cues rode the same boundaries onto the subtitle track.
  await expect(page.getByTestId("dialogue-lipsync-publish-result")).toContainText("已上字幕轨");
  expect(clipCreates).toHaveLength(1);
  expect(clipCreates[0]?.body).toMatchObject({
    source_node_id: SCENE_NODE_ID,
    subtitle_text: DIALOGUE_LINE,
  });

  // ② The advisory's jump: 「🎬 看看怎么接」 lands the playhead in the boundary
  // shot and the picker fetches the readings for THAT pair — one click.
  await page.getByTestId("dialogue-advisory-transitions-0").click();
  await expect(page.getByTestId("transition-proposals")).toBeVisible();
  await expect(page.getByTestId("transition-apply-sound_bridge")).toBeVisible();

  expect(transitionRequests).toHaveLength(1);
  const transitionBody = transitionRequests[0]?.body as {
    shot_a_id?: string;
    shot_b_id?: string;
    segments?: Array<{ text: string }>;
    polish_narratives?: boolean;
    propose_readings?: boolean;
  };
  // The pair is the boundary shot and its successor …
  expect(transitionBody.shot_a_id).toBe(SHOT_1_ID);
  expect(transitionBody.shot_b_id).toBe(SHOT_2_ID);
  // … priced against the segments the applied run measured, never a re-estimate.
  expect(transitionBody.segments?.[0]?.text).toBe(DIALOGUE_LINE);
  // Both LLM layers are OFF by default: the machine proposes, the creator chooses.
  expect(transitionBody.polish_narratives).toBe(false);
  expect(transitionBody.propose_readings).toBe(false);
  await expect(page.getByTestId("transition-proposals-polish")).not.toBeChecked();
  await expect(page.getByTestId("transition-proposals-propose")).not.toBeChecked();
  // Rule readings only: no 「LLM 补充」 badge reaches the picker.
  await expect(page.getByTestId("transition-origin-continuous_motion")).toHaveCount(0);
  // An infeasible reading stays visible WITH its reason — never silently gone.
  await expect(page.getByText("暂不可用：没有可用停顿")).toBeVisible();

  // ③ Apply the sound-bridge reading: a zero-operation reading confirms the
  // cut and records the relation. The label lives on the shot strip's boundary.
  await page.getByTestId("transition-apply-sound_bridge").click();
  await expect(page.getByTestId("transition-proposals-note")).toContainText("已登记");
  await expect(page.getByTestId("transition-proposals-note")).toContainText(SHOT_2_ID);

  const intentMarker = page.getByTestId(`shot-strip-intent-${SHOT_2_ID}`);
  await expect(intentMarker).toBeVisible();
  await expect(intentMarker).toHaveText("声音桥");
  await expect(intentMarker).toHaveAttribute("data-intent", "sound_bridge");
  // And the boundary names the relation as a PAIR — the §13 question is about
  // the relation between two shots.
  await expect(relationBefore).not.toContainText("未登记");
  await expect(relationBefore).toContainText("声音桥");
});
