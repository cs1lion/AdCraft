# test-materials — 跨功能测试素材库

> 定位：为项目整体（重点：拉片复刻、3D 预演、timeline 双阶段导演、provider 参考通道）
> 准备**按风格单元化**的测试材料与测试方案，独立存放、不混入产品代码。
> **本目录不修改任何产品代码。**
>
> 建立：2026-09-27（同日三轮：素材单元化重组 + 质量门套件）。
> 全部素材无版权依赖：视频/音频/图片均为 ffmpeg 合成，文本为手写样例。

## 1. 目录结构（风格单元制）

```
test-materials/
├── README.md                     本文件（索引 + 快速开始）
├── truth.json                    机器可读真值（build_materials.py 生成，runner 断言依据）
├── plans/                        功能线横切方案（共享前置/流程/已知发现 + 单元索引）
│   ├── replica-teardown-plan.md    拉片复刻
│   ├── 3d-previs-plan.md           3D 预演
│   ├── timeline-plan.md            timeline（节拍/切片/同步/绑定）
│   └── reference-channel-plan.md   provider 参考通道
├── units/                        ★ 风格单元（自包含：unit.md 方案 + 素材 + brief）
│   ├── replica-fastcut/            快剪带货   — unit.md + brief(-en).txt + 视频
│   ├── replica-luxury/             高级慢节奏质感
│   ├── replica-dialogue/           中文对话小剧场（brief 含换台词/整片复刻两份）
│   ├── replica-textonly/           纯字幕直出
│   ├── replica-action/             动作快切运镜
│   ├── replica-beatsync/           卡点混剪（切点=120 BPM 整拍）
│   ├── replica-compare/            对比测评
│   ├── replica-vlogtour/           探店 vlog
│   ├── replica-tutorial/           教程步骤
│   ├── scene-indoor-dialogue/      3D NL·茶馆对话（基准）
│   ├── scene-outdoor-run/          3D NL·跑道跟拍
│   ├── scene-product-turntable/    3D NL·商品转盘（无人物）
│   ├── scene-night-street/         3D NL·夜景街景
│   ├── scene-crowd-corridor/       3D NL·走廊群戏（压力）
│   ├── scene-warehouse-chase-en/   3D NL·英文仓库追逐
│   └── scene-vague-negative/       3D NL·刻意含糊负例
├── fixtures/                     公共夹具（非风格型）
│   ├── videos/                     无声 / 4s 下界 / 61s 超长 / 3D 房间横移 / 切片锚长片
│   ├── audio/                      节拍轨（120/90/140/60/170/变速/过短/静音）+ 音频参考
│   └── images/                     3D 单图/全景/多视角/深度图 + 参考图画幅正反例
├── text/adreplica/               .adreplica 手写正例 ×3 / 反例 ×4（解析器验证过）
├── tools/
│   ├── build_materials.py        素材生成脚本（一条命令重建 units+fixtures+truth.json）
│   └── run_tests.py              自动化测试 runner（6 套件，agent 友好入口）
└── results/                      runlog + runner 产物 run-*/
```

**单元即入口**：要测某个风格，打开 `units/<unit>/unit.md` 即得素材真值、
用例 id、断言与执行命令；横切前置（后端启动、状态语义、已知发现）看对应 plan。

## 2. 快速开始（agent 友好）

```bash
# ① 无需后端：规格(media) + 内容质量(quality) + 解析器(adreplica) + 节拍(beats)
cd apps/api && uv run python ../../test-materials/tools/run_tests.py --suite local

# ② 起后端后的 API 套件（静态链路真跑；LLM 用例额度不可用时自动 SKIP 附原因）
cd apps/api && uv run python start_backend.py    # 终端 A
uv run python ../../test-materials/tools/run_tests.py --suite api-replica,api-scene3d

# 常用：--list 列用例 | --only <id> 重跑失败 | --full-matrix 全风格矩阵 | --strict SKIP 计失败
```

- 状态语义：PASS=断言通过；FAIL=产品缺陷或断言不符（带 expected/actual）；SKIP=环境未就绪，不算失败。
- 结果落盘 `results/run-*/report.json + summary.md`，退出码 0=无 FAIL。
- 场景 NL 单元为 agent 判读用例（走 LLM 叙事链路），结论记 `results/` 对应 runlog。

## 3. 质量门（quality 套件，QC-01…QC-14）

每条视频素材四项像素/信号级检查（阈值见 `tools/run_tests.py`，真值来自 `truth.json`）：

1. **镜头颜色**：各镜中点平均色 vs 设计底色（欧氏距离 ≤90）；
2. **文字可读**：按文字极性统计灰度像素数（≥150 @480p）——快 zoom 后段文字
   被推出画面这类问题会被抓出；
3. **切点准确**：跨切点 RGB 帧差显著高于镜头内抖动（MAD 门）——相邻镜头
   色差过小的设计会被打回（luxury/tutorial 首轮即被抓出并改色重制）；
4. **音频电平**：Overall RMS 在 -42~-3 dBFS（非静音、无削波）。

## 4. 真值速查

完整镜头级真值（每镜时长/底色/文字/文字色）在 `truth.json`（机器可读）；
各单元人类可读版在 `units/*/unit.md`。节拍轨实测：120→120.2 / 90→90.7 /
140→139.7 / 60→60.1 / 170→84.7（半频）/ 变速→74.9（可解释不崩溃）；
<2s → too_short；静音 → indeterminate。

## 5. 与 `e2e_output/replica_e2e/` 样例的关系

`apps/api/scripts/replica_e2e_build_samples.py` 产出的 12s 样片服务 API 脚本化
E2E（replica_e2e_run.py 11 步）。本库是其超集与分工：风格矩阵、边界与反例、
四条功能线、质量门。两套不冲突，E2E 仍用原套。

## 6. Git 建议（未改动 .gitignore，留待决策）

- 建议纳入版本管理：`plans/`、`units/**/*.md`、`units/**/brief*.txt`、
  `text/`、`tools/`、`truth.json`、本 README。
- `units/*/​*.mp4`、`fixtures/` 为可再生二进制：要么忽略，要么接受体积
  （当前合计约 17MB）。若忽略，在仓库根 `.gitignore` 追加：
  `test-materials/fixtures/` 与 `test-materials/units/**/*.mp4`。

## 7. 素材设计已知坑（生成脚本内也有注释）

- drawtext 裸 `%` 静默吞字——文案避开 `%`；字体 `'C\:/Windows/Fonts/msyh.ttc'`；
- `zoompan` 默认锚左上，必须显式居中（否则快 zoom 丢文字，QC 会抓出）；
- 相邻镜头底色必须保持可辨色差（否则切点帧差门 QC 会打回）；
- 素材变更后必须重跑 `build_materials.py` 同步 `truth.json`（断言唯一来源）。

## 8. 实测基线（2026-09-27）

- local 套件（media 26 + quality 14 + adreplica 6 + beats 8）：**54/54 PASS**。
- api 套件：6 PASS / 1 FAIL / 10 SKIP——唯一 FAIL 为真实产品缺口：
  `agent_canvas_nodes` CHECK 约束不含 `'replica'`（详见
  [plans/replica-teardown-plan.md](plans/replica-teardown-plan.md) §3）；
  10 个 SKIP 中 8 个为 LLM step plan 额度耗尽（429）。
