# ADR 0017: 3D 分镜预演参考片段节点（Previs Clip Node）

日期：2026-10-03
状态：已采纳
关联：ADR 0005（3D 低模预演与 §4a 降级阶梯）、ADR 0012（导演口令条）、ADR 0014（导演 take 快照层）

## 背景

导演口令 3D 功能（ADR 0012/0014）让 scene-3d 节点成为导演台：SceneScript、镜头表、
导演 take、全场景 animatic 渲染（`scene3d_emit_video` 默认开，节点输出视频资产 +
`previs_trajectory`）。但"分镜预演参考片段"——按镜头粒度的 3D 预演——不是画布上的
一个节点：它只是 scene-3d 节点输出里的整段 animatic。于是：

1. 分镜片段（storyboard_video）生成时无法以"片段"粒度把预演挂为参考；
2. 导演台的产物与成片生成之间缺一层在画布上可见、可操作、可追溯的关系。

## 决策

### 1. 预演参考片段是一个画布节点，不是新节点类型

`video` 节点类型 + 新创作角色 `scene_3d_previs_clip`（语义角色注册表同号新增，
输出媒体 video，结构化内容 `PrevisClipContentV2`）。

- 预演片段就是一段视频资产：复用 video 节点的预览/播放（poster + Play 大窗）、
  资产管线、时间线拖放，零新增媒体面。
- 与 `storyboard_video` 同模式：身份由创作角色承载，节点类型保持媒体原语。
- `creative_role` 列无 CHECK 约束（只有 node_type 有），无需迁移。

### 2. 来源 = 导演台发布；关系第一层落在图上（scene-3d → clip）

`POST /api/v2/workflows/{workflow_id}/scene-3d-nodes/{node_id}/previs-clips`
（body: `{shot_id}`，Idempotency-Key 必填）：

1. 读 scene-3d 节点的 SceneScript，按 `shot_id` 取镜头帧区间
   （`start_frame`/`end_frame` ÷ `frame_rate`）；
2. 读该节点 `output_asset_id` 的 animatic 视频字节，ffmpeg 重编码裁切出该镜头片段
   （台词床音一并保留）；
3. 抽 5 张关键帧（0/25/50/75/100%）发布为派生图片资产；
4. 通过 `connected_authoring.create_connected_node` 在画布创建 previs clip 节点
   （anchor = scene-3d 节点，downstream，`video_reference` 绑定），节点
   `source_asset_id` = 裁切片段资产，`structured_content` 记录完整血缘：
   `PrevisClipContentV2 { scene_3d_node_id, shot_id, shot_label, take_id,
   frame_range, duration_seconds, previs_keyframes[], previs_control_level }`；
5. scene-3d 节点 `structured_content.published_previs_clips` 追加该片段节点 id
   （血缘双向可查）。

未渲染 animatic 时发布动作报 `scene3d_animatic_missing`（可查询，绝不静默）。

### 3. 消费 = 与分镜片段连线（clip → storyboard_video）

`video → video` 的 `video_reference` 连接策略已存在（connection policy 表既有行，
本 ADR 不改策略）。预演片段节点连到分镜片段视频节点，即"这一镜照这段预演拍"。

### 4. flash 降级通道：关键帧替代视频参考（ADR 0005 §4a 落地）

`agnes-video-2.5-flash` 拒绝 `videos` 参数（catalog `video: 0`，
`seedance_adapter` 已 withhold+warn——但 withhold 后关系就断了）。本次补上通道：

`apply_provider_reference_limits` 之后、`materialize_inputs` 之前执行
`substitute_previs_keyframes_for_videoless_models(manifest, resolution)`：
目标模型视频参考额度为 0 且图像额度 > 0 时，把 `source_semantic_role ==
scene_3d_previs_clip` 的被扣 video 输入替换为其发布时记录的关键帧图片资产
（`reference_instruction` 注明"跟随预演运镜与构图"），原 video 绑定记
`omitted_previs_clip_keyframes_substituted`，替换输入的 binding_metadata 带
`previs_control_level: "images_only"`——降级可查询，绝不静默。

支持视频参考的模型（如 `agnes-video-2.5`）不受影响，仍走 `videos` 数组通道。

### 5. 运行守卫

previs clip 节点不进生成调度：`MediaNodeExecutor` 对
`creative_role == scene_3d_previs_clip` 的 video 节点报
`previs_clip_publish_only`（片段由导演台发布与重发布，不烧视频额度）。

## 后果

+ 导演台产物第一次以镜头粒度进入成片链路，且图上三处可见：节点卡血缘徽标、
  scene-3d → clip 连线、clip → storyboard_video 连线。
+ flash 下预演关系仍有实效（关键帧引导运镜/构图），且与 ADR 0005 §4a 的
  降级词汇（previs_control_level）对齐。
− 关键帧是派生资产（每片段 5 张图的存储成本）；发布依赖 scene-3d 节点已有
  animatic 渲染产物。
− 预演片段节点的 `general_video` 生成运行被守卫挡住——这是刻意的：片段的
  内容来源是渲染管线，不是提示词到视频的生成。
