# 拉片复刻（Replica Teardown）测试方案

> 功能线横切方案：共享前置、流程与已知发现。**每个风格的专属素材/真值/断言
> 在各自单元目录 `units/replica-*/unit.md`**，本方案不再重复。

## 0. Agent 执行入口（自动化优先）

```bash
# ① 无需后端：素材规格（media）+ 内容质量（quality）+ .adreplica 解析器（adreplica）
#    + 节拍分析器（beats）
cd apps/api && uv run python ../../test-materials/tools/run_tests.py --suite local

# ② 需后端（先启动：cd apps/api && uv run python start_backend.py）
#    静态链路真跑；LLM 用例在 key/额度不可用时自动 SKIP 并附真实原因
cd apps/api && uv run python ../../test-materials/tools/run_tests.py --suite api-replica
```

- 用例清单 `--list`；重跑失败 `--only <id>`；teardown 全风格矩阵 `--full-matrix`（默认只跑 4 条代表性素材控制 LLM 成本）。
- 结果：`results/run-*/report.json + summary.md`；退出码 0=无 FAIL。
- 状态语义：**PASS**=断言通过；**FAIL**=产品缺陷或断言不符（带 expected/actual 证据）；**SKIP**=环境未就绪（后端未起/LLM 额度/依赖缺失），reason 为真实报错，不算失败。

## 1. 风格单元索引

| 单元 | 风格 | 质量门 | teardown 用例 | 断言要点 |
|---|---|---|---|---|
| `units/replica-fastcut` | 快剪带货 | QC-01 | RT-01（fast） | 5-7 镜；avg≈2.5s；含 BUY NOW |
| `units/replica-luxury` | 高级慢节奏 | QC-02 | RT-02 | 3-5 镜；avg≈7.5s；不得判快节奏 |
| `units/replica-dialogue` | 中文对话小剧场 | QC-03 | RT-03（fast） | 4-6 镜；avg≈4s；中文台词 |
| `units/replica-textonly` | 纯字幕直出 | QC-04 | RT-04（fast） | 3-5 镜；含「轮到你了」；直出门 RT-DE |
| `units/replica-action` | 动作快切运镜 | QC-05 | RT-05 | 6-9 镜；avg≈1.5s；zoom 类运镜 |
| `units/replica-beatsync` | 卡点混剪 | QC-06 | RT-06（fast） | 12-20 镜；avg≈1.0s |
| `units/replica-compare` | 对比测评 | QC-07 | RT-07 | 3-5 镜；对比结构 |
| `units/replica-vlogtour` | 探店 vlog | QC-08 | RT-08 | 5-7 镜；avg≈3s |
| `units/replica-tutorial` | 教程步骤 | QC-09 | RT-09 | 3-5 镜；含 STEP |

边界夹具（非风格，`fixtures/videos/`）：无声=QC-10/RT-10、4s 下界=QC-11/RT-11、
61s 超长拒绝=QC-12/RT-12。

## 2. 共享流程（横切）

1. **teardown**：`POST /api/v1/replica/teardown`（multipart：file + user_description + num_frames），
   brief 正文在各单元 `brief.txt`「粘贴以下内容」之后。
2. **蓝图**：`POST /replica/blueprint`（report → blueprint）→ 槽位/锚点来自报告。
3. **`.adreplica`**：`POST /replica/blueprint/export` ↔ `/import`；正反例在 `text/adreplica/`
   （解析器本体用例 AD-01…AD-06，API 用例 RT-IM）。
4. **变体**：`POST /replica/blueprint/style-variants`，同参确定性（RT-VAR）。
5. **直出门**：`POST /replica/blueprint/direct-execute-plan`（RT-DE，textonly 单元结构）。
6. **实例化**：`POST /replica/instantiate`（RT-INST，见 §3 已知发现）。
7. **链接下载**：`POST /replica/ingest-link`（RT-LINK，默认 SKIP，`--link-url` 提供后跑）。
8. **GUI 抽检**：Reference 页 → 🎬 拉片复刻（秒级计时/取消）→ 蓝图工作台 → 源码 tab。

## 3. 已知发现与前置

- **RT-INST 为已知 FAIL（真实产品缺口）**：`agent_canvas_nodes` 的 CHECK 约束
  `ck_agent_canvas_nodes_type` 不含 `'replica'`（最新迁移 20260917_01 只放宽到
  voice-cast），replica 节点 INSERT 被包装成 503 canvas_node_conflict。与 v0.2
  handover「replica 迁移未入库」一致；修复=补 alembic 迁移，合入前该用例预期 FAIL。
- LLM 额度（step plan）2026-09-27 耗尽（429）时 teardown/全链用例 SKIP；恢复后重跑即真断言。
- whisperX 未启用时 transcript 显式降级（`source="unavailable"`）是正确行为；
  `no_audio_track` 见 fixtures silent 单元（QC-10）。
- 实测基线（2026-09-27）：local 54/54 PASS；api 套件 6 PASS / 1 FAIL / 10 SKIP。

## 4. 记录方式

自动结果由 runner 落 `results/run-*/`；人工/GUI 抽检结论记
`results/replica-runlog.md`（素材 / 日期 / 断言结果 / 偏差）。
