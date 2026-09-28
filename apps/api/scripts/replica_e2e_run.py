"""拉片复刻端到端测试（真实 LLM + 真实 ffmpeg + 真实 V2 数据库）。

流程（对齐 docs/plans/replica-teardown.md 的全链路）：

    样例视频 ──上传──▶ asset_id
        ──teardown（真实多模态 LLM，约 1-3 分钟）──▶ 拆解报告
        ──blueprint──▶ 蓝图 ──export──▶ .adreplica（落盘）
        ──手改──▶ import 重编译──▶ 蓝图'
        ──style-variants──▶ 风格候选 ──direct-execute-plan──▶ 零模型费判定
        ──建项目/workflow ──建 replica 节点──▶ instantiate
        ──▶ script 节点 + replica→script 绑定 + 实例化指针写回（校验）

用法（apps/api 下）：
    uv run python scripts/replica_e2e_run.py

产物：e2e_output/replica_e2e/run_<时间戳>/（report.json、teardown 报告、
导出与手改的 .adreplica、复刻脚本）。数据库与上传目录隔离到该 run 目录内，
不污染仓库数据。
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
API_ROOT = Path(__file__).resolve().parents[1]
# 直接以脚本运行时 sys.path[0] 是 scripts/，补上 apps/api 以导入 app 包
sys.path.insert(0, str(API_ROOT))

SAMPLES_DIR = REPO_ROOT / "e2e_output" / "replica_e2e"
RUNS_ROOT = SAMPLES_DIR / "runs"

# 隔离设置必须在导入 app 之前生效（get_settings 会缓存）
_RUN_ID = time.strftime("%Y%m%d_%H%M%S")
RUN_DIR = RUNS_ROOT / f"run_{_RUN_ID}"
(RUN_DIR / "data").mkdir(parents=True, exist_ok=True)
os.environ.setdefault("MEDIA_DATA_DIR", str(RUN_DIR / "data"))

BRIEF = (SAMPLES_DIR / "sample_brief.txt").read_text(encoding="utf-8").strip()
VIDEO = SAMPLES_DIR / "sample_ad_4shots.mp4"
HANDWRITTEN = SAMPLES_DIR / "sample_handwritten.adreplica"

STEPS: list[dict] = []


def step(name: str, fn):
    """跑一步并记录（失败即停，报告落盘）。"""
    print(f"\n=== {name} ===", flush=True)
    started = time.time()
    try:
        result = fn()
        elapsed = round(time.time() - started, 1)
        STEPS.append({"step": name, "status": "ok", "seconds": elapsed,
                      "summary": _summarize(result)})
        print(f"    ok ({elapsed}s)", flush=True)
        return result
    except Exception as exc:  # noqa: BLE001 - E2E 报告需要失败现场
        elapsed = round(time.time() - started, 1)
        STEPS.append({"step": name, "status": "failed", "seconds": elapsed,
                      "error": str(exc)[:500]})
        _write_report()
        print(f"    FAILED ({elapsed}s): {exc}", flush=True)
        raise SystemExit(1) from exc


def _summarize(result):
    if isinstance(result, dict):
        return {k: (v if isinstance(v, (str, int, float, bool)) else f"<{type(v).__name__}>")
                for k, v in list(result.items())[:8]}
    if isinstance(result, (str, int, float, bool)) or result is None:
        return result
    return f"<{type(result).__name__}>"


def _write_report(extra: dict | None = None) -> None:
    payload = {"run_id": _RUN_ID, "steps": STEPS}
    if extra:
        payload.update(extra)
    (RUN_DIR / "report.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def _fixture_teardown(upload_result: dict) -> dict:
    """样例地面真值拆解（LLM 429 降级用，报告显式标注 degraded-fixture）。"""
    metadata = upload_result["metadata"]
    return {
        "success": True,
        "degraded_fixture": True,
        "report": {
            "whole_piece_reading": "四段式促销结构：折扣钩子→新品展示→效果证明→行动号召。",
            "format_name": "e2e-fixture-promo",
            "shots": [
                {"index": i, "start_seconds": start, "end_seconds": end,
                 "shot_size": "medium", "camera_motion": "zoom-in",
                 "subject_action": "", "on_screen_text": text,
                 "transition_to_next": "cut", "note": ""}
                for i, (start, end, text) in enumerate(
                    [(0.0, 3.0, "HALF PRICE SALE"), (3.0, 6.0, "NEW PRODUCT"),
                     (6.0, 9.0, "DAY 7 RESULT"), (9.0, 12.0, "BUY NOW")], start=1)
            ],
            "beats": [
                {"role": "hook", "description": "折扣钩子", "line": "",
                 "start_seconds": 0.0, "end_seconds": 3.0},
                {"role": "proof", "description": "新品与效果", "line": "",
                 "start_seconds": 3.0, "end_seconds": 9.0},
                {"role": "cta", "description": "行动号召", "line": "",
                 "start_seconds": 9.0, "end_seconds": 12.0},
            ],
            "rhythm": {"avg_shot_seconds": 3.0,
                       "cut_points_seconds": [0.0, 3.0, 6.0, 9.0],
                       "energy_curve": "均匀"},
            "systems": {"captions": "底部大字", "music": "促销电子",
                        "graphics": ["价格贴：提到折扣时弹入"], "sfx": ["落版 whoosh"]},
            "transcript": {"source": "unavailable", "language": "", "reason": "engine_disabled",
                           "lines": [], "words": []},
            "constraints": ["fixture 降级：LLM 额度耗尽，使用样例地面真值"],
        },
        "frame_analyses": [],
        "video_metadata": metadata,
        "num_frames_analyzed": 8,
        "user_description": BRIEF[:200],
    }


def main() -> None:
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from app.api.v1.router import api_router as api_v1_router
    from app.api.v2.router import api_router as api_v2_router

    # 最小组装：只挂 v1/v2 路由 + V2 持久化 bootstrap，不跑 app.main 的
    # lifespan（恢复循环/广播等常驻逻辑与一次性 E2E 无关）。
    from app.core.config import get_settings
    from app.services.persistence_bootstrap import PersistenceBootstrapService

    application = FastAPI()
    application.include_router(api_v1_router, prefix="/api/v1")
    application.include_router(api_v2_router, prefix="/api/v2")
    application.state.v2_persistence_state = PersistenceBootstrapService(
        get_settings()
    ).bootstrap()
    client = TestClient(application, base_url="http://testserver")

    artifacts: dict = {}

    if True:
        # 1) 上传样例视频（scene-3d 上传端点，与 Reference 页同一入口）
        def upload() -> dict:
            response = client.post(
                "/api/v1/scene-3d/upload-reference",
                files={"file": (VIDEO.name, VIDEO.read_bytes(), "video/mp4")},
                data={"extract_keyframes": "true", "num_keyframes": "8"},
            )
            assert response.status_code == 200, response.text
            body = response.json()
            assert body["success"] is True
            assert body["metadata"]["duration_seconds"] > 10
            return body

        upload_result = step("1.上传样例视频", upload)
        asset_id = upload_result["asset_id"]
        artifacts["asset_id"] = asset_id
        print(f"    asset_id={asset_id} duration={upload_result['metadata']['duration_seconds']}s")

        # 2) 真实 LLM 拉片拆解（最慢的一步）。
        # LLM 额度耗尽（429）时显式降级为样例地面真值 fixture：报告标注
        # degraded-fixture，后续链路继续被行使——不静默、不假装是 LLM 产物。
        # D8：拆解是任务——POST 只提交（拿 job_id），轮询任务状态取结果。
        def teardown() -> dict:
            response = client.post(
                "/api/v1/replica/teardown",
                data={"asset_id": asset_id, "user_description": BRIEF[:200], "num_frames": "8"},
            )
            if response.status_code != 200 and "rate_limited" in response.text:
                print("    LLM 额度耗尽（429）→ 降级为样例地面真值 fixture")
                return _fixture_teardown(upload_result)
            assert response.status_code == 200, response.text
            job_id = response.json()["job_id"]
            deadline = time.time() + 1800  # 与后端总预算口径一致
            while time.time() < deadline:
                status = client.get(f"/api/v1/replica/teardown/jobs/{job_id}")
                assert status.status_code == 200, status.text
                body = status.json()
                if body["status"] == "completed":
                    assert body["report"]["shots"], "拆解应产出镜头表"
                    assert body["report"]["beats"], "拆解应产出结构段落"
                    return body
                if body["status"] in ("failed", "cancelled"):
                    raise AssertionError(
                        f"teardown 任务 {body['status']}: "
                        f"{body.get('error') or body.get('error_type')}"
                    )
                time.sleep(5)
            raise AssertionError("teardown 任务轮询超时（30 分钟）")

        teardown_result = step("2.teardown 真实拉片拆解", teardown)
        report = teardown_result["report"]
        (RUN_DIR / "teardown_report.json").write_text(
            json.dumps(teardown_result, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        artifacts["shots"] = len(report["shots"])
        artifacts["beats"] = len(report["beats"])
        print(f"    shots={len(report['shots'])} beats={len(report['beats'])} "
              f"format={report['format_name']}")

        # 3) 报告 → 蓝图（带真实元数据：时长/画幅）
        metadata = teardown_result["video_metadata"]
        width, height = metadata["width"], metadata["height"]
        import math

        divisor = math.gcd(width, height)

        def build_blueprint() -> dict:
            response = client.post(
                "/api/v1/replica/blueprint",
                json={
                    "report": report,
                    "source_video_asset_id": asset_id,
                    "duration_seconds": metadata["duration_seconds"],
                    "aspect": f"{width // divisor}:{height // divisor}",
                    "replica_goal": BRIEF.splitlines()[0],
                },
            )
            assert response.status_code == 200, response.text
            body = response.json()
            assert body["success"] is True
            assert body["blueprint"]["slots"], "蓝图应有默认槽位"
            return body

        blueprint_result = step("3.报告转蓝图", build_blueprint)
        blueprint = blueprint_result["blueprint"]

        # 4) 导出 .adreplica（落盘为产物）
        def export_document() -> dict:
            response = client.post(
                "/api/v1/replica/blueprint/export",
                json={"blueprint": blueprint},
            )
            assert response.status_code == 200, response.text
            body = response.json()
            assert "<advideo" in body["adreplica"]
            return body

        export_result = step("4.导出 .adreplica", export_document)
        exported_text = export_result["adreplica"]
        (RUN_DIR / export_result["filename"]).write_text(exported_text, encoding="utf-8")
        artifacts["adreplica_file"] = export_result["filename"]

        # 5) hypit 式手改（换槽位替换值 + 加一条 sfx 锚点）→ 导入重编译
        def hand_edit_and_import() -> dict:
            import re

            edited = re.sub(
                r'(<slot kind="product"[^>]*?)replace-with=""',
                r'\g<1>replace-with="sample_product.png"',
                exported_text,
                count=1,
            )
            edited = edited.replace(
                "</events>",
                '    <sfx id="e_e2e" during="'
                + (blueprint["beats"][0]["beat_id"] if blueprint["beats"] else "b1")
                + '" trigger="落版">落版 whoosh</sfx>\n  </events>',
            )
            assert edited != exported_text, "手改应生效"
            (RUN_DIR / "hand_edited.adreplica").write_text(edited, encoding="utf-8")
            response = client.post(
                "/api/v1/replica/blueprint/import", json={"adreplica": edited}
            )
            assert response.status_code == 200, response.text
            body = response.json()
            product = next(
                s for s in body["blueprint"]["slots"] if s["kind"] == "product"
            )
            assert product["replace_with"] == "sample_product.png"
            assert product["applied"] is True
            return body

        import_result = step("5.手改文档导入重编译", hand_edit_and_import)
        blueprint = import_result["blueprint"]

        # 6) 风格变体（确定性风格导演）
        def style_variants() -> dict:
            response = client.post(
                "/api/v1/replica/blueprint/style-variants",
                json={"blueprint": blueprint, "n": 3},
            )
            assert response.status_code == 200, response.text
            body = response.json()
            assert len(body["variants"]) == 3
            assert body["variants"][0]["names"]
            return body

        variants_result = step("6.风格变体推荐", style_variants)
        artifacts["top_variant"] = " × ".join(variants_result["variants"][0]["names"])

        # 7) direct-execute 可行性门
        def direct_plan() -> dict:
            response = client.post(
                "/api/v1/replica/blueprint/direct-execute-plan",
                json={"blueprint": blueprint},
            )
            assert response.status_code == 200, response.text
            body = response.json()
            assert body["success"] is True
            assert isinstance(body["feasible"], bool)
            return body

        direct_result = step("7.direct-execute 可行性门", direct_plan)
        artifacts["direct_execute_feasible"] = direct_result["feasible"]

        # 7.5) direct-execute 渲染验收（ADR 0010 R1）：纯字幕可行样例 →
        # 编译走 HTTP 端点 → 渲染走进程内剪辑域渲染器（工作流桥接归 R3，
        # 桥接前这是诚实的进程内验收形态）。
        def render_caption_sample() -> dict:
            caption_video = SAMPLES_DIR / "sample_caption_only.mp4"
            assert caption_video.exists(), "先运行 replica_e2e_build_samples.py"
            # 纯字幕样例的地面真值结构（与构建脚本一致）：4 镜头纯屏上文字
            from app.schemas.agent_canvas_ad_media import (
                ReplicaBeatV2,
                ReplicaBlueprintContentV2,
                ReplicaShotV2,
            )

            blueprint = ReplicaBlueprintContentV2(
                replica_goal="纯字幕促销片直出（E2E 渲染验收）",
                aspect="9:16",
                duration_seconds=6.0,
                format_name="caption-promo",
                beats=[
                    ReplicaBeatV2(beat_id=f"b{i}", role=role, start_seconds=start,
                                  end_seconds=end)
                    for i, (start, end, role, _t) in enumerate(
                        [(0.0, 1.5, "hook", "HALF PRICE SALE"),
                         (1.5, 3.0, "proof", "NEW PRODUCT"),
                         (3.0, 4.5, "proof", "DAY 7 RESULT"),
                         (4.5, 6.0, "cta", "BUY NOW")], start=1)
                ],
                shots=[
                    ReplicaShotV2(index=i, start_seconds=start, end_seconds=end,
                                  on_screen_text=text, subject_action="")
                    for i, (start, end, _role, text) in enumerate(
                        [(0.0, 1.5, "hook", "HALF PRICE SALE"),
                         (1.5, 3.0, "proof", "NEW PRODUCT"),
                         (3.0, 4.5, "proof", "DAY 7 RESULT"),
                         (4.5, 6.0, "cta", "BUY NOW")], start=1)
                ],
                systems_captions="底部大字",
                systems_music="促销电子",
                systems_sfx=["whoosh"],
            )
            compile_response = client.post(
                "/api/v1/replica/blueprint/direct-execute",
                json={
                    "blueprint": blueprint.model_dump(mode="json"),
                    "plan": {"feasible": True, "blockers": [], "zero_model_steps": [],
                             "generation_steps": []},
                },
            )
            assert compile_response.status_code == 200, compile_response.text
            compiled = compile_response.json()
            assert compiled["needs_placeholder_video"] is True

            # 进程内渲染：剪辑域渲染器消费 canonical timeline
            from app.schemas.workflow_v2 import WorkflowItemV2, WorkflowSlotV2, WorkflowV2
            from app.services.v2_final_composition_renderer import (
                V2FinalCompositionRenderer,
            )
            from app.core.config import get_settings

            import dataclasses

            font = Path(r"C:\Windows\Fonts\arial.ttf")
            settings = dataclasses.replace(
                get_settings(),
                final_composition_render_mode="timeline_editor",
                final_composition_subtitle_font_path=str(font) if font.exists() else None,
            )
            if settings.final_composition_subtitle_font_path is None:
                raise AssertionError("本机无可读字幕字体，渲染验收无法进行")
            now = "2026-09-27T00:00:00+00:00"
            workflow = WorkflowV2(
                workflow_id="wf_e2e_render", name="e2e render", prompt="e2e",
                audio_mode="bgm_only", created_at=now, updated_at=now,
            )
            item = WorkflowItemV2(item_id="item_fc", node_id="node_fc",
                                  item_type="final_composition", display_name="FC")
            slot = WorkflowSlotV2(slot_id="slot_fc", node_id="node_fc",
                                  item_id="item_fc", slot_type="final_video",
                                  media_type="video")
            renderer = V2FinalCompositionRenderer(
                data_dir=RUN_DIR / "data", settings=settings
            )
            result = renderer.render(
                workflow, item, slot,
                {
                    "canonical_timeline": compiled["timeline"],
                    "render_id": "render_e2e_caption",
                },
            )
            assert result.status == "completed", getattr(result, "metadata", {})
            output_path = RUN_DIR / "data" / result.local_file_path
            assert output_path.exists()
            assert (output_path.parent / "placeholder-video.mp4").exists()
            return {"output_file": str(output_path)}

        render_result = step("7.5 渲染验收（纯字幕直出）", render_caption_sample)
        artifacts["render_output"] = render_result["output_file"]

        # 8) 建项目（自带 workflow）→ 建 replica 节点（蓝图即内容）
        def create_project_and_node() -> dict:
            response = client.post(
                "/api/v2/projects",
                json={"name": f"replica-e2e-{_RUN_ID}", "description": BRIEF[:120]},
                headers={"Idempotency-Key": f"e2e-{_RUN_ID}"},
            )
            assert response.status_code in (200, 201), response.text
            body = response.json()
            project = body.get("project") or body
            workflow_id = project["workflow_id"]

            workflow_response = client.get(f"/api/v2/workflows/{workflow_id}")
            assert workflow_response.status_code == 200, workflow_response.text
            # 强 ETag 值本身含引号，原样回传给 If-Match
            etag = workflow_response.headers.get("ETag", "")

            node_response = client.post(
                f"/api/v2/workflows/{workflow_id}/nodes",
                json={
                    "node_type": "replica",
                    "creative_role": "replica_blueprint",
                    "role_contract_version": "ad-media-role-v2",
                    "title": "E2E 复刻蓝图",
                    "summary_prompt": "端到端测试创建的复刻蓝图节点",
                    "generation_prompt": None,
                    "structured_content": blueprint,
                    "model_selection_mode": "default",
                    "model_ref": None,
                    "parameters": {},
                    "position": {"x": 200.0, "y": 120.0},
                    "source_asset_id": None,
                },
                headers={"If-Match": etag},
            )
            assert node_response.status_code in (200, 201), node_response.text
            node = (node_response.json().get("node") or {})
            return {"workflow_id": workflow_id, "replica_node_id": node.get("node_id", "")}

        project_result = step("8.建项目与 replica 节点", create_project_and_node)
        workflow_id = project_result["workflow_id"]
        replica_node_id = project_result["replica_node_id"]
        artifacts["workflow_id"] = workflow_id
        artifacts["replica_node_id"] = replica_node_id

        # 9) 手写 .adreplica 导入（验证第三方文档路径）——直接调 import
        def import_handwritten() -> dict:
            text = HANDWRITTEN.read_text(encoding="utf-8")
            response = client.post(
                "/api/v1/replica/blueprint/import", json={"adreplica": text}
            )
            assert response.status_code == 200, response.text
            body = response.json()
            assert body["blueprint"]["format_name"] == "handwritten-sample"
            return body

        step("9.手写 .adreplica 导入", import_handwritten)

        # 10) 实例化：script 节点 + 自动绑定 + 指针写回
        def instantiate() -> dict:
            response = client.post(
                "/api/v1/replica/instantiate",
                json={
                    "workflow_id": workflow_id,
                    "replica_node_id": replica_node_id,
                    "slot_updates": {"product": "sample_product.png"},
                },
            )
            assert response.status_code == 200, response.text
            body = response.json()
            assert body["success"] is True
            assert body["binding_id"].startswith("binding_")
            return body

        instantiate_result = step("10.instantiate 实例化", instantiate)
        artifacts["script_node_id"] = instantiate_result["script_node_id"]
        artifacts["binding_id"] = instantiate_result["binding_id"]
        (RUN_DIR / "replica_script.txt").write_text(
            instantiate_result["script_text"], encoding="utf-8"
        )

        # 11) 校验工作流：绑定存在 + 指针写回
        def verify_workflow() -> dict:
            response = client.get(f"/api/v2/workflows/{workflow_id}")
            assert response.status_code == 200, response.text
            workflow = response.json()
            bindings = workflow.get("bindings", [])
            nodes = {n["node_id"]: n for n in workflow.get("nodes", [])}
            assert instantiate_result["script_node_id"] in nodes, "script 节点应存在"
            binding_ok = any(
                b.get("source", {}).get("source_node_id") == replica_node_id
                and b.get("target_node_id") == instantiate_result["script_node_id"]
                for b in bindings
            )
            assert binding_ok, "replica→script 绑定应存在"
            replica_content = nodes[replica_node_id]["structured_content"]
            assert (
                replica_content.get("instantiated_script_node_id")
                == instantiate_result["script_node_id"]
            ), "实例化指针应写回蓝图节点"
            return {"bindings": len(bindings), "nodes": len(nodes)}

        verify_result = step("11.校验绑定与指针", verify_workflow)
        artifacts.update(verify_result)

    _write_report({"artifacts": artifacts, "output_dir": str(RUN_DIR)})
    print("\n=== E2E 全链路通过 ===")
    print(json.dumps(artifacts, ensure_ascii=False, indent=2))
    print(f"报告与产物：{RUN_DIR}")


if __name__ == "__main__":
    main()
