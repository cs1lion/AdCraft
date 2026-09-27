# ADR 0011: 角色外观契约——资产是真相源，预演是不得编造的代理

## Status

Proposed（2026-09-27）。等待资产/素材管线 owner 确认"结构化色板由谁落库"后转 Accepted。
本 ADR 由 V0.2 §5 Continuity State 的**服装维度**触发——该维度此前留下半句"需要资产层的
结构化外观契约（ADR 级）"，本 ADR 即那一句的记录与决策形状。

## Context

V0.2 §5 把服装列为连续态的一个维度，并给出失败样例："同一个角色在两场里换了装"。
该维度在工程上被拆成两半，两半的成熟度不同：

* **可算的一半已落地**（本会话 2026-09-27）：
  - 场景内结构性安全——一个 `SceneCharacter` 只有一个 `appearance`，所以
    "Scene 02 把她换成黑风衣"在单份脚本里无法被 author；
  - 跨节点由 `wardrobe_drift.check_cross_node_character_drift` 比对同一
    `character_asset_id` 的外观色、绑定冲突，以及**声明的色板**漂移
    （`character_palette_drift`）。
* **"怎么声明"已落地**：`CharacterAppearance.palette`（1–4 hex、可选、加性）+
  3D 检查器的「服装色板」字段（`setCharacterPalette`），作者可以写下"她本来穿什么"。
* **资产侧仍是自由文本**：`CharacterDesignAssetContentV2`
  （`apps/api/app/schemas/agent_canvas_ad_media.py`）的 `wardrobe` /
  `face_and_hair` 是描述性文字；`CharacterMainRoleBriefV2` 同样只有
  `wardrobe` 自由文本。于是"预演声明的色板"与"资产声明的色板"之间**没有桥**。

### 为什么这块必须 ADR 而不是又一条 if

缺的不是字段，是**所有权**：色板由谁写、写在哪个层、谁有权改、下游谁消费。
三处都是不同上下文（角色生成 LLM / 素材资产库 / 3D 预演），任何一处单方面拍板都会让
另外两处产生第二份真相。

### 用户诉求（文档原话）

§5 的表格要求服装"继续继承"，§14.7 要求"改一句话/换一个词只重新生成对应 Audio Event"
——两侧的共同前提是：**角色的外观是一个可引用的事实，不是每个节点各自的描述**。

## 现有代码事实（扩展点，必须复用）

| 事实 | 位置 | 对本决策的意义 |
|---|---|---|
| `CharacterAppearance.palette` 已存在 | `app/schemas/scene_script.py` | 声明侧的 schema 不必再议；争议只在"资产侧同一事实放哪" |
| 跨节点看门已存在 | `app/services/scene3d/wardrobe_drift.py` | 消费方已有入口，新增资产侧比对是在同一函数里加一条 finding |
| 执行器已能读同工作流所有 scene-3d 脚本 | `_read_sibling_scene_scripts`（`agent_canvas_node_execution.py`） | 若真相源放**节点**，消费方零新增管道 |
| 角色设计内容经 `CharacterMaterializationResultV1.structured_content` 流动 | `app/schemas/agent_canvas_materialization.py` | 见下方"未解决项"——这是它**没有**落到资产库的证据 |
| `V2AssetLibraryRepository` 不保存结构化内容 | `app/persistence/asset_library_repository.py`（无 `structured_content`） | 真相源放**资产库**需要一次持久化扩展，跨管线 |
| 前端角色资产来自 `workflow.assets` | `AgentCanvasInlineWorkbench.tsx` 的 `characterAssetOptions` | `ProjectAssetSummaryV2` 无结构化内容 ⇒ 前端今天拿不到资产色板 |

## 设计决策

### 1. 资产是真相源，预演是代理，代理不得编造

预演（低精度多边形 + 单色）是**替代品**：它替观众/替下游视频模型指代这个角色。代理自己
发明一套颜色，等于在资产绑定唯一要钉住的事实上撒谎。因此：

* 资产声明的色板是**被继承**的对象；
* 预演声明的色板是**对资产色板的一次指代**，不是独立创作。

### 2. 由作者填，不由程序从图里取

曾考虑从角色设计参考图算主色（PIL/numpy 在 API 侧可用，`cv2` 也在）。否决：算出来的
"主色"是统计量，不是衣着事实——一张三视图里包含背景、皮肤、头发、服装，程序无法指认
哪一块是"黑色风衣"。作者在图旁边选色是最可靠的信号，且与既有检查器字段一致。

### 3. 声明侧的兼容规则（已随落地确定）

* 可选、加性：没有色板的旧脚本/旧资产行为逐字节不变；
* 宽容：非 hex/空/超长的条目被丢弃并给理由，不让整场失败（与 `color` 字段同策略）；
* 全角括号 `（…）` 不当作歧义——那是作者既有写法，不是 provider 的注释语法。

### 4. 消费侧的两级降险（已落地 + 本 ADR 的开放项）

* **已落地**：跨节点比对同一资产的声明色板（`character_palette_drift`）——
  两场对"她穿什么"说法不一致即 advisory；
* **开放项**：单节点内比对"预演声明色板 ↔ 资产声明色板"。之所以开放，是因为消费方
  必须先能读到资产侧色板，而那需要下面"未解决项"的拍板。

### 5. 判定语气沿用仓库规矩

advisory 不阻断；唯一允许 FAIL 的是"确定的坏"（例如声明色板与资产色板完全不相交且
角色已绑定该资产——指代关系已断）。其余一律 warn + remedy。

## 未解决项（等 owner 拍板）

**结构化色板落在哪一层？** 两条路，代价与 owner 都不同：

| 方案 | 落点 | 消费方改动 | 代价 |
|---|---|---|---|
| A. 资产库扩展 | `AssetVersionMetadataV2` / 新表存 `structured_content` | 资产库 + 前端 `ProjectAssetSummaryV2` + 工作台取数 | 跨素材管线持久化，需其 owner |
| B. 节点内容即桥 | character-design 节点的 `structured_content`（今天已有） | 执行器 `_read_sibling_scene_scripts` 同款读法多读一类节点 | 小，但把"角色身份事实"寄存在画布节点上，节点被删即失 |

两条路都可行；**推荐 B 作为过渡、A 作为终点**——B 不阻塞施工且立刻可用，A 才是身份
事实的应有归宿。本 ADR 不替素材管线 owner 选 A 的排期。

## 与现有架构的兼容性

* 完全加性：所有新字段 Optional，旧 payload 不变；
* 与 ADR 0009（节点域意图隔离）不冲突：色板是角色身份属性，不是节点意图；
* 与 ADR 0005 §5（Continuity State）的关系：本 ADR 是 0005 服装维度"可算部分"的
  资产侧续篇，实施状态写在这里，避免 0005 越写越长。

## 风险与缓解

| 风险 | 缓解 |
|---|---|
| 两处真相（资产色板 vs 预演色板）再次分裂 | 消费侧只做 advisory；真相源明确为资产，预演侧字段在文档与 UI 上都标注为"指代" |
| 作者不填色板，功能空转 | 空声明 = "还没决定"，看门跳过而非误报；检查器提示说明留空的含义 |
| 取色方案被误用为"自动继承" | 决策 2 明确否决从图取色；若日后再提，需连同"如何指认衣着区域"一起论证 |

## 实施状态（2026-09-27 更新：B 路径已实施）

### 接手会话（2026-09-27 同日）新增
- 单句重合成端点 `POST /scene-3d/voice-cast-resynth-line` 落地（交接文档「二.3」）
- 跨会话保留集 `TransitionProposalsRequest.retained_reading_ids` 落地（交接文档「二.4」）

* **B 路径（节点即桥）已落地**：`CharacterDesignAssetContentV2.appearance_palette` +
  `CharacterMainRoleBriefV2` / `CharacterIdentityAuthorityProjectionV1` 的同名字段（色板随身份走，
  turnaround 不得声明第二套衣服）+ 编译器两分支映射 + 确定性 fixture 不发明色板 +
  执行器 `_read_sibling_character_palettes`（资产库无结构化内容 ⇒ 桥是产出该资产的
  character-design 节点：`output_asset_id` ↔ 节点 structured_content，零新增管道）
* **消费侧已落地**：`wardrobe_drift` 新增 `character_palette_vs_asset_drift`——资产声明与预演
  穿着不相交才报（60 RGB 容差内同色；资产未声明跳过；未绑角色不在范围）。该检查**单节点即成立**，
  因此置于多节点早退守卫之前（否则单场工作流——最常见的审片场景——永远不跑）
* 仍开放：A 路径（资产库持久化）作为终点的排期，需素材管线 owner；B 到 A 迁移时只需改
  `_read_sibling_character_palettes` 的取数来源，看门判定不变
* 已落地：`CharacterAppearance.palette`、`setCharacterPalette`、3D 检查器「服装色板」字段、
  `character_palette_drift` 跨节点看门、`SceneShot.transition_intent` 与 `intent_audit`
  （§13 第 5 问的"标签"答复）。
* 未落地：上表"未解决项"（资产侧结构化色板的落点与消费）。
* 若最终不决策：已落地部分仍独立成立——作者能声明、跨节点能比对，文档 §5 的失败样例
  （两场换装）已有可算内核。
