# 用 three.js 替换 Blender 渲染层 — 替换方案（待确认）

> 状态: **待用户确认**，未开始实施。
> 触发: 用户确认"只要形到位，精细度不做要求"，且最小验证通过。
>
> **2026-10-08 更新（架构结论修订）**：阶段 1–5 已完成（见 §6），相机接线经复核后重做。
> 渲染层把预演从**不成立**推到**成立**；离"可用"剩下的差距全在资产与动画，已单独成文：
> `docs/plans/previs-asset-and-motion-gap.md`（含与另一份 prop-keyframes 计划的差异评估）。
>
> **不再以"取代 Blender"为目标**，改为"分工 + 互相仲裁"，见 §8。原 §6 第 6 项
> （退役 Blender）随之从"待办"改为"已决策：不做"——它此前看起来像在排队，实际结论是
> 保留。§8 写清了理由与三条角色的边界，避免下一位读者把它重新当成待办捡起来。

## 1. 最小验证结论（本方案的地基）

用仓库既有 Playwright + 真 Chrome WebGL 通道，把 `test-materials/jinghai_scenescript.json`
（4 镜 / 4 相机 / 3 角色 / 720 帧 / 24s）灌进 `SceneScript3DPreview`，逐帧 seek + 捕获 12 帧。

| 指标 | 实测 | 说明 |
|---|---|---|
| 帧间差异 | 12/12 全部不同 | 逐帧驱动生效 |
| 色阶 / 颜色数 | 250 / 1121–1239 | 真实内容，非空白 |
| 镜头切换 | f_0240 diff 扩至全宽 1264px | 第 240 帧 = 第二镜起点，切换被捕获 |
| 捕获耗时 | 均值 104ms/帧**含 Playwright 往返** | 页内捕获应更快 |
| 720 帧推算 | **75 秒** | Blender 实测 ~600 秒 |
| 服务端 CPU | **0** | Blender 占满一个 worker |

**踩到的坑（已修，记录在案）**：第一版用 `canvas.toBlob()` 在渲染回调外读取，12 帧全是
**纯黑**（mean=0，1 色阶）。原因：未开 `preserveDrawingBuffer` 时绘制缓冲在合成后即清空。
改用 Playwright 元素截图（读合成后的画面）后正常。**这一条决定了 §4.1 的选型。**

### 验证未覆盖的（方案内列为风险）

- 角色 rig：预览仍是 box + sphere，**不是** Blender 的四肢剪影
- 无人值守执行（curl 触发 node，无浏览器）
- depth control pass
- ffmpeg 编码与音频床 mux
- WebGL 跨 GPU 的确定性

---

## 2. 判定：值得做

收益直接量化：**单镜 ~10 分钟服务端 CPU → 0，且快 8 倍**。加上：

- **单一实现**：现在 `blender_converter.py`（894 行 Blender Python 生成器）与 three.js 视口
  是两套词汇表实现，必须人工保持一致。收敛后 `SCENE_SCRIPT_GEOMETRY` 成为唯一几何源。
- **一致性问题当场消失**：作者现在拖的是 box，渲出来是有腿的——替换后所见即所得。
- **依赖消失**：`BLENDER_EXECUTABLE`、CI 装 Blender 5.2.1、版本兼容（Blender 5.x 已删
  compositor pass socket）全部不再相关。
- **预览变好**：角色补四肢 rig 是必须做的（见 §3.6），这一步本身提升编辑体验。

---

## 3. 需替换的现有逻辑

### 3.1 `app/services/scene3d/blender_renderer.py`（整文件退场）

| 成员 | 现状 | 处置 |
|---|---|---|
| `get_blender_capability()` | 探测 `blender --version` | 退役 |
| `render_scene_script()` | 生成脚本 + `subprocess.run` + 读 PNG 序列 | 替换为「帧源适配器」 |
| `_render_timeout_for()` | 2.0 秒/帧斜率（本人实测标定） | 退役；改为客户端心跳 + 服务端超时 |
| `RenderResult.blender_version` | 上报到节点 | 字段退役 |

### 3.2 `app/services/scene3d/blender_converter.py`（894 行，整文件退场）

包含：25 种 `_build_*` 资产函数、`_control_pass_lines()`、相机/角色/道具关键帧插入、
两盏 AREA light、`_ASSET_COLORS` / `_PART_COLOR_OVERRIDES` / `_DEGRADED_ASSET_COLOR`。

**注意 `_ASSET_COLORS` 与 `_PART_COLOR_OVERRIDES` 不是可丢弃的装饰**——CHANGELOG 记载
实测全类型一帧 518400 像素 0 个彩色像素（整个预演一片默认灰），配色是后来补的。前端
`SCENE_SCRIPT_GEOMETRY` 需要等价映射，且**降级资产色（#FF2BD1）这个"响亮失败"信号必须
保留**——它是"资产未绑定"的可视告警，静默降级违反工程标准 §4。

### 3.3 `app/services/scene3d/encoder.py`（保留，输入源改变）

PNG 序列 → H.264 MP4 的 ffmpeg 逻辑不变。变的是帧从哪来：服务端本地目录 → 客户端回传的
帧流（或 headless 服务的输出）。

### 3.4 `app/services/agent_canvas_node_execution.py`（渲染编排重写）

| 成员 | 现状 | 处置 |
|---|---|---|
| `self._renderer`（注入 `render_scene_script`） | Blender 渲染 | 换成帧源适配器 |
| `rendered_frames` = `"animation"` \| `"keyframes"` | 已接线的语义 | **保留**（这是"预演真的动起来"的开关） |
| `scene3d_keyframe_frames` | 两趟都发布 | **保留** |
| `scene3d_max_concurrent_renders = 1` | 串行闸门 | 语义改变：客户端并发不再是 CPU 竞争 |
| `_render_timeout_seconds` 平顶 | 30 秒底 | 随执行模型重定 |

### 3.5 `app/services/scene3d/control_passes.py` + `previs_clip_publisher.py`

- `control_passes.collect_control_passes()`：Blender 5.x 下 normal/flow **已降级为
  unavailable**，只剩 depth 且每镜 5 关键帧采样。three.js 侧用 `DepthTexture` 可复现同等
  （甚至更好）质量。合同不变，实现替换。
- `previs_clip_publisher.py`：从 MP4 + 关键帧路径裁片段，**不依赖渲染器实现，保留**。
  这是已上线且有端到端验证的链路（片段按 shot 起点落时间线），不应触碰。

### 3.6 前端 `SceneScript3DPreview.tsx` 角色渲染（必须改）

现在：一个 box（躯干）+ 一个球（头）+ 嘴。Blender：torso + neck + head + LegL/LegR +
ArmL/ArmR。

**这是唯一"必须做"的前端改动**，理由不是对齐 Blender，而是：替换后预览即成片，一个 box
角色不足以支撑"形到位"。移植量约 30 行 primitives（`blender_converter.py:65-111` 的
`_build_lowpoly_human` 几何是分段比例，可直接照搬）。

同时保留 three.js 已有而 Blender 没有的两个表演：**gesture 头部前倾 15°** 与 **talk 嘴部
逐帧张开**（后者由 `characterActionAtFrame` 驱动，语义已与后端唇形合并刻意对齐——CHANGELOG
记载"前端与渲染器必须同意，否则嘴提前闭上"）。

### 3.7 关于"人物行动"的诚实结论

**Blender 侧也没有肢体动画。** `blender_converter.py` 全文搜 `walk|swing|cycle` 零命中，
`action` 仅 2 处且都是 `select_all(action=...)`。关键帧只插入 `location` 与
`rotation_euler.z`（710-711 行）。四肢建形时写死，之后无一行旋转。

所以：**替换不会损失任何人物动作能力**，因为两侧都只有"整体位移 + 朝向"。真正的差距是
剪影（Blender 看得见四肢，three.js 是个 box），§3.6 正好补上。

### 3.8 随之一同退役

- `app/services/scene3d/blender_mcp_client.py` + `BLENDER_MCP_TOOL_WHITELIST` 及其
  `/scene-3d/operations` 的 `use_mcp` 分支——**MCP 的存在意义就是驱动 Blender 建模**。
  Blender 退役后它失去目标。当前它在本机也跑不起来（`blender-mcp` 不在 PATH、`.env` 未配、
  无 UI 入口），退役成本接近零。
- `.env` 的 `BLENDER_EXECUTABLE`

---

## 4. 需接通的其他模块

### 4.1 【核心决策，需你拍板】渲染在哪执行

| 方案 | 无人值守 | 服务端 CPU | 实现量 | 风险 |
|---|---|---|---|---|
| **A. 客户端捕获 + 帧回传** | ❌ **不能** | **0** | 中 | 开页面才跑；回传带宽 |
| **B. 服务端 headless Chrome + three.js** | ✅ | 中（可能比 Blender 慢） | 中 | 浏览器依赖 + 软件 GL 速度未测 |
| **C. A+B 并存，A 为默认** | 部分 | 低 | 大 | 两条路径的一致性 |

我的建议是 **C，但分阶段**：先做 A 打通链路（工作量小、收益立竿见影、能立刻看到差异），
把 B 作为"无人值守兜底"第二步再做。**A 阶段结束时就应能判断 B 是否还需要。**

需要你确认的是：**无人值守跑片（agent 自主生产，playbook 的核心场景）是硬需求吗？**
如果是，A 从一开始就不能是唯一路径。

### 4.2 捕获通道（新增模块）

- 页内逐帧捕获：`requestAnimationFrame` 内 `renderer.render()` → 读像素
  （**不能用 §1 踩坑的 `toBlob`**，须在绘制后立即读，或显式 `preserveDrawingBuffer`）
- 帧回传：分片 + 序号 + 校验；断线重连续传
- 服务端落盘：沿用现有 frames 目录布局，编码器无需改

### 4.3 执行模型 / 编排层

scene-3d node 当前由 `POST /workflows/{id}/runs` 触发（本人以 curl 验证过，无浏览器参与）。
方案 A 需要给节点加"等待浏览器会话"语义：

- 节点状态机新增等待态（已有 `working`/`ready`/`draft`/`failed`）
- 心跳与超时（作者关页面 → 明确失败，**不是静默挂起**）
- 与 `render_slot` / `DynamicCanvasScheduler` 的租约模型整合

### 4.4 确定性 / 回放纪律

本仓库对确定性的要求是宗教级的（prompt digest、冻结基线、
`isolated_agent_model_replay_enabled`）。WebGL 输出**随 GPU/驱动/抗锯齿变化**。

处置建议：
- 固定捕获参数（像素比、抗锯齿、视口尺寸）写进 SceneScript 派生设置
- **断言对象改为"结构确定性"而非"像素确定性"**：脚本生成、关键帧索引、片段时长、时间线
  落位这些本就可确定性测试（现有 2733 个后端测试大部分不受影响）
- 回放（replay）语义明确改为"回放脚本与编排"，不回放像素

### 4.5 depth control pass

three.js 用 `DepthTexture` / `gl.readPixels` 读深度缓冲，输出到同一 `control_depth/`
目录布局，`collect_control_passes()` 合同不变。

### 4.6 音频床 mux

`mux_audio_to_video` 留在服务端，消费编码后的 MP4，**不受影响**。

### 4.7 资产词汇表与配色

- `SCENE_SCRIPT_GEOMETRY` 已是**对 schema 枚举的全映射**（TypeScript 强制：新增 kind 不编译），
  道具/环境无需补。**只需补角色**（§3.6）。
- 需移植：`_ASSET_COLORS`、`_PART_COLOR_OVERRIDES`、`_DEGRADED_ASSET_COLOR`（#FF2BD1）

### 4.8 测试资产（重写而非删除）

| 现有 | 处置 |
|---|---|
| `test_scene3d_blender_mcp.py` | 随 §3.8 退役 |
| `test_scene3d_renderer_integration.py` | 重写为帧源适配器契约 |
| `test_scene3d_encoder_frame_timing.py` | 保留（编码器未变） |
| `test_scene3d_motion_plumbing.py`（本人新增） | 改造：从断言 Blender 脚本改为断言帧管线 |
| `test_previs_anchor_style_guardrail.py`（本人新增） | **保留**——与渲染器无关 |
| `test_agent_canvas_previs_timeline_handoff.py` 等 | **保留**——链路语义不变 |
| `tests/browser/threejs-capture.spec.ts`（本人新增） | 固化为捕获契约（含 §1 的反假通过断言） |

---

## 5. 与替换无关但挡着"形到位"的既有缺口

这些换渲染器一分都不解决，但如果目标是"自然语言构建白模 + 行动参考"，它们才是真瓶颈：

1. **`SceneProp` / `SceneEnvironmentObject` 没有 `keyframes`**（schema `extra="forbid"`）。
   →「门扇开启」做不了。角色和相机有，道具环境没有。
2. **`SceneCharacter.action` 五个词（stand/talk/walk/sit/gesture）没有任何一处被翻译成
   肢体姿态**，前后端都没有。→ `walk` 的实际效果是身体滑动。

建议：即使做替换，这两项也应单独排期。第 1 项是 schema 加法，收益面最大（three.js 视口、
渲染、时间线全部自动受益）。

---

## 6. 实施分期（截至本回合的实际进度）

| 阶段 | 内容 | 状态 |
|---|---|---|
| **0** | 最小验证（§1） | 完成 |
| **1** | 角色 rig（§3.6） | 完成 |
| **2** | 服务端渲染通道（捕获 + 编码） | 完成 |
| **3** | 编排接线（`SCENE3D_RENDERER_BACKEND=threejs`） | 完成 |
| **4** | depth control pass（§4.5） | 完成 |
| **5** | 视口相机跟随分镜相机 | 完成（depth subagent 暴露的缺口） |
| **6** | ~~退役 Blender~~ | **已决策：不做**（见 §8） |

### 本回合实测数字

| 项 | 结果 |
|---|---|
| 720 帧渲染（服务端 headless Chrome） | **77.2 秒**（Blender 同场景约 530 秒，约 6.9 倍） |
| 深度通道 | 20 张 `depth_<N>.png`（每镜 5 个），喂给真实 `collect_control_passes` -> `completeness: partial`，帧号与它重新推导的一致 |
| 编码（仓库 `encode_png_sequence`，未改） | `success=True, frame_count=720`；产物 h264 / 1264x540 / 721 帧 / 24.03s |
| 相机跟随 | 镜内差异 bbox 局部、切镜扩到全宽；10 对连续帧 0 对相同 |
| 回归 | canvas+timeline 1348 测试全过；后端全量 2742 passed（3 个并行调度 flaky 单独复跑 18/18） |

每阶段结束后跑一次真机主线，不叠加到最后一口气验证——本会话的教训是：连续多轮
"测试全绿"之后，一次端到端就抓出致命 bug（预演片段发布 500）。

### 仍未做 / 需要决策

1. **无人值守执行模型**（§4.3）：渲染由一个 headless Chrome 会话完成，API 进程持有它。
   批跑多镜头时是串行占用；尚未做节点状态机的"等待会话"语义与心跳。
2. **默认切换**：开关默认仍是 `SCENE3D_RENDERER_BACKEND=blender`。**已决策：不切**（见 §8）——
   three.js 是可选快路径，不是继任者；把它设为默认会让参照实现不再被运行，从而失去对照组。
3. **退役清单**：`blender_renderer.py`、`blender_converter.py`、
   `BLENDER_EXECUTABLE` **已决策：保留**（见 §8）。其中 `blender_mcp_client.py` +
   `BLENDER_MCP_TOOL_WHITELIST` + `use_mcp` 分支是例外：它驱动的是 Blender **建模**而非渲染，
   本机跑不起来、无 UI 入口，与"渲染层选谁"无关，属于可清理的死代码（未清理，待单独一刀）。
4. **§5 的两个 schema 缺口**（道具/环境无 keyframes、action 无姿态实现）——
   与渲染器无关，独立排期。
5. **相机 FOV**：schema 无镜头字段，当前用预览的 50 度；Blender 由 `lens` 推导。

---

## 7. 本回合被真机抓出、而单测全部放过的四个 bug

记录在此是因为它们形状相同，且每一个都足以让整条链"看起来是好的"：

1. **`Number("")` 是 0 且 `Number.isFinite(0)` 为真** -> 缺省 `--end` 被算成"第 0 帧"而非
   "未传"，调用方要整段只得一帧。
2. **父目录数错**（先 `apps/api/web`，后 `apps/apps/web`）-> capability 报
   unsupported，resolver 静默回落 Blender，一次"成功"的渲染其实是 Blender 干的。
   测试抓不住它，因为那个用例在 capability 非 ready 时直接 return——已改成无条件
   断言驱动路径。
3. **块内 const 的报告变量**（`wanted` / `depthRendered`）-> 全部帧写成功后崩在
   stdout，一次完美的渲染被报成失败。
4. **硬编码 orbit 相机** -> 720 帧全从一个视点拍，分镜与运镜完全没进产物。

第 2 条尤其值得记住：**一个"跳过断言"比"断言错误"更危险**，因为它同时移除了
失败信号和修复压力。

---

## 7. 需要你确认的四个问题

1. **无人值守跑片是硬需求吗？**（决定 §4.1 选 A 还是 C）
2. **客户端渲染意味着渲染发生在作者的机器上**——多作者各自渲染，产物会有 GPU 差异。可接受吗？
3. **是否接受分阶段**，尤其是阶段 1–3 期间 Blender 与 three.js 并存？
4. **§5 的两个 schema 缺口**（道具/环境无关键帧、action 无姿态）要一并做，还是单独排期？

---

## 8. 架构结论修订：不再以"取代 Blender"为目标（2026-10-08）

### 8.1 初衷，以及它在哪兑现了

一句话：让"预览"和"成片"是同一个东西。

- Blender 路径：SceneScript -> `blender_converter.py` 生成 Python -> `blender --python` -> PNG。
  场景逻辑被实现两遍——转换器里的 `_build_lowpoly_human` 与前端 `SceneScript3DPreview.tsx` 的
  `lowPolyHumanRig`。这就是所谓"两套词汇表"。
- three.js 路径：SceneScript -> URL fragment -> `render.html` 挂载 `SceneScript3DPreview`
  （作者编辑时看的同一个组件）-> 逐帧元素截图 -> PNG。

一张表，兑现与未兑现：

| 兑现了（几何题，统一） | 未兑现（有设计判断，改为镜像） |
|---|---|
| 相机（预览相机即渲染相机） | 姿态库 `character_pose.py` <-> `characterPose.ts` |
| 七段人形 rig（1:1 移植） | 物体运动 `object_motion.py` <-> `objectMotion.ts` |
| 深度通道（render target） | held 道具握持 `held_item_grip.py` / `heldItems.ts` |
| 抓帧链路 | |

未兑现的三项不是疏忽，是清醒的选择：成对镜像 + 一致性测试（`test_character_pose_parity.py`、
`test_object_motion_parity.py` 及对应 fixtures）。**几何统一，判断镜像**——这是本方案的最终结论。

### 8.2 三条角色，以及各自的边界

| 角色 | 承担者 | 说明 |
|---|---|---|
| 创作回路 | three.js | 作者拖物体、拖时间轴、看构图。**这个角色在渲染工程之前就存在，且不可替代——它就是编辑器本身。** |
| 快速渲染路径 | three.js | 可选，实测同场景约 8 倍于 Blender；不依赖 `BLENDER_EXECUTABLE`。**不是默认。** |
| 参照实现 / 仲裁者 | Blender | 1131 行久经考验的转换器；three.js 产物的"对不对"由它回答。 |

### 8.3 为什么保留 Blender 是资产而非负债

1. **它是零成本的**：不是默认路径，没人跑它。留着不花钱，删除要承担"参考实现消失"的风险。
2. **它是唯一能回答"three.js 渲得对不对"的东西**。没有它，"720 帧跑通"不可验证——
   本方案作者曾因此收回过一次性能数字（那套 harness 只断言非黑，未断言帧间差异）。
3. **精度天花板更高**：白模预览够用的那天之前，光照/材质那条路是现成的；现在删了，
   将来要重建 1131 行。
4. **两个实现互为对照组**。本回合三个致命 bug 全是靠"质疑自己的证据链"抓到的，而不是靠
   任何单个实现的自信：相机 prop 只在创建时读一次、抓帧页面把自己的 HUD 与播放条烧进每一帧
   （并因此让驱动的冻结守卫永久失效）、`include_control_passes` 是收了不用的假参数。

### 8.4 一句话结论

**不是"取代"，是"分工 + 互相仲裁"。** 相机 bug 那一类（预览显示 A、渲染出 B）在
同一份代码下无处藏身；而"渲得对不对"没有 Blender 就无法回答。两者都是必需的。

—— 另注：`blender_mcp_client.py` 一节见 §6 决策第 3 条。
