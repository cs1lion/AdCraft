# 同步对比面板与画布体验 — 优化清单（实现铺路）

> 状态：**部分已实施（2026-10-11 首批）**。来源：2026-10-11 三轮代码评审（SyncComparePanel 全量 + base.css + 新增脚本）+ 对标产品调研。
> 作用：所有条目已核实到文件行号，可直接拆 issue 或开工；每条标注优先级与预估规模。
> 相关文件：`apps/web/src/features/agent-canvas/canvas/SyncComparePanel.tsx`、`syncCompareModel.ts`、`SyncComparePanel.css`、`AgentCanvasPageSurface.tsx`。
>
> **首批已落地**：A1、A2、A3（=B1-1）、A4、B1-3、A5 中的 Esc/IME/nudge 抽取/图标、设计文档一期 §4.5（dev-up --resume）。实现方式与本文预估的差异见各条目内标注。

---

## A. 缺陷修复（评审实锤）

### A1. P2 · 切换「并排 ↔ 滑动分割」丢播放进度并静默停播 ✅ 已修

两种模式的 JSX 树完全不同（`SyncComparePanel.tsx:251` vs `:288`），切换时两个 `<video>` 卸载重建：进度归零、视频暂停，但 `playing` state 仍为 true，UI 显示 ⏸，再点一次按钮执行的是暂停。重置 effect 依赖为 `[leftId, rightId, open]`（`:75`），不含 `mode`，不触发恢复。

**实施（2026-10-11）**：采用方案 A——双 pane 常驻，`is-split` 双列网格 / `is-wipe`、`is-diff` 同格叠加（`grid-area: 1/1`），切视图只换 CSS 类，video 元素永不重建。回归测试锁元素同一性 + currentTime 保留。

### A2. P2 · A 播完后 B 被钉死反复抖动，播放按钮状态失真 ✅ 已修

无 `onEnded`：A（主时钟）到结尾后 `playing` 仍 true，轮询继续。若 B 比 A 长（或 offsetB 为正），B 每 220ms 被 `expectedRightTime`（`syncCompareModel.ts:22`）拉回 A 的结尾，一帧一进地抖；按钮显示 ⏸ 但视频都停着。

**实施（2026-10-11）**：左 video 加 `onEnded` → 暂停 B + `setPlaying(false)`；轮询内加 `a.ended` 短路双保险。带 jsdom 回归测试。

### A3. P2 · 双视频音频叠加（无音源控制）✅ 已修（=B1-1）

两个 `<video>` 均无 `muted`（grep 0 处），白模与成片都带音轨时两路声音直接打架。

**实施（2026-10-11）**：音源三档 A/B/静音 segmented control（transport 内），默认 A（对标 Premiere 参考监视器单路参考音）；React 受控 `muted` prop 实现。

### A4. P2 · 提交卫生 ✅ 已修

- `output/`、`tmp/`、`apps/web/scripts/demo-video/`（40+ 一次性脚本+录制产物）已进 `.gitignore`（对齐仓库既有"scratch 永不提交，要留就刻意提升"原则）。
- demo-video 同步排除出 eslint（`eslint.config.js` ignores）——否则 scratch 脚本的 7 个 `no-empty` 把全量 lint 打红。
- 未删除任何 scratch 文件（并行会话可能在用）；要长期保留的脚本（如 verify-sync-compare.mjs）由用户决定后再单个提升进版本库。

### A5. P3 组（单条都小，可合并一个 issue）

| 条目 | 位置 | 状态 |
|---|---|---|
| base.css padding 改动影响全站 ≤900px/≤620px 断点 | `base.css:655,668,690` | 待确认（录屏补偿→还原；侧栏对齐→CHANGELOG 补记）；**未入提交** |
| 视频加载失败无反馈；资产版本更新静默重载丢进度 | `<video>` 无 `onError` | ✅ 已修：onError 错误 pill + 重试（`load()` 重拉）；url 变化纳入 Transport 重置依赖 |
| 漂移校正硬 seek 拉扯 | 轮询校正 | ✅ 已修：`b.seeking \|\| b.readyState < 3` 跳过本轮，防弱网 seek 风暴 |
| wipe 两侧宽高比不同时错位 | stage 叠加布局 | ✅ 已修：`aspectMismatch`（差超 1%）时叠加视图显示警告角标 |
| divider `role="slider"` 拿不到键盘（方向键被全局拦截） | 键盘 handler | ✅ 已修：divider 自行处理方向键 ±2% 并 stopPropagation |
| 小屏 transport 溢出（8 控件一行） | `SyncComparePanel.css` | ✅ 已修：≤860px 换行、进度条独占一行 |
| modal 无 Esc 关闭/焦点陷阱 | dialog | ✅ Esc 已做；焦点陷阱待办 |
| 逐帧步进硬编码 24fps；`,`/`.` 中文输入法不命中 | 键盘 handler | ✅ IME 全角已接入；fps 已常量化 `FRAME_RATE` |
| `nudgeOffset` 限幅逻辑长在组件里不可测 | 组件 | ✅ 已抽 `clampOffsetSeconds` 进 model + 单测 |
| 工具栏按钮图标 ⏸ 语义像暂停 | 工具栏 | ✅ 已换 ⇄ |
| 漂移平滑升级：小漂移用 playbackRate ±5% 微调代替硬 seek | 轮询校正 | 待办（现有 seeking/readyState 守卫已消除风暴，此项是体验打磨） |

---

## B. 对标抄袭清单

### B1. 审片/NLE 线（对标 Premiere 参考监视器、Resolve、Frame.io、SyncSketch、CineSync）

| # | 功能 | 抄谁 | 落法 | 规模 |
|---|---|---|---|---|
| B1-1 | 单路参考音 + A/B/静音切换 | Premiere 参考监视器 | ✅ 已实施（音源 segmented control，默认 A；兼修 A3） | 0.5 天 |
| B1-2 | In/Out 点 + 区间循环 | 全体 NLE 的 I/O 键 | ✅ 已实施：I/O 键 + 入/出按钮 + 进度条色带；越出点回入点循环（`loopBoundaryTime`，越点自动交换保持 in ≤ out） | 1 天 |
| B1-3 | Difference / 叠化混合模式 | Figma onion skin、开源 video-compare | ✅ 已实施：新增第三视图「差异」（顶层 `mix-blend-mode: difference`，黑=一致亮=差异 + 提示角标）；叠化 opacity 滑杆仍待办 | 0.5 天 |
| B1-4 | 版本栈对比 | Frame.io Version Stack | 节点右键「与上一版对比」→ 按 `output_asset_version_id` 取相邻两版 | 2 天 |
| B1-5 | 一键自动对齐 | Resolve/Premiere 音频波形 merge；自有亮度轨迹互相关（NCC 0.978，见通览视频标定） | 把已有标定代码搬进面板：跑亮度轨迹相关 → 算出 offsetB 自动填 | 1-2 天 |
| B1-6 | 镜号刻度/时间戳评论 | SyncSketch timestamped comments、Resolve markers | scene-3d 分镜 manifest 铺上 transport 做刻度，点击跳镜；导演口令钉时间戳 | 2-3 天 |
| B1-7 | 破 gang 独立 scrub | Resolve unganged trim | Shift 拖单侧独立 seek，松手 re-gang | 1 天 |
| B1-8 | Loupe 放大镜 | Frame.io | 双击框选区域，两侧同步放大（transform 同步） | 2 天 |
| B1-9 | 导出对比片段 | —（自有 ffmpeg 管线） | 当前配置（split/wipe/offset/区间）→ ffmpeg 合成对比 MP4；演示物料管线可省手工录屏 | 2 天 |
| B1-10 | SMPTE 帧时码 + 帧对截图 | NLE 标配 | `formatTime` 出 `SS:FF`；canvas 截图导 PNG 对 | 0.5 天 |

### B2. 画布本体线（对标 ComfyUI、Blender 节点、TouchDesigner、n8n、tldraw、React Flow）

| # | 功能 | 抄谁 | 落法 | 规模 |
|---|---|---|---|---|
| B2-1 | MiniMap | React Flow v12 自带 `<MiniMap>` | ⚠️ **实施后撤回**：仓库早有冻结测试封禁 MiniMap（`AgentCanvasChatPanel.test.tsx:1919`，commit f2415b30 "remove minimap and chat divider"，2026-08-10，无理由说明）。按工程标准 §6 不静默覆盖既有决策，已还原。重新引入前需找到当年移除动机（视觉干扰 or 性能），取得产品决策后改冻结测试 | — |
| B2-2 | 节点结果缩略图常显 | Blender viewer、TouchDesigner viewer flag、ComfyUI 节点出图 | 生成完成节点卡上铺最后一帧/结果图（`mediaAssetContentPath` 现成） | 1-2 天 |
| B2-3 | Bypass/Mute 节点 | ComfyUI bypass、Blender mute | 节点右键 bypass：数据直通下游，不重跑 | 1-2 天 |
| B2-4 | 执行数据钉在节点上 | n8n | 节点挂最近一次运行输入/输出/耗时/错误（对接 executor/ledger 数据） | 3 天 |
| B2-5 | 激光笔/演示模式 | tldraw laser pointer | 画布内置激光笔，替代手工光标注入的录屏方案 | 1 天 |
| B2-6 | Cmd+K 命令面板 | Linear/Notion/tldraw | 画布动作统一键盘入口 | 2 天 |
| B2-7 | Subgraph/分组折叠 | ComfyUI subgraph、Blender Frame | 大工程，立 issue 不排期 | 1-2 周 |

## C. 落地顺序建议

1. **本周级**（半天级×4）：A1、A2（两个 P2 bug）→ A4（gitignore）→ B1-1（兼修 A3）→ B1-3（一行 CSS）→ B2-1。
2. **月级**（改变审片工作流）：B1-2 区间循环 → B1-4 版本栈 → B1-5 自动对齐 → B1-9 导出对比。
3. **立 issue 慢慢还**：A5 全组、B1-6/7/8、B2-2/3/4/5/6、B2-7。

验收方式：每条完成后按 `docs/agents/engineering-standards.md` 跑 `apps/web` 阶梯（`check:quality`，UI 面变化加 `npm run check`）；A1/A2 修复须带回归测试（现有 15 条单测中无覆盖）。
