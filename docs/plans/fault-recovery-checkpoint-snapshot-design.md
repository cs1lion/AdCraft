# 故障恢复 Checkpoint 与 Snapshot — 设计探索

> 状态：**设计探索，未拍板，未实施**。2026-10-11 基于全量代码调查写成；§1 的代码事实均带文件引用。
> 目的：把散落在各处的恢复机制收敛成一张图，给出 checkpoint 的设计框架，识别真实缺口并探索方案与取舍，为分期实施铺路。
> 关联：`docs/plans/last-hundred-meters-plan.md`（D6/D7 已涉及 localStorage 恢复与 renderId 幂等）· `sync-compare-and-canvas-optimization-backlog.md`（B2-4 执行数据钉节点与本文件 §4.2 联动）。

---

## 1. 现状盘点：系统已有的"可恢复资产"

### 1.1 四层持久化状态

| 层 | 内容 | 恢复语义 | 代码锚点 |
|---|---|---|---|
| L1 作者意图 | `workflow_revisions` 不可变修订链（document_json 全量 + content_hash） | `restore_revision()` = 恢复历史修订为**下一个**不可变修订 | `models.py:129-158`、`workflow_authoring_repository.py:270-286` |
| L2 编排态 | `agent_canvas_workflows.revision/layout_revision` + 节点表 | 乐观锁（expected_revision 比对）、layout CAS | `models.py:584-613`、`agent_canvas_repository.py:628-648,490-495` |
| L3 执行态 | `agent_canvas_executions`（含 `partial_completed`）→ `execution_members`（state/phase/attempt_no + run_intent_snapshot）→ `agent_canvas_node_leases`（租约+心跳）→ `agent_canvas_provider_tasks`（含 `recovering` + recovery_deadline） | DB 状态机 + 租约过期回收 + `compute_ready_wave` 逐波续跑 | `models.py:2052-2243`、`agent_canvas_runtime.py:416-452` |
| L4 产物 | `assets`（身份）+ `asset_versions`（不可变，version_no/sha256/parent_version_id）→ 本地对象存储 `data/assets/{originals,generated,...}` | 两阶段提交：`ResultPublicationIntentRow`（payload_digest + expected_storage_key + expected_object_sha256）→ 不可变回执 | `models.py:292-355,2288-2383`、`v2_asset_store.py:22-46` |

### 1.2 已有的快照族

| 快照 | 载体 | 作用 | 时机 |
|---|---|---|---|
| run_intent_snapshot | member 行内三字段（id/json/digest） | 冻结执行前意图，恢复时不再问上游 | member 进入执行前 |
| prompt_context_snapshots | 独立表 | 提示词上下文复用，重试不重算 | 生成前 |
| video_parameter_compilation_snapshots | 独立表 | 参数编译复用 | 编译后 |
| WorkflowV2RuntimeSnapshot | `v2_runtime_snapshot_service.py` | 运行时全量视图 | 服务侧构建 |
| run_snapshots | `agent_canvas_run_snapshots.py` | 运行记录 | 执行侧 |
| ledger_json 全量快照 | requirement ledger 修订链 | 需求清单版本化 | 修订时（`models.py:615-683`） |
| internal_document_checkpoint | 幂等键 `internal-checkpoint:{envelope_id}` | 文档检查点幂等 | 写入前 |
| post-ready checkpoint | `agent_canvas_post_ready_checkpoint.py` | ready 后检查点 | ready 后 |
| 前端草稿 | localStorage（scene3dDraft.ts） | 表单防丢 | 输入时 |

### 1.3 已有的恢复触发器与服务生命周期

- 启动恢复：`v2_execution_recovery.py`（RecoveryTrigger：startup / explicit_resume，扫 queued/running/waiting 执行与 provider task）+ 陈旧记录对账、provider 恢复、产物发布恢复三个专用服务。
- 进程：Node agent runtime(:8765) / FastAPI(:8000) / Vite(:5189)；生产 compose 三容器 `restart: unless-stopped` + healthcheck；开发 `scripts/dev-up.sh` pid 文件幂等拉起。
- 备份：**仅一次性迁移前快照**（`persistence/backup.py`，只在 DB 处于 pre-authoring 修订时生成一份）。无周期备份、无 PITR。

**小结**：L1-L4 每层都有不可变或可重放的骨架，crash-only 风格的启动恢复已大体成立。缺的不是"从零设计 checkpoint"，是**四个具体缺口**（§3 矩阵）。

---

## 2. 设计框架：三个正交轴

任何 checkpoint 设计先在这三个轴上定位，再用一句话校验：

> **恢复 = 已固化状态 + 确定性重放。** 问三个问题：checkpoint 之间丢了什么？重放那段需要什么输入？重放是否确定？

| 轴 | 取值 | 现状倾向 |
|---|---|---|
| 粒度 | workflow / 节点 / member-phase / provider-task / **帧块** | 到 provider-task 为止，帧块缺失 |
| 时机 | 事件日志（journal）/ 周期快照 / 边界快照（事务边界） | 全是边界快照，无 journal |
| 作用域 | 进程崩溃恢复（crash-only）/ 逻辑回滚（undo）/ 时间旅行 | 崩溃恢复较全；时间旅行有裂缝（§3） |

---

## 3. 故障场景 × 现有路径 × 缺口矩阵

| # | 故障场景 | 现有恢复路径 | 缺口 |
|---|---|---|---|
| F1 | FastAPI 进程崩溃 | 启动触发器扫执行 + 租约回收 | 无（crash-only 成立） |
| F2 | agent runtime 崩溃 | lease TTL 过期 → provider task `recovering` → re-dispatch | 无 |
| F3 | provider 429/流式中断 | member 整体重试；prompt/编译 snapshot 降重试成本 | 流式 token 无 checkpoint——生成是秒-分钟级任务，**可接受，不建议做** |
| F4 | 渲染中途崩溃（three.js 720 帧 / ffmpeg 编码） | 无——从 0 重渲 | **最大缺口**。渲染是全系统最贵最长的单任务（77 秒/720 帧，Blender 时代 600 秒） |
| F5 | 逻辑回滚（撤销一批生成） | `restore_revision` 回滚图结构 | **裂缝：资产不回退**。restore 后 `output_asset_id` 仍指向新版本产物——"回到过去的画布引用着来自未来的产物" |
| F6 | 整机/磁盘损失 | 一次性迁移备份（不适用） | 无周期备份/PITR；`data/` 资产与 DB 的一致性窗口靠两阶段提交 intent 检测，但无演练 |
| F7 | 隔离服务随会话死亡（实机演示教训：429 断会话连带服务死） | dev-up.sh 手工幂等重启 + 启动触发器自动 resume | 恢复是人肉三步：重启服务 → 确认触发器 → 验画布；无一键复活 |
| F8 | 前端崩溃/断网丢编辑 | localStorage 草稿（scene3d） | 画布视口/面板态/未提交布局无覆盖（layout CAS 已兜底并发，不丢已提交的） |

---

## 4. 缺口设计探索

### 4.1 帧块级渲染 checkpoint（对 F4，预期收益最大）

**命题：checkpoint 单位应是"帧序列"，不是"编码后视频"。** 原因是确定性：x264 的前视量化（lookahead）跨段边界，分段编码再 concat 在拼接处可能产生帧级亮度差异（历史实机观测：53-89 帧 61dB 差异即前视量化噪声）。要做字节级可续渲染，中间产物必须无跨块依赖。

**方案**：
1. 渲染通道按 chunk（如 120 帧）落**帧序列**（PNG/无损）到 `data/assets/render-chunks/{execution_id}/{shot}/{chunk_index}/`；
2. 每段完成后原子登记到 render manifest（段→目录→帧数+sha256），幂等键 `{execution_id, shot, chunk_index}`——复用 `internal_document_checkpoint` 的幂等键模式；
3. 崩溃续跑 = 读 manifest → 跳过已完成段 → 只渲缺段 → **最后一次统一编码**；
4. 段落盘即心跳内进度上报，与 lease TTL 咬合（渲一段远小于 TTL，不再有"长任务喂狗"问题）。

**取舍**：720 帧 PNG 的 IO 与磁盘成本（估 720×~2MB ≈ 1.5GB/镜，需 GC 策略）；manifest 原子性要沿用备份模块已有的 tmp → fsync → `os.replace` → manifest 原语（`persistence/backup.py:41-52` 就是现成实现）。

**验证**：kill -9 at 50% → 续跑产物与一次性渲染**字节一致**（沿用白模帧差异判定的验收口径）；GC 不删活动 execution 的段。

### 4.2 执行事件日志 execution journal（对 F1-F3 的可观测性升级）

**现状问题**：L3 是"状态字段 + 各类快照"，恢复后能跑，但"**为什么**在这个状态"不可考——实机排障只能翻日志文件。

**方案**：member 状态迁移追加式事件表（`state_from/state_to/reason/ts/payload_digest`），恢复时重放重建状态；周期性落 state snapshot 作重放截断点。与 backlog B2-4（执行数据钉节点）共享同一数据源。

**取舍**：写放大（每迁移一行）；迁移路径需双写灰度（先双写、读侧切换、再停旧字段）。若判断节点执行量级不足以养 journal，可降级为"只在异常迁移（recovering/retry/lease 夺回）时记事件"的**异常日志表**——成本 1/10，保留 80% 排障价值。**推荐降级版起步。**

### 4.3 工作流时间旅行：checkpoint 三元组（对 F5）

**命题：真正的"回到过去" = (workflow_revision, 资产版本 pin 集, 执行状态)。** 现状只恢复第一元。

**方案**：
1. `restore_revision()` 时同步生成"资产 pin manifest"（node_id → 当时引用的 asset_version_id），节点读输出时优先走 pin；
2. 被 pin 的版本进 GC 豁免名单；
3. 两个 checkpoint 入口：作者手动"命名 checkpoint"；自动 checkpoint 钩在危险操作前（批量跑 `agent_canvas_automatic_run_commands` 入口、模板应用）。

**取舍**：pin manifest 与现有 `output_asset_id` 直读的关系要明确（建议 pin 只覆盖 restore 派生出的 revision，活在 revisions 上不新增表）；UI 深度限制（只 pin 最近 N 个 checkpoint）控制 GC 压力。

### 4.4 DB 周期备份与恢复演练（对 F6）

**方案**：`VACUUM INTO` 定期快照（复用 backup.py 的验证+manifest 模式，扩展为按日期滚动 N 份）起步；量级上来再评估 litestream（WAL 流复制）。**恢复顺序固定**：先资产对象（不可变、可并行复制）→ DB → 启动触发器收敛。孤立 intent（有 intent 无回执）按 expected_storage_key+sha256 校验后补交或废弃——两阶段提交已自带检测手段，缺的是把这套写成**恢复演练脚本**并进 CI。

### 4.5 演示环境一键复活（对 F7）✅ 已实施（2026-10-11）

**方案**：`scripts/dev-up.sh --resume` = 幂等拉起三服务 → 轮询 backend 健康至多 90s → 打印 health JSON 与恢复说明。FastAPI lifespan 启动恢复（`main.py`：`_recover_agent_canvas_executions` + `auto_run_dispatcher.run_once()` + provider 轮询循环）本来就是自动的，命令的职责是给出"恢复已发生"的证据；超时非零退出并指向日志。**未实机验证**（本机未起服务），下次服务重启时顺手验一次。

### 4.6 前端会话快照（对 F8，小）

视口/面板开关/未提交布局 → localStorage（复制 scene3dDraft 模式）。与 F6 类似的恢复顺序原则：本地态永远可弃，服务端态是真相源。

---

## 5. 推荐分期

| 期 | 内容 | 理由 | 验证 |
|---|---|---|---|
| 一（止血） | §4.5 一键复活 + §4.4 备份脚本与演练 | 演示可靠性；半天级 | kill 主进程 → 一键复活 → 触发器报告零 orphan |
| 二（最大杠杆） | §4.1 帧块 checkpoint | 渲染是最贵任务，重试从分钟级降为秒级 | kill -9 at 50% → 字节一致续渲 |
| 三（体验） | §4.3 时间旅行 + §4.2 异常事件表（降级版） | 解锁"撤销一批生成"与排障 | restore 后画布引用 pin 版本；recovering 迁移可在表里查到 |
| 持续 | 每期附带 chaos 用例进 CI | 恢复逻辑不演练等于没有 | 对应 kill 点位的回归脚本 |

## 6. 开放问题（需拍板）

1. 帧序列 checkpoint 的磁盘成本（~1.5GB/镜）可接受吗？还是接受"短 GOP 分段 + overlap 编码"的轻微不一致换空间？
2. 时间旅行 pin 的深度限制与 GC 豁免策略（最近 N 个 checkpoint？按名字豁免？）。
3. §4.2 是否值得全量 journal，还是同意从"异常事件表"降级版起步？
4. SQLite 的长期去留：若切 Postgres，§4.4 大半变成原生能力，先别过度投入。
