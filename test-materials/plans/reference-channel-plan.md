# Provider 参考（视频/音频/图）通道测试方案

> 功能线横切方案。schema：`SeedanceInputManifestV1{image_inputs, video_inputs,
> audio_inputs}`（apps/api/app/schemas/seedance_inputs.py:147）。
> 适配层行为（Agnes 占位编号、超预算第二条 clip 整体省略、local clip 不能作
> URL 发送等）已由 `apps/api/tests/test_seedance_agnes_video_audio_references.py`
> 锁定——本方案做端到端/GUI 探索。

## 0. Agent 执行入口（自动化优先）

```bash
# 素材规格/质量真值（无需后端）
cd apps/api && uv run python ../../test-materials/tools/run_tests.py --suite media,quality

# 共用上传入口（无 LLM）
cd apps/api && uv run python ../../test-materials/tools/run_tests.py --suite api-scene3d --only S3-UP
```

## 1. 素材与用例

| 素材 | 类型 | 用例与预期 |
|---|---|---|
| `fixtures/images/ref_product_3x4_768x1024.png` | 3:4 正例 | 参考图入口通过画幅窗口 |
| `fixtures/images/ref_turnaround_3view_1536x512.png` | 转身表反例 | 被拒绝/标记（应点名"多视图拼贴"类原因）；行为已在单测锁定，端到端记录实际文案 |
| `fixtures/images/ref_ultrawide_1024x288.png` | 32:9 反例 | 同上 |
| `fixtures/videos/slice_ref_16x9_40s.mp4` | 切片锚长片 | timeline 12-18s 窗切片投递：`timeline_slicing_report` 区间 ≈[12,18]，12s 数字 3、16s 数字 4（见 timeline-plan §2） |
| `fixtures/audio/ref_music_15s.wav` | 音频参考 | audio_inputs 投递、占位 `<Audio 1>` 按提交顺序编号 |
| `units/replica-luxury/rep_luxury_16x9_30s.mp4` | 接近预算的长片 | 双视频参考触发预算超限 → 第二条整体省略并给原因（不得截断） |

## 2. 步骤

1. **画幅窗口**：三张图分别走参考图入口，正例通过、两个反例被拒/标记。
2. **切片投递**：slice_ref 挂参考 + timeline 12-18s clip（联动 timeline-plan §2）。
3. **音频投递**：ref_music 挂音频参考。
4. **预算超限**：luxury + 另一条视频同挂 → 第二条省略 + 原因；local clip 直发
   URL 显式报错。
5. **公共 URL**：provider 收到公共可访问 URL（内网部署下记录实际表现）。

## 3. 记录方式

自动结果落 `results/run-*/`；GUI/端到端结论记
`results/reference-channel-runlog.md`（素材 / 入口 / 实际报错文案 / 切片区间）。
