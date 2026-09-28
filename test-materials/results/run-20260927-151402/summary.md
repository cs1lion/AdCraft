# 测试运行 run-20260927-151402

- 时间：2026-09-27T15:14:02.318491+00:00
- 后端：http://127.0.0.1:8000（local 套件不依赖）
- 结果：**PASS 2 / FAIL 1 / SKIP 0**
- 退出码：1

| 用例 | 套件 | 状态 | 耗时 | 标题 | 说明 |
|---|---|---|---|---|---|
| RT-IM | api-replica | PASS | 0.05s | 3 正例 .adreplica 经 API 导入 | {"valid_luxury_16x9.adreplica": {"slots": 6, "applied": 3}, "valid_textonly_1x1.adreplica": {"slots": 6, "applied": 0},  |
| RT-DE | api-replica | PASS | 0.01s | 纯字幕蓝图直出门 feasible | {"feasible": false, "zero_model_steps": 3, "generation_steps": ["{'step': 'shot_1', 'detail': '镜头画面需生成（有画", "{'step': 's |
| RT-INST | api-replica | FAIL | 1.45s | 蓝图实例化：项目→节点→script+绑定 | HTTP 503 | detail={'code': 'canvas_node_conflict', 'message': 'Agent Canvas persistence conflict.', 'details': {}} |

## 重跑失败用例

```bash
python tools/run_tests.py --only RT-INST
```
