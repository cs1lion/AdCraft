# Agent 自主设计测试项目 playbook：复杂场景的画面/声音质量与流程补足

> 2026-10-04《静海攻防》成片 v1→v6 全流程返工的复盘沉淀。用户三问：① 不先做人物三视图和场景图对不对、该不该补；② agent 模拟真实用户自主设计测试项目还应补什么；③ 连同复杂场景设计准则一并成文。本文回答三问并给出落地清单。
>
> 关联：`docs/adr/0017-previs-clip-node.md`（预演片段节点）、`docs/adr/0005-3d-low-fidelity-previs.md`（预演与关键帧降级）、`docs/agents/engineering-standards.md`（自检梯子）。

## 1. 复盘：v1→v6 到底出了什么问题

成片链路：Script → scene-3d 预演（animatic）→ 预演片段节点 → 分镜 video 节点（flash）→ voice-cast → 时间线 → editing 导出。六版返工里肉眼可见的问题和它们的根因分层：

| # | 现象 | 直接原因 | 根因层 |
|---|------|---------|--------|
| 1 | 首镜是 Blender 白模 | flash 把预演关键帧直接光栅化 | **异质桥接**：关键帧同时锚定构图和质感 |
| 2 | S2/S3/S4 仍有 3D 渲染感，与 s1 割裂 | 同款锚定、提示词没压风格 | 同上 + 风格指令未模板化 |
| 3 | 部分预演"不动"，像静止空场景 | 角色 keyframe 位移≈0、机位移量≈1 单位 | **作者态密度**：工具不补动作 |
| 4 | 语音是"提示词+脚本朗读感" | voice-cast 节点无 audio_bed，回退读 `generation_prompt` | **静默降级** + 词源分散 |
| 5 | 字幕没烧上 | 字体路径未配 + Windows ass 转义缺陷 | 环境配置 + 平台缺陷（已修） |
| 6 | script 六场戏只出四镜、台词被改写 | 剧本/镜头表/分镜词/配音床四层词源各写各的 | **无单一事实源** |
| 7 | 配音床 31.5s > 视频 25.5s，尾句被切 | 床时长与剪辑时长无联动 | 无时长派生 |
| 8 | 重渲时节点被 5 秒模板场景覆盖 | 无效 scene_script 静默回退生成器 | **静默降级**（最危险的一类） |

四个结构性问题（详见 v6 CHANGELOG）：

1. **叙事事实源分散**：Script 节点 / scene_script / storyboard_content / audio_bed / 字幕轨五层词源无派生关系，改一处不传播。
2. **预演与生成是异质媒体**：flash `video:0`，预演视频进不去，只靠 5 张静态关键帧桥接；关键帧强锚定"构图+质感"，风格只能写进提示词正文。
3. **各环节默认值按效率调，不按观看调**：`scene3d_render_keyframes_only=true`（25 帧≈20 秒）、`video_limit=1`、NodeLeaseService TTL 60s、flash 4-12s/720p/串行 429——每个默认阈值都与"复杂场景"冲突。
4. **失败走静默降级而非显式报错**：读提示词当配音、模板覆盖 scene_script、structured_content 整列丢失、字体缺失只标记不拦。单独都可查询，叠起来就是用户看到的质量崩塌。

## 2. 结论一：人物三视图和场景图该先做——而且不是风格偏好，是项目自身策略

**该补，必须补在预演之前。** 依据是代码里已存在的能力与约束，不是外加流程：

- **能力已在**：`CharacterTurnaroundRoleBriefV2`（front/side/back 三视图，`character_turnaround_identity_conflict` 身份冲突检测）、`SceneBoardRoleBriefV2`（3x3 环境板：`environment_identity/spatial_logic/lighting/materials/atmosphere` + 9 视角 + `environment_only`）。
- **策略已强制**：`agent_canvas_role_reference_policy.py` 的 `storyboard_video` 策略里 `scene_board` 是 **required=True** 的参考源（canonical_order=4），`character_turnaround` 在角色激活时 required。本轮是靠"预演片段 → flash 关键帧替换白名单"绕过了身份层——所以角色一致性只剩低多边形剪影级保真，换镜就漂。
- **预演侧已接线**：scene-3d 执行器的 `_scene3d_reference_bindings` 会记录节点绑定的场景板/角色三视图，"这个 SceneScript 是照着哪套设计搭的"可查询。

**补齐顺序（写进标准流程）**：

```
creative_brief / world_setting
  → character_main → character_turnaround（三视图，身份锚点）
  → scene_board（3x3 环境板，空间/光照/材质锚点）
  → script（六场戏）
  → scene-3d previs（镜头表，参考上面两套身份资产）
  → 预演片段 → storyboard_video（携带 turnaround + scene_board + 预演关键帧）
  → voice-cast（逐行）→ timeline → editing
```

身份层先行解决三件事：视频模型的身份参考（不是只有剪影）、`wardrobe_drift` 跨节点服装漂移检查有比对基准、`scene3d_consistency` 的 `character_unbound` 告警消零。

## 3. 结论二：复杂场景（更多动作、更丰富情节）设计准则

1. **剧本是唯一源，镜头表从剧本算**：`screenplay_items[].estimated_sec` 累加 × 帧率 = 每镜帧区间；scene_script 的角色走位/机位由该镜 `action`/`camera_atmosphere` 派生；`storyboard_content` 用原字段、`dialogue` 直接挂原句。超 flash 12s 上限的镜头做显式"节奏压缩"（合并），不随机丢场。
2. **三张一致性报告当闸门**：`scene3d_consistency` / `blocking_continuity` / `scene3d_transition_intent` 从"发布不拦"改为发布预演片段的前置条件——角色无位移 keyframe 的镜头、切点无空间锚衔接的镜头不发。
3. **表演按 keyframe 密度排**：每镜每角至少一次位移、一次朝向变化、一次动作切换；台词走 `speech_bindings` 绑角色（`auto_lip_sync` 已通）；分拍事件（墙破→涌入→开火）用 trigger events，别把整场塞一个镜头。
4. **切点连续性三原则**：空间锚衔接（上一镜收在何处、下一镜就在该处或其视线前方开场）、先埋伏后 payoff（角色先在背景出现再给近景）、声桥优先于硬切（警报/引擎声跨切点延续）。
5. **语音逐行落位，不用单床**：audio_bed 不回吐逐句时间戳（instruction 里写"第 N 句 X 秒开口"模型不听），复杂情节必须 per-line 合成 + 时间线逐句 clip（`start_time` 自定）+ 角色音色固定映射。需补：per-line 合成的角色音色参数字段（当前 `_synthesize_lines` 传空 `character_id`）。
6. **风格指令模板化**："严禁素模/白模/低多边形/3D 渲染感 + 实拍电影质感"作为 storyboard_content 强制后缀，每镜都带（v4/v6 实测有效）。
7. **时长派生**：镜头表带"预计成片秒数"列；配音床/字幕长度从剧本 `estimated_sec` 派生，不从生成结果反推。
8. **成本模型进排期**：N 镜 × flash 串行（每镜 1-3 分钟 + 429 间隔 30s）；全帧 animatic 按 900 帧≈11 分钟估；渲染/生成失败只重那一镜，不整批重来。

## 4. 结论三：agent 模拟真实用户自主设计测试项目——流程补足点

真实用户不会"一口气跑到成片再看"。对照本轮差距：

| 真用户行为 | 本轮 agent 的差距 | 补足 |
|---|---|---|
| 先定风格参考（`active_style_skill`） | 未锁定风格就跑生成 | 建项目后先选/锁风格技能，写进 brief |
| 先出角色三视图 + 场景图 | 直接手搓 scene_script | 按 §2 顺序，身份资产先生成再预演 |
| 先做一镜样片验证风格 | 四镜一起生成，v3 才发现风格割裂 | **pilot shot 纪律**：首镜生成→抽帧验收→风格指令定稿→再铺量 |
| 每阶段人眼验收 | 无中间验收点，一次到成片 | 每个产物（brief/三视图/场景板/animatic/每镜成片入时间线）设验收点 |
| 台词/字幕由剧本驱动 | 手写音频床 + 手排字幕 | 从 `screenplay_items[].dialogue` 派生，禁止手抄 |
| 预算意识（90s 剧本→实际多少） | 无决策记录，拍成 25s 没说明 | 镜头表带时长/成本列，压缩决策显式记录 |
| 看成片反馈，只重做问题镜头 | 整批重生成 | 失败/不满意只重该镜（previs clip 原子化正好支持） |
| 验收靠"看" | agent 也靠"看"且看不到 | **验收脚本化**（见下） |

**验收脚本化（替代人眼的最小集）**，导出后自动跑、不达标不出片：

- 切点检测（`ffmpeg select=gt(scene,...)`）对比镜头表设计切点；
- 字幕 cue 数 vs 剧本台词数；cue 时间窗 vs 该镜起止；
- 每个 cue 窗口音轨 RMS（确认有语音、不是静音/环境音）；
- 字幕烧录检测（cue 窗口底部亮像素计数 vs 无 cue 基线）；
- 音画时长差（配音床 vs 时间线总长）≥1s 告警；
- 视频轨总时长 vs 剧本 `target_duration_sec` 偏差报告。

**流程纪律**：复杂项目按 ①身份层 → ②pilot 镜 → ③批量 → ④逐镜验收 → ⑤成片六步走，每步产物落节点并可在前端回看；agent 自主测试时应扮演"会中途喊停的真实用户"——样片不过就不进批量，而不是把问题带到成片。

## 5. 落地清单（按优先级）

| 优先级 | 事项 | 类型 |
|---|---|---|
| P0 | 标准流程加入身份层（三视图/场景板前置） | 流程 |
| P0 | 有效 scene_script 预校验（含相机关键帧∈镜头区间）纳入所有写入路径 | 代码 |
| P0 | pilot shot 纪律 + 验收脚本六项（切点/字幕数/RMS/烧录/时长差/剧本偏差） | 流程+脚本 |
| P1 | per-line voice-cast 补角色音色参数 + 时间线逐句落位 | 代码（小） |
| P1 | 一致性三报告升级为预演片段发布闸门 | 代码（中） |
| P1 | 从 Script 派生镜头表（帧区间/台词/时长自动算） | 代码（中） |
| P2 | 风格指令模板化进 storyboard_content 生成路径 | 代码（小） |
| P2 | 预算/时长列 + 失败单镜重渲入口 | 产品 |
