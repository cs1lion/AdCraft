# 拉片复刻调研：Hypit 机制研究 + AdCraft 落地方案

> 调研对象：GitHub `hypit-ai/hypit`（Trendshift #1，12k+ Star，TypeScript，v0.1.x）
> 关联视频：B 站《Jev 搭配 Hypit 简直是王炸‼️》BV1fShv6yErB（Hypit 官方号，26s）
> 本文档回答四个问题：
> 1. Hypit 到底怎么工作，哪些特性值得借；
> 2. 在 AdCraft 做"拉片复刻"功能是否可行、怎么做有创意（开启按钮 / 界面 / 输入输出）；
> 3. 把视频翻译成 HTML 类语言，能否彻底替代 prompt 自然语言（优缺点）；
> 4. B 站视频里 Jev+Hypit 的做法是什么，能否给本项目赋能。

> **落地状态（2026-09-27）**：§2 的 **P0 拉片拆解 + P1 复刻半场均以"蓝图即 replica 节点"形态交付**——`POST /api/v1/replica/{teardown,blueprint,instantiate}`、`replica` 画布节点与复刻工作台（槽位替换/锚点事件/一键生成复刻工作流）。**§3.5 的 `.adreplica` 文档层亦已交付**：蓝图 ↔ `.adreplica` 标记文本双向转换（`POST /api/v1/replica/blueprint/{export,import}`，词汇表为 §3.5 草案最小实现、语法基因取自 hypit 一手样例；手改文本重编译回蓝图即回写闭环）。交付记录见 [`docs/plans/replica-teardown.md`](./replica-teardown.md)，CHANGELOG 有对应条目。**未开始**：direct-execute 渲染器本体——归属与接口已决策（[ADR 0010](../adr/0010-direct-execute-renderer-in-editing-domain.md) Proposed，剪辑域分期 R1 字幕轨直出 → R2 MG → R3 工作台入口）；源码 tab 原位高亮编辑与锚点双向跳转已交付（2026-09-27）。**2026-09-27 路线图收尾已交付**：实例化扩展（绑定自动创建 + `instantiated_script_node_id` 写回）、风格导演/变体引擎（`variants.py` 确定性打分 + `/replica/blueprint/style-variants`，组合应用待多风格激活改造——§5 风险 4）、链接下载（`/replica/ingest-link`，yt-dlp 可选依赖显式降级）、direct-execute 可行性门（`/replica/blueprint/direct-execute-plan`；渲染器属剪辑域，ADR 0008）。**WhisperX 词级锚定已交付（2026-09-27）**：参考视频 → ffmpeg 抽音轨 → whisperX 词流（`SPEECH_ALIGNMENT_ENGINE=whisperx` 启用，降级显式可查询）→ 锚点事件绑定具体词（`resolve_word_anchors` 段落窗内确定性解析）→ `.adreplica` 行内 `@{id}词@{/id}`（时间为词流派生数据，不落盘）。**前端流畅性与引导已优化（2026-09-27）**：上传时长上限 10s→60s（对齐拉片场景）、拉片秒级进度与可取消、元数据透传（时长/画幅进蓝图与 `.adreplica`）、创建后下一步引导、工作台源码 tab 与外部更新状态同步。

---

## 0. 结论速览（TL;DR）

| 问题 | 结论 |
|---|---|
| Hypit 值得借鉴吗 | **值得，而且它的 Skill 本身就是一套可迁移的"拉片方法论"**。但不要引入它的 Runtime/SVML 实现，借鉴"语义锚定 + 组件化替换 + 可编译工作流"思想，用 AdCraft 自己的画布节点体系落地 |
| 拉片复刻可行吗 | **可行，且 AdCraft 已有 60% 地基**：参考视频上传/抽帧/多模态分析（scene3d）、35 个风格 Skill、pi-coding-agent 运行时、无限画布。缺的是"结构模板"这一层中间表示和"读片→替换→生成"的产品界面 |
| 最有创意点的方案 | 把"拉片"产品化为四态工作台：**读片（逐词字幕网格+整片解读）→ 拆解（镜头表/节奏曲线/系统清单）→ 替换（槽位化组件替换：人/货/景/词/风格）→ 变体（一次 N 个风格混搭变体）**，产出直接实例化成画布工作流 |
| 内部用 SVML 描述视频？ | **建议采纳（本地化为 AdSVML），但只做"创作期文档层"，执行仍走画布引擎**。标记语言相对 JSON 的三个不可替代优势：行内词锚定、git 级 diff 编辑、单一真相源多投影。且本项目已有 coding-agent 运行时 + Agent 工作文档机制 + "一个 clip 两个相位"哲学，落地条件比一般项目好得多 |
| 标记语言能替代 prompt 吗 | **不能彻底替代，也不应该**。它覆盖"结构/时间/关系"层 100%，覆盖不了"物质层"（画面/声音仍靠 prompt）。正确姿势：AdSVML 管结构与语义锚定，prompt 退到叶子节点做素材导向——hypit 自己就是这个分工（SVML 里到处是 text:Value） |
| 能"完美移植"吗 | **不能，且要避免把完美当目标**。思想层（词锚定/组件边界/文件即真相源/swap 即 diff）可完整移植；语法对标不照抄；hypit 的组件生态（100+ 包、prompt kits、craft 文档）与运行时搬不走也不该搬。正确姿势：概念移植、形态重生 |
| SVML 能"完美覆盖"prompt 吗 | **不能**。prompt 是随机生成器的控制面，SVML 是确定性组合结构，功能位不同；信息论上无损描述视频=mp4 本身，而模型不吃帧级回放。但产品意义上"用户不看见 prompt"可以做到——SVML 是 prompt 的编译器，不是掘墓人 |
| Jev+Hypit 方案 | Jev（TypeSafe AI 的 System One 决策模型）负责"按需求给风格库打分/选择"，Hypit 负责"随机混搭风格并批量出图"。**AdCraft 有 35 个风格 Skill，正好缺一个"风格导演"**：用 Jev 式结构化判断给风格打分、混搭、做廉价质检，直接赋能"一键 100 个风格方案" |

---

## 1. Hypit 调研：它到底是什么

### 1.1 一句话定位

Hypit **不是视频生成模型，也不是网页应用**，而是给 AI Coding Agent（Claude Code / Codex 等）的一套**"视频编程语言 + 制作知识包 + 工具链"**。安装方式就说明了一切：

```bash
npx skills add hypit-ai/hypit -g
```

装完你在任意目录对 Agent 说 `/hypit Clone this video: /path/to/video.mp4`，Agent 就会：读片 → 分析 → 写成一份视频工程文件 → 调用生成服务 → 渲染成片。

### 1.2 四层架构

```
┌─ Skill 层（知识）     skills/hypit/SKILL.md + references/（约 40 篇方法论）
│    "怎么读片、怎么导演、怎么写组件"——告诉 Agent 什么是好视频
├─ 语言层（表示）       .svml（主工程）/ .svs（配方）/ .svrun（运行记录）
│    视频的"源码"：XML 风格标记语言，可 diff、可复用、可编译
├─ 工具链层（命令）     hypit 可执行程序：plan / build / render / media fetch …
│    Model/Provider 分离（GPT Image / Seedance / FishAudio / WhisperX…）
└─ 运行时层（执行）     Build 状态机（失败不重复花钱）+ 64 个无头 Chromium 并发渲染
     + Studio（浏览器里看时间线、留评论、调参数）
```

### 1.3 SVML 核心机制（本调研最重要的部分）

读了 `examples/ranking-football/reference.svml` 原文后，确认它的设计地基是两条：

**（1）素材锚定在"词"上，而不是"秒"上。** Script 里只有台词，没有时间码：

```xml
<script id="story">
  <ronaldo>
    <HOST>Ronaldo is <D | Dee> tier. || Bro has @{hair-gel} more || hair gel than @{trophy} trophies || at this point.@{/trophy}@{/hair-gel} ...
  </ronaldo>
</script>
```

`@{hair-gel}` 这种行内锚点把"什么时候出现发胶梗图"绑在**台词单词**上。WhisperX 做逐词对齐后，所有 B-roll、字幕、音效自动落在正确的时间点。**改一句台词，整条片子自动重排，其他部分原封不动。**

**（2）一切皆组件，组件可编译。** 同一份文件里：

```xml
<text:Value id="broll-trophy-prompt">A surreal comedy photograph of a monumentally oversized trophy...</text:Value>
<gpt:Image id="broll-trophy" prompt={broll-trophy-prompt} aspect-ratio="4:3" resolution="2K"/>
<seedance:ReferenceVideo id="ronaldo-take" model="mini" prompt={ronaldo-prompt} duration="10">
  <seedance:Reference image={presenter.image} person-reference="true"/>
  <seedance:Reference audio={presenter-voice.reference}/>
</seedance:ReferenceVideo>
<media-track:Item id="trophy" image={broll-trophy.image} extent={trophy-extent}
  during={story.selection.trophy} frame={trophy-frame} motion={recipes.motion.broll-right}/>
<caption-fine:Track id="captions" document={story.caption} timeline={speech.timeline}>…</caption-fine:Track>
<film:Film id="main" canvas={vertical} timeline={speech.timeline}>
  <film:Track source={speech-picture.visual}/>
  <film:Track source={speech-sound.audio}/>
  <film:Track source={football-tiers.visual}/>
  <film:Track source={broll.visual}/>
  <film:Track source={captions.track}/>
  <film:Track source={music-bed.audio}/>
</film:Film>
<render:Video id="final" composition={main.composition} timeline={speech.timeline}/>
```

可以看到三类要素分工明确：
- **值/提示**（text:Value）：自然语言 prompt 只出现在这里和模型调用参数里；
- **生成物**（gpt:Image / seedance:ReferenceVideo）：声明式调用，带引用依赖；
- **结构与合成**（Frame/Extent/Timeline/Track/Film/render）：纯几何与时间，无 prompt。

**（3）组件化替换 = 换文件里的几行。** `swap-host.svml` 是同一结构的变体：Script、TierBoard、梗图位置、字幕全部不变，只把 presenter（人）、voice（猫叫）、各球员头像换成新生成节点。`swap-topic.svml` 换话题（球员→科技公司创始人），`swap-effect.svml` 换特效。**这就是"组件化替换达到复刻"的工程本质：结构 DNA 与物质素材分离。**

**（4）成本与门槛（务实数据）：**
- 官方样片真实成本 **$1.07–1.15/条**（含 Seedance 2 Mini 视频 + GPT Image 2 图片 + WhisperX 对齐）；
- 字幕/动效/代码渲染画面**不调生成模型也能出片**（零模型费）；
- 协议是 **修改版 Apache-2.0：多租户 SaaS 需商业授权**——自用/二创概念没问题，但不能直接把它打包成 AdCraft 的托管服务组件（见 §2.2 路线 B 的风险）；
- 依赖 Agent 生态（Claude Code/Codex）和 Node 22.15+ / pnpm monorepo（100+ workspace 包）。

### 1.4 Hypit 的"拉片方法论"（最值得抄作业的部分）

`skills/hypit/references/creation/reference-video.md`（16KB 全文已读）定义了一套读片方法，摘要：

- **整片读法**：从开头到结尾跟随 hook→论点→注意力转移→payoff，形成"这条片子为什么成立"的临时解释；
- **细节读法**：每个设计元素都要回答——内容与外观、空间关系、入场、持续行为、退出，并且**定位到它服务的词/停顿/动作上**；
- **互相修正**：整片理解与细节观察循环深化；跨镜头存活的物体属于"比镜头更长寿的系统"，要跟踪它的状态变化；
- **产出物**：`Analysis`（整片解读）+ `Timeline`（带时间的细节与意义），最终变成"哪些关系在人/产品/措辞变化后应该保留，哪些应该重新设计"。

`transformations.md` 给出 **7 个变换镜头**（透镜）：主体身份 / 产品品牌 / 脚本语言CTA / 平台时长画幅 / 视觉基调 / 增删系统 / 多参考融合。核心原则："**先保留角色（role），再重建形式（form）**"——换人之前先搞清楚这个人在片子里同时承担了几个角色（主播/头像/声音/B-roll 主角/MG 里的身份），要一起换。

### 1.5 对 AdCraft 的可行性判断

AdCraft 现有资产盘点（代码级确认）：

| 已有能力 | 位置 | 对拉片复刻的意义 |
|---|---|---|
| 参考视频上传/抽帧/元数据 | `apps/api/app/services/scene3d/reference_upload.py`、`POST /scene-3d/upload-reference` | 输入侧现成 |
| 参考视频多模态分析 → SceneScript | `reference_video_analyzer.py`、`POST /scene-3d/analyze-reference`（6帧逐帧分析+综合，1-2分钟） | **只做了"场景重建"一个维度**，没有台词/节奏/字幕/音效/结构维度 |
| 无限画布 + 8 种节点（text/script/image/video/audio/editing/scene-3d/voice-cast） | `apps/web/src/features/agent-canvas/`、`types-v2.ts` `CanvasNodeTypeV2` | 产出侧现成：拉片结果可直接实例化成节点 |
| 35 个风格 Skill + 风格选择器 | `apps/api/agent/video-skills/`（6 大类 35 个）、`AgentCanvasStyleSelector.tsx` | Jev+Hypit 方案的本落点 |
| pi-coding-agent 运行时 + Skill 清单 | `apps/api/agent/`（Node 22+，`src/skills.ts`、`skills/manifest.json`） | 加一个"拉片 Skill"架构上零障碍 |
| 文档/工件能力 | `AgentCanvasDocuments.tsx`（画布里已能放 HTML 类工件） | 拉片报告、HTML 结构预览的容器现成 |
| 3D 预演/时间线/剪辑 | scene3d、editing 节点 | 替代了 Hypit 的 Studio 渲染管线 |

**缺的三块**：
1. **结构模板中间表示**（拉片报告 → 可编辑的"复刻蓝图"）——AdCraft 现在从文字直接到分镜，没有"从参考视频结构到分镜"这一跳；
2. **读片产品界面**（现在是藏在 3D 节点里的小 panel）；
3. **槽位化替换与变体引擎**（换人/货/景/词/风格 → N 个变体）。

---

## 2. 拉片复刻功能：创意实施方案

### 2.1 三条路线对比

| 路线 | 做法 | 优点 | 缺点 | 结论 |
|---|---|---|---|---|
| **A. 借思想，自有 IR**（推荐） | 抄 hypit 的"词锚定+组件化+方法论"，定义 AdCraft 自己的复刻蓝图 JSON，实例化成画布节点；读片逻辑写成新 Skill `video_agent_reference_teardown` | 与画布/资产库/多模型路由完全咬合；无协议风险；团队完全可控 | 要从零定义 IR 和组件库 | ✅ **主路线** |
| B. 直接嵌入 hypit | 把 hypit 工具链塞进后端，svml 当 IR | 立即可用，方法论完整 | 修改版 Apache-2.0 多租户 SaaS 需商业授权；Node 工具链与 Python 后端双栈；SVML 与画布节点两套世界要对账；渲染/账号体系与 AdCraft 并行 | ❌ 不作为主路线，可作 P3 的"高级导出"彩蛋 |
| C. 完全自研 DSL | 设计 AdSVML 标记语言+编译器 | 上限最高 | 过度工程，P0-P2 不需要 | ❌ 暂缓；先用 JSON IR，验证后再考虑语法糖 |

### 2.2 推荐的系统形态

```
参考视频 ──▶ ①读片引擎（多模态+ASR）──▶ ②复刻蓝图（.adreplica 标记语言，见 §3）
                                              │
用户替换指令（人/货/景/词/风格）◀── ③槽位化替换面板（画蓝图）
                                              │
                          ④变体引擎（风格混搭 × N）
                                              │
                          ⑤编译器/实例化器 ──▶ 画布工作流（script/storyboard/image/video/editing 节点+连线）
                                              │
                          ⑥成片（复用现有 editing 合成）
```

**核心新增物：复刻蓝图（Replica Blueprint）**——一份 `.adreplica` 文档（§3.5 定义语法），同时被人和 Agent 读写。**其内存 IR 形态如下**（由 `adreplica_parser.py` 从 XML 解析生成，schema 校验+兜底）：

```json
{
  "blueprint_version": "1",
  "source": { "video_asset_id": "...", "duration_seconds": 21.3, "aspect": "9:16" },
  "analysis": {
    "whole_piece": " hook-反差-证明-CTA 四段式；前3秒用'错误示范'抓注意力…",
    "hook_type": "false-demo",
    "genre_format": "product-comparison"
  },
  "script_beats": [
    { "id": "b1", "role": "hook", "intent": "制造错误预期",
      "line": "别再这样洗脸了" }
  ],
  "semantic_events": [
    { "id": "e1", "anchor": { "type": "word", "beat": "b1", "event_ref": "wrong-demo" },
      "kind": "broll", "role": "错误示范图", "source_asset": "kf_03.jpg",
      "recreate_hint": "同机位同景别，换成用户商品" }
  ],
  "shot_table": [
    { "id": "s1", "shot_size": "closeup", "camera_motion": "static",
      "duration_s": 2.1, "transition_in": "hard-cut", "subject_role": "host" }
  ],
  "rhythm": { "avg_shot_s": 2.4, "cut_points_s": [0, 2.1, 4.8, ...], "energy_curve": "..." },
  "systems": {
    "caption": { "style": "karaoke-word-box", "placement": "lower-third", "persists": true },
    "music": { "mood": "upbeat-electro", "sync": "cut-aligned" },
    "mg": [ { "name": "price-tag", "trigger": "on-price-word", "behavior": "pop-in-hold-exit" } ]
  },
  "slots": {
    "host":   { "type": "character", "current": "原片女主播", "replace_with": "user_character_asset_id" },
    "product":{ "type": "product",   "current": "原片洗面奶", "replace_with": null },
    "script": { "type": "copy",      "current": "原台词", "rewrite": true },
    "style":  { "type": "style",     "skill_ids": ["gentle-everyday-vlog"] },
    "voice":  { "type": "voice",     "current": "女声温柔", "replace_with": null }
  }
}
```

> 关键设计：**词级锚定**（`semantic_events.anchor.event_ref` 对应 `.adreplica` 里的 `@{wrong-demo}`，抄 hypit 的 mixed content 语法，不要 JSON 的 offsets 平行结构——论证见 §3.2）；景别/运镜/节奏沿用 AdCraft 已有分镜 schema。**落盘形态是标记语言而非 JSON**：`.adreplica` 是单一真相源，本 JSON 只是解析后的内存表示。

### 2.3 开启的按钮（三入口 + 推荐组合）

| 入口 | 位置 | 交互 | 适合 |
|---|---|---|---|
| **E1 首页第二 CTA**（推荐） | `HomeShowcase` hero 区，"开始创作"旁增加 **「🎬 拉片复刻」** 次级按钮 | 点击 → 新建项目直接进入"拉片模式"（工作台而非空白画布） | 新用户一眼看懂差异化能力 |
| **E2 画布节点选择器**（推荐） | `AgentCanvasNodePicker` 新增 `"replica"` 节点类型（label: 拉片复刻） | 桌面上双击/拖拽视频文件到画布空白处 = 快捷创建 | 老用户在创作中途"参考一条片子" |
| E3 对话指令 | 聊天输入 `/拉片` 或直接粘贴 B 站链接 | Agent 走 yt-dlp 下载（hypit 就是这么做的） | 演示炫技场景 |

**推荐组合 E1+E2**：E1 负责"被看见"，E2 负责"被复用"。拖动视频落到画布即触发的语义，与项目已有的研究共识一致（"拖拽本身在表达意图"）。

进阶创意：**右键参考视频节点 →「以此为结构复刻」**，把任意已上传资产变成结构源。

### 2.4 界面设计（拉片工作台，四态）

新 Panel：`apps/web/src/features/agent-canvas/canvas/ReplicaWorkbench.tsx`（复刻 `ReferenceVideoPanel` 的上传契约 + `SceneScriptPanel` 的布局契约）。四个态共享一个左侧窄栏：

```
┌─ 状态轨道 ───────────────────────────────────────────┐
│ ① 上传/链接 → ② 读片 → ③ 拆解 → ④ 替换 → ⑤ 生成      │
└──────────────────────────────────────────────────────┘
```

**态② 读片（拉片进行时）**——把"AI 正在拉片"变成可见的仪式感：
- 左侧：原片播放器 + **逐词字幕网格**（抄 hypit：word-timed transcript 网格，词与画面变化对着看）；
- 右侧：实时滚动的"读片笔记"（整体解读 + 逐条发现），配关键帧缩略图；
- 进度真实化（排队/ASR/逐帧分析/综合，与画布节点状态同款语言）。

**态③ 拆解（拉片报告）**——报告即可编辑的结构：
- 四张联动卡片：**镜头表**（序号/景别/运镜/时长/转场/主体/台词区间，行可点，点行跳视频到该时刻）、**节奏曲线**（每秒剪切密度+能量曲线，标注 hook 点）、**系统清单**（字幕/音乐/MG/音效各自的触发规则）、**槽位地图**（人/货/景/词/风格/声音 6 槽，标注"原片值"和"将替换为"）。

**态④ 替换（槽位面板）**——组件化替换的主界面：
- 每个槽位一张卡：`原片：女主播` → 拖入资产库角色 / 点击「从资产库选」/「重新生成」；
- **替换影响预览**：换词 → 显示"字幕与音效将随新词重排（词锚定）"；换人 → 提示"该角色还出现在 头像/ pts 3 个位置，将一并替换"（抄 hypit 的 role 思维）；
- 顶部 toggle：**保留结构**（默认，只换槽位）/ **放飞结构**（允许 Agent 重切）。

**态⑤ 生成 → 画布**：
- 点击「生成复刻工作流」→ 蓝图实例化为一组画布节点（script 节点带 beats、storyboard 节点带镜头表、image/video 节点带 recreate_hint、editing 节点带时间线），节点间自动连线，用户落地在熟悉的画布里继续改；
- 同时弹出**变体矩阵**（见 §5.4）：N 个风格混搭方案卡（480P 预览优先，符合项目"低成本审片"原则），点一个即按该风格重跑。

### 2.5 输入 / 输出定义

**输入**（表单字段）：
| 字段 | 必填 | 说明 |
|---|---|---|
| 视频文件或链接 | ✅ | 复用 `upload-reference`；链接走服务端下载（对标 hypit `media fetch`） |
| 复刻目标 | ✅ | "换商品不换人"/"全换"/"只换词"/"换风格"（对应 transformations.md 的透镜） |
| 替换素材 | ○ | 角色/商品/Logo（资产库引用，没有就留空让 Agent 生成） |
| 新文案 | ○ | 不提供则 Agent 按原 beats 重写 |
| 平台/时长/比例 | ○ | 默认跟随原片 |
| 预算确认 | ✅ | 预估消耗（视频模型最贵），落 brief（抄 hypit 的 money 原则） |

**输出**：
| 输出 | 形态 | 去向 |
|---|---|---|
| 拉片报告 | 人类可读（报告卡+词网格） | 工作台展示；存画布文档节点 |
| 复刻蓝图 IR | JSON（可 diff/可版本化） | 后端存储；节点结构化内容 |
| 复刻工作流 | 画布节点组+连线 | 立即进入创作 |
| 成片 | MP4 | 复用 editing 合成 |
| 变体矩阵 | N 个 480P 预览 | 审片后选择 |

### 2.6 后端改动清单（草案）

```
新增 Skill:   apps/api/agent/skills/video_agent_reference_teardown/SKILL.md
              （含 references/：拉片读法+变换透镜+蓝图 schema；抄 hypit 方法论而非代码）
新增服务:     apps/api/app/services/replica/
                ├── ingest.py            # 链接下载(yt-dlp) + 复用 reference_upload
                ├── transcribe.py        # ASR 逐词时间戳（优先本地 whisperx，退化用对话节点已有 ASR）
                ├── frame_reader.py      # 镜头边界检测（现有 keyframes 之上加切检）
                ├── teardown.py          # 多模态读片 → .adreplica 文档（核心）
                ├── adreplica_parser.py  # .adreplica XML → IR（schema 校验 + normalize 兜底）
                ├── blueprint.py         # IR schema、slot 应用、替换影响分析
                ├── instantiate.py       # IR → canvas 节点创建请求
                ├── reverse.py           # canvas workflow → .adreplica（"项目即代码"导出）
                └── variants.py          # 风格混搭 × N（见 §4.4）
新增端点:     POST /api/v1/replica/analyze          # 视频/链接 → .adreplica 文档（异步任务+进度）
              PUT  /api/v1/replica/document/{id}    # 人/Agent 编辑 .adreplica 源码
              POST /api/v1/replica/instantiate      # 文档 → 画布工作流
              POST /api/v1/replica/variants         # 变体矩阵
新增文档类型: AgentWorkingDocumentKindV2 += "video_source"（.adreplica 源码；repository 需扩文本载荷）
新增节点类型: types-v2.ts CanvasNodeTypeV2 += "replica"（+ nodeDefaults + NodePicker + Icon + Panel）
```

### 2.7 分期与验收

| 阶段 | 内容 | 周期估计 | 验收 |
|---|---|---|---|
| **P0** | Skill 方法论 + 读片引擎（ASR+抽帧+读片）→ 只出**拉片报告**（不生成） | 2-3 周 | 上传任意 15-30s 广告视频，产出镜头表+节奏+系统清单+词网格，人工评分可用 |
| **P1** | `.adreplica` 标记语言层（§3.5）+ 槽位替换 + 编译实例化到画布 | 3 周 | "换商品"场景：.adreplica 一键变 6-8 个画布节点并出成片；改一句台词全片锚点事件正确重排 |
| **P2** | 变体引擎（§4.4）+ 480P 预览矩阵 + 画布内源码编辑器 | 2 周 | 一键 N 个风格变体，可预览可挑选；画布里可直接改源码 |
| **P3** | 彩蛋：.adreplica ↔ hypit SVML 互转、direct-execute 快车道（零模型费场景）、配方沉淀 | 1-2 周 | 双向互换演示；纯字幕/MG 短片不调生成模型直出 |

> P0 甚至可以更快：把 `reference_video_analyzer.py` 的逐帧分析 + 新增 ASR 词对齐拼起来，先出报告验证价值，再投资语言层。注意 §3.7 的修正：**P1 直接上标记语言，不要先做 JSON IR 再迁移**。

---

## 3. 深挖：在项目内部用 SVML 式结构化语言描述视频

> 本章是对初版"HTML 类语言"讨论的精确化：用户真正想问的是 **hypit 的 SVML 本身**——能不能在 AdCraft 内部采用这种结构化标记语言作为视频的描述格式。结论先行：**建议采纳，但必须本地化为 AdSVML，且只做"创作期文档层"，不动现有执行引擎**。下面给完整论证。

### 3.0 先看清楚 SVML 的完整家谱（一手资料确认）

| 扩展名 | 角色 | 实例（ranking-football 样片） |
|---|---|---|
| `.svml` | 视频主工程：Script（台词+词锚点）、生成调用、组件挂载、合成与渲染 | `reference.svml`、`swap-host.svml`、`swap-topic.svml`、`swap-effect.svml` |
| `.svs` | 配方/样式表：CSS 风格的 key-value + JSON 数组参数，被 svml 引用 | `recipes.svs`（`ranking.football` 的五行色板、`media.performance` 的 fit/stack-order…） |
| `.svrun` | 运行记录：一次 Build 的候选与产物，可复用 | `reference.svrun` |

关键架构事实（读 `docs/guide/studio-companion-architecture.md` 确认）：**Studio 不是另一个编辑器，而是 SVML 的投影**。组件（component）自带 Companion，声明"这个组件在时间线上暴露哪些实体、Inspector 暴露哪些字段"；Studio 里的每次编辑都回写到 Source 属性 → 重编译同一个 Run → 编译失败则回滚并报错。**一份文件、多重投影、编辑必回写**——这就是 SVML 架构的精髓。

### 3.1 为什么"项目内部用 SVML 式语言"在 AdCraft 特别成立

比一般项目更强的四个落地条件，全部已在代码级确认：

1. **运行时本来就是 coding-agent 形态**。`apps/api/agent` 基于 `@earendil-works/pi-coding-agent`，技能经 `skills/manifest.json` 加载、`verify-skills.ts` 校验（hash 登记）。coding-agent 的原生作业对象就是**文本文件 + diff + schema 校验 + 失败重试**——SVML 文件放进这个运行时是零摩擦的；而如果放进"节点 JSON + REST"世界里，每次改一个词都要走一次 API 序列化。
2. **已有"agent 工作文档"先例**。`AgentWorkingDocumentKindV2 = anchor_registry | storyboard_production_plan`，经 `agent_working_documents.py` 严格 schema（`extra="forbid"`）持久化、由画布 `AgentCanvasDocuments.tsx` 投影展示。"agent 写一份结构化文档 → 画布渲染它 → 用户在文档与画布间审阅"这个模式**已经跑通两例**，SVML 文档是同一模式的第三个成员（kind: `video_source`）。
3. **ADR 0008 的哲学同构**。ADR 0008 明确拒绝了"导演表/剪辑表"双时间线，确立"**一个 clip、两个相位**"（intent + media），并规定"模型永远收不到时间线，收到的是排练片"。SVML 正是这个哲学的极端形态：**SVML 是谱，编译/渲染是翻译层，画布节点和 editing 时间线都是它的投影**。引入 SVML 不违背任何既有 ADR，反而是把 ADR 0008 的"谱"显式化。
4. **资产/角色契约/供应商抽象已就位**。SVML 只需引用 `asset_id`、`skill_id`、节点角色契约（`ad-media-role-v2`）和 `model_selection_mode`，不需要自己管 provider 路由——这恰好补上 hypit 把 provider 焊死在语言里（`<gpt:Image>`/`<seedance:ReferenceVideo>`）的设计短板，与 AdCraft"多平台一键配置"的产品价值观对齐。

### 3.2 标记语言 vs 纯 JSON IR：三个不可替代的优势

这是本轮最核心的选型判断。JSON 不是不行（API 友好），但在本场景有三个硬伤：

1. **行内词锚定**。拉片复刻的命根子是"B-roll/字幕/音效挂在台词的某个词上"。SVML 的 mixed content 天然表达：
   ```xml
   <beat id="b1" role="hook">别再@{wrong-demo}这样洗脸了@{/wrong-demo}了</beat>
   ```
   JSON 要表达同一件事得拆成 `{text, offsets:[{start,end,event_id}]}` 的平行结构——可读性差、LLM 编写错误率高、diff 噪声大。而 XML/HTML 式标记是 LLM 训练量最大的格式之一（HTML/JSX/Vue 模板），**语法顺从性显著优于任何自制 DSL**。
2. **git 级 diff 与渐进式编辑**。`.svml` 是纯文本：改一句台词是一个 1 行 diff，Agent 可以用"读文件→小 patch→重编译"的循环工作，失败就地回滚；JSON 树里任何一次小改都可能引发大范围结构位移，审查成本高。
3. **人可读的单一真相源 + 多投影**。SVML 文件同时被人（源码视图）、Agent（编辑）、系统（编译成节点/执行）消费，天然规避 §3.4 会讲到的"双真相源"风险；hypit 的 Studio Companion 已经证明这套投影机制可行。

### 3.3 标记语言能"彻底覆盖 prompt"吗：分三层看

- **结构层（镜头顺序/景别/运镜/时长/转场/槽位）**：SVML 可 100% 覆盖，且比 prompt 精确——"快节奏" prompt 听不懂，`<shot dur="1.2" cut="hard"/>` 机器能执行；
- **关系层（事件挂哪个词、系统跨镜头生命周期、替换影响范围）**：SVML 可 100% 覆盖，这正是 hypit 相对传统剪辑软件的本质进步；
- **物质层（画面质感/表演/声音/审美）**：**覆盖不了，也不该覆盖**。生成模型只吃 prompt+参考；hypit 自己的 `.svml` 里 `text:Value` 占了一半篇幅——**SVML 不是 prompt 的掘墓人，是 prompt 的编译器上下文**："这张 B-roll 是挂在'续航'一词上的产品特写、同机位同景别"这句话本身就是最准的 prompt 生成器。

> 附带修正一个传播中的误读："视频=代码"不等于"没有自然语言"，而是**自然语言被结构约束、被锚点定位、被配方参数化**。这是升维，不是替换。

### 3.4 缺点与边界（诚实清单）

1. **转录有损**：视频→SVML 丢的是像素级轨迹与微小时差。对策：产品语义明确为"复刻关系不复刻像素"，并对齐 hypit 的做法（WhisperX 词对齐 + 语义重生成）。
2. **双真相源风险**：SVML（文档）与画布节点（投影）若双向可改必然漂移。对策（硬规则）：**SVML 文档是创作期唯一真相源；节点是其投影；画布上的手改标记为 deviation，合程时reverse-sync 回文档或丢弃**。hypit 的规则更严——Studio 一切编辑必须回写 Source。
3. **语言蔓延（language sprawl）**：词汇表会诱发贪多。对策：MVP 只收 §3.5 的约 15 个元素，每个新元素必须有明确编译目标，否则不收。
4. **双栈校验成本**：Python（pydantic）与 TS（ajv）各一份 schema。对策：以 Python 为权威，TS 侧只做编辑期提示；并抄 SceneScript 的 normalize 兜底经验（LLM 常犯错的自动修复，如 scale 数组→标量）。
5. **简单场景过度工程**：15 秒单镜头商品片直接 prompt 更快。SVML 的价值在"结构复用的复刻/变体"场景，入口上要对齐（拉片复刻/变体才进 SVML 通道，普通创作走现有通道）。
6. **XML 工具链**：解析/校验/高亮要自建薄层（不引重型 XML 框架），这部分工作量约 3-5 人日，可接受。

### 3.5 AdSVML 草案（本地化的最小词汇表）

**设计原则**：抄 hypit 的语法天赋（mixed content + 引用 + 配方），换掉它的词汇表（provider 焊死→角色契约；它管渲染→我们编译成画布节点）。

```xml
<advideo version="1" aspect="9:16" fps="30">
  <!-- 槽位：原片角色→用户资产；style 单挂或混搭（Jev 方案见 §4.4） -->
  <cast>
    <host   ref="asset:char_001"/>
    <product ref="asset:prod_042"/>
    <style  ref="skill:gentle-everyday-vlog" mix="skill:lived-in-epic-cinema@0.4"/>
  </cast>

  <!-- 台词 + 行内词锚点（拉片复刻的命根子） -->
  <script>
    <beat id="b1" role="hook">别再@{wrong-demo}这样洗脸了@{/wrong-demo}了</beat>
    <beat id="b2" role="proof">连洗{7}天@{/seven-days}，毛孔细了一圈</beat>
  </script>

  <!-- 镜头表：编译后落入 ADR 0008 的 clip intent 相位，不是第二套时间线 -->
  <timeline>
    <shot id="s1" size="closeup" motion="static" dur="2.1" cut-in="hard" during="b1"/>
    <shot id="s2" size="medium"  motion="push-in" dur="3.4"           during="b2"/>
  </timeline>

  <!-- 挂在词/镜头上的系统事件 -->
  <events>
    <broll during="{wrong-demo}" src="asset:kf_03"
           recreate="same-framing-swap-product" motion="slide-left"/>
    <caption style="karaoke" placement="lower-third" per-speaker="host"/>
    <sfx at="s2" src="asset:whoosh" gain="0.8"/>
  </events>

  <!-- 生成意图：role/model_selection_mode 对齐 ad-media-role-v2，provider 解析留到编译期 -->
  <gen id="g_broll1" kind="general_image" role="broll"
       prompt="…同机位特写，错误示范…" model="default"/>
  <render out="1080x1920"/>
</advideo>
```

**家族文件**（对齐 hypit 的 .svml/.svs/.svrun 分工）：
- `.adreplica`（主工程）：上面的结构；
- `.adrecipe`（配方）：字幕样式、动效曲线、节奏模板——未来可沉淀"钩子类型库"；
- `.adrun`（运行记录）：一次生成的候选与产物指针（复用 AdCraft 现有资产版本历史即可，不必新造）。

**编译目标（明确边界）**：
```
.adreplica ──compile──▶ 画布节点创建请求（script/storyboard/image/video/editing + 连线）
        └──reverse──▶ 画布 workflow 导出回 .adreplica（"项目即代码"）
执行仍走：现有工作流引擎 + ADR 0008 两相位时间线 + editing 合成
```
即：**SVML 管创作期，引擎管执行期，中间一层编译器**。等语言与组件库稳定后（P3），再评估对"纯字幕/MG 零模型费场景"开直执快车道（hypit 用无头 Chromium 录帧，AdCraft 可用 Puppeteer/既有渲染件，但这是优化不是前提）。

### 3.6 与现有系统的集成点（具体到文件）

| 集成点 | 改动 |
|---|---|
| `AgentWorkingDocumentKindV2`（`apps/web/src/types-v2.ts:2001` + `apps/api/app/schemas/agent_working_documents.py`） | 增加 `"video_source"`（`.adreplica` 源码，text payload，需给 repository 扩文本载荷支持） |
| `AgentCanvasDocuments.tsx` | 新增源码视图：左 `.adreplica` 源码（高亮+锚点跳转），右投影预览；编辑回写文档 |
| `apps/api/agent/skills/` | 新 Skill `video_agent_reference_teardown`（读片→写 .adreplica）+ `video_agent_adreplica_authoring`（写/改语言，抄 hypit SKILL.md 的结构：词汇表+常见错误+示例） |
| `apps/api/app/services/replica/` | `blueprint.py` 升级为 `adreplica_parser.py`（XML→IR，normalize 兜底）+ `instantiate.py`（IR→节点请求）+ `reverse.py`（节点→.adreplica） |
| 画布 | `replica` 节点 (§2.3) panel 内嵌 `.adreplica` 源码编辑器（MVP 可只读+对话改，P2 上直接编辑） |

### 3.7 对分期计划的修正（重要）

初版给的是"P1 先 JSON IR、P3 再考虑语法糖"。**本轮深挖后改口：P1 直接上 `.adreplica` 文本层**，理由：

1. 从 JSON IR 再迁移到标记语言是重工（解析、校验、UI、回写做两遍），而词锚定在 JSON 里的孱弱会从第一天就拖累拉片复刻的核心体验（换词重排）；
2. 项目的 coding-agent 运行时 + 工作文档机制 + git 文化，让"文本文件为真相源"的成本远低于一般项目；
3. hypit 已经替整个行业验证了"SVML 形态可行、Agent 写得动、用户看得懂"，我们不需要再证伪一次。

不变的边界：**P1 的 .adreplica 只编译到画布节点，不直执**；直执与 `.adrecipe` 配方沉淀放 P3。

---


## 4. B 站视频拆解：Jev + Hypit 风格混搭方案

### 4.1 视频内容还原（BV1fShv6yErB）

- 标题：《Jev 搭配 Hypit 简直是王炸‼️》，发布者：Hypit 官方号，时长 26s；
- 简介要点：**Hypit 只用 13.07 秒就设计出 100 个风格迥异的 AI 数字人**；没有千篇一律的脸和"AI 味"；做法是——**把你的目标想法投递给 Jev，Jev 根据需求挑选各种合适的风格，Hypit 再把这些风格随机组合、混搭成各种耳目一新的形象**；每个数字人都有独特形象风格，配上自然表情和生活化细节，更像真人。

### 4.2 Jev 是什么

- TypeSafe AI（前 OpenAI 研究员 Diogo Almeida 创立）2026-09-15 发布的 **"System One"（系统一）决策模型**；
- 定位：**机器原生意智**——不写小作文，只做结构化判断。输入 = 一段 state + 若干有类型的问题，问题类型：**Choice**（选项+概率）、**Score**（有序量表）、**Noul**（是非+为真概率）；
- 性能（官方/OpenRouter 实测）：适合任务上比大模型**快 20–200 倍、便宜 40–400 倍**，30 类请求分类中位延迟 154ms（第二名 GPT-5.6 Luna 为 860ms）；
- 生态热度：LangChain "Jev-as-a-Judge" 实验、被用于浏览器 Agent 决策、广告投放判断等。

### 4.3 方案原理总结（四步）

```
① 需求 → Jev：把"我要一批 XX 调性的数字人"连同候选风格描述一起发给 Jev
② Jev 结构化打分/选择：对每个风格维度做 Choice/Score（如"适合美妆吗: Score 中高"、"与品牌冲突吗: Noul false"），筛出兼容风格集
③ Hypit 随机组合：把筛出的风格标签（发型/服装/妆容/光线/摄影/时代感…）两两混搭，组成 N 组互不相同的"风格基因组"
④ 批量生成：每组基因组驱动 prompt 生成形象图 → 13 秒产出 100 个差异度充分的候选
```

**本质：用"廉价结构化决策"做风格导航，用"组合爆炸"做多样性，用"批量生成"做规模。** 关键洞察是 100 个不重样并不需要 100 次创意，而是需要**一个足够好的风格维度库 + 组合去重**。

### 4.4 对 AdCraft 的赋能（重点）

AdCraft 已经有 **35 个风格 Skill、6 大分类、风格选择器和资产库**——Jev 缺的"风格库"我们有了，Jev 做的"挑选+组合"正是我们的风格选择器缺的智能。四个赋能点：

**（1）风格导演（Style Director）——拉片拆解的第 5 维度。** 现在读片拆"镜头/节奏/系统"，加一维**风格 DNA**：从参考视频提取色调、摄影、剪辑、字幕、音乐、类型六维特征向量。然后：
- **正向**：给定用户 brief（商品/平台/受众），给 35 个风格 Skill 逐个 Choice/Score 打分 → Top-K 兼容集 → **随机混搭 K 个风格 Skill 组合**（Jev+Hypit 同款操作）→ 每个组合跑一版 480P 概念片（项目 research 里的"低成本审片"）→ 用户挑一个放大制作；
- **反向**：上传参考视频直接反推"它的风格基因组最接近哪几个 Skill 混搭"，拉片复刻时风格槽一键填充。

**（2）Jev 式廉价质检岗。** AdCraft 全链路多处需要"小判断"：候选图/视频是否遵守角色一致性、生成结果是否含违规内容、候选版本哪个更好、某个镜头要不要重抽、模型路由选哪家。这些用大模型贵且慢，用 Jev 这类毫秒级结构化判断正合适（LangChain 已在验证 judge 场景）。**落地不依赖接入 Jev 本体**：用结构化输出的小模型/GLM 模仿 Choice/Score/Noul 三问式即可，接口保持一致。

**（3）风格轮盘（一键 100 案）。** 首页/画布放「🎡 风格轮盘」：选一个脚本 + 资产，一次产出 N=20~100 个风格混搭的 480P 缩略方案矩阵（每个仅 1-2 个代表镜头），便宜、可视化、可分享——这是把 B 站视频的效果产品化，也是最差异化的卖点演示。

**（4）B 站同款"数字人形象秀"。** 角色设计节点里加「批量形象探索：100 个风格混搭角色」按钮，服务于角色资产库的"多风格角色矩阵"。

---

## 5. 风险与开放问题

1. **ASR 词级对齐是整条链的地基**（没有它就没有词锚定），需确认中文场景的 whisperX 部署与成本；降级方案：对话节点现成的 ASR + 线性插值。
2. **"像素级复刻"预期管理**：产品文案必须强调"复刻结构与关系，不复刻像素"；同时准备 hypit 同款 disclaimer。
3. **多模态 LLM 的读片质量上限**：SceneScript 阶段已遇到"3D 低保真人物识别难"问题，拉片读片对细微剪辑的识别（遮挡转场、微动效）会更难，P0 要用真实广告片反复校准 prompt。
4. **风格 Skill 与复刻蓝图的耦合度**：风格 Skill 现在是"激活一个"，混搭需要支持多 Skill 并行激活或合并输出，需要 `curation-map.json` 机制配合改造。
5. **Jev 是外部 API**（jev-latest，TypeSafe AI），商业化前需评估可用性与费用；建议先做"Jev 式接口、内部模型实现"。
6. **成本护栏**：变体引擎是烧钱大户，必须预算确认 + 480P 预览优先 + Build 状态机（不重复为失败付费）。
7. **（新增）SVML 采纳特有风险**：LLM 生成非法 XML（对策：schema 校验+normalize 兜底+编译错误上下文回喂重试）；词汇表蔓延（对策：MVP 15 元素封顶、新元素须有编译目标）；画布手改与文档漂移（对策：文档为唯一真相源、手改标记 deviation、reverse-sync 或丢弃）；双栈 schema 维护（对策：Python 权威+TS 只做提示）。完整论证见 §3.4。
8. **（新增）开放问题**：`.adreplica` 的 text payload 是否复刻 `storyboard_production_plan` 的大 JSON 方案，还是给 `agent_working_document_repository` 扩纯文本列——影响 P1 工作量约 2-3 人日，需在 P1 启动时与文档机制的 owner 对齐。

---

---

## 6. 四个尖锐问题的正面回答

### 6.1 能做到"完美移植"吗——不能，且"完美"是错误的目标

先拆"移植"的标的，逐层判断：

| 层 | 能否 1:1 移植 | 说明 |
|---|---|---|
| 思想层（词锚定 / 组件边界 / 文件即真相源 / swap 即 diff / Build 状态机） | ✅ 完整移植 | 设计公理，与实现无关 |
| 语法层（SVML 标签集） | ⚠️ 对标不照抄 | 我们不求兼容 SVML 文件，只求同构重生（AdSVML）；provider 焊死→角色契约是**刻意分歧** |
| 词汇/组件生态（100+ workspace 包、prompt kits、recipes、Studio Companions、image/video/voice-direction 等 craft 文档） | ❌ 搬不走 | 这是 hypit 真正的护城河：一个半月 1k star 背后是长期沉淀的组件库与"怎么对模型说话"的实证经验；协议上也不允许整体搬运 |
| 运行时（Build 状态机 / 候选机制 / 无头 Chromium 渲染器） | ❌ 不移植 | AdCraft 已有工作流引擎 + editing 合成 + ADR 0008 两相位时间线，移植=用别人的约束劣化自己的体系 |

为什么必须放弃"完美"：
1. SVML 的许多设计是**为它的约束优化的**（托管给 coding agent、无画布、provider 写死、Studio 即界面）；AdCraft 有画布、资产库、多 provider 抽象，照抄等于把我们的优势抄没，还把它的约束（如 Studio-only 编辑模型）连同双真相源风险一起搬进来；
2. 正确的移植单位是**公理而非工件**：词锚定、组件化替换、文件即真相源、变体工程这四条公理迁移过来，配合 AdCraft 的画布/资产/风格库，完全可以比 hypit 更适配广告生产场景。

### 6.2 SVML 能完美覆盖 prompt 的作用吗——不能，三个递增的理由

**（1）功能位不同。** prompt 是**随机生成过程的控制面**：图像/视频模型是 one-to-many 的采样器，prompt 的工作是把采样分布拉向目标（材质措辞、机位语言、表演指导、模型专属的 capture 用语）。SVML 是**确定性的组合结构**：决定什么出现在哪、响应什么词、何时入场退出。结构面替代不了控制面——正如 CSS 替代不了"这张照片拍什么"。

**（2）最先进的"视频即代码"系统在扩大 prompt 工程，而不是消灭它。** hypit 的 SKILL.md 用三大整篇 references（`image-direction.md` / `video-direction.md` / `voice-direction.md`）专讲怎么对模型说话；`reference.svml` 里 `text:Value` 占近半篇幅；还有 prompt kits（`<text:Render template={image-kit.phone-ugc-v1}>`）做模板化。这是全行业最强的反证：**SVML 不是 prompt 的掘墓人，是 prompt 的编译器与上下文供给系统**——"这张 B-roll 挂在'续航'一词、同机位特写、换成用户商品"这句话让 prompt 更准，而不是不需要 prompt。

**（3）信息论上不可能无损。** 要把视频描述到"不再需要任何自然语言补益"，就得编码每一帧——那就是 mp4 本身；而视频模型除了参考视频通道（**像素复刻，换不了内容**）不吃帧级回放。视频→SVML 必然有损（轨迹是推断的、时刻是近似的、表演细节丢失），损失只能由自然语言意图 + 模型先验补偿，这道缺口永远存在。

**但有一个产品意义上的"覆盖"成立**：用户侧可以不看见 prompt。当 AdSVML + Skill + 配方模板 + kits 成为 prompt 的生成系统，普通用户只编辑槽位和台词，prompt 由系统生成——这是**入口覆盖**，不是**机制替代**。产品宣传可以用前者，架构必须给高级用户留 prompt 逃生门（hypit 的 `text:Value` 就是逃生门）。

### 6.3 LLM 读视频生成 SVML，靠什么实现——四件套流水线

```
视频文件
 ├─(ffmpeg/CV)  抽帧 + 镜头边界检测 + （可选）深度/姿态估计 → 时间轴上的候选切点与关键帧
 ├─(ASR/WhisperX) 逐词时间戳转录                            → "时间的脊柱"：词 → 秒的映射
 ├─(VLM 多模态)  逐帧/网格化语义理解                          → 场景/人物/景别/运镜/道具/视觉系统行为
 └─(LLM 文本生成) 综合以上，按 Skill 词汇表写出 SVML          → 语法由 few-shot + schema 约束
        ↓
 校对环：schema 校验 → normalize 兜底 → 编译/渲染预览 → 发现不符 → 带上下文修正
```

决定产品预期的四个事实：
- **LLM 从不连续看片**：它看的是抽帧 + 转录；运动轨迹是**推断**而非测量（hypit 与我们的 SceneScript 同款限制，`reference-video-analyzer.md` 已记录）——所以复刻的是关系不是像素，§5 风险2 的预期管理由此而来；
- **切镜头检测靠 CV**（ffmpeg scene detect），不让 LLM 数帧；
- **词锚定精度来自 WhisperX 逐词对齐**——整条链的地基，挂了就只剩模糊秒级锚；
- 写 SVML 这步本质是**受约束的文本生成**：词汇表（已安装组件）+ 示例（reference.svml 级 few-shot）+ schema 校验 + 编译错误回喂重试。

### 6.4 自然语言生成 SVML，靠什么实现——同一模型，约束路径不同

NL→SVML 是**纯文本任务**（不用看视频），与 7.3 共享后半段：

1. **Skill 即编译器说明书**：词汇表 + 语法 + 组件目录 + craft 判断（什么场景用什么组件）+ 完整示例。LLM"会写"不是魔法，是 Skill 把接口知识外置成了文件；
2. **约束三件套**：schema 校验（`extra="forbid"` 式严校验）、配方模板（把常用组合固化成 `<text:Render template=...>`，避免每次都从零拼长 prompt）、迭代修复环（编译失败→错误上下文回喂→重写，hypit Build 状态机同款，失败不重复花钱）；
3. **在 AdCraft 的落法**：pi-coding-agent 直接写 `.adreplica` 文件（原生文件编辑 + diff + 回滚）→ `adreplica_parser.py` 校验 → 失败带上下文重试。质量拆解上：script beats 可复用现有 `video_agent_script_authoring` skill，镜头表复用 storyboard skill，编译步负责装配——**上限不在 LLM 会不会写 XML，在词汇表和配方库的沉淀**（呼应 §3.4 的语言蔓延担忧：词汇表必须慢增长，每个新元素都要有编译目标）。

---

## 7. 附录

### 7.1 关键参考

- Hypit 仓库：https://github.com/hypit-ai/hypit （README.zh-CN / examples/ranking-football/{reference,swap-host,swap-topic,swap-effect}.svml / skills/hypit/SKILL.md / references/creation/{reference-video,transformations}.md）
- B 站视频：https://www.bilibili.com/video/BV1fShv6yErB/ 《Jev 搭配 Hypit 简直是王炸‼️》
- Jev 资料：CSDN《一文搞懂 Jev：专为 AI Agent 打造的"系统一"决策模型》、新浪《刷屏了！前 OpenAI 研究员做的 Jev》、imooc《别拿大模型当"分类器"了》
- 本项目相关文档：`docs/reference-video-analyzer.md`、`docs/plans/infinite_canvas_ai_short_video_research_v0.2.md`、`docs/adr/0007-timeline-driven-production.md`、`docs/adr/0008-timeline-two-phase-directing-and-assembly.md`
- 本项目集成点代码：`apps/api/app/schemas/agent_working_documents.py`（AgentWorkingDocumentKindV2）、`apps/api/app/persistence/agent_working_document_repository.py`、`apps/api/agent/src/skills.ts` + `scripts/verify-skills.ts`（skill 装载与校验）、`apps/web/src/features/agent-canvas/documents/AgentCanvasDocuments.tsx`（文档投影 UI）
- 本项目相关代码：`apps/api/app/services/scene3d/reference_video_analyzer.py`、`apps/api/agent/skills/manifest.json`、`apps/api/agent/video-skills/catalog.json`、`apps/web/src/features/agent-canvas/canvas/ReferenceVideoPanel.tsx`、`apps/web/src/features/agent-canvas/model/nodeDefaults.ts`

### 7.2 一句话给团队

> **拉片复刻 = Hypit 的方法论 × AdCraft 的画布与资产库 × Jev 的风格决策**：P0 验证"读片报告"，P1 以 `.adreplica` 标记语言打通"文档→画布"，P2 上"风格轮盘"做传播爆点。不要引入 hypit 的实现，要引入它的世界观——**视频不是一次性生成物，是可编译、可替换、可批量变体的工程；而在本项目，这门"源码语言"就是内部 SVML 化的 `.adreplica`**。
