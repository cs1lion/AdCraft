# 风格单元：中文对话小剧场（replica-dialogue）

> 单元自包含：本方案 + `brief.txt`（换台词）/ `brief-full-clone.txt`（整片复刻）+ 视频素材。

## 风格定位

双人正反打小剧场：A/B 两位"口播者"交替，中文大字幕，节拍为
钩子→反驳→证明→动摇→合流。考察**中文屏上文字识别**与对话节拍拆解；
也是 whisperX 词级锚定的首选素材（无语音合成条件下以字幕代台词）。

## 素材与真值

- 文件：`rep_dialogue_9x16_20s.mp4`（20s / 9:16 / 540×960@30）
- 音频：A/B 两种音高交替（440/330/470/350/550 Hz）

| 镜 | 时长 | 底色 | 屏上文字 |
|---|---|---|---|
| 1 | 4s | #7a3b2e | A：你敢信？ |
| 2 | 4s | #2e5a7a | B：我不信。 |
| 3 | 4s | #7a3b2e | A：它真的有用！ |
| 4 | 4s | #2e5a7a | B：那我试试！ |
| 5 | 4s | #5a2a7a | 合：冲！！（黄字） |

切点：0 / 4 / 8 / 12 / 16 秒。

## 用例与预期

| id | 内容 | 预期 |
|---|---|---|
| QC-03 | 质量 | 全过 |
| RT-03 | teardown 拆解（LLM，brief=换台词） | 镜头数 4-6；avg_shot 3.2-4.8s；中文台词被读出 |
| AD-01/AD-02 | `text/adreplica/valid_dialogue_cjk_anchors.adreplica` 用本片结构做 CJK 词锚验证 | 2 个词锚绑定；往返锁定 |

## 执行

```bash
cd apps/api && uv run python ../../test-materials/tools/run_tests.py --only QC-03,RT-03
```
