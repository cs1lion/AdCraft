# ADR 0009: 节点意图隔离 — 改一个节点，不波及前后关联节点

## Status

Proposed（2026-09-26，用户提出的设计方向）。本文先固化**范围分类学与依赖模型**；实现分解在文末「实施状态」逐项登记。**2026-09-26 回填**：P0 范围报告后端已落地（见文末），UI 消费半句未做。

## Context

用户的设计诉求：**"我想单独修改某个节点的内容，做到完全不影响前后关联节点。"**

今天的现实是：画布上唯一的"生效"事件是**执行**——一次 rerun 从当前作者状态重新推导该节点的全部产物，并借 auto-clip 就地刷新它在时间线上的 clip。作者改一个角色位置后若重跑，付出的是整节点重生；更要紧的是，**系统从不告诉作者"你这一改影响了谁"**——上下游要么被静默重算，要么被静默保留，两种都让画布像一条脆弱的流水线，而不是可编辑的创作空间（V0.2 §10 的三层模型要求"用户表达意图"与"系统执行指令"可分离；§14.12 要求局部重做不破坏未修改部分）。

已存在的正确零件（本 ADR 不重建它们，只把它们接成契约）：

| 零件 | 位置 | 它已经保证 |
|---|---|---|
| patch 拒写输出态 | `CanvasNodePatchRequestV2` | 作者侧写不进去 `output_asset_id`——输出只能由执行路径产生 |
| binding 只消费 output | `CanvasBindingSourceNodeV2.source_node_id` | 下游结构性消费的是**产物**，从不是 `structured_content` |
| structured_content 合并语义 | `patch_node`（scene-3d 存活验证） | 补丁是 merge 不是 replace，其他键存活 |
| 作者态与节点态分离 | 3D 编辑器 dirty/save/revert | 草稿可反复改，保存才落节点 |
| 唇形显式重应用 | `DialogueLipSyncPanel` | 改台词 ≠ 自动重算口型，作者点"应用"才同步 |
| 字幕幂等替换 | `publishSubtitleCues` | 重发布=替换本节点此前 cues，不堆叠 |

**结论性观察：数据层的隔离其实已经成立**（补丁写不到输出、绑定只读输出）。缺的是三件事：**把隔离说出来的 UX 契约**、**跨节点的陈旧标记**、**以及区分"内容编辑"与"结构编辑"的显式规则**。

## Decisions

### 1. 节点内容分三类，只有第三类会波及邻居

```
AUTHORING（作者态）  generation_prompt / structured_content / parameters /
                     metadata / title / intent_hint / model_*
   └─ 编辑 = 草稿变更。无人结构性消费（binding 只读 output）。邻居零影响。
      影响的是"下一次执行会产出什么"——这恰恰是作者意图本身。

OUTPUT（产物态）     output_asset_id / output_asset_version_id
   └─ 只能由执行路径改变。它的改变才是跨节点事件。

EXECUTION（执行态）  status / latest_attempt / error / revision
   └─ 执行的过程与结果记录，不参与隔离判断。
```

**规则 1（内容隔离）**：AUTHORING 字段的任何补丁**不得**触发任何邻居的重算、重渲染或重生成。它只把本节点标为「有未同步的作者修改」（见决策 3）。

**规则 2（唯一的跨节点事件是产物变更）**：OUTPUT 改变（且仅此）才让绑定了它的下游进入陈旧态（见决策 4）。上游 rerun 后下游**不被自动重跑**——V0.2 的审片循环里"什么时候再生成"是作者的决定，不是系统的。

**规则 3（结构编辑单独一类，允许波及但必须可见）**：以下编辑**确实**改变下游将看到的东西，它们不享受内容隔离，但必须产生可查询的陈旧条目与补救：

| 结构编辑 | 波及谁 | 为什么 |
|---|---|---|
| 增删改 binding（source/target/input_role/enabled） | 该 consumer | 它下次执行的输入集变了 |
| 改 timeline clip 的时间窗 | 该窗的 video 节点 | 它的参考切片是为旧窗算的（ADR 0008 §3） |
| 删除节点 / 断边 | 其 consumers | 输入消失（既有孤儿检测覆盖） |
| 改 scene-3d 的角色 id | 绑定/唇形/字幕 cue 的引用方 | id 是跨节点引用的键 |

### 2. 补丁 API 的范围语义：声明式，不是猜测式

`PATCH /nodes/{id}` 的响应必须回答**作者真正在问的问题**："我这一改，影响了什么？" 响应携带 `scope_report`：

```json
{
  "scope_report": {
    "edited_keys": ["structured_content.scene_script.characters[0].keyframes"],
    "affected_neighbours": [],
    "node_dirty": true,
    "dirty_reasons": ["场景脚本有 3 处作者修改未执行"],
    "notes": ["本次编辑不影响任何已绑定节点；下次执行时生效。"]
  }
}
```

- `affected_neighbours` 为空的**含义必须被UI明说**（"未动：其余镜头与时间线"），而不是留白——留白会被读成"系统没算"。
- 编辑落在 OUTPUT 字段上时，补丁**拒绝**（既有 schema 已无此字段；新增的 endpoints 不得开口子）。
- `structured_content` 继续 merge 语义；补丁里的每个键标 `added/updated/removed`，让"你到底改了什么"可回答（V0.2 §10：系统要让用户看见"我理解你的意思是……"）。

### 3. 节点级 dirty：作者态与产物态的分界，从 3D 编辑器推广到所有节点

3D 编辑器早已有 dirty/save/revert——本 ADR 把它**推广为节点级契约**：任何 AUTHORING 补丁后，节点带 `authoring_dirty`（含 reasons 与 changed key 列表）；执行成功后清除。UI 上节点卡显示未同步徽章，与既有的"已保存/有未保存修改"同义。

**这不是给作者添麻烦，是给作者确定性**：它把"我改了但还没让整条链知道"变成一个显式状态，而不是一次 rerun 的隐性代价。

### 4. 陈旧标记：带原因、带旧版本、带一键补救，且永不自动销毁

OUTPUT 变更时， consumers 获得 `stale_dependencies` 条目：

```json
{
  "stale_dependencies": [{
    "source_node_id": "scene-node-1",
    "input_role": "video_reference",
    "consumed_version": "ver_9",
    "current_version": "ver_12",
    "remedy": "re-run"
  }]
}
```

- **remedy 是一键重跑该 consumer 自己**，不是重跑链路；更不是自动重跑。
- 陈旧 ≠ 失效：旧产物仍在，作者可以带着旧参考继续审片，想同步时再同步。删除/覆盖永远由作者触发。
- 这与唇形的显式重应用、字幕的幂等替换是同一原则在不同层的贯彻：**局部同步由作者触发，系统只负责把"哪里陈旧、旧的是哪个版本、怎么补"说清楚**。

### 5. 与时间线双相（ADR 0008）的接法

导演态 clip 携带的时间窗与参考切片引用，就是 AUTHORING 状态的时间线投影：改窗（结构编辑，规则 3）→ 该 video 节点陈旧，remedy 是重新切片+重跑；改 scene 的角色位置（内容编辑，规则 1）→ 邻居零影响，只有该 scene 节点自己变 dirty。两条规则在同一面板上可同时成立，因为它们本就分类不同。

## 与既有 ADR 的关系

- **不改写 ADR 0007**：时间线仍是编排层；节点仍是生成单位。本 ADR 补充的是"作者编辑的作用域语义"。
- **不改写 ADR 0008**：双相时间线不变。本 ADR 为它提供规则 2/3 的分类依据（窗=结构，内容=局部）。
- **延伸 ADR 0005**：SceneScript 是事实源的立场不变；本 ADR 声明"改 SceneScript 是 AUTHORING 编辑，其隔离性由 binding 只读 output 保证"。

## Withdrawn candidates（如实记录）

- **每次编辑自动重跑下游消费者。** 这正是用户要消除的级联；且昂贵、摧毁审片控制权（V0.2：Preview→修改→再 Preview，何时再生成是作者的决定）。
- **编辑即分叉（不可变节点，每次编辑生成新节点）。** 与"就地编辑"的作者预期冲突（3D 编辑器的 dirty/save/revert 已是正确隐喻），并让画布迅速爆炸；分叉仍是显式操作（V0.2 §13），不是编辑的副产品。
- **工作流级全局 dirty 标记。** 粒度过粗——作者需要的是"哪个节点、哪几个键、影响了谁"的节点级真相。
- **为隔离新建节点副本/快照表。** OUTPUT 已有 `output_asset_version_id` 可作版本锚点；再建副本表只会产生双源一致性负担（同 ADR 0008 放弃独立导演表的理由）。

## 实施状态

已在位（本 ADR 接管的既有零件）：patch 拒写 output ✓ · binding 只读 output ✓ · merge 补丁 ✓ · 3D 编辑器 dirty ✓ · 唇形显式重应用 ✓ · 字幕幂等替换 ✓

待建（按依赖顺序，各带验收）：

- [~] **P0 范围报告**（2026-09-26：**前后端均已落地**）——后端 `build_patch_scope_report` + 响应字段；前端 `patchScopeReport` store + `PatchScopeNote`（共享工作台外壳，所有节点类型），"未影响其他节点"这个空 case 是大声的那个。**同回合修一个契约层缺陷**：web 归一化器的未知字段白名单原本不含 `scope_report`（`forbidUnknownFields` 会 throw），答案曾死在 API client；客户端测试 mock 已改为后端真实形状：`app/services/agent_canvas_scope_report.py`（`build_patch_scope_report`）+ patch 响应 `scope_report` 字段（`schemas/agent_canvas.py:498`，经 `agent_canvas.py:2447` 接线）已在位，9 项测试锁定（`tests/test_agent_canvas_scope_report.py` + `test_agent_canvas_patch_scope_endpoint.py`）：AUTHORING 补丁 → `affected_neighbours == []` 且 diff 出 edited_keys；补丁字段登记表（`AUTHORING_PATCH_FIELDS`）保证新字段必须显式分类才能继承"local"。**剩余的是本 ADR 要求的那半句 UI**：前端无任何 `scope_report` 消费者——"未动：其余镜头与时间线"这句话还没有被说出来（节点卡/工作台消费 pending）。验收中"改 binding → consumer 出现在列表"一项按登记表设计成立，但同样缺 UI 呈现。
- [ ] **P1 节点级 authoring_dirty**：AUTHORING 补丁置脏（reasons + changed keys），执行成功清除；节点卡徽章。验收：改台词不执行 → 徽章常驻且写明"有未同步的作者修改"；执行后消失。
- [ ] **P2 stale_dependencies 账本**：OUTPUT 变更时给 consumers 写条目（source/role/consumed_version/current_version/remedy），consumer 工作台显示一键重跑。验收：scene 重跑后 video 节点带陈旧条目与"重新切片并重跑"按钮，且**不自动重跑**。
- [ ] **P3 结构编辑的可见波及**：binding/窗/节点删除的编辑产生同款陈旧条目（规则 3 表逐行落地），删除节点的孤儿提示并入同一账本。
- [ ] **P4 回归锁**：一条集成测试固定三条不变量——① AUTHORING 补丁不产生任何邻居状态变化；② OUTPUT 变更不触发任何自动重跑；③ 结构编辑必须产生可查询的波及条目（无静默）。
