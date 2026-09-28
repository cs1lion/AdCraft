# 风格单元：卡点混剪（replica-beatsync）

> 单元自包含：本方案 + `brief.txt`（复刻目标=换商品不换节奏）+ 视频素材。

## 风格定位

音乐卡点混剪：16 镜 @1.0s，切点**严格落在 120 BPM 整拍**上（每 0.5s 一拍、
每两拍一切），ONE/TWO/THREE/GO 循环计数。考察节奏-切点对齐结构的拆解，
也是 timeline 节拍检测与吸附功能的内容素材。

## 素材与真值

- 文件：`rep_beatsync_9x16_16s.mp4`（16s / 9:16 / 540×960@30）
- 音频：整段 120 BPM 脉冲（880Hz、0.5s 一拍）——对这片跑节拍检测应得 ≈120
- 配色：#e63946 / #2a9d8f / #e9c46a / #264653 四色循环；文字 ONE/TWO/THREE/GO（72px）

切点：0,1,2,…,15 秒（16 镜）。

## 用例与预期

| id | 内容 | 预期 |
|---|---|---|
| QC-06 | 质量（16 个切点帧差逐一检查） | 全过 |
| RT-06 | teardown 拆解（LLM，brief=换商品） | 镜头数 12-20（允许 LLM 合并近似镜）；avg_shot 0.6-1.6s |
| BT-01 | 本片音轨同款节拍（120 BPM）检测 | bpm 118-122 |

## 执行

```bash
cd apps/api && uv run python ../../test-materials/tools/run_tests.py --only QC-06,RT-06,BT-01
```
