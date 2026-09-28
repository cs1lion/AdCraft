# 用例 C：故事改写（拉片复刻核心）

> 这是拉片复刻最该被演示的能力，也是本项目做得比参照产品深的地方。
> 每个用例都设计成**只改一处**，便于定位是叙事层、数据层还是渲染层出问题。

---

## 通用操作路径

```
上传参考视频 → 拆解 → 生成蓝图 → 打开源码 tab 或槽位编辑
   → 改 script 槽位 → 重新 instantiate / 直出 → 对比成片
```

---

## RW-1 · 换一句台词（最小改动）

**改前**（`<script>` 槽位）
```xml
<script>
<line speaker="narrator">冬天到了，头发又塌了。</line>
<line speaker="narrator">试试这瓶无硅油洗发水。</line>
</script>
```

**改后**（只换第 1 句）
```xml
<script>
<line speaker="narrator">熬夜到三点，头发还是塌的。</line>
<line speaker="narrator">试试这瓶无硅油洗发水。</line>
</script>
```

**验收**
| 检查 | 期望 | 关联实现 |
|---|---|---|
| 锚点存活 | 第 2 句及之后的锚点**不失效** | `narrative.py` selection 与帧时间解耦 |
| 时间重投影 | 改后句时长变，段落窗随之调整 | `reproject_anchor_seconds` |
| 结构恒等 | 镜头表拓扑不变（结构守卫不得报漂移） | `structure_guard.py` |
| 成片 | 第 1 句字幕变、第 2 句起不变 | 直出链路 |

> **这是最能证明"复刻结构、不复刻像素"的一条**。改一句台词若导致全片重排，
> 说明锚定还绑在时间上——那正是 G4 要解决的问题。

---

## RW-2 · 换人称与角色

**改前**
```xml
<script>
<line speaker="narrator">她打开浴室的灯。</line>
<line speaker="narrator">水声很轻。</line>
</script>
```

**改后**
```xml
<script>
<line speaker="narrator">他推开公司的门。</line>
<line speaker="narrator">键盘声很密。</line>
</script>
```

**验收**
- 角色槽位（character）若也换，结构守卫应放行（槽位替换是允许的）
- 一致性检查不应因"角色名变了但资产没变"而误报
- 若报错，报错必须**可行动**（指出该改哪个槽位），不是抛原始异常

---

## RW-3 · 换卖点（结构不变，内容全换）

**改前**
```xml
<script>
<line speaker="narrator">控油，有效期 72 小时。</line>
</script>
```

**改后**
```xml
<script>
<line speaker="narrator">含氨基酸，温和到可以每天洗。</line>
</script>
```

**验收**
- 变体渲染计划应给出**可见的字幕样式差异**（recipe 层，G5）
  - 🔴 若所有变体样式签名相同，说明 `variant-render-plans` 前端入口未接（P1-3 未做）
- 槽位内容可变、拓扑不可变——结构守卫生效

---

## RW-4 · 整段删减（压力用例）

**改前**：3 个 `<line>`
**改后**：删掉中间一句，只剩 2 个

**验收**
- 词窗/beat 归属应重算，不留孤儿锚点
- 字幕不应出现重复或空窗
- 若投不出时间，代码应**清除**词级绑定退回段落级，而不是保留过期秒数

---

## 改写用例通用记录模板

每次跑完在 `demo-materials/runs/<时间戳>/` 下留：

```
rewrite/RW-<id>/
├── before.adrеplica    # 改前的 .adreplica 导出
├── after.adreplica     # 改后
├── drift-report.json   # 结构守卫输出（应为空或仅槽位差异）
├── final.mp4           # 成片
└── note.md             # 实际表现 vs 期望
```

> `before/after` 用 `/blueprint/export` 导出即可——这同时验证了
> `recipe/export` / 文档层往返（当前无前端入口，属 P1-4）。
