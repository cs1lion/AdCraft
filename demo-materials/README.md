# demo-materials — 实机演示素材库

> 建立：2026-09-28
> 定位：为**实机演示与端到端测试**准备的素材，独立于产品代码与自动化测试素材。
> 测试方案见 `docs/plans/live-demo-e2e-plan.md`。
> **本目录不含产品代码，不被产品导入。**
> 来源与许可见 [`SOURCES.md`](./SOURCES.md)。

---

## 快速索引

| 目录 | 内容 | 数量 |
|---|---|---|
| `videos/replica-reference/` | 拉片复刻的参考视频（网络下载，含真实剪辑结构） | 5 |
| `scripts/` | 文案脚本：创意输入 brief + **故事改写前后对照** + 负例 | 5 份 |
| `images/` | 商品 / 角色 / 场景参考图（固定 seed 可复现） | 8 |
| `audio/` | 音频参考（**当前为空**，用 `test-materials/fixtures/audio/` 兜底） | 0 |
| `runs/` | 演示留痕产物（每次验收一个时间戳目录） | 运行时生成 |
| `outputs/` | 真实产物落盘（音频 / 视频 / 成片） | 运行时生成 |

---

## 三条演示线与素材对应

| 演示线 | 用哪份素材 | 关键用例 |
|---|---|---|
| **主链路**（创意→成片） | `scripts/brief-product-launch.md` + `images/product/` | 商品发布，15s 竖屏 |
| **品牌 TVC** | `scripts/brief-brand-tvc.md` + `images/scene/` | 无口播，纯字幕 + BGM（专压 G7 音轨缺陷） |
| **拉片复刻** | `videos/replica-reference/bigbuckbunny-720p-10s.mp4` + `scripts/rewrite-cases.md` | 拆解 → 蓝图 → **改写** → 直出 |
| **3D 工作台** | `images/scene/` + `scripts/brief-brand-tvc.md` 的场景描述 | NL → SceneScript → 导演指令 → 预演 |
| **负例 / 约束** | `scripts/negative-briefs.md` | 空输入 / 超长 / 含糊 / provider 挂 / 额度耗尽 |

---

## 选用建议（第一次演示照着做）

```
① 起环境  → 跑 L0 冒烟
② 热身    → 先跑一次真实生成任务，确认额度与连通（别把额度问题留到现场）
③ 主链路  → brief-product-launch.md，走 S0→S8
④ 复刻线  → bigbuckbunny-720p-10s.mp4，跑 RW-1 换一句台词
⑤ 负例    → negative-briefs.md 的 NB-7（未解析素材），这是最能说明问题成熟度的用例
⑥ 收尾    → 产物落 runs/<时间戳>/，写 summary.md
```

---

## 留痕目录规范

```
demo-materials/runs/<YYYYMMDD-HHMM>/
├── summary.md        # 结论：通过/失败/已知缺失，附统计
├── report.json       # 机器可读：用例 ID × 状态 × 耗时
├── console.log       # 浏览器 console 导出
├── backend.log       # 后端日志
├── screenshots/      # 每步关键界面
├── rewrite/          # 改写用例的 before/after + drift-report
└── outputs/          # 真实产物
```

---

## 纪律

1. **SKIP 必须写原因**，"没测"不能记成"通过"。
2. **已知缺陷显式列出**，不靠记忆；现场失败用诚实话术（见测试方案 §9）。
3. **素材不混来源**：新增素材先登记 `SOURCES.md`，许可列不得留空。
4. **二进制不进 git**：`videos/` 与 `images/` 是可再生二进制，
   建议在仓库根 `.gitignore` 追加：
   ```
   demo-materials/videos/
   demo-materials/images/
   demo-materials/runs/
   demo-materials/outputs/
   ```
   （`SOURCES.md` / `README.md` / `scripts/` 应进版本控制）
5. **不要用下载素材做自动化断言**：那类断言应继续用 `test-materials/` 里
   带机器可读真值的合成素材；本目录服务于**真实演示与人工核对**。
