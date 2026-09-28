# 场景单元：刻意含糊负例（scene-vague-negative）

> 单元自包含：本方案 + `nl.txt`。对齐 3D 预演用户指南 §2 的 "too vague"
> 反例——信息缺失输入（A room / Some people / They do things）。

## 用法与预期

**不预设 PASS/FAIL**。记录系统兜底行为：
- 是反问/提示补全，还是用默认值填充？
- 若填充，SceneScript 里哪些字段是默认值、能否被用户辨识？
- 结果作为输入引导 UX（勘察缺口）的证据记入 `results/3d-previs-runlog.md`。

## 执行

agent 判读用例；这是负例资产，勿删。
