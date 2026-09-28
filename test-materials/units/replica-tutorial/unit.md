# 风格单元：教程步骤（replica-tutorial）

> 单元自包含：本方案 + `brief.txt`（复刻目标=换主题）+ 视频素材。

## 风格定位

编号步骤教程片：静态浅色底 + 深色 STEP 大字，四段推进。考察拆解器对
**编号/步骤结构**与浅底深字（反向对比极性）的处理；浅色系相邻镜头
保持可辨色差（卡过切点质量门）。

## 素材与真值

- 文件：`rep_tutorial_1x1_16s.mp4`（16s / 1:1 / 720×720@30）
- 音频：660Hz 轻响（音量 0.2）

| 镜 | 时长 | 底色 | 屏上文字 |
|---|---|---|---|
| 1 | 4s | #f5ead0（奶油） | STEP 1 PREP |
| 2 | 4s | #d8eedd（薄荷） | STEP 2 MIX |
| 3 | 4s | #d6e2f5（periwinkle） | STEP 3 COOK |
| 4 | 4s | #f2dcea（绯红调） | STEP 4 PLATE |

切点：0 / 4 / 8 / 12 秒。

## 用例与预期

| id | 内容 | 预期 |
|---|---|---|
| QC-09 | 质量 | 全过 |
| RT-09 | teardown 拆解（LLM，brief=换主题） | 镜头数 3-5；屏上文字含 STEP |

## 执行

```bash
cd apps/api && uv run python ../../test-materials/tools/run_tests.py --only QC-09,RT-09
```
