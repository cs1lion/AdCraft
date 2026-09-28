# 交接引导：最后一百米修复与实机演示

> 建立：2026-09-28
> 用途：把 D/E 阶段的修复与演示任务交给另一位同事时，把这份文档给他。
> 他只需读这份文档 + 下面列出的文件，不需要翻历史会话。

---

## 0. 先拿到这四份（必读，按序）

| 顺序 | 文件 | 为什么 |
|---|---|---|
| 1 | `docs/plans/last-hundred-meters-plan.md` | 主计划。D/E 阶段的任务、优先级、验收标准都在这 |
| 2 | `docs/plans/live-demo-e2e-plan.md` | 测试方案。**验收哲学**在这里：验骨架与反馈诚实度，不验画质 |
| 3 | `docs/agents/engineering-standards.md` | 自检阶梯、测试纪律、可观测降级、契约同步 |
| 4 | `demo-materials/README.md` + `SOURCES.md` | 素材在哪、怎么选、哪些网络源不可达 |

**补充读（了解背景，各 10 分钟）**：
- `apps/api/CONTEXT.md` / `apps/web/CONTEXT.md` —— **领域词汇表**。
  写代码和写文档必须用表里的词（比如"Slot"不能叫"Output"，"Workflow"不能叫"Pipeline"）。
- `docs/plans/replica-completion-research.md` —— 复刻线做到哪、哪些缺口是历史遗留
- `docs/adr/0010` / `0012` / `0013` / `0014` —— 直出渲染域、导演指令栏、降级与触发、导演 takes

---

## 1. 第一天的动作顺序

1. **起环境，跑 L0 冒烟**（`live-demo-e2e-plan.md` §2）。
   L0 不过就不要开始修——环境问题的结论会污染后面所有判断。
2. **跑一次可达性检查**建立基线认知：
   ```bash
   cd apps/web && npm run report:endpoint-reachability
   ```
   会输出 205 路由 / 31 死端点。**每次交付前这个数不能增加。**
3. **跑一次后端 replica+scene3d 测试**看当前基线：
   ```bash
   cd apps/api
   .\.venv\Scripts\python.exe -m pytest tests/ -q -k "replica or scene3d"
   ```
   预期 **1028 passed / 1 failed**，那 1 个失败就是 D1。
4. 从 **D1** 开始（见 §2）。D1 是地基，其余任务都排在它后面。

---

## 2. 任务 → 文件 → 验收 对照表

### D 阶段（演示阻断项）

---

#### **D1 · 成片没音轨** 🔴 地基任务

| | |
|---|---|
| **问题** | `test_resolved_bgm_renders_real_audio_into_final_video` 从未真正执行过 |
| **根因** | 测试把资产写到 `library/bgm_e2e.mp4`，而 `v2_data_boundary.py:4` 的顶层白名单只有 `{assets, v2}` → 被拒。作者机器无 ffmpeg → `@pytest.mark.media` skip → 记为通过 |
| **先读** | `apps/api/tests/test_replica_direct_execute_render_media.py`（整个文件，重点 :188-240）<br>`apps/api/app/services/v2_data_boundary.py`（80 行，全读）<br>`apps/api/app/services/replica/direct_execute_bridge.py` |
| **改哪** | `apps/api/tests/test_replica_direct_execute_render_media.py:202` → `library/bgm_e2e.mp4` 改成合法路径（如 `assets/audio/bgm_e2e.mp4`） |
| **怎么验** | ```bash<br>cd apps/api<br>.\.venv\Scripts\python.exe -m pytest tests/test_replica_direct_execute_render_media.py -v<br>ffprobe -v error -select_streams a -show_entries stream=codec_name -of csv=p=0 <成片路径><br>``` |
| **完成判据** | 用例 PASS **且** ffprobe 能探到音频流。**若改完路径仍失败，那就是产品缺陷**——继续查 `V2FinalCompositionRenderer` 的音频图构建，如实记录，不要改测试绕过 |
| **注意** | 这条同时锁 `role: bgm/sfx` 标记（历史上 BGM 被静默跳过过一次）。别为了让测试过而删断言 |

---

#### **D2 · 未解析素材被静默剥掉**

| | |
|---|---|
| **问题** | 直出时未解析的 BGM/SFX clip 被写盘前剥掉（`direct_execute_bridge.py:153`），前端只显示一句文案 → 用户以为 BGM 进去了 |
| **先读** | `apps/api/app/services/replica/direct_execute_bridge.py`（189 行，全读）<br>`apps/api/app/services/replica/direct_execute_render.py` 的 `unresolved_intents_of`（:478）<br>`apps/api/app/api/v1/endpoints/replica.py` 的 `/blueprint/direct-execute/render`（:786）<br>`apps/web/.../ReplicaBlueprintPanel.tsx` 的直出结果区（:380-470） |
| **改哪** | 后端：确保响应带足补齐所需信息；前端：把 `unresolved_assets` 渲染成**可操作清单**（每行：intent / 时长 / 补齐按钮） |
| **怎么验** | 跑 `demo-materials/scripts/negative-briefs.md` 的 **NB-7**。不补齐时必须明说"已跳过 N 个素材"，且给出补齐入口 |
| **完成判据** | 用户能：看到跳过了什么 → 点补齐 → 选素材 → 重新直出 → 成片真的有了这段声音 |

---

#### **D3 · 闸门失败显示成成功**

| | |
|---|---|
| **问题** | `DirectorCommandBar.tsx:199` 和 `:296` 在闸门拒绝时仍设 `ok: true`，而 `ok` 决定渲染成灰色 note 还是红色 error |
| **先读** | `apps/web/src/features/agent-canvas/canvas/DirectorCommandBar.tsx:190-300`、`:571`<br>`docs/adr/0012-director-command-bar.md`（理解"gate 是契约"的设计意图） |
| **改哪** | 同上两行 |
| **怎么验** | ```bash<br>cd apps/web && npx vitest run src/features/agent-canvas/canvas/DirectorCommandBar.test.tsx<br>``` 补一条：闸门拒绝时 UI 走错误通道 |
| **完成判据** | 提交一条非法导演指令，界面红色报错，且错误文案指出是哪个 op 被拒 |

---

#### **D4 · Blender 不可用前端零提示**

| | |
|---|---|
| **问题** | 后端有具名错误 `scene3d_blender_unavailable`（`agent_canvas_node_execution.py:2445`）和 `mcp_unavailable`（`scene_3d.py:1456`），前端**零引用** |
| **先读** | 上面两处后端代码；`apps/web/src/features/agent-canvas/workbench/LocalEngineWorkbench.tsx` 的 `error` 处理 |
| **改哪** | 前端：识别这两个 error_type，给出可行动提示（装 Blender / 走降级路径 / 联系谁） |
| **怎么验** | 临时让 Blender 不可用 → 触发预演 → 界面必须说明原因和下一步 |
| **完成判据** | 用户看到的是"Blender 未安装，无法预演，<下一步>"，不是"失败"两个字 |

---

#### **D5 · 三处保存静默失败**

| | |
|---|---|
| **问题** | `LocalEngineWorkbench.tsx:551 / 577 / 595` 三处 `.catch(() => {})` |
| **先读** | 同文件 :540-600（三个 persist 函数） |
| **改哪** | 三处 catch：转成可见错误 + 可重试 |
| **怎么验** | 让 `patchNode` 失败（断后端）→ 点"存 take" / 改分句 / 改变体 → 必须看到错误 |
| **完成判据** | 任一保存失败用户都看得见，且能重试 |

---

#### **D6 · 3D 草稿刷新即丢**

| | |
|---|---|
| **问题** | 草稿在 React state（`LocalEngineWorkbench.tsx:516`），无 `beforeunload`、无 localStorage |
| **先读** | 同文件 draftScript / save / revert 逻辑；`SceneScript3DEditor.tsx` 的 `onSave` / `onRevert` / `dirty`（:269-273、:996-1010） |
| **改哪** | 新增：编辑后写 localStorage 草稿 + `beforeunload` 提示 + 加载时恢复 |
| **怎么验** | 编辑场景 → 不保存 → 刷新 → 内容还在，且有"恢复的是未保存草稿"的提示 |
| **注意** | 参考 `agentCanvasViewport.ts` 现有的 localStorage 用法，沿用同样的 key 命名风格 |

---

#### **D7 · 直出无幂等、renderId 刷新丢失**

| | |
|---|---|
| **问题** | `ReplicaBlueprintPanel.tsx:214-215` renderPhase/renderId 只在组件 state；重试每次 `save_timeline`（覆盖用户原 final 时间线）+ 新建 render_id |
| **先读** | 同文件 :210-220、:355-475（提交与轮询）；`direct_execute_bridge.py:124-189` |
| **改哪** | 加幂等键；renderId 持久化；暴露"正在渲染 N 秒"与取消入口 |
| **怎么验** | 连点两次直出 → 只产生一次渲染；渲染中刷新 → 回来还能查到任务 |
| **完成判据** | 重复操作不产生重复产物；中断可恢复 |

---

### E 阶段（演示保障）

| 任务 | 先读 | 改哪 | 怎么验 |
|---|---|---|---|
| **E1** 变体审片 | `docs/plans/replica-hypit-gap-analysis.md` G5 段；`replica.py:678`；`ReplicaBlueprintPanel.tsx` 的 `StyleVariantCandidate`（:1050-1139） | 新增变体预览；**接 `recipe_id`/`recipe_name`**（当前前端类型里没有这两个字段） | 跑 `rewrite-cases.md` RW-3：各变体字幕样式**可见地不同** |
| **E2** 配方导入导出 | `apps/api/app/services/replica/recipe.py`；`replica.py:429/443`；源码 tab | 工作台加两个按钮 | 导出 `.adrecipe` → 改 → 导入 → 样式生效 |
| **E3** 分镜 finding 可见 | `apps/api/app/services/scene3d/storyboard_export.py:157`；`scene_3d.py:1738` | `/storyboard` 响应加 findings；`StoryboardPanel.tsx` 渲染 | 构造有空隙/短镜的场景 → UI 有提示 |
| **E4** 多轮记忆接线 | `LocalEngineWorkbench.tsx:742` vs `:732`；`TransitionProposalsPanel.tsx:183-191` | 给 `SceneScript3DEditor` 补传 `workflowId`/`nodeId`/`initialEngagedIds` | 提案 → 刷新 → 保留集还在 |
| **E5** 错误可行动 | `replica.py` 结构漂移错误（:730）；`ReplicaBlueprintPanel.tsx:391-404` | 逐条展示漂移清单；展开 422 细节 | 故意触发结构漂移 → 看到逐条可行动的说明 |
| **E6** 进度与取消 | `apps/api/app/services/scene3d/render_job_manager.py`；`scene_3d.py:602-700` | 前端接 `render/async` + 轮询 + 取消 | 触发预演 → 有进度 → 能取消 |

---

## 3. 不能违反的几条

| 规则 | 来源 | 说明 |
|---|---|---|
| **领域词汇** | `CONTEXT.md` | Slot / Workflow / Asset Version / Node 等词不能换说法 |
| **契约同步** | 工程标准 §2 | 生成的产物不能手改；改 schema 要重新生成 + `npm run check:agent-canvas-contract` |
| **可观测降级** | 工程标准 §4 | **任何降级必须有可查询的状态标记**，静默降级是明确禁止的。D2/D4/D5 都是这条的违规 |
| **测试标记** | 工程标准 §3 | pytest marker 严格，未标记是缺陷；媒体语义要有真实 ffmpeg 测试 |
| **死端点不增** | 本项目 | `npm run check:endpoint-reachability` 必须通过 |
| **ADR 冲突要显式提出** | `docs/agents/domain.md` | 你的改动若与 ADR 冲突，说出来，别默默覆盖 |
| **不留死代码** | 本项目 | 算出来不用、后端无调用方的模块，要么接上要么删（见 E3 / `director_takes.py`） |

---

## 4. 交付物要求（每完成一个任务）

```
1. 代码 + 测试（新增测试要能因缺陷变红）
2. 自检阶梯结果（工程标准 §1，贴命令与输出数字）
3. npm run check:endpoint-reachability 通过
4. CHANGELOG.md 加一条（仓库既有纪律，逐条写，含诚实的边界说明）
5. demo-materials/runs/<时间戳>/ 下的留痕：截图 + 产物 + note.md
```

> **SKIP 必须写原因；"没测"不能记成"通过"；没修的缺陷要在 summary 里显式列出。**

---

## 5. 建议的提交方式

按任务粒度提交，commit message 里带上计划编号，便于回溯：

```
fix(replica): D1 G7 media 测试路径合法化——resolve-library 音频路径真跑通
fix(web): D3 导演指令栏闸门失败走错误通道
feat(web): E1 变体审片——让 .adrecipe 样式差异第一次被用户看见
```

推送到分支而非 main，便于逐项 review。
