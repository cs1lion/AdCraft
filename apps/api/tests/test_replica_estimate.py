"""Unit tests for the P4 speech-duration estimate (hypit packages/estimate 落地).

三层锁定：

- 预估纯函数：语言探测、分语种速率（CJK 字/拉丁词——一个速率打天下会把
  中文按词速、英文按字速算错一个量级）、混合文本分段求和、pace 三档缩放、
  速率表本身（改速率 = 显式决定）；
- 可行性门 pace 预检：超窗台词进 pace_warnings（可行动字段齐全）、**不
  影响 feasible**（内容问题不是成本问题）、短句静默；
- 透出：渲染桥把 pace_warnings 带进响应（合成前说出来），端点 to_dict 含
  新字段（向后兼容的加法）。
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.schemas.agent_canvas_ad_media import (
    ReplicaBeatV2,
    ReplicaBlueprintContentV2,
    ReplicaShotV2,
)
from app.services.replica import estimate as es
from app.services.replica.direct_execute import plan_direct_execute


# ---------------------------------------------------------------------------
# 预估纯函数
# ---------------------------------------------------------------------------


def test_detect_language_by_script() -> None:
    assert es.detect_language("别再这样洗脸了") == "cjk"
    assert es.detect_language("buy now") == "latin"
    assert es.detect_language("第7天 DAY 7") == "cjk"  # 有 CJK 即按 CJK 档
    assert es.detect_language("   ") == "empty"


def test_rate_table_is_explicit_and_locked() -> None:
    """速率表是显式决定：数值与档位都在这里，改它要看得到代价。"""
    assert es.CJK_CHARS_PER_SECOND == 4.8
    assert es.LATIN_WORDS_PER_SECOND == 2.8
    assert es.PACE_FACTORS == {"slow": 0.8, "normal": 1.0, "fast": 1.3}


def test_estimate_cjk_by_chars() -> None:
    # 18 字 / 4.8 = 3.75
    assert es.estimate_speech_seconds("别再这样洗脸了这款洗面奶真的超级好用") == 3.75


def test_estimate_latin_by_words() -> None:
    # 7 词 / 2.8 = 2.5
    assert es.estimate_speech_seconds("buy now and get it today ok") == 2.5


def test_estimate_mixed_text_sums_per_language() -> None:
    """混合文本分段求和：2 CJK 字 + 3 拉丁词（"7" 按词计）各按自己的速率。"""
    # 2/4.8 + 3/2.8 = 0.417 + 1.071 = 1.488
    assert es.estimate_speech_seconds("第7天 DAY 7") == 1.488


def test_estimate_empty_is_zero() -> None:
    assert es.estimate_speech_seconds("") == 0.0
    assert es.estimate_speech_seconds("，。！") == 0.0


def test_estimate_pace_scales() -> None:
    text = "别再这样洗脸了"
    base = es.estimate_speech_seconds(text, pace="normal")
    slow = es.estimate_speech_seconds(text, pace="slow")
    fast = es.estimate_speech_seconds(text, pace="fast")
    assert slow < base < fast
    # 容差而非恒等：实现是"原始值 × 因子后一次性 round"，测试若先 round 再乘
    # 会引入双重舍入差（本测试曾因此误报）
    assert abs(fast - base * 1.3) <= 0.001
    assert abs(slow - base * 0.8) <= 0.001


def test_beat_pace_check_reports_actionable_fields() -> None:
    check = es.estimate_beat_pace(text="别再这样洗脸了这款洗面奶真的超级好用而且一点都不刺激", window_seconds=3.0)
    assert check["fits"] is False
    assert check["language"] == "cjk"
    assert check["unit"] == "chars"
    assert check["count"] == 26
    assert check["estimated_seconds"] == 5.417
    assert check["window_seconds"] == 3.0
    assert check["budget_seconds"] == 3.15  # 5% grace
    assert check["ratio"] == 1.806


def test_beat_pace_check_fits_short_line() -> None:
    check = es.estimate_beat_pace(text="买它", window_seconds=3.0)
    assert check["fits"] is True
    assert check["ratio"] is not None and check["ratio"] < 1.0


# ---------------------------------------------------------------------------
# 可行性门预检
# ---------------------------------------------------------------------------


def _blueprint(line: str, window_end: float = 3.0) -> ReplicaBlueprintContentV2:
    return ReplicaBlueprintContentV2(
        shots=[
            ReplicaShotV2(
                index=1,
                start_seconds=0.0,
                end_seconds=window_end,
                on_screen_text="HALF PRICE SALE",
                subject_action="",
            )
        ],
        beats=[
            ReplicaBeatV2(
                beat_id="b1",
                role="hook",
                start_seconds=0.0,
                end_seconds=window_end,
                line=line,
            )
        ],
        systems_captions="底部大字",
        systems_music="促销电子",
    )


def test_gate_flags_over_window_line_without_touching_feasibility() -> None:
    """pace 告警不影响 feasible（内容问题不是成本问题）——两条断言都要锁。"""
    blueprint = _blueprint("别再这样洗脸了这款洗面奶真的超级好用而且一点都不刺激")

    plan = plan_direct_execute(blueprint)

    assert len(plan.pace_warnings) == 1
    warning = plan.pace_warnings[0]
    assert warning["beat_id"] == "b1"
    assert warning["role"] == "hook"
    assert warning["text"] == blueprint.beats[0].line
    assert warning["fits"] is False
    assert warning["ratio"] > 1.0
    # feasible 只由 blockers/generation 决定：有台词 → 需 TTS → 本就不可行，
    # 但 pace 不是它的原因（messaging 可查：generation_steps 里没有 pace 项）
    assert all(step["step"] != "pace" for step in plan.generation_steps)
    assert plan.feasible is False


def test_gate_is_silent_for_lines_that_fit() -> None:
    plan = plan_direct_execute(_blueprint("买它"))
    assert plan.pace_warnings == ()


def test_gate_to_dict_carries_pace_warnings_additively() -> None:
    payload = plan_direct_execute(_blueprint("别再这样洗脸了这款洗面奶真的超级好用而且一点都不刺激")).to_dict()
    assert "pace_warnings" in payload
    assert payload["pace_warnings"] and payload["pace_warnings"][0]["beat_id"] == "b1"


# ---------------------------------------------------------------------------
# 端点/桥透出
# ---------------------------------------------------------------------------


@pytest.fixture
def direct_client():
    app = FastAPI()
    from app.api.v1.endpoints import replica as replica_endpoint

    app.include_router(replica_endpoint.router)
    return TestClient(app)


def test_direct_execute_plan_endpoint_reports_pace_warnings(direct_client) -> None:
    response = direct_client.post(
        "/replica/blueprint/direct-execute-plan",
        json={"blueprint": _blueprint("别再这样洗脸了这款洗面奶真的超级好用而且一点都不刺激").model_dump(mode="json")},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["pace_warnings"]
    assert body["pace_warnings"][0]["estimated_seconds"] > body["pace_warnings"][0]["window_seconds"]


def test_direct_execute_plan_endpoint_silent_for_short_line(direct_client) -> None:
    response = direct_client.post(
        "/replica/blueprint/direct-execute-plan",
        json={"blueprint": _blueprint("买它").model_dump(mode="json")},
    )
    assert response.status_code == 200, response.text
    assert response.json()["pace_warnings"] == []
