# 风格单元：对比测评（replica-compare）

> 单元自包含：本方案 + `brief.txt`（复刻目标=换商品）+ 视频素材。

## 风格定位

前后对比测评片：灰暗"用前"→明亮"用后"→数据强化→结论定格。考察拆解器
对**对比结构**（before/after + verdict）的语义识别。

## 素材与真值

- 文件：`rep_compare_9x16_16s.mp4`（16s / 9:16 / 540×960@30）
- 音频：300→600→450→520 Hz

| 镜 | 时长 | 底色 | 屏上文字 | 运镜 |
|---|---|---|---|---|
| 1 | 4s | #8a8a8a（灰） | BEFORE | 静止 |
| 2 | 4s | #f4a832（亮橙） | AFTER | 缓推 |
| 3 | 4s | #2a6f4e | 3X FASTER | 缓拉 |
| 4 | 4s | #1b3a5c | VERDICT WORTH IT（48px） | 静止 |

切点：0 / 4 / 8 / 12 秒。

## 用例与预期

| id | 内容 | 预期 |
|---|---|---|
| QC-07 | 质量 | 全过 |
| RT-07 | teardown 拆解（LLM，brief=换商品） | 镜头数 3-5；avg_shot 3.0-5.0s；文字含 BEFORE/AFTER/VERDICT 之一 |

## 执行

```bash
cd apps/api && uv run python ../../test-materials/tools/run_tests.py --only QC-07,RT-07
```
