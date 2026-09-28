# 风格单元：快剪带货（replica-fastcut）

> 单元自包含：本方案 + `brief.txt`（中文复刻目标）/ `brief-en.txt`（英文）+ 视频素材。
> 全部用例可经 `test-materials/tools/run_tests.py` 执行（映射见「用例」节）。

## 风格定位

短视频平台最常见的促销带货片：高频切点 + 屏上英文大字驱动 + 递进式话术
（钩子→卖点→证明→促销→CTA）。考察拆解器对**快节奏、文字驱动**结构的读片能力。

## 素材与真值

- 文件：`rep_fastcut_9x16_15s.mp4`（15s / 9:16 / 540×960@30）
- 音频：每镜正弦 440→494→554→622→698→784 Hz 递升（切点在频谱上可辨）

| 镜 | 时长 | 底色 | 屏上文字 | 运镜 |
|---|---|---|---|---|
| 1 | 2.5s | #d7263d | STOP SCROLLING | 缓推 |
| 2 | 2.5s | #1b2a6b | 3 SECOND HACK | 缓拉 |
| 3 | 2.5s | #146b3a | IT JUST WORKS | 缓推 |
| 4 | 2.5s | #b3541e | REAL RESULTS | 缓拉 |
| 5 | 2.5s | #6a1b4d | HALF PRICE TODAY（黄字） | 缓推 |
| 6 | 2.5s | #2415a0 | BUY NOW | 缓拉 |

切点：0 / 2.5 / 5 / 7.5 / 10 / 12.5 秒。

## 用例与预期

| id | 内容 | 预期 |
|---|---|---|
| QC-01 | 每镜颜色/文字像素/切点帧差/音频电平 | 全过 |
| RT-01 | teardown 拆解（LLM，brief=换商品） | 镜头数 5-7；avg_shot 2.0-3.2s；屏上文字含 BUY NOW |
| RT-CHAIN | 报告→蓝图→导出→重编译全链（LLM×1） | format/slots 一致 |
| S3-UP | 同片走 scene-3d 上传入口（无 LLM） | asset_id + 时长>14s |

## 执行

```bash
cd apps/api && uv run python ../../test-materials/tools/run_tests.py --only QC-01,RT-01
```
