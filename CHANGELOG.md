# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Changed — Provider 视频/音频参考通道（`videos[]` / `audios[]`）+ 公网可达 URL
- **`apps/api/app/tools/seedance_adapter.py`** — Agnes 分支此前**只发 `images[]`**：`videos[]` / `audios[]` 从未被构造，已投递的 video/audio 参考被静默丢弃；更糟的是 `mode` 只按图片数量判定，于是只带视频参考的镜头以 `"mode": "text"` 发出——字节照付，素材一次没被读。现在三类各自成数组（`videos` 元素是 object，带 `url`/`start_seconds`/`require_audio`；`audios` 是 `string[]`），任一非空即 `mode: "reference"`，并按同一提交顺序在 prompt 尾部追加 `<Picture N>` / `<Video N>` / `<Audio N>` 及其用途（文档要求说明素材用途）。`provider_file_id` / 内联 `data_url` 现在抛 `provider_reference_delivery_unavailable`，不再静默消失
- **`apps/api/app/services/provider_model_catalog.py`** — `agnes-video-2.5-flash` 的 `reference_limits` 由 `video: 3` 改为 **`video: 1`**（文档写明 `videos` 最多 1 个，`video: 3` 无依据）；`image` **保持 5 不动**——文档写 8，但 2026-09-22 一次真实 400 是 `{"max_images": 5}`，改成 8 会复现"元数据承诺了 provider 不授予的权限、然后整个请求被拒"
- **`apps/api/app/services/agent_canvas_reference_composition.py`** — 修掉"视频运镜吃图片份额"这个潜伏 bug：`has_motion` 现在只统计**图片类型**的运镜参考。此前 `media_type=="video"` 的运镜也被算作 motion，把 `design_budget` 压到 2，成品参考被白白 withhold——可视频参考占的是 `videos[]`，从来不是图片槽位。不变式：视频类型运镜无条件 admitted 且不削减图片份额；只有图片类型运镜（`storyboard_grid`）与设计参考分享那 5 个槽位
- **`apps/api/app/core/config.py`** + **`apps/api/app/services/v2_provider_reference_input_delivery.py`** — 新增 `provider_reference_public_base_url`（环境变量 `PROVIDER_REFERENCE_PUBLIC_BASE_URL`，为空则行为完全不变）与 `_canvas_public_url()`：资产库把 `public_url` 存成**路径**（`media_paths.public_url_for_path` → `/media/...`），而 `is_provider_compatible_public_url` 以"没有 scheme"拒掉它，于是**任何非图片资产今天都过不了投递门**（`media_requires_remote_transport`）。命名主机后路径即补成绝对 URL 交给既有门禁裁决。已绝对的不改写（指向 CDN 不会覆盖别人刻意记的 URL）；鉴权的 `/api/v2/assets/.../content` 不补——补了只会把本地明确拒绝变成 provider 侧一个 401（`main.py:111` 的豁免名单划的是同一条线：`/media` 豁免，内容路由不豁免）
- **测试** — `apps/api/tests/test_provider_reference_public_base_url.py`（11 条，驱动 `_deliver_canvas_version` 真跑投递：命名主机后 clip 以 `video_url` 送出，未命名则如实报 `media_requires_remote_transport`）、`apps/api/tests/test_seedance_agnes_video_audio_references.py`（13 条）、`apps/api/tests/test_agent_canvas_reference_composition.py`（视频 motion 不再压份额）
- **已知边界（部署侧，非代码）** — `videos` 一次请求只能发 1 段；`videos[].url` 必须公网 https 可达。2026-09-23 实测那台 CVM（49.233.207.18）开机后 80 口在发 nginx + 本项目 web 前端，但 **443 完全没有证书**（TCP 通、TLS 握手被 RST、`no peer certificate available`），所以它当前无法满足 https 要求；门禁只看 scheme 与地址类型，公网 IP + https 是过闸的，过闸不等于那台机器真的在服务

### Fixed — 生图/火山接口瞬时故障不可恢复，3D 预演在画布上基本不可用

#### 图像生成：StepFun-only 迁移（P0）
- **`apps/api/app/tools/volcengine_image_generations.py`**、**`apps/api/app/services/provider_model_catalog.py`** — 图像 provider 收敛到 StepFun（`step-image-edit-2`），移除火山方舟作为生图路径的兜底；新增目录自测 `apps/api/tests/test_stepfun_only_image_catalog.py`，断言 `capability="image"` 条目只解析到 StepFun，防止火山系重新混入

#### Provider 瞬时故障：分类 + 退避重试（P0）
- **`apps/api/app/services/v2_provider_error_classification.py`（新增）** — HTTP 状态 → `(error_code, retryable)` 的单一来源：`408/504 → provider_timeout`、`429 → provider_rate_limited`、`500/502/503/599 → provider_temporary_unavailable`，其余 5xx → `provider_server_error`；同时识别响应体里的 `engine_overloaded` / `"try again later"` / `服务繁忙`。之前火山返回 **HTTP 503 `engine_overloaded`** 被统一写成 `provider_request_failed` 且 `retryable: false`，用户看不到重试入口，只能等服务恢复
- **`apps/api/app/services/v2_provider_executor.py`** — `MediaApiError` 与兜底 `except Exception` 两个分支都套用分类，并把 `retryable` 写进 `V2ProviderResult.metadata`
- **`apps/api/app/services/agent_canvas_node_execution.py`** — 结果 `retryable` 为真时按指数退避原地重试（默认 1s→2s→4s，最多 3 次），每次记 `provider_task_recovering` 事件，可观测
- **`apps/api/app/tools/media_response_parsing.py`** — 提取 `metadata["provider_error_code"]`，并补 503 专用的 `user_action` 提示
- **`apps/api/app/core/config.py`** — 新增 `provider_transient_retry_attempts`（默认 3）、`provider_transient_retry_base_delay_seconds`（默认 1.0）

#### 3D 预演：超时可调 + 按帧数推导 + Blender 并发闸（P1）
- **`apps/api/app/core/config.py`** — 新增 `scene3d_render_timeout_seconds`（默认 **1800**，收敛到 30–3600）、`scene3d_max_concurrent_renders`（默认 1）、`scene3d_render_keyframes_only`（默认 True）、`scene3d_render_startup_seconds`（默认 90）、`scene3d_render_seconds_per_frame`（默认 6.0）
- **`apps/api/app/services/agent_canvas_node_execution.py`** — 画布节点改用显式 `timeout_seconds`；超时预算按 `startup + per_frame × frame_count` 推导，`scene3d_render_timeout_seconds` 退化为上限；默认只渲 5 个关键帧。原来这里恒为 600s 且 N 个分镜节点并发派发、N 个 Blender 进程互相饿死（实测 6 分镜并发只有 3 个成功，串行 + 1800s 则 6/6）
- **`apps/api/app/services/agent_canvas_node_execution.py`** — `Scene3DNodeExecutor` 注入进程级 `threading.Semaphore`，「Run all」依然并发派发、但 Blender 串行执行，不改变节点间依赖调度语义
- **`apps/api/app/services/scene3d/blender_renderer.py`** — `TimeoutExpired` 报错带上超时前已产出的帧数，区分「差一点就渲完」和「一开始就卡住」；`RenderResult` 新增 `degraded_assets: tuple[str, ...]`
- **`apps/api/tests/test_agent_canvas_local_engine_executors.py`** — 假渲染器签名同步为关键字参数

#### 3D 预演：资产几何补齐 + 配色单一来源（P1）
- **`apps/api/app/services/scene3d/blender_converter.py`** — `_ASSET_BUILDERS` 补齐 11 个环境类型（`tree/platform/stairs/rock/fence/window/flat_roof` 等）与 10 个道具类型（`chair/stool/rect_table/box/crate/vase/weapon/scroll/book/cup` 等），`PropType`/`EnvironmentType` 每个成员现在都有几何
- **`apps/api/app/services/scene3d/blender_converter.py`** — **配色**：新增 `_ASSET_COLORS` / `_DEGRADED_ASSET_COLOR`（`#FF2BD1`）/ `_PART_COLOR_OVERRIDES`，`_build_asset` 的 parenting 循环统一赋材质（角色保留自己的 body/head 配色）。此前只有 `_build_lowpoly_human` 赋过材质，实测**全类型一帧 518400 像素里 0 个彩色像素**——整个预演是一片默认灰
- **`apps/api/app/services/scene3d/blender_converter.py`** — **去掉静默降级**：fallback 时在生成脚本里追加 `# PREVIS_DEGRADED_ASSET: <id> (<type>)`，并把降级项回传到 `RenderResult.degraded_assets` → 节点产出媒体 metadata（ADR 0005「queryable, never silent」）。修复后实测：**75.11% 像素有色**，故意降级一个类型则渲染出 543 个品红像素（0.105%），肉眼可辨
- **`apps/api/tests/test_scene3d_asset_geometry_coverage.py`** — 93 个测试：全枚举集合断言、生成脚本 AST 解析、bpy operator 关键字表（bpy 只在**脚本运行时**报 `keyword unrecognized`，2026-09-19 E2E 的 vase/cup 分镜就是这么挂的）、真 Blender 全类型渲染、降级可见性（品红像素）、配色契约

#### BGM / 409 / 422 / 轮询可诊断性
- **`apps/api/app/tools/bgm_provider_factory.py`** — provider 不匹配与不支持的报错列出「配置值 / 解析值 / 支持的三值」，`stepfun_music` 提前校验 music 能力配置，不再让用户看到 provider 不匹配的假象
- **`apps/api/app/services/provider_model_catalog.py`** — 为 `stepfun_music` 增加 music 能力条目
- **`apps/api/app/services/agent_canvas_ad_media.py`** — 422 `invalid_role_content` / `semantic_role_node_type_mismatch` 填 `details.validation_paths` 与 `content_schema_ref`（Pydantic `error.errors()` 的 `loc`，限长）
- **`apps/api/app/services/agent_canvas_runtime.py`** — 409 `failed_node_retry_required` 填 `details.missing_field/expected_value/node_ids`；`node_runtime[].execution_id` 与 `active_execution_id` 在 member 缺失时回退到最近一次 attempt，轮询者至少能区分「从未跑过」和「跑完了」

### Added — Reference Video Upload & Depth Map (White Model) Extraction

#### Reference Video Upload (P0)
- **`apps/api/app/services/scene3d/reference_upload.py`** — 参考视频上传服务（格式/大小/时长验证，ffprobe元数据提取，均匀关键帧提取，asset_id生成，上传目录管理）
- **`apps/api/app/api/v1/endpoints/scene_3d.py`** — 新增3个端点：`POST /upload-reference`（上传视频+验证+关键帧提取）、`GET /reference-videos`（列出已上传视频）、`GET /reference-videos/{asset_id}`（获取单个视频元信息）
- **`apps/web/src/features/agent-canvas/canvas/ReferenceVideoPanel.tsx`** — 前端上传组件（拖拽上传+进度条+验证反馈+视频元信息显示+关键帧预览）
- **`apps/web/src/features/agent-canvas/canvas/SceneScriptPanel.tsx`** — 新增"Reference"标签页，集成参考视频上传功能

#### Depth Map (White Model) Extraction (P0)
- **`apps/api/app/services/scene3d/depth_estimator.py`** — 深度估计服务（MiDaS单目深度估计，支持DPT_Large/DPT_Hybrid/MiDaS_small三种模型，6种colormap，逐帧处理+视频编码+关键帧提取，懒加载依赖，CPU/GPU自动切换）
- **`apps/api/app/api/v1/endpoints/scene_3d.py`** — 新增2个端点：`POST /extract-depth`（从视频提取深度图白模）、`GET /depth-dependencies`（检查依赖安装状态）
- **`apps/web/src/features/agent-canvas/canvas/ReferenceVideoPanel.tsx`** — 集成白模提取功能（提取按钮+处理状态+结果显示+深度关键帧预览）
- **`apps/api/pyproject.toml`** — 新增依赖：torch>=2.0.0、timm>=0.9.0、opencv-python>=4.8.0、numpy>=1.26.0

#### Prompt Editing (P0)
- **`apps/web/src/features/agent-canvas/canvas/SceneScriptPanel.tsx`** — 新增"Prompt"标签页（调用`/scene-3d/prompt`端点生成提示词，global_prompt/negative_prompt/per-shot prompt均可编辑，保存按钮+重新生成按钮，reference_mode和reference_instructions显示）

#### Tests & Docs
- **`apps/api/tests/test_reference_upload_and_depth.py`** — 18个测试（8个上传验证测试+5个元数据验证测试+3个深度估计配置测试+1个依赖检查测试+1个集成测试）
- **`docs/3d-previs/reference-and-depth-api.md`** — 完整API文档（5个端点的请求/响应/错误格式，使用工作流，依赖说明，性能参考）

### Added — 3D Low-Fidelity Previs (自然语言→3D动画→可控视频)

#### Core: SceneScript 中间格式 (P0)
- **`apps/api/app/schemas/scene_script.py`** — SceneScript Pydantic schema，11个模型（SceneScriptRoot/SceneInfo/SceneCharacter/SceneProp/SceneEnvironmentObject/SceneCamera/SceneShot/CharacterKeyframe/CameraKeyframe/SpeechBinding/CharacterAppearance）+ 12个交叉验证器（坐标范围、rotation_y弧度检测、shot无重叠、shot不超总帧数、camera/speech引用完整性、id唯一性、keyframe边界等）
- **`apps/api/tests/test_scene_script.py`** — 43个单元测试

#### Backend: LLM解析与节点注册 (P1)
- **`apps/api/app/services/scene3d/parser.py`** — LLM输出→SceneScript解析器（markdown代码块提取、JSON解析、schema验证、结构化错误反馈、retry_feedback生成）
- **`apps/api/app/services/workflow_node_catalog.py`** — 注册 `scene-3d` 节点（category=visual_planning, output_asset_roles=["scene_script"], downstream到video/bgm/final-composition）
- **`apps/api/app/schemas/workflow_v2.py`** — WorkflowAssetSemanticTypeV2添加 `"scene_script"`
- **`apps/api/agent/skills/video_agent_3d_storyboard/`** — Agent Skill（SKILL.md + 2个examples：静态双人对话、动态角色走进+推镜）
- **`apps/web/src/types-v2.ts`** — WorkflowNodeTypeV2添加 `"scene-3d"`
- **`apps/api/tests/test_scene3d_parser.py`** — 23个单元测试

#### Backend: Blender渲染管线 (P2)
- **`apps/api/app/services/scene3d/blender_converter.py`** — SceneScript→Blender Python脚本转换器（纯函数可单元测试，10+种low-poly资产构建函数：lowpoly_human/round_table/pillar/wall/floor/gable_roof/door/lantern/rect_table/chair/stool/box/crate/vase/weapon/scroll/book/cup）
- **`apps/api/app/services/scene3d/blender_renderer.py`** — Blender headless渲染器（subprocess管理+超时+artifact收集+能力探测缓存）
- **`apps/api/app/services/scene3d/encoder.py`** — PNG序列→MP4编码器（ffmpeg libx264）
- **`apps/api/app/services/scene3d/keyframes.py`** — 5关键帧提取器（每shot提取0%/25%/50%/75%/100%，Blender 1-indexed帧号适配）
- **`apps/api/tests/test_scene3d_pipeline.py`** — 22个单元测试
- **`apps/api/tests/test_scene3d_renderer_integration.py`** — 5个集成测试（用D:\Blender\blender.exe真实渲染1秒30帧场景验证）

#### Frontend: 3D预览 (P3)
- **`apps/web/src/types/scene-script.ts`** — SceneScript TypeScript类型定义（镜像后端schema）
- **`apps/web/src/features/agent-canvas/canvas/SceneScript3DPreview.tsx`** — 3D预览组件（Three.js+@react-three/fiber+@react-three/drei，渲染low-poly角色/道具/环境/相机gizmo，OrbitControls，播放控制+帧滑块，HUD显示帧信息）

#### Frontend: 画布节点集成 (P4)
- **`apps/web/src/features/agent-canvas/canvas/SceneScriptPanel.tsx`** — 面板组件（3D预览/场景信息/JSON三标签页，信息面板显示播放状态栏）
- **`apps/web/src/features/agent-canvas/model/sceneScriptUtils.ts`** — 辅助函数（从节点structured_content/metadata提取SceneScript、isScene3DNode检测、getTotalFrames、getActiveCameraId）
- **`apps/web/src/features/agent-canvas/canvas/AgentCanvasNode.tsx`** — 修改：NodeSurface中检测SceneScript并显示SceneScriptPanel
- **`apps/web/src/features/agent-canvas/canvas/SceneScriptPlaybackContext.tsx`** — 共享播放状态Context+Provider+hook（requestAnimationFrame统一播放循环，3D标签页↔信息标签页同步，切换不丢失播放位置，预留onTimeChange外部同步接口）

#### Backend: 视频模型集成 (P5)
- **`apps/api/app/services/scene3d/prompt_builder.py`** — 逐镜头提示词生成器（相机语言映射shot_type→camera description、相机移动检测push-in/pan/dolly、角色动作语言映射、环境/灯光描述、道具描述、负向提示词、全局提示词；determine_reference_mode三级降级：video→keyframes→none；keyframe_guidance_text生成5帧引导文本）
- **`apps/api/app/services/scene3d/reference_assets.py`** — 参考素材管理（VideoModelInput构建、ReferenceVideoAsset、ReferenceKeyframeSet、format_reference_instructions人类可读指令）
- **`apps/api/tests/test_scene3d_prompt_builder.py`** — 31个单元测试

#### Backend: 镜头模板库+多画幅适配 (P6)
- **`apps/api/app/services/scene3d/shot_templates.py`** — 7种预设模板（dialogue_shot_reverse/dialogue_wide_then_cu/monologue_to_camera/character_entrance/establishing_shot/product_showcase_orbit/walk_and_talk）+ ShotTemplate数据类 + list_templates/get_template + generate_from_template调度器 + 3个具体生成器
- **`apps/api/app/services/scene3d/aspect_ratios.py`** — 6种画幅（16:9/9:16/1:1/4:3/21:9/4:5）+ AspectRatio数据类 + adapt_camera_for_aspect相机距离适配（portrait后移√(base/target)）+ adapt_scene_script_for_aspect全场景适配+render_settings + get_render_resolution preview/standard/high三级质量 + _hfov_to_vfov FOV转换
- **`apps/api/tests/test_scene3d_templates_aspect.py`** — 46个单元测试

#### Backend: API端点
- **`apps/api/app/api/v1/endpoints/scene_3d.py`** — 12个REST端点：
  - `GET /scene-3d/capability` — 查询Blender渲染能力
  - `POST /scene-3d/render` — 同步渲染SceneScript→视频+关键帧
  - `POST /scene-3d/render/async` — 提交异步渲染任务
  - `GET /scene-3d/render/{job_id}` — 查询异步任务状态
  - `GET /scene-3d/render/jobs` — 列出所有任务
  - `POST /scene-3d/render/{job_id}/cancel` — 取消任务
  - `POST /scene-3d/keyframes` — 从已渲染帧提取5关键帧
  - `POST /scene-3d/prompt` — 生成视频模型提示词+参考素材指导
  - `GET /scene-3d/templates` — 列出可用镜头模板
  - `POST /scene-3d/template` — 从模板生成SceneScript
  - `GET /scene-3d/aspect-ratios` — 列出可用画幅
  - `POST /scene-3d/adapt-aspect` — 适配SceneScript到目标画幅
- **`apps/api/app/api/v1/router.py`** — 注册scene_3d路由

#### Backend: 异步渲染任务队列
- **`apps/api/app/services/scene3d/render_job_manager.py`** — 线程安全的内存任务管理器（RenderJob数据类、RenderJobManager类、submit/get/list_jobs/cancel/cleanup/shutdown、后台ThreadPoolExecutor执行、进度跟踪0.0-1.0、任务状态pending/running/completed/failed/cancelled、get_render_job_manager单例）

#### Backend: 语音编排层与口型同步
- **`apps/api/app/services/scene3d/speech_orchestration.py`** — 完整的语音时间线管理：
  - `SpeechSegment` — 语音片段（角色/文本/起止时间/情感/音频路径）
  - `SpeechTimeline` — 时间线管理（重叠检测/间隙检测/越界检测/空文本检测/segments_for_character/segments_at_time/active_character_at_time/to_speech_bindings）
  - `TTSEngine` Protocol + `SimpleTTSEngine`（占位，可插拔）
  - `LipSyncGenerator` — 口型关键帧生成器（音节级开合变化，合并到角色动画，merge_into_scene_script）
  - `build_timeline_from_script()` — 从对话脚本自动构建时间线
- **`apps/api/tests/test_scene3d_speech.py`** — 39个单元测试

#### Backend: StepFun TTS引擎接入
- **`apps/api/app/services/scene3d/stepfun_tts.py`** — StepFun（阶跃星辰）TTS引擎实现：
  - `StepFunTTSEngine` — 继承SimpleTTSEngine，实现TTSEngine协议，调用StepFun OpenAI兼容TTS API（POST /v1/audio/speech）
  - 支持模型：step-tts-mini / step-tts-2 / stepaudio-2.5-tts
  - 支持环境变量配置：STEPFUN_API_KEY / STEPFUN_TTS_ENDPOINT / STEPFUN_TTS_MODEL / STEPFUN_TTS_VOICE
  - 无API key时自动回退到SimpleTTSEngine行为（不生成音频，只返回路径）
  - `synthesize_batch()` — 批量合成
  - `create_stepfun_tts_from_settings()` — 从app settings创建
- **`apps/api/app/core/config.py`** — 添加StepFun TTS配置字段（stepfun_api_key/stepfun_tts_endpoint/stepfun_tts_model/stepfun_tts_voice）+ 环境变量读取
- **`apps/api/tests/test_scene3d_stepfun_tts.py`** — 16个单元测试

#### Documentation
- **`docs/adr/0005-3d-low-fidelity-previs.md`** — ADR架构决策（含降级策略4a：参考视频→5关键帧→纯提示词）
- **`docs/plans/3d-previs-construction.md`** — P0-P6建设计划（已更新状态为completed）
- **`docs/3d-previs/README.md`** — 文档索引
- **`docs/3d-previs/prompt-engineering-guide.md`** — 提示词工程指南
- **`docs/3d-previs/blender-integration-guide.md`** — Blender集成指南
- **`docs/3d-previs/user-input-guide.md`** — 用户输入指南

### Architecture Decisions
- **SceneScript中间格式**：LLM不直接调bpy，输出结构化JSON→确定性转换器→Blender渲染
- **双引擎**：前端Three.js即时预览 + 后端Blender生产渲染
- **三级降级策略**（ADR 0005 §4a）：参考视频 → 5关键帧图片 → 纯提示词
- **共享播放状态**：SceneScriptPlaybackContext统一管理播放循环，3D标签页↔信息标签页同步
- **可插拔TTS**：TTSEngine Protocol，StepFunTTSEngine实现，无key时自动回退

### Test Coverage
- 单元测试：221个（43 schema + 23 parser + 22 pipeline + 31 prompt_builder + 46 templates/aspect + 39 speech + 16 stepfun_tts）
- 集成测试：5个（真实Blender渲染）
- 总计：226个测试全部通过
- ruff clean（所有后端代码）
- 前端tsc通过（仅预存在的AgentCanvasMarkdown.tsx无关错误）
- agent verify:skills通过

### Added — scene-3d 节点接入主工作流 + 旁白支持

#### Backend: 节点执行器
- **`apps/api/app/services/agent_canvas_node_execution.py`** — 新增 `execute_scene_3d` 函数：SceneScript→Blender渲染PNG帧→ffmpeg编码MP4→返回NodeExecutionOutcome，限制30帧同步执行，6种清晰错误处理；NodeExecutionDispatcher注册scene_3d_executor；fake/real模式均支持
- **`apps/api/app/schemas/agent_canvas.py`** — CanvasNodeTypeV2 Literal添加 `"scene-3d"`（否则节点无法创建）；新增WorkflowProgressResponse+NodeProgressSummary schema
- **`apps/api/app/api/v2/endpoints/agent_canvas.py`** — 新增 `GET /workflows/{workflow_id}/progress` 端点：返回图计数（total/ready/working/failed/draft）+ progress_percent + blocked_nodes（含next_action）+ working_nodes + overall_status

#### Backend: 旁白（TTS+音频合成）
- **`apps/api/app/services/scene3d/encoder.py`** — 新增MuxResult+mux_audio_to_video（ffmpeg -c:v copy -c:a aac -shortest）
- **`apps/api/app/services/scene3d/fish_audio_tts.py`** — Fish Audio TTS引擎（POST /v1/audio/speech，兼容raw-bytes/JSON b64/URL三种响应形状）
- **`apps/api/app/services/scene3d/tts_engine_factory.py`** — create_tts_engine_from_settings，按"第一个配置了key的provider"自动选引擎（StepFun/FishAudio）
- **execute_scene_3d旁白支持** — 从structured_content读取narration和narration_voice，调用create_tts_engine_from_settings自动选引擎，TTS生成MP3，ffmpeg合成音频到视频；Best-effort降级（TTS/合成失败时继续返回纯视频）

#### Frontend: 旁白面板
- **`apps/web/src/features/agent-canvas/canvas/SceneScriptPanel.tsx`** — 新增Narration标签页+NarrationContent组件+narration/narrationVoice props
- **`apps/web/src/types-v2.ts`** — 添加scene-3d节点类型+WorkflowProgressResponse类型

### Added — ADR 0006 自由创作反馈闭环

#### Design
- **`docs/adr/0006-free-authoring-and-guidance.md`** — ADR架构决策：引导是顾问不是门禁；自由创作永不失败到不可用；状态可见性是一等公民；authoring_origin(user_free|agent_guided|template)+intent_hint

#### Backend: Schema扩展
- **`apps/api/app/schemas/agent_canvas.py`** — CanvasNodeCreateRequestV2/CanvasNodeV2新增authoring_origin（user_free|agent_guided|template，默认user_free）+intent_hint（自由节点上用户写"这节点想干嘛"）
- **`apps/api/app/schemas/agent_canvas_guided_interactions.py`** — GuidanceAwaitingV2.kind新增 `"free_node_advisory"`；resume_policy新增 `"free_node_completed"`
- **`apps/api/app/services/agent_canvas_guidance_awaiting.py`** — 新增enter_free_node_advisory方法（轻量级建议等待，不阻塞工作流）

#### Backend: /progress端点优化
- **`apps/api/app/api/v2/endpoints/agent_canvas.py`** — 对authoring_origin=="user_free"的failed节点生成针对性next_action（有intent_hint时显示"Free node for: {intent_hint}. Retry or edit prompt first."）

#### Frontend: 进度条API驱动
- **`apps/web/src/api/v2Client.ts`** — 新增getWorkflowProgress方法
- **`apps/web/src/features/agent-canvas/AgentCanvasPageSurface.tsx`** — 新增serverProgress state，有working/failed节点时每3秒轮询/progress端点；进度条优先使用服务端数据，无服务端数据时回退本地计算；failed状态显示blocked_nodes的next_action

#### Frontend: runNode结构化阻塞原因
- **`apps/web/src/features/agent-canvas/runtime/useAgentCanvasRuntime.ts`** — 新增NodeRunBlockedError类（code: no_workflow/unsupported_node_type/source_only_node/not_runnable_status + message + suggestedNext）；runNode的4个early-return分支全部改为throw NodeRunBlockedError；runNodeById catch后显示友好信息

#### Frontend: failed节点重试+批量重试+诊断面板
- **`apps/web/src/features/agent-canvas/canvas/AgentCanvasNode.tsx`** — 新增onRetry prop解构，status==="failed"&&onRetry时显示红色重试按钮（↻ Retry）
- **`apps/web/src/features/agent-canvas/runtime/useAgentCanvasRuntime.ts`** — 新增retryAllFailed函数（遍历所有failed节点依次调用runNode，单个失败非致命）
- **`apps/web/src/features/agent-canvas/AgentCanvasPageSurface.tsx`** — 工具栏新增"Retry all"按钮（有failed节点时显示）；诊断面板（可展开，显示failed节点列表+next_action+单独重试按钮+节点统计信息total/ready/working/failed/draft/progress%）
- **`apps/web/src/features/agent-canvas/agent-canvas-page.css`** — 重试按钮+批量重试按钮+诊断面板+统计信息样式

### Fixed — 主页最近项目跳转bug
- **`apps/web/src/pages/HomeShowcase.tsx`** — 重写InteractiveRecentCards支持真实项目+formatRelativeTime+openProject交互（修复所有卡片点击都进到同一个项目的bug）
- **`apps/web/src/pages/HomePage.tsx`** — 用useEffect+v2Api.listProjects获取项目（不能用useApp，因为HomePage在LightweightShell路由下没有WorkspaceProvider包裹），navigate传projectId

### Improved — 空状态引导+进度指示器
- **`apps/web/src/features/agent-canvas/chat/AgentCanvasChatPanel.tsx`** — 空状态添加4个示例提示词按钮+placeholder改进
- **`apps/web/src/features/agent-canvas/AgentCanvasPageSurface.tsx`** — 画布空状态改为详细引导→双模式说明（Chat-guided + Free-form）+工具栏全局进度指示器（4种状态：生成中/失败/待运行/完成，进度百分比=ready节点数/总节点数）

### Documentation
- **`README.md`** — News添加3D预演功能发布条目；Core Features新增第14项"3D Low-Fidelity Previs (Camera-Controlled Storyboarding)"完整描述

### Added — Structured Derivation Flow (结构化派生流：世界观→剧本→分镜→3D预演→资产绑定→渲染)

#### P0: 数据模型扩展
- **`apps/api/app/schemas/agent_canvas_ad_media.py`** — StoryboardPanelV2扩展7个结构化字段：`scene_id`/`character_ids`/`prop_ids`/`shot_type`(wide/medium/close-up/ecu/ots)/`camera_move`(static/pan/tilt/dolly/zoom/crane/handheld)/`duration_seconds`(0.5-60)/`scene_script_id`
- **`apps/api/app/schemas/scene_script.py`** — SceneScript扩展3个资产引用字段：`SceneCharacter.character_asset_id`/`SceneProp.prop_asset_id`/`SceneEnvironmentObject.scene_asset_id`
- ruff clean，43 scene_script测试通过

#### P0.5: world_setting审计
- 审计结论：现有`WorldSettingCoreV2`已覆盖era(era_and_place)/world rules(1-8条)/style baseline(visual_continuity)/core conflict(premise)
- `world_setting`是`CanvasCreativeRoleV2`成员（非独立节点类型），内容存储在text节点中，55个文件使用
- 主要缺失：multi-scene ownership（无owned_scene_ids）
- 决策：扩展现有world_setting（添加owned_scene_ids），不新建节点

#### P1a: script→panels派生（LLM驱动）
- **`apps/api/app/services/storyboard_panel_derivation.py`** — StoryboardPanelDerivationService：script_text+world_setting_summary+target_panel_count→StoryboardPanelV2[]
- 使用httpx直接调用LLM API（OpenAI兼容），system_prompt定义分镜艺术家角色
- _extract_json_array处理markdown code block和嵌套数组；_parse_and_validate解析并验证面板，自动分配panel_index，无效面板跳过并记录warning
- 6种错误码：empty_script/llm_unavailable/llm_http_error/no_json_in_output/invalid_json/no_valid_panels
- **`apps/api/tests/test_storyboard_panel_derivation.py`** — 18个测试

#### P1b: panel→SceneScript派生（规则映射）
- **`apps/api/app/services/scenescript_derivation.py`** — SceneScriptDerivationService：StoryboardPanelV2→SceneScriptRoot（确定性规则映射）
- shot_type→camera position+SceneCamera.shot_type（5种映射）；camera_move→camera keyframes（7种：static/pan/tilt/dolly/zoom/crane/handheld）
- subject_action→character action+keyframes（5种：walk/talk/gesture/sit/stand，walk生成2关键帧左→右动画）
- character_ids/prop_ids/scene_id→asset-bound SceneCharacter/SceneProp/SceneEnvironmentObject（P0资产引用字段自动填充）
- duration_seconds→SceneInfo.duration+total_frames；warnings系统+derived_fields审计追踪
- **`apps/api/tests/test_scenescript_derivation.py`** — 44个测试

#### P2: 面板资产绑定+speech_bindings
- **`apps/api/app/schemas/agent_canvas_ad_media.py`** — StoryboardPanelV2扩展`character_speech_map: dict[str, str]`（character_id→speech_audio asset_id）
- **`apps/api/app/services/panel_asset_binding.py`** — PanelAssetBindingService：aggregate()→PanelAssetBundle（character_ids/scene_id/prop_ids/speech_bindings/warnings，含all_asset_ids去重+has_speech+bound_speech_count）；generate_speech_bindings()带bound/free模式；validate_binding_consistency()跨面板（语音资产变更检测+场景变更检测）
- SceneScriptDerivationService集成：speech_bindings从character_speech_map自动填充，默认bound模式（语音驱动镜头时序per ADR-0003）
- **`apps/api/tests/test_panel_asset_binding.py`** — 17个测试 + 7个speech集成测试

#### P3: 视频生成消费预演参考（编排服务）
- **`apps/api/app/services/panel_previs_orchestration.py`** — PanelPrevisOrchestrationService：StoryboardPanelV2[]→逐面板SceneScript（via P1b）→逐面板VideoModelInput（via build_video_model_input）→FinalCompositionPlan
- 参考模式确定per ADR 0005 §4a：支持参考视频→"video"模式；仅支持图片→"keyframes"（每面板5张图，0/25/50/75/100%）；prompt-only作为最后手段
- previs_control_level降级标记（full/video_only/images_only/text_only）可查询、永不静默；复用prompt_builder.previs_control_level()（无重复实现）
- FinalCompositionPlan：面板顺序、每面板时长、转场（cut/dissolve/fade）、reference_modes、control_levels、总时长
- 跨面板绑定一致性验证（P2）；Warnings：混合控制级别、无预演面板、非连续面板索引、>60秒总时长
- **`apps/api/tests/test_panel_previs_orchestration.py`** — 27个测试

#### P3a: Provider层控制信号标记（Party B交付）
- **`apps/api/app/services/scene3d/prompt_builder.py`** — PREVIS_CONTROL_LEVELS + previs_control_level(mode, control_signals_available)
- **`apps/api/app/services/scene3d/reference_assets.py`** — VideoModelInput.previs_control_level property + control_signals_available
- **`apps/api/app/services/v2_provider_executor.py`** — _execute_real_video injects previs_control_level into provider payload
- **`apps/api/app/services/provider_model_catalog.py`** — previs_control_signal_support {depth,normal,flow} fingerprint
- **`apps/api/tests/test_v2_previs_control_level.py`** — 179测试通过（含mutation checks）

#### P4: world_setting扩展+创作流引导服务
- **`apps/api/app/schemas/agent_canvas_world_setting.py`** — WorldSettingCoreV2扩展`owned_scene_ids: tuple[str, ...]`（max 32，建立world→scenes层级）
- **`apps/api/app/services/creation_flow_guidance.py`** — CreationFlowGuidanceService：6阶段流程（world_setting→script→storyboard→scene_3d→binding→render）
- assess_flow(nodes)→FlowAssessment（current_stage/completed_stages/progress_percent/next_action/next_action_detail/blockers/warnings/is_complete）
- 每阶段StageStatus（completed/has_nodes/ready_nodes/total_nodes/blockers）；next-action生成（Create/Run/Move-to/Complete）
- get_flow_stages()+get_stage_guidance()供前端UX使用
- **`apps/api/tests/test_creation_flow_guidance.py`** — 22个测试

#### P5: 前端集成（API+组件+UI）
- **后端API端点**：`GET /workflows/{id}/creation-flow`（创作流评估）+ `GET /creation-flow/stages`（阶段定义）
- **前端API客户端**：v2Api.getCreationFlowAssessment()+getCreationFlowStages()
- **TypeScript类型**：CreationFlowAssessmentResponse/CreationFlowStage/CreationFlowStageStatus
- **`apps/web/src/features/agent-canvas/canvas/CreationFlowGuidance.tsx`** — 创作流引导组件（6阶段进度条+当前阶段高亮+下一步建议+阻塞项面板+警告提示+可展开阶段详情+自动轮询5秒）
- **`apps/web/src/features/agent-canvas/canvas/creation-flow-guidance.css`** — 组件样式
- **`apps/web/src/features/agent-canvas/AgentCanvasPageSurface.tsx`** — 工具栏添加"🎬 Creation Flow"切换按钮+组件渲染
- **`apps/web/src/features/agent-canvas/agent-canvas-page.css`** — 按钮+面板样式
- TypeScript编译通过；端到端测试3/3通过

#### Documentation
- **`docs/plans/3d-creation-flow-collaboration.md`** — 协作公共告示（含Party A/B分工、§4的5个open questions已回答、Status ledger）

#### Test Coverage
- 结构化派生流测试：135个（18 storyboard_panel_derivation + 51 scenescript_derivation + 17 panel_asset_binding + 27 panel_previs_orchestration + 22 creation_flow_guidance）
- P3a provider层测试：179个（含test_v2_previs_control_level）
- 端到端API测试：3/3通过
- ruff clean（所有后端代码）
- 前端tsc通过

### Fixed — 图像/火山接口瞬时故障不可恢复 + 创作流程卡点（2026-09-19 E2E 复盘）

#### 图像/火山接口：503 engine_overloaded 不再一次性判负（ISSUE-12）
- **`apps/api/app/services/v2_provider_error_classification.py`**（新增）— 共享的 provider HTTP 状态分类器 `classify_provider_http_status()` / `classify_provider_error()`：`408`/`504`→`provider_timeout`、`429`→`provider_rate_limited`、`500`/`502`/`503`/`599`→`provider_temporary_unavailable`、其余 5xx→`provider_server_error`，其余→`(None, False)`。响应体含 `engine_overloaded` / `try again later` / `服务繁忙` 时即使状态码是 400 也判为瞬时故障。返回的 code 全部已存在于 `RETRYABLE_PROVIDER_ERROR_CODES`，因此 V2 轮询器无需改动即可识别
- **`apps/api/app/tools/media_response_parsing.py`** — `MediaApiError.metadata` 提取 provider 自身的 `error.type` 到 `provider_error_code`；补 503 专用 `user_action` 提示（原先对 503 返回 None）
- **`apps/api/app/services/v2_provider_executor.py`** — `MediaApiError` 分支与通用 `Exception` 分支都改走分类器决定 `error_code`，可重试时把 `retryable: True` 写进 `V2ProviderResult.metadata`
  - **注意（画布路径的真正入口）**：画布媒体节点走的是 `execute_minimal()` 自己的 `except Exception`（`_execute_native_minimal` 无匹配 adapter 时返回 `None`，随即落到这里），该处原先硬编码 `error_code="provider_generation_failed"` 且**完全不写 metadata**。只修 `_execute_native_minimal` 会让分类在 V2 流水线上生效、却在画布节点上毫无变化——这正是 2026-09-20 复测时图像节点仍然 `retryable: false` 的原因。现已在该处套用同一分类器，并从 `MediaApiError.metadata` 取回真实 HTTP 状态与响应体
- **`apps/api/app/services/agent_canvas_node_execution.py`** — 新增 `_submit_with_transient_retry()`：`retryable` 为真时按指数退避原地重试（1s→2s→4s，上限 30s），并把 `provider_retry_attempts` / `provider_retry_attempts_total` 记进结果 metadata——只在第 3 次成功的节点不能再与一次成功的节点混淆
- **`apps/api/app/core/config.py`** — 新增 `provider_transient_retry_attempts`（默认 3）与 `provider_transient_retry_base_delay_seconds`（默认 1.0）
- **`apps/api/tests/test_provider_error_classification.py`**（31 个）+ **`apps/api/tests/test_provider_transient_retry.py`**（8 个）— 含不变量测试：分类器产出的每个 code 都必须 ∈ `RETRYABLE_PROVIDER_ERROR_CODES`，否则画布侧退避会重试而 V2 轮询器放弃，即"瞬时"出现两套定义
- **`apps/api/tests/test_canvas_provider_error_classification.py`**（7 个）— 直接驱动 `execute_minimal()` 本身（而不是它背后的子系统）断言 503→`provider_temporary_unavailable`+`retryable`、400 不被提升、overload 响应体能提升非 5xx。补这条是因为原有分类测试全绿时画布路径其实是坏的：`execute_minimal` 才是画布真正读的那一层
- **全模态复测通过（2026-09-20 13:42–13:45，`verify_models.py` 干净重跑）**：video/storyboard PASS（`volcengine_ark` / `agnes-video-2.5-flash`，5.17s / 1,514,976 B，`asset_cf3b372ba5c1cc093717de51`）、audio/bgm PASS（`stepfun_music` / `stepaudio-3-music-preview`，194.1s / 3,107,634 B）、audio/voice PASS（6.74s / 109,352 B）；media-toolchain 与 agent-runtime PASS。每个节点都观察到 `attempt admitted` + 真实 `exec_id`，证明上一轮"把上一轮的失败当成本轮结果"的探针陷阱已消除
- **唯一未过的是图像，且原因在 provider 侧**：`provider_temporary_unavailable` + 完整 503 `engine_overloaded` 响应体 + "safe to retry as-is" 提示，14:32 复测仍同一条（详见下方"图像能力的真实可用面"）
- **测试套件**：`727 passed / 72 deselected / exit 0`（`-p no:randomly -m "not integration and not e2e"`，308.68s）
- **已知不一致（可见性，非功能）**：节点错误对象里 `retryable` 仍为 `false`，而同一对象的 `message` 写着 "safe to retry as-is"。原因是 `agent_canvas_execution_state.py:17-25` 的 `APPROVED_TRANSIENT_ERROR_CODES` 是**白名单**，只收编 `provider_poll_temporary_failure` 等内部码，不收编 provider 提交侧分类器产出的码；该白名单同时是 `ActionableFailureV1` 的准入闸（`:86-89`），所以给错误附 `actionable_failure` 也进不去。未改的理由：这张白名单的另一个消费者是 `guidance_awaiting.reconcile_terminal_member()`（人工等待行为的结算），放行 provider 码会连带改变它；且画布节点本来就可以直接重跑（`useAgentCanvasRuntime.ts:525` 只要求 `status === "failed"`），UI 并不读这个布尔。要收敛需单独立项改"瞬时"的定义归属

#### 3D 预演在画布上基本不可用（ISSUE-09）
- **`apps/api/app/services/agent_canvas_node_execution.py`** — 渲染调用显式传 `timeout_seconds=self._scene3d_timeout_seconds`（原先 `blender_renderer.py` 的 `=600` 恒定生效，多分镜必然超时）；`Scene3DNodeExecutor` 增加 `threading.Semaphore` 渲染闸，使"Run all"仍并发派发、但 Blender 串行执行，N 个进程不再互相饿死（实测 6 分镜并发仅 3 成功，串行+1800s 则 6/6）
  - **闸必须是进程级而非实例级**：节点 dispatcher（因而 `Scene3DNodeExecutor`）是**按请求**构建的（`agent_canvas.py:946`），所以按实例建 semaphore 只能串行化单次 run 内的租约，两次并发的"Run all"仍会各自起一个 Blender 互相饿死。改为模块级共享闸 `_shared_scene3d_render_slot()`，首次使用时按 `SCENE3D_MAX_CONCURRENT_RENDERS` 定尺寸，之后所有 executor 复用同一个；`render_slot` 参数保留给测试注入
- **`apps/api/app/services/scene3d/blender_renderer.py`** — `TimeoutExpired` 报错带上超时前已产出的帧数，使"差一点就渲完"与"一开始就卡住"可区分
- **`apps/api/app/core/config.py`** — 新增 `scene3d_render_timeout_seconds`（默认 1800，收敛到 30–3600）与 `scene3d_max_concurrent_renders`（默认 1）
- **并发闸 + 超时复验通过（2026-09-20 13:13–13:36）**：用 `run_scene3d_concurrent.py` 打**真正失败过的派发形态**——一次 run、`scope=selected_nodes` 六个分镜租约同时派出——结果 **6/6 ready**（`asset_aa9b0126…`/`5014d41c…`/`00f1bf77…`/`a95b1e12…`/`cef4832a…`/`cdf10fa7…`），`600s` 超时失败 0 个，六个节点均为新 attempt。渲染全程 `wmic` 实测同一时刻 `blender.exe` 进程数恒为 1，证明并发闸确实生效而非仅"恰好没撞上"
- 复验前发现的真实阻塞不是并发：首轮 3/6 失败的根因是上述 `radius1` 关键字崩溃，即 ISSUE-02 新增几何自身的 bug。两者修复叠加后才拿到 6/6——单看任一修复都会误判

#### 资产静默降级违反 ADR 0005（ISSUE-02）
- **`apps/api/app/services/scene3d/blender_converter.py`** — 补齐 `PropType`(12)/`EnvironmentType`(13) 中此前无几何的类型；`_build_asset` 命中 fallback 时不再无声替换，改为在生成脚本头部追加 `# PREVIS_DEGRADED_ASSET: <id> (<type>)` 注释，并在 `RenderResult` 新增 `degraded_assets` 字段回传
- **`apps/api/tests/test_scene3d_asset_geometry_coverage.py`** — 对 `get_args(PropType)` / `get_args(EnvironmentType)` 全成员参数化断言每个都有 builder（新枚举成员无法再静默缺几何），另断言降级痕迹可从脚本标记与 `degraded_asset_ids()` 双路读出；2026-09-20 追加算子契约类后共 56 个

#### 新增几何用了 Blender 不存在的算子关键字（ISSUE-02 遗留，2026-09-20 复测发现）
- **`apps/api/app/services/scene3d/blender_converter.py`** — `_build_vase` / `_build_cup` 向 `bpy.ops.mesh.primitive_cylinder_add` 传 `radius1=` / `radius2=`。圆柱算子只有单一的 `radius`；`radius1/radius2` 属于 `primitive_cone_add`。这个错不在生成脚本时暴露，而在 Blender **执行**脚本时抛出 `Converting py args to operator properties:: keyword "radius1" unrecognized`，把整次渲染连带节点判负。锥形的 `vase`/`cup` 改走 `primitive_cone_add` 后已在本机 Blender 5.2.1 实测通过（`dimensions` 正常返回）
- **`apps/api/tests/test_scene3d_asset_geometry_coverage.py`** — 新增 `TestBuildersOnlyCallRealBlenderKeywords`：对**每一个** builder 生成的片段解析 `bpy.ops.mesh.primitive_*_add(...)` 的关键字，与从本机 Blender 5.2.1 `get_rna_type().properties` 读出的算子契约表比对。补这条是因为"每个枚举成员都有 builder"这条断言对本次 bug 完全无感——vase 和 cup 都有 builder，只是builder 产出的代码跑不起来
- **根因教训**：几何覆盖率测试只验证"有 builder"，不验证"builder 产出的代码能跑"。26 个新增 builder 里此前只有 3 个分镜被真实执行过，另外 23 个的 API 正确性从未被检验

#### BGM provider 解析与模型目录错配（ISSUE-13）
- **`apps/api/app/services/v2_provider_executor.py`** — `_generate_bgm_audio()` 在默认 provider factory 下**以 `settings.bgm_provider` 为准**构造适配器，不再把 plan 的 `provider_id` 传下去：模型目录里没有任何 music 条目，plan 的 `provider_id` 之所以解析成 `tianpuyue`，只因为 tianpuyue 是唯一另一个 audio（TTS）provider；把它传给 `build_bgm_provider_adapter` 就会与 `BGM_PROVIDER=stepfun_music` 相撞并抛出 provider 不一致。目录里没有 music 条目不应当改写运营者的显式配置；`BGM_PROVIDER` 为空时改为传 `None`，让工厂报"未配置"而不是编造一个不一致
- **`apps/api/app/services/v2_provider_executor.py`** — 同一处：`BGM_MODEL` 已配置时把 `provider_model_id` 从 plan 里剔除。该 id 冻结自 `audio` 能力默认值 `tianpuyue:TemPolor-i3`，是**TTS** 模型而非配乐模型（目录里没有 music 条目的直接产物）；`stepfun_music.py:145` 的 `frozen_provider_model_id or select_stepfun_music_model(...)` 会让它压过运营者的 `BGM_MODEL`，StepFun 于是返回 HTTP 404 `The model "TemPolor-i3" does not exist or you do not have access to it`——听起来像权限问题，实为配置错位。`BGM_MODEL` 为空时保留 plan 的 id，适配器自身的默认值仍然生效
- **`apps/api/tests/test_canvas_provider_error_classification.py`** — 新增 `TestBgmUsesConfiguredMusicModel`（2 个）：断言 TTS 默认 id 不会泄漏进配乐请求、`BGM_MODEL` 为空时 plan 的 id 仍保留
- **实测（2026-09-20 13:00 前后）**：`agent_canvas_provider_tasks.task_52d4c07e5e5252c4035adcfc` 的 `provider=stepfun_music`、`provider_model=stepaudio-3-music-preview`，remote task `01a0bd02-…` 在 124 秒内 `succeeded`，产出 3,107,634 字节 / 194 秒的 mp3（`asset_8a254438b05c2809865ff8ef`）
- **仍未解决（可见性缺陷，已定位到行）**：该 asset 行仍写着 `provider=tianpuyue` / `model_id=TemPolor-i3`，而真正干活的是 `stepfun_music` / `stepaudio-3-music-preview`。机制已查明：`agent_canvas_node_execution.py:160-161` 的 `generated_asset_publication_metadata()` 把 `provider`/`model_id` 硬写成**冻结的目录解析**（`context.provider_id` / `context.model_id`），随后 `agent_canvas_publication_metadata.py:298` 的 `values.update(_select(..., frozen))` 在 `_provider_facts(provider_metadata)` **之后**执行，于是冻结值覆盖了结果 descriptor 里 provider 自报的真实值。这是刻意设计——该函数 docstring 写明"Project declared facts only; provider metadata cannot assign source authority"（产出物溯源要反映"提交时被授权解析到的模型"，而不是 provider 自称用了什么）。image/video/text 一直没暴露它，是因为它们的目录解析恰好就是真实 provider；BGM 是唯一一个 provider 完全不来自模型目录（而来自 `BGM_PROVIDER`）的模态，两者的分裂才显形。真实身份并未丢失，只是不在 `asset_versions.provider/model_id` 这两个列里：`agent_canvas_provider_tasks.result_descriptor.provider_asset` 与 `provider_model` 一直记着 `stepfun_music` / `stepaudio-3-music-preview`
- 未改动默认值解析的理由：`provider_model_bootstrap.py:113-135` 的 `_recognized_defaults()` 是**按 key 硬编码**的，给目录加一条 `stepfun_music` music 条目不会改变已存在的 `audio` 默认值；但它会进入 `audio` 能力的 automatic 解析排序（现有条目 `automatic_tier_priority` 为 1/2）。要根治标签问题需改的是上面那两行的溯源语义，影响所有模态，属独立变更，本次不做
- **`apps/api/app/tools/bgm_provider_factory.py`** — 不支持的 provider 显式列出三个合法值；`bgm_provider_configuration_error()` 增加 music 能力预检（`stepfun_music` 走 `validate_stepfun_music_settings`），把真正的缺配置原因提前暴露，而不是让用户看到一个 provider 不匹配的假象
- **`apps/api/tests/test_bgm_provider_selection.py`**（7 个）

#### 409 / 422 错误体 `details` 为空（ISSUE-08 / ISSUE-11）
- **`apps/api/app/services/agent_canvas_runtime.py`** — 新增 `_skip_error_details()`，按 reason 给出可行动指引：`failed_node_retry_required`→`{"missing_field": "retry_failed", "expected_value": true, "node_ids": [...]}`，`node_already_ready`/`node_already_working`→指出应传"既非 ready 也非 working"的节点，`node_prompt_empty`→`missing_field: generation_prompt` 等
- **`apps/api/app/services/agent_canvas_ad_media.py`** — 把 Pydantic 的 `ValidationError` 摊平成 `validation_paths`（`loc` 元组转点号路径，限长 32 防响应膨胀），并附上准确的 `content_schema_ref`（此前非 `scene`/`storyboard_sequence` 角色统一落到 `invalid_role_content`，用户看不出该填哪个模型）；`semantic_role_node_type_mismatch` 补 `expected_node_type`/`received_node_type`
- **`apps/api/tests/test_agent_canvas_error_details.py`**（9 个）— 断言 `_persistence_http_error` 透传出来的 `details` 非空且含指引字段

#### 轮询者无法关联到当次 run（ISSUE-10）
- **`apps/api/app/persistence/agent_canvas_runtime_repository.py`** — 新增 `get_latest_execution()`：`get_active_execution()` 只看非终态行，两次运行之间读取的轮询者看到空快照，无法区分"从未跑过"与"跑完了"
- **`apps/api/app/services/agent_canvas_runtime.py`** — `node_runtime[].execution_id` 在 member 缺失时回退到节点最近一次 attempt 的 `execution_id`；无 active execution 时回填最近一次 execution 的 id 与终态

#### 测试基建：并发调度测试的时间窗过窄
- **`apps/api/tests/test_v2_parallel_scheduler.py`** — `test_v2_global_run_reports_four_image_slots_running_concurrently` 的派发等待从 `timeout=2` 放宽到 15。实测四个 image slot 在 0.00s / 0.34s / 0.68s / 0.97s 全部派出（并发能力正常），但"规划第四个 slot"本身就要约 1 秒，在 pytest 开销下越过 2 秒，使这个测试**在一个功能正常的调度器上恒定失败**（3/3 + 全量套件各复现一次，`git stash` 掉本次改动后同样失败，故与本次修复无关）。
- 并发断言本身没有被削弱：`release` 直到四个 provider 同时阻塞才置位，且 `running_slot_ids` / `running_node_ids` 断言仍证明四者确实在同时运行，随后还要等四个 slot 各自产出 `selected_asset_id`

#### E2E 复测探针自身的三个陷阱（2026-09-20 复测发现）
- **`e2e_output/rose/verify_models.py`** — `run_node()` 在轮询时把第一次读到的终态当成本次 run 的结果。但一个上一次已 `failed` 的节点，在本次 attempt 被受理前 `node_runtime` 里就一直是 `failed`，于是探针把**上一轮的失败**报成本轮失败：13:0x 的 BGM 复测因此被判 `bgm_provider_model_unsupported`，而那次 StepFun 404 是 11:57 的、修复早已让它通过。改为先记录 `(visible_status, attempt_no, execution_id, updated_at)` 基线，只有观察到变化才认定 attempt 已受理，再等它进入终态；未受理时明确告警而不是静默上报一个旧状态
- **`e2e_output/rose/verify_models.py`** — 产物目录写错：`save()` 取自 `driver_nodes`，读的是那个模块 import 时绑定的 `OUT`（`.../stages`），本脚本里重新绑定的 `OUT`（`.../models`）对它毫无作用，导致所有 `node_*.json` / `runtime_*.json` 落进 `stages/` 并互相覆盖。改为显式 `driver_nodes.OUT = OUT`。顺带修：运行前对 failed 节点必须带 `retry_failed: True`，否则测到的是 409 重试守卫而非 provider 调用
- **`e2e_output/rose/run_scene3d_concurrent.py`**（新增）— 用真正失败的派发形态（**一次 run、六个租约同时派出**）复验 ISSUE-09：断言 6/6 ready、断言不出现 `timed out after 600s`、断言每个节点都是新 attempt。先前的"串行 6/6"只证明了超时改动，没有证明并发闸
- **`e2e_output/rose/recheck_image_node.py`**（新增）— 只重跑分镜图节点，区分"provider 仍然过载"与"代码仍把它一次性判负"：节点必须回到 `ready`，或再次报 `provider_temporary_unavailable`，而不是旧的 `provider_generation_failed`。写它时踩到 `driver_nodes.call()` 只接受**路径**不接受完整 URL（传 `f"{BASE}/..."` 会让 URL 变成 `http://127.0.0.1:8000http://...`，报错是 `getaddrinfo failed` 而不是明显的 404），已改为传路径
- **`e2e_output/rose/probe_image_engines.py`**（新增）— 见下方"图像能力的真实可用面"
- **探针现在额外报告产出物的 `provider`/`model`（取自 asset 行）而非仅 asset_id**——"哪个模型真的跑成了"只有 asset 行答得出来，节点自身的 `model_ref` 是目录解析的结果（对 BGM 而言是个 TTS 模型）

#### 图像能力的真实可用面（2026-09-20 14:30 探明）
- **`e2e_output/rose/probe_image_engines.py`**（新增）— 用 app 自己的 `serialize_volcengine_image_generation_request()` 逐个问 `/api/v1/models` 里 capability=image 的 5 个真实模型，只打印结局（HTTP 状态 + provider 的 `error.type`），不复述凭据。结论：本部署的图像能力**只剩 1 个可用模型**
  - `step-image-edit-2`（= `IMAGE_GENERATION_MODEL`，画布分镜图节点钉的就是它）→ HTTP 503 `engine_overloaded`，**provider 侧仍在过载**（13:42、14:32 两次独立实测都是同一条）
  - `doubao-seedream-4-0-250828` / `-4-5-251128` / `-5-0-lite-260128` / `-5-0-pro-260628` → HTTP 404 `model_invalid`（"The model ... does not exist or you do not have access to it"）
- **为什么这 4 个不可用**：`IMAGE_GENERATION_ENDPOINT`（`.env:38`）指向 **`https://api.stepfun.com/step_plan/v1/images/generations`**，即 StepFun 的 step_plan 网关，而不是 Volcengine Ark 原生端点。该网关只转发生图模型里的 `step-image-edit-2`，4 个 `doubao-seedream-*` 是 Ark 原生模型，走这个网关一律 404。`provider_credentials.py:1477` 也印证了这一点：可信来源白名单只列了 `https://ark.cn-beijing.volces.com`，而配置里用的并不是它
- **这解释了 13:42 的图像失败不是本代码库的缺陷**：节点 `status=failed`、`retryable=false`、`user_action="safe to retry as-is"` 三件事同时为真而不矛盾——分类与退避都对，只是 provider 在 14:32 仍然繁忙
- **顺带发现的一致性隐患（本次不改）**：`provider_model_bootstrap.py:113-135` 的 `_recognized_defaults()` 把 `image` 的识别默认值硬编码为 `volcengine_ark:doubao-seedream-5-0-lite-260128`，而这个模型在本部署不可达（404）。因为它只在 `key not in existing` 时播种、库里已冻结 `volcengine_ark:step-image-edit-2`，所以当前无影响；但一旦重置模型默认值，图像能力会落到一个必然 404 的模型上
- **消除方向（需运营决策，非代码修复）**：要么等 StepFun/Volcengine 恢复，要么把 `IMAGE_GENERATION_ENDPOINT` 换成服务 doubao-seedream 的网关（Ark 原生端点）——这会让当前唯一可用的 `step-image-edit-2` 反过来不可用，属部署侧权衡

### Known Limitations
- Blender 5.2 已知问题：加载.blend后 FFMPEG 枚举不可用，改用PNG序列+ffmpeg转H.264 MP4
- 异步渲染任务队列为内存存储，进程重启后任务丢失（后续可扩展到Redis/DB）
- 口型同步为音节级估算，非音素级（低保真预演阶段已足够）
- 时间线与EditingTimeline的双向同步暂未实现（两者管理不同内容，价值有限）
- 片尾字幕渲染需要 `FINAL_COMPOSITION_SUBTITLE_FONT_PATH` 指向一个存在的字体文件（部署配置，非代码缺陷）：为空时媒体工具链报告 `subtitle_font_unavailable`，`subtitles`/`subtitle_burn_in` 关闭，其他能力不受影响
