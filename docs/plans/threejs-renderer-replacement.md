# 用 three.js 替换 Blender 渲染层 — 替换方案（待确认）

> 状态: **待用户确认**，未开始实施。
> 触发: 用户确认"只要形到位，精细度不做要求"，且最小验证通过。

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

## 6. 建议的实施分期

| 阶段 | 内容 | 出口判据 |
|---|---|---|
| **0. 已完成** | 最小验证（§1） | 720 帧 75s、帧间有差异、镜头切换可见 |
| **1. 角色 rig** | §3.6 移植四肢到 three.js 预览 | 预览剪影与 Blender 渲染一致；既有视口回归通过 |
| **2. 页内捕获通道** | §4.2 + §4.1-A | N 帧回传 → ffmpeg → MP4 可播放 |
| **3. 编排接线** | §4.3 节点状态机 + 心跳 | curl 触发 → 浏览器渲染 → 节点 ready，全链路端到端 |
| **4. depth pass** | §4.5 | `collect_control_passes` 契约通过 |
| **5. 退役 Blender** | §3.1 / §3.2 / §3.8 | 全量测试改造后回归；`.env` 移除 `BLENDER_EXECUTABLE` |
| **6.（可选）无人值守兜底** | §4.1-B | 实测 headless 速度 vs Blender，再决定是否保留 Blender |

**每阶段结束后跑一次真机主线**，不叠加到最后一口气验证——本会话的教训是：连续多轮
"测试全绿"之后，一次端到端就抓出致命 bug（预演片段发布 500）。

---

## 7. 需要你确认的四个问题

1. **无人值守跑片是硬需求吗？**（决定 §4.1 选 A 还是 C）
2. **客户端渲染意味着渲染发生在作者的机器上**——多作者各自渲染，产物会有 GPU 差异。可接受吗？
3. **是否接受分阶段**，尤其是阶段 1–3 期间 Blender 与 three.js 并存？
4. **§5 的两个 schema 缺口**（道具/环境无关键帧、action 无姿态）要一并做，还是单独排期？
