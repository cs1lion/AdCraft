# 测试运行 run-20260927-151154

- 时间：2026-09-27T15:11:54.033385+00:00
- 后端：http://127.0.0.1:8000（local 套件不依赖）
- 结果：**PASS 5 / FAIL 2 / SKIP 10**
- 退出码：1

| 用例 | 套件 | 状态 | 耗时 | 标题 | 说明 |
|---|---|---|---|---|---|
| RT-IM | api-replica | PASS | 0.07s | 3 正例 .adreplica 经 API 导入 | {"valid_luxury_16x9.adreplica": {"slots": 6, "applied": 3}, "valid_textonly_1x1.adreplica": {"slots": 6, "applied": 0},  |
| RT-DE | api-replica | FAIL | 0.04s | 纯字幕蓝图直出门 feasible | 纯字幕蓝图 feasible=true 且无必须生成环节 |
| RT-VAR | api-replica | PASS | 0.09s | 风格变体同参确定性 | {"count": 3, "first": "{'variant_id': 'variant_78e6e7f87d15', 'skill_ids': ['one-take-commercial'], 'names': ['一镜到底空间广告' |
| RT-CHAIN | api-replica | SKIP | 1.95s | 报告→蓝图→导出→重编译全链（LLM×1） |  |
| RT-01 | api-replica | SKIP | 1.93s | teardown 拆解 rep_fastcut_9x16_15s.mp4（LLM） |  |
| RT-04 | api-replica | SKIP | 1.84s | teardown 拆解 rep_textonly_1x1_10s.mp4（LLM） |  |
| RT-06 | api-replica | SKIP | 2.37s | teardown 拆解 rep_beatsync_9x16_16s.mp4（LLM） |  |
| RT-12 | api-replica | PASS | 0.14s | 61s 超长片 teardown 拒绝 | "HTTP 400 | detail={'error': 'Video too long: 61.0s (max 60s for a teardown)', 'error_type': 'input'}" |
| RT-INST | api-replica | FAIL | 1.19s | 蓝图实例化：项目→节点→script+绑定 | HTTP 428 | detail={'code': 'workflow_precondition_required', 'message': 'If-Match is required for workflow mutations.',  |
| RT-LINK | api-replica | SKIP | 0.0s | 链接下载（未提供 --link-url） | 未提供 --link-url，跳过网络下载用例 |
| S3-UP | api-scene3d | PASS | 1.11s | 上传参考视频（共用入口，无 LLM） | {"asset_id": "ref_5a977e69f02f", "duration": 15.02322} |
| S3-DEPS | api-scene3d | PASS | 9.33s | 深度依赖探测（MiDaS/timm） | "" |
| S3-IMG | api-scene3d | SKIP | 0.62s | 单图场景分析 room（LLM） |  |
| S3-PANO | api-scene3d | SKIP | 0.47s | 全景 2:1 触发立方体切分（LLM） |  |
| S3-ORBIT | api-scene3d | SKIP | 0.28s | 6 图多视角融合（LLM） |  |
| S3-REF | api-scene3d | SKIP | 1.5s | 参考视频→SceneScript（LLM，1-2 分钟） |  |
| S3-DEPTH | api-scene3d | SKIP | 0.0s | 视频深度提取（默认跳过） | 加 --with-depth 也仅提示手动步骤；依赖探测见 S3-DEPS |

## 重跑失败用例

```bash
python tools/run_tests.py --only RT-DE,RT-INST
```
