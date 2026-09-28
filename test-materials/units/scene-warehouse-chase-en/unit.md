# 场景单元：英文仓库追逐（scene-warehouse-chase-en）

> 单元自包含：本方案 + `nl.txt`（全英文模板）。语言覆盖用例：
> 英文空间词（left/right/deep/far end）与运动词（dodge/peek/track）的解析。

## 用法与预期

1. 粘贴 `nl.txt` 正文（英文）。
2. 核对：SceneScript 与中文模板同等结构化；仓库货架窄巷空间；追逐走位；
   低角度开场 + 跟踪 + 特写的镜头序列。
3. 对照 `scene-indoor-dialogue` 的结果记录中英文解析质量差异（若有）。

## 执行

agent 判读用例；结论写入 `results/3d-previs-runlog.md`。
