# 风格单元：纯字幕直出（replica-textonly）

> 单元自包含：本方案 + `brief.txt`（复刻目标=直出验证）+ 视频素材。

## 风格定位

打卡挑战类纯文字片：静态纯色底 + 全屏大字幕 + 脉冲音轨，无实拍主体、
无口播。是**直出可行性门（direct-execute）**的核心素材：全部镜头应归入
零模型费环节；镜头内的"台词"属 TTS 生成环节（诚实计入 generation_steps）。

## 素材与真值

- 文件：`rep_textonly_1x1_10s.mp4`（10s / 1:1 / 720×720@30）
- 音频：880Hz 正弦（音量 0.25）

| 镜 | 时长 | 底色 | 屏上文字 |
|---|---|---|---|
| 1 | 2.5s | #f5e6d3 | 第一天 坚持早起 |
| 2 | 2.5s | #d9ecf5 | 第七天 看得见变化 |
| 3 | 2.5s | #ecddf5 | 第三十天 习惯成型 |
| 4 | 2.5s | #222831 | 现在轮到你了（白字） |

切点：0 / 2.5 / 5 / 7.5 秒。

## 用例与预期

| id | 内容 | 预期 |
|---|---|---|
| QC-04 | 质量 | 全过 |
| RT-04 | teardown 拆解（LLM，brief=直出验证） | 镜头数 3-5；avg_shot 2.0-3.2s；含「轮到你了」 |
| RT-DE | `text/adreplica/valid_textonly_1x1.adreplica`（本片结构）走直出门 | blockers 空；≥3 个零模型费步骤；TTS 计入生成步骤 |

## 执行

```bash
cd apps/api && uv run python ../../test-materials/tools/run_tests.py --only QC-04,RT-04,RT-DE
```
