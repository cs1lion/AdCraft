# 3D 预演工作台参考框架（四张截图的理解结果）

> 来源：2026-10-04 用户提供的四张参考截图，经 StepFun `step-5-preview`
> （`detail: "high"`）逐字识别。生成脚本 `understand-images.py`（不入库，
> 属一次性工具）。本文件是 `feat/scene3d-shot-preview-bridge` 分支的设计依据。

## 截图清单

| 文件 | 内容 |
|---|---|
| `713f9da3`（2520×1701） | 3D 预演**编辑态**：左 70% 视口 + 右 25% 项目资产/属性 + 左下悬浮机位视频卡 + 底部播放条 |
| `b8407185`（2531×1710） | **agent 执行后**：3D 视口中央弹出 Agent 结果对话框；把 3D 与视频的血缘讲得最清楚 |
| `abda88f2`（2517×1692） | **成片预演态**：中央大视口播成片 + 底部 AI 指令栏 + 分镜时间轴（25s / 6 镜） |
| `3883418a`（2493×1689） | **节点画布**：左「视频」节点 → 白线 → 右「AI生成」预览节点；左下参数台 |

## 本质：一个「机位」把 3D 和视频钉在一起

```
SceneScript（3D 场景）
   └─ 机位 camera keyframes ──┐
                              ├─► 分镜 shot（25s / 6 个）
                              │      └─► 渲染 ► 视频片段 asset
                              └─ 「机位01 | 双人全景」= 3D 机位 = 视频片段标题
```

`b8407185` 的 agent 输出是这套模型最直白的陈述：

> 飞船起飞的动画已加在「机位05 | 飞船俯瞰」对应的镜像段（4.5s-8.0s），并从该
> 机位重新构图取景，整段成片（25s、6个分镜）已一并交付。

即：**机位是唯一纽带**——一个 3D 相机 ↔ 一个分镜段 ↔ 一个视频片段，三者同名同生
共死；agent 改的是 3D，交付物是视频，并明确"从该机位重新构图取景"。

## 与仓库现状的对照（2026-10-04 实测）

| 参考图概念 | 现状 | 结论 |
|---|---|---|
| 机位 ↔ 分镜段 | `SceneShot.camera → SceneCamera.id`，后端 4 个 validator 兜底 | ✅ 已存在 |
| 分镜段 → 视频片段 | `PublishedPrevisClipEntryV2 { node_id, shot_id, clip_asset_id, take_id }`，存于 scene-3d 节点 `structured_content.published_previs_clips` | ✅ 已存在 |
| 机位人类可读名 | 相机 id 为机器名（`cam_1`）；无 `display_name` | ❌ **真缺口** |
| 机位视频卡 UI | `StoryboardPanel` 只以列表展示血缘，视口内无播放卡 | ❌ 待建 |
| 双模式（场景调度/成片预演） | 无 `viewMode` | ❌ 待建 |
| agent 按段交付报告 | `preview_3D_scene` 工具名在仓库中不存在 | ❌ 待建 |

## 本次分支的做法

不新建 `CameraShot` 实体——那会与已有的 `SceneShot` + `SceneCamera` +
`published_previs_clips` 三处打架，制造两个真相源（违反 engineering-standards
§2 契约同步 / §6 决策留痕）。改为**把已有链条暴露成 UI**：

1. **纯前端、零 schema 变更**（先做，风险最低，可立即验证链条能打通）
   - `shotLabels.ts`：`cameraLabel()` + `shotForFrame()`（后者从
     `SceneScript3DPreview.tsx` 内联实现提取）
   - `<CameraGizmo>` 挂 `机位NN | display_name` 标签
   - `ShotPreviewCard`：按 shot 从 `publishedPrevisClips` 找 `clip_asset_id`，
     用 `MediaSurface` 播放
2. **additive schema 变更**（链条跑通后再决定）：`SceneCamera.display_name`
   （可选 + 默认 None，同 `transition_intent` 模式）

## 复刻要点（来自逐字识别）

- 机位标签形态：摄像机图标 + `机位01 | 双人全景`，带播放与全屏按钮
- 成片预演态底部：AI 指令栏占位文字「选中一个元素或机位，描述如何调整..」
  + 分镜块（00:02/00:04/00:06…，总 00:25）+ 播放/缩放
- 节点画布左下面板：`+参考` / `标记` / `特效` / `角色库` / `运镜` 五个胶囊
  + 素材缩略图（序号 / 时长）+ 提示词文本 + 模型参数行
- 右侧属性面板：`位置`/`缩放`（带锁）/`旋转` 的 X/Y/Z + `状态` 按钮
