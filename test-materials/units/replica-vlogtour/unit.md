# 风格单元：探店 vlog（replica-vlogtour）

> 单元自包含：本方案 + `brief.txt`（复刻目标=换场景）+ 视频素材。

## 风格定位

探店 vlog：邀请跟随→场景亮相→价格钩子→人气证明→推荐→收藏号召的
六拍情绪递进，轻推拉运镜。考察拆解器对 **vlog 叙事节拍与号召类 CTA**
（SAVE THIS）的识别。

## 素材与真值

- 文件：`rep_vlogtour_9x16_18s.mp4`（18s / 9:16 / 540×960@30）
- 音频：440→494→554→622→698→784 Hz 递升

| 镜 | 时长 | 底色 | 屏上文字 | 运镜 |
|---|---|---|---|---|
| 1 | 3s | #c96f3a | COME WITH ME | 缓推 |
| 2 | 3s | #3a6fc9 | THIS PLACE | 缓拉 |
| 3 | 3s | #c9a53a | ONLY 10 YUAN | 缓推 |
| 4 | 3s | #7a3ac9 | SO CROWDED | 缓拉 |
| 5 | 3s | #3ac97a | MUST TRY | 缓推 |
| 6 | 3s | #c93a6f | SAVE THIS | 缓拉 |

切点：0 / 3 / 6 / 9 / 12 / 15 秒。

## 用例与预期

| id | 内容 | 预期 |
|---|---|---|
| QC-08 | 质量 | 全过 |
| RT-08 | teardown 拆解（LLM，brief=换场景） | 镜头数 5-7；avg_shot 2.2-3.8s |

## 执行

```bash
cd apps/api && uv run python ../../test-materials/tools/run_tests.py --only QC-08,RT-08
```
