# 最后一百米 —— 实机演示驱动的实施计划（v2）

> 建立：2026-09-28（v1 同日，v2 因目标升级而重写）
> **目标重定义**：从"修缺陷清单"升级为——
> **项目启动实机演示，前后端真实访问，完成「创意输入 → 文本 → 音频 → 视频 → 剪辑 → 成片」全链路。**
> 关联：`live-demo-e2e-plan.md`（测试方案，本文的执行前置）·
> `replica-completion-research.md` · `3d-workbench-and-pipeline-completion.md` ·
> `v0.2-handover-open-items.md` · ADR 0010/0012/0013/0014
> 素材：`demo-materials/`

---

## 0. v2 的关键变化

| | v1（缺陷清单驱动） | v2（演示驱动） |
|---|---|---|
| 成功定义 | 缺陷数下降 | **一条真实链路从创意走到成片，骨架和反馈都诚实** |
| 优先级依据 | 缺陷严重度 | **是否阻断演示** |
| 成片质量 | 未讨论 | **明确不作为验收标准** |
| 新增门槛 | — | L0 冒烟不过 → 演示取消，不进入后续 |

**验收哲学**：我们验收的是**产品骨架与交互的诚实度**，不是模型的艺术水平。
按钮点了没反应、错误被吞掉、转圈不超时 —— 这些不过；
成片 480p 糊了点 —— 可以过。

---

## 1. 复核台账（2026-09-28 实测，按「是否阻断演示」重排）

> 全部经工具或源码行号复核，详见 v1 文档与本轮留痕。

### 1.1 阻断演示（S1）—— 必须演示前修掉

| # | 问题 | 证据 | 演示后果 |
|---|---|---|---|
| **D1** | **成片没音轨**（G7 验收从未真正执行） | `test_replica_direct_execute_render_media.py:202` 用 `library/` 路径，被 `v2_data_boundary.py:4` 拒绝；作者机器无 ffmpeg → skip → 记为通过 | 当场事故：播出来是哑片 |
| **D2** | 未解析素材被**静默剥掉** | `direct_execute_bridge.py:153` 写盘前剥 clip，前端只显示一句文案 | 用户以为 BGM 进去了，实际没有 |
| **D3** | 闸门失败显示成**成功** | `DirectorCommandBar.tsx:199/296` 设 `ok: true` | 点"导演指令"看似生效，实则被拒 |
| **D4** | Blender 不可用前端**零提示** | 前端无 `blender_unavailable` 引用 | 3D 线演示到渲染直接失败，用户看不懂 |
| **D5** | 三处保存**静默失败** | `LocalEngineWorkbench.tsx:551/577/595` `.catch(() => {})` | take/分句/变体存不上，无感知 |
| **D6** | 3D 草稿**刷新即丢** | 全仓无 `beforeunload`；localStorage 不存脚本草稿 | 演示中误刷新 → 当场重做 |
| **D7** | 直出**无幂等**、renderId 刷新丢失 | `ReplicaBlueprintPanel.tsx:214-215` 仅组件 state | 刷新后正在跑的渲染查不回来 |
| **D8** | **拆解的"取消"是假的** | `ReplicaTeardown.tsx:462` 只 `abortRef.current?.abort()`（前端 fetch）；后端 `replica.py:372` 用 `asyncio.to_thread` 跑，无 job id、无结果回收、无 timeout | 点了取消后端仍在烧 LLM——演示中一次误点就白烧额度 |

### 1.2 可见缺陷（S2）—— 演示中会被问住

| # | 问题 | 证据 |
|---|---|---|
| E1 | 复刻 4 个端点无前端入口 | `resolve-library` / `variant-render-plans` / `recipe/export` / `recipe/import`（DEAD）<br>另有 2 条 UI-MISSING（仅 `apps/api/scripts` 调用）：`direct-execute` / `direct-execute-plan` |
| E2 | 3D 17 个端点无前端入口 | 含 `render`、`render/async`、`render/jobs`、`render/{job_id}`、`render/{job_id}/cancel`（后端有进度与取消，前端零引用——工作台本身没有渲染按钮，渲染只走节点执行器） |
| E3 | 分镜 finding 算了不返回 | `check_storyboard_span` 16 条测试，`/storyboard` 只调 `build_storyboard`（`scene_3d.py:1738`） |
| E4 | 多轮记忆"已落地"实为未接线 | `LocalEngineWorkbench.tsx:742` 未传 `workflowId`/`nodeId`（对比 `:732`） |
| E5 | 白模开关绕过 ops 闸门 | `LocalEngineWorkbench.tsx:633-650` 直接 `patchNode` |
| E6 | 错误不可行动 | 结构漂移逐条清单、422 细节未展开；blockers 清单只在 `error_type === "direct_execute_not_feasible"` 时渲染 |
| E7 | 端点吞异常 | `scene_3d.py:2772` `except Exception: pass`（注释却写着 never-silent） |
| E8 | **配方库静默降级** | `ReplicaBlueprintPanel.tsx:256-258` `catch {}` 吞掉拉取失败，直出静默退回默认形态。注释写明是"有意不让可选可不强的配方绊倒直出"——**意图合理，但违反工程标准 §4（降级必须可查询）**：用户以为选中了配方，实际没有 |

### 1.3 体验债（S3）—— 演示时口头说明即可

| # | 问题 |
|---|---|
| F1 | 无 undo 栈（"撤销修改"是整体回退到上次保存） |
| F2 | take 上限不可见 / 不可删 / `operations` 恒为空 |
| F3 | 渲染无进度、无取消 |
| F4 | `voice-cast-resynth-line` 后端有、前端零入口 |
| F5 | 契约闸只覆盖 5 个 schema；前后端 4 对镜像词汇表无跨边界契约 |

---

## 2. 实测基线（2026-09-28）

| 项 | 结果 | 说明 |
|---|---|---|
| `apps/web` typecheck | 0 error | |
| `apps/web` vitest | **2516 passed / 80 failed**（15 文件） | 交接文档记 38 失败 → **恶化一倍以上** |
| `apps/api` replica+scene3d | **1028 passed / 1 failed** | 唯一失败即 D1 |
| 端点可达性 | 205 路由 / **33 死端点** | 首次量化；修正前缀误判后 +2 |

前端失败最集中：`AgentCanvasInlineWorkbench.test.tsx` **22/83 失败**
→ 工作台这一层**当前没有可信回归保护**，动它之前必须先解决。

---

## 3. 可达性检查（已交付，可进 CI）

| 文件 | 作用 |
|---|---|
| `apps/web/scripts/check-backend-endpoint-reachability.mjs` | 205 路由 × 5 类消费方，三档输出 |
| `endpoint-reachability-baseline.json` | 33 条已知死端点 |
| `endpoint-reachability-exemptions.json` | 1 条外部 webhook 豁免 |

```bash
npm run report:endpoint-reachability    # 报告
npm run check:endpoint-reachability     # CI 闸，已验证 exit 1
```

**死端点分组**：A 接入口即可用（4 条复刻）· B 需先定夺语义（17 条 3D）· C 疑似 v1 遗留（12 条）。

**工具自身修过的三个坑**（都会产生误报，误报比没检查更糟）：

1. 前端 URL 有三种拼法——字面量绝对路径、`${SCENE_3D_BASE}/x` 常量拼接（base 常声明在别的模块）、`request("/asset-library/entities")` 相对路径（前缀由 helper 加）。只认一种 → 100+ 误报。
2. 模板插值**不能截断到 `${`**——`/workflows/${id}/x` 会退化成 `/workflows/`，丢掉全部 workflow 作用域路由。必须整体替换成无斜杠占位符。
3. **路由匹配必须做尾部锚定**。否则 `/blueprint/direct-execute` 会匹配上 `/blueprint/direct-execute/render` 这个字面量，被误判成"可达"。修正后又暴露：占位符不能用 `__p__` 这类以 `_` 开头的写法——它会被尾部锚定的 `\w` 判定为"路径续写"，制造新的漏报（`asset_references` 一度从可达变成死端点）。占位符改用 `~p~`。修正前后死端点 31 → 33。

> 它解决的是一整类问题：**后端完成 + 测试全绿 + 文档标 ✅，但用户永远看不到。**

---

## 4. 实施计划

### D 阶段 · 演示阻断项（最高优先，目标：演示当天不翻车）

| 项 | 动作 | 验收 |
|---|---|---|
| **D1** | 修 G7 测试路径 `library/` → `assets/audio/`，**真跑一遍**并用 ffprobe 确认成片有音轨 | media 用例 PASS + 音轨探针留证；若仍失败则如实记为产品缺陷并继续修 |
| **D2** | 未解析素材改为**可见提示 + 补齐入口**（清单 → 选素材 → 重新直出） | 走 `NB-7`：不补齐时必须明说"已跳过 N 个素材" |
| **D3** | `DirectorCommandBar.tsx:199/296` 失败态改 `ok: false` | 闸门拒绝走红色错误通道（补测试） |
| **D4** | Blender 不可用给可行动提示 | 3D 线演示到渲染不再"看不懂的失败" |
| **D5** | 三处 `.catch(() => {})` → 可见错误 + 可重试 | take/分句/变体保存失败用户看得见 |
| **D6** | 3D 草稿持久化（beforeunload 提示 + localStorage 恢复） | 刷新不丢未保存编辑 |
| **D7** | 直出幂等键 + renderId 落盘可恢复；补渲染取消入口 | 重复点击不重复渲染；刷新能查回任务；能中断 |
| **D8** | 拆解改为**可取消的任务**：后端返回 job id，轮询/取消，teardown 加 timeout；前端"取消等待"改为真取消 | 点了取消后端真的停；或在超时时明确失败而非无限等待 |

> **D1 是地基**：它同时验证了"最后一米"最核心的一句承诺。
> 在 D1 通过之前，不要对外声称"零模型费直出可用"。

### E 阶段 · 演示保障（并行演示线可用）

| 项 | 动作 | 验收 |
|---|---|---|
| **E1** | `variant-render-plans` 前端：变体并排预览 | 能**看出**变体差异（G5 的兑付点） |
| **E2** | `recipe/export` + `import` 接到源码 tab | 改写用例可存 before/after |
| **E3** | storyboard finding 在 UI 可见 | 空隙/短镜有提示 |
| **E4** | 补传 `workflowId`/`nodeId`/`initialEngagedIds` | 刷新后保留集恢复 |
| **E5** | 结构漂移逐条展示 + 422 细节展开 | 每条错误能指向下一步 |
| **E6** | 渲染进度 + 取消（接 `render/async` 系列） | 长任务可见、可中断 |
| **E8** | 配方拉取失败改为可见降级（保留"不让配方绊倒直出"的意图，但必须告知用户"配方库不可用，已用默认形态"） | 降级可感知、可查询（工程标准 §4） |

### P 阶段 · 产品完善（演示之后）

| 项 | 动作 |
|---|---|
| P1 | undo 栈；take 上限可见 + 可删 + 差异对比 |
| P2 | 语音拖入时间线、唇形关键帧接线（P4 原有条目） |
| P3 | 契约闸扩展（replica/scene3d schema + 镜像词汇表跨边界测试） |
| P4 | 超大端点文件拆分（`scene_3d.py` 2770 行 / `replica.py` 1100 行），端点层不直连 DB |
| P5 | 前端失败基线治理：80 条失败逐条定责（修 / 豁免+理由），此后**新增失败 = 0** |

### 前置动作（今天就做）

| 项 | 理由 |
|---|---|
| 落提交：34 个未推送 + 62 个工作区改动 | 这个风险**已真实发生过一次**（交接文档记录的 309 文件险丢） |
| `.gitignore` 追加 `demo-materials/{videos,images,runs,outputs}/` | 可再生二进制不进库 |

---

## 5. 素材与测试

素材在 `demo-materials/`（详见其 README 与 SOURCES）：

- **视频** 5 个（真实剪辑结构，含 3 个静音片 + 2 个带音轨 1080p）
- **文案** 5 份（创意 brief ×3、**故事改写前后对照 RW-1~RW-4**、负例 NB-1~NB-8）
- **图片** 8 张（商品/角色/场景，固定 seed 可复现）
- **网络可达性实测表**在 `SOURCES.md` §1 —— **不要依赖 Wikimedia / archive.org / YouTube**（本机不可达）

测试方案见 `live-demo-e2e-plan.md`：L0 冒烟 → L1 主链路 S0–S8 →
L2 可交互性 → L3 状态反馈 → L4 负例 → L5 留痕。

---

## 6. 明确不做（新功能推迟到 D+E 完成）

片段级重拍 · 导演 NL 层 · 创意片头 · 3D-BOX 独立入口 · 拆解素材回填时间线

**理由**：这些都是在"链路通得住"之后的增量。在 D1–D7 未修前加功能，
只会让死端点清单更长、让演示更容易翻车。

---

## 7. 完成定义

### 一次演示算通过，需同时满足

1. **L0 冒烟通过**（环境起得来）
2. **L1 主链路 S0→S8 全通**，每步有留痕（截图 + 产物）
3. **D1 验证通过**：成片有音轨，ffprobe 留证
4. **可达性检查通过**：死端点数不增
5. **summary.md 显式列出所有已知缺陷**，包括没修的

### 一个阶段算完成，需满足

1. 自检阶梯按 `docs/agents/engineering-standards.md` §1 跑过并贴结果
2. 可达性检查通过（死端点数不增）
3. 有可回溯留痕产物，不靠"我记得跑过"
