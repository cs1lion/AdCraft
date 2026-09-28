# ADR 0011: 角色外观契约——资产是真相源，预演是不得编造的代理

## Status

**B 路径：Accepted（2026-09-27 落地）**；**A 路径：Proposed（2026-09-28）**。
B 路径（character-design 节点 `output_asset_id` ↔ 其 `structured_content.appearance_palette`
即桥）已实现：`agent_canvas_node_execution._read_sibling_character_palettes` +
`wardrobe_drift.check_cross_node_character_drift(asset_palettes=...)` +
`character_palette_vs_asset_drift` 看门。A 路径（资产库持久化
`AssetVersionMetadataV2.structured_content`）为 Proposed：落点与读侧参考实现已逐行核对并记录在
下方「Path A 实施草案（读侧参考实现，不迁移写侧）」，但 schema/迁移/写侧改动与排期仍等素材管线
owner 拍板（见该节末尾的决策项）。本 ADR 由 V0.2 §5 Continuity State 的**服装维度**触发——该维度
此前留下半句"需要资产层的结构化外观契约（ADR 级）"，本 ADR 即那一句的记录与决策形状。

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

## Path A 实施草案（读侧参考实现，不迁移写侧）

> 2026-09-28。本节是 A 路径的**规格与读侧参考实现**，不是实施许可：写侧/持久化的任何改动归
> 素材管线 owner（见文末决策项）。本节所有落点结论都已对着
> `app/schemas/v2_asset_library.py` 与 `app/persistence/asset_library_repository.py` 逐行核对。

### A.1 落点判定：`structured_content` 今天能落在哪、读侧怎么拿到它

`app/schemas/v2_asset_library.py` 里描述"一个不可变版本"的只有一对类：`AssetVersionCreate`（写）
与 `AssetVersionMetadataV2`（读）。两者都继承 `_AssetLibraryModel`（`extra="forbid"` +
`frozen=True`），且**今天都没有 `structured_content` 字段**——这正是 B 路径存在的原因。该文件
已占用的自由 JSON 槽只有两个（列名见 `app/persistence/models.py` 的 `AssetVersionRow`）：

| 现有字段 | 对应列 | 现状 |
|---|---|---|
| `AssetVersionCreate.metadata` / `AssetVersionMetadataV2.metadata` | `asset_versions.metadata_json` | 已被 `workflow_asset_version` 投影占用，且 `mark_version_unavailable` 会原地改写它 |
| `AssetVersionCreate.quality` / `AssetVersionMetadataV2.quality` | `asset_versions.quality_json` | 技术质量用 |

读侧是**逐列枚举**的，这是最容易被漏的一处：`asset_library_repository.py` 的 `_version_select()`
显式列出列（没有 `select(AssetVersionRow)`），`_version_from_row()` 按这组固定 key 构造
`AssetVersionMetadataV2`。因此"加一列却不同改这两处"= 对所有读方不可见：`resolve_versions`、
`find_version`、`find_latest_ready_versions`、`find_versions_by_id`、`list_versions_for_slot`、
`list_versions_for_workflow`、`_get_version`，以及 `AssetEntityMemberV2.version`
（`get_entity` / `AssetLibraryEntityDetailV2` 这条线）会一起失明。

所以 A 路径唯一不 Invent 新概念的位置是：`asset_versions` 上一个 nullable 的
`structured_content_json` 列，经 `AssetVersionCreate.structured_content` →
`AssetVersionMetadataV2.structured_content` 这一对（与其他版本字段同款）投影，再用**已存在**的
`V2AssetLibraryRepository.find_latest_ready_versions(asset_ids)` 读出（一次有界查询、不碰文件
系统、同一资产的最新 `ready` 版本才是"它现在穿什么"）。前端侧唯一出口是
`app/schemas/agent_canvas.py` 的 `ProjectAssetV2`（`ProjectAssetSummaryV2 = ProjectAssetV2`）：
它今天只有 `prompt_provenance` / `actual_media_facts` / `generation_provenance` / `quality_metadata`
四个 `dict[str, JsonValue]` 透传槽，**没有结构化内容专属字段**——"前端今天拿不到资产色板"这件事
在 schema 上是可见的，不是猜的。

### A.2 Schema / 持久化 delta（精确到字段名与类型）

**1. `app/schemas/v2_asset_library.py`**（两处，紧邻 `quality` 同款形状）

* 写侧模型 `AssetVersionCreate`：`structured_content: dict[str, JsonValue] | None = None`
  （没有色板声明的旧版本写 NULL——可选、加性）
* 读侧模型 `AssetVersionMetadataV2`：`structured_content: dict[str, JsonValue] | None = None`
  （类保持 `frozen=True`：调用方无法原地改返回的 payload）
* 不动 `AssetEntityMemberCreate` / `AssetEntityMemberV2`：色板是**版本**属性，不是成员关系
  属性；fork（`derived_from_entity_id`）只能靠 pin 到哪个版本来继承外观，而不是在成员行上再抄
  一份。

**2. `app/persistence/models.py`**：

```python
AssetVersionRow.structured_content_json: Mapped[str | None] = mapped_column(Text)
```

（与 `quality_json` 同款 nullable Text；表名 `asset_versions`）

**3. `app/persistence/asset_library_repository.py`**（读侧，本草案范围内）：

* `_version_select()`：加 `AssetVersionRow.structured_content_json`
* `_version_from_row()`：
  `structured_content=_json_object(str(row["structured_content_json"])) if row["structured_content_json"] is not None else None`
  （与 `quality` 同 guard；`_json_object` 已在脏 payload 上抛
  `V2PersistenceError("asset_library_metadata_invalid", ...)`）
* 写侧三处——`_create_asset_version_in_transaction` 的 `insert(...)` 字面量、
  `_import_asset_version_in_transaction` 的 `update(...)` 值、`mark_version_unavailable` 的
  `values(...)`——**在本草案范围之外**，归 owner。不写这三处，新读侧字段恒为 `None`：
  也就是说 B→A 迁移本质是一次"取数来源"的开关切换，不是看门重写。

**4. 迁移**

* 新 revision 沿用仓库现有格式，`20260928_01_add_asset_version_structured_content.py`，
  `revision = "20260928_01"`、`down_revision = "20260927_01"`（当前 head），
  `op.batch_alter_table("asset_versions")` + `batch.add_column(sa.Column("structured_content_json", sa.Text(), nullable=True))`，
  直接照抄 `20260915_02` 的写法。
* 只加 nullable 列，**不 backfill 历史版本**：历史资产"没声明"是"还没决定"，不是数据缺陷。
* `app/persistence/schema.py` 的 `verify_v2_schema` 会拿 models 与 alembic head 对账：模型加了列
  而没有迁移 = drift，启动即失败（这是仓库故意设计的早失败，别绕过它）。
* 落库顺序沿用 `20260927_01` 的教训（迁移漏了，旧库 CHECK 直接拒写）：先 migration，后 schema
  字段，后 repository 读侧，最后才切来源。

### A.3 读侧参考实现（签名 + docstring，不含实现）

```python
def read_declared_appearance_palettes(
    asset_ids: Sequence[str],
    *,
    repository: V2AssetLibraryRepository,
) -> dict[str, list[str]]:
    """每个角色资产**声明**的服装色板（ADR 0011，Path A）。

    输入是场景脚本绑定的 character asset id；输出是 asset id → 1–4 个规范化
    （大写、`#` 前缀、保序去重）hex。取数来自资产库的
    ``AssetVersionMetadataV2.structured_content``，经
    ``repository.find_latest_ready_versions`` 一次有界查询读出：同一资产的最新
    ``ready`` 版本才是"它现在穿什么"。

    资产**没有**声明时，该 asset id 不出现在返回映射里：未声明 = "还没决定"，
    调用方据此跳过，而不是发明一个颜色。任何读取失败都降级为空映射，并让调用方
    可查询地说明"为什么本次没跑"（ADR 决策 5 的语气）；本函数绝不把异常抛给看门。

    B→A 迁移时**只改这一个函数**：今天它在 character-design 节点的
    ``structured_content`` 里读（``_read_sibling_character_palettes``），Path A
    落地后改读资产库；``wardrobe_drift.check_cross_node_character_drift`` 的签名
    与 ``character_palette_vs_asset_drift`` 判定一字不改。
    """
```

### A.4 什么必须不变

* **写/持久化路径**：不加列、不写 insert/update 值、不改 `metadata_json` 既有键、不动
  result-commit 权威。本 ADR 这节不授权任何写侧改动。
* **看门**：`check_cross_node_character_drift` 的签名、`character_palette_vs_asset_drift` 的成立
  条件（`PALETTE_MATCH_TOLERANCE = 60.0` 内同色、资产未声明即跳过、未绑角色不在范围）与它置于
  `len(scripts_by_node) < 2` 早退**之前**的位置。
* **声明侧**：`CharacterDesignAssetContentV2.appearance_palette`（B 路径的产出字段）与
  `CharacterAppearance.palette`（预演侧字段）都保持原样——A 不是第三份色板字段，只是同一事实的
  新存储归属。
* **产出侧**：`CharacterMaterializationResultV1.structured_content` 原地不动；A 只决定它落到
  **哪里**，不改变它是什么。
* **不可变版本**：历史行不得回填色板；换装 = 新版本（`parent_version_id` 接续），与 `version_no`
  的单向性一致。
* **契约形状**：`_AssetLibraryModel` 的 `extra="forbid"` / `frozen=True`；所有新字段 Optional。
* **语气**：仍是 advisory；决策 5 里唯一允许 FAIL 的形状不变。

### A.5 等 owner 拍板的决策（两个选项及其后果）

**问题：结构化外观色板在资产库里放在哪种"家"里？**

* **选项 1（推荐）：专门的列 + 类型化字段**——`asset_versions.structured_content_json` ↔
  `AssetVersionCreate.structured_content` / `AssetVersionMetadataV2.structured_content`。
  **后果**：色板成为资产库里的一等公民，写入即经 pydantic 校验（`extra="forbid"` 会当场拒掉
  形状不对的 payload），可加 schema 级约束与索引，与"资产是真相源"的定位一致，前端也能拿到一个
  有名字的字段；代价是一次 alembic 迁移 + 写侧三处 + `verify_v2_schema` 对账，跨素材管线，
  需要 owner 排期。
* **选项 2（零迁移的退路）：塞进既有的 `metadata_json`**——例如
  `AssetVersionCreate.metadata["appearance_palette"]`，读侧 `_version_select()` 一字不改。
  **后果**：今天就能落地、无迁移、不被 owner 排期阻塞，预演侧看门可立即改为读资产库；代价是
  这个文件里唯一的自由 JSON 家已被 `workflow_asset_version` 投影占用、且被
  `mark_version_unavailable` 原地改写——"两处真相"的风险会从资产库里长回来，payload 也不再经
  `AssetVersionCreate` 的类型化校验（坏形状要到读侧 `_json_object` 才炸）。它还会立下先例：
  此后任何结构化内容都可以不走 schema，而这正是本 ADR 想钉住的反面。

未决策前，B 路径照常服务（已落地、零依赖 A）；一旦拍板选项 1，迁移只改 A.3 那一个函数的取数
来源，看门判定不变。

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
