# Timeline（双阶段导演）测试方案

> 功能线横切方案。节拍轨与切片锚视频在 `fixtures/`；卡点混剪内容素材在
> `units/replica-beatsync`。节拍素材已用仓库真实 `BeatAnalyzer` 实测（2026-09-27）。

## 0. Agent 执行入口（自动化优先）

```bash
# 节拍分析器真值 + 卡点素材质量（无需后端）
cd apps/api && uv run python ../../test-materials/tools/run_tests.py --suite beats,quality
```

beats 套件：BT-01…BT-05（匀速/边界 BPM 真值）、BT-06（变速轨）、
BT-07（too_short）、BT-08（静音）。结果与状态语义见
[replica-teardown-plan.md](replica-teardown-plan.md) §0。

## 1. 节拍检测用例（含实测预期）

流程：建 workflow → audio clip 指向 `fixtures/audio/*` → `GET /api/v2/workflows/{wid}/timeline/clips/{cid}/beats`。

| 素材 | 真值 | 实测（BeatAnalyzer） | 端点预期 |
|---|---|---|---|
| `beat_120bpm_20s.wav` | 120 BPM | bpm=120.2 conf=1.0 41 拍 | 200；118-122 |
| `beat_90bpm_20s.wav` | 90 | bpm=90.7 31 拍 | 200；88-94 |
| `beat_140bpm_accent_30s.wav` | 140 底鼓+半拍嚓声 | bpm=139.7 71 拍 | 200；136-143 |
| `beat_60bpm_20s.wav` | 60（_MIN_BPM 下界） | bpm=60.1 21 拍 | 200；57-63 |
| `beat_170bpm_20s.wav` | 170 高速档 | bpm=84.7（半频） | 200 但可能判半频——记录实际值 |
| `beat_mixed_120to150_20s.wav` | 前 10s 120 / 后 10s 150 | bpm=74.9 | 200 但非真值（不崩溃、可解释） |
| `beat_tooshort_1s.wav` | <2s | 报错 at least 2 seconds | **422** `beat_analysis_too_short` |
| `beat_silent_10s.wav` | 全静音 | 报错 steady beat | **422** indeterminate |

吸附 UI 轨：audio clip 检出节拍后开 "Snap clip drags to detected beat markers"
（data-testid=timeline-snap-beats），拖 video clip 落点应吸附节拍标记。

## 2. 切片与联动用例

`fixtures/videos/slice_ref_16x9_40s.mp4`：8 段 ×5s，第 k 段大数字 k +
音高 300+40k Hz（质量门 QC-14 逐镜校验过）。

1. 挂为 video 节点参考资产，timeline 建 12-18s clip。
2. 触发生成前指导 → 查 `timeline_slicing_report`：切片区间 ≈[12.0,18.0]（±1 帧）；
   抽帧断言 12s 处数字 3、16s 处数字 4。
3. 边界：窗口超出资产末端 → 钳制 + warning；图片参考 → 不切片。

## 3. playhead / 绑定 / 字幕（GUI 轨）

1. playhead：timeline ↔ 3D 视口双向同步，无回声振荡。
2. voice-character binding：clip 绑定角色 → 徽章显示 + 播放高亮说话角色。
3. 字幕导出：dialogue 单元台词建字幕 clip → `GET .../timeline/subtitles` SRT 对齐。

## 4. 记录方式

自动结果落 `results/run-*/`；手动/端点轨记 `results/timeline-runlog.md`
（素材 / clip 窗口 / 实测 bpm 或切片区间 / 偏差）。
