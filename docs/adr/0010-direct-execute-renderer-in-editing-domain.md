# ADR 0010: direct-execute 渲染器归属剪辑域 — 接口契约与分期

## Status

Proposed（2026-09-27）。等待剪辑域（editing/时间线）owner 确认排期后转 Accepted。
本 ADR 由拉片复刻路线图 P3 项"direct-execute 快车道"的**可行性门交付**触发
（`services/replica/direct_execute.py` + `POST /replica/blueprint/direct-execute-plan`），
用于回答渲染器本体"谁做、接口是什么、按什么顺序做"。

## Context

拉片复刻路线图（`docs/plans/replica-teardown.md` §11）P3 项要求："纯字幕/MG 短片
不调生成模型直出（hypit 无头 Chromium 同款）"。已交付的可行性门把蓝图确定性地
分类为零模型费环节与必须生成环节：

- **零模型费**：纯屏上文字镜头（字幕渲染）、音效库、BGM 库、剪辑合成；
- **必须生成**：有画面主体的镜头、TTS 语音、已应用的主体替换。

可行性门只有判定没有执行。渲染器本体的归属受三条既有约束：

1. **§3.5 编译边界**（调研档）：`.adreplica`/蓝图只编译到画布节点，
   "SVML 管创作期，引擎管执行期"——不建第二执行链；
2. **ADR 0008**：时间线是一条时间线的两个相位，组装走 editing 节点的
   ffmpeg 链路；
3. **工程标准 §6**：跨域决策进 ADR，不静默越界。

结论：直出渲染器**不能落在拉片复刻域**（那就是第二执行链），必须归属剪辑域，
复用 ADR 0008 Phase 2 的组装链路。缺的是把"可行性门 → 剪辑域执行"的接口
契约与分期写清楚——即本 ADR。

## Decisions

### 1. 渲染器归属剪辑域，作为 editing 组装链路的一个入口

不新建执行引擎。零模型费直出 = ADR 0008 Phase 2 组装的一个特例：
所有 clip 的媒体都是**库素材 + 字幕渲染帧**，无生成模型参与。

### 2. 接口契约（复刻域 → 剪辑域）

**输入**（复刻域已交付、结构化、无 LLM）：

- `DirectExecutePlan`（`feasible` / `zero_model_steps` / `generation_steps` /
  `blockers`）——可行性门判定；
- `ReplicaBlueprintContentV2`——shots（含纯屏上文字镜头的 `on_screen_text`
  与时间窗）、beats（`line` 台词 → 字幕内容）、systems（captions/sfx/music）。

**输出**：editing 域组装清单（clip intent 相位）——字幕渲染步骤
（drawtext/字幕轨）、音效/BGM 库选段、时间窗拼接参数。**不做**复刻域内
直接输出 MP4。

### 3. 分期

- **R1 字幕轨直出**：仅含纯屏上文字镜头的 feasible 蓝图 → drawtext 帧 +
  音效库 + BGM 库 → editing 组装出片；
- **R2 MG 组件**：价格贴/关键词高亮等系统条目 → 与既有 MG 系统对齐；
- **R3 工作台入口**：复刻工作台「零模型费直出」按钮，仅 `feasible=true`
  时可用；non-feasible 蓝图展示缺失清单（可行性门已提供）。

### 4. 验收

- `tests/test_replica_direct_execute.py` 判定的 feasible 案例
  （纯字幕片）经剪辑域 R1 链路端到端零模型费出片（media 标记测试）；
- non-feasible 蓝图被入口拒绝并展示 blockers + generation_steps 清单。

## Consequences

- 拉片复刻域**不再实现渲染器**（可行性门即其终态），排期移交剪辑域 owner；
- R3 入口依赖 R1；多风格一键混搭应用（路线图另一剩余项）归属风格系统的
  "多 Skill 并行激活"改造，与本 ADR 无依赖关系；
- 若剪辑域排期拒绝 R1，P3 项保持"可行性门已交付"的诚实状态，不降级为
  复刻域内的临时渲染路径。
