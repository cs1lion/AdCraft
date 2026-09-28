# 3D 预演（3D Previs）测试方案

> 功能线横切方案。**每个场景的专属 NL 模板与预期在 `units/scene-*/unit.md`**；
> 公共图像/视频夹具在 `fixtures/`。

## 0. Agent 执行入口（自动化优先）

```bash
# 素材规格与内容质量（无需后端）
cd apps/api && uv run python ../../test-materials/tools/run_tests.py --suite media,quality

# 需后端：上传（S3-UP）与深度依赖探测（S3-DEPS）真跑；
# analyze-image / analyze-reference 在 LLM key/额度不可用时自动 SKIP 附真实原因
cd apps/api && uv run python ../../test-materials/tools/run_tests.py --suite api-scene3d
```

## 1. 场景单元索引（NL 模板，agent 判读）

| 单元 | 场景 | 考察点 |
|---|---|---|
| `units/scene-indoor-dialogue` | 茶馆对话（基准） | 五要素齐全、走位+三段镜头 |
| `units/scene-outdoor-run` | 滨江跑道 | 单角色连续位移+移动镜头 |
| `units/scene-product-turntable` | 商品转盘 | 无人物边界（不得臆造角色） |
| `units/scene-night-street` | 夜景街景 | 狭长空间+群戏+环绕镜头 |
| `units/scene-crowd-corridor` | 走廊群戏（压力） | 五人物并发走位（记录丢弃项） |
| `units/scene-warehouse-chase-en` | 英文仓库追逐 | 英文空间/运动词解析 |
| `units/scene-vague-negative` | 刻意含糊负例 | 兜底行为记录（不判对错） |

## 2. 公共夹具用例（runner 自动化）

| id | 素材 | 预期 |
|---|---|---|
| S3-UP | fastcut 单元视频走上传入口 | asset_id + 时长>14s（无 LLM） |
| S3-DEPS | — | opencv/numpy/timm/ffmpeg 依赖清单；all_available=false 则深度提取 SKIP |
| S3-IMG | `fixtures/images/s3d_room_800x600.png` | 单图分析 analyzed=1（LLM） |
| S3-PANO | `s3d_panorama_2048x1024.png`（精确 2:1） | panorama_image_indices 非空（触发 6 面立方体切分） |
| S3-ORBIT | `s3d_orbit_1..6_512x512.png` | 6 图融合 analyzed=6 |
| S3-REF | `fixtures/videos/s3d_refroom_16x9_8s.mp4` | 非空 SceneScript；横移运镜与家具色块被读出（LLM） |
| S3-DEPTH | — | 手动步骤（`/extract-depth` 视频深度），依赖见 S3-DEPS |

图像手动用例：`s3d_corridor_depth_800x600.png` 深度/白模（强透视，中心近四周远）；
`ref_turnaround_3view / ref_ultrawide` 画幅反例走 provider 参考通道
（见 plans/reference-channel-plan.md）。

## 3. 前置与记录

- Blender（本机 `D:\Blender\blender.exe` 已配置）渲染链：SceneScript 3D 编辑 →
  headless 渲染 MP4+关键帧+控制通道 → `previs_control_level=full`（手动基准链）。
- 结果：自动用例落 `results/run-*/`；场景判读记 `results/3d-previs-runlog.md`
  （用例 / SceneScript 产出 / 空间核对 / 降级级别 / 丢弃动作清单）。
- 实测基线（2026-09-27）：S3-UP / S3-DEPS PASS（依赖齐全）；S3-IMG/PANO/ORBIT/REF
  因 LLM 额度 429 SKIP，恢复后重跑即真断言。
