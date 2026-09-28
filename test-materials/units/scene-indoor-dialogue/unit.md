# 场景单元：茶馆室内对话（scene-indoor-dialogue）

> 单元自包含：本方案 + `nl.txt`（自然语言模板）。基准用例：五要素齐全
> （SCENE/CHARACTERS/ACTION/CAMERA/STYLE），3 角色 + 入场走位 + 三段镜头。

## 用法与预期

1. 前端 scene-3d 节点 → 自然语言描述，粘贴 `nl.txt` 中 SCENE 起的正文。
2. 核对 SceneScript：3 角色站位（A 左、B 对面、C 门口）；走位（门→桌边）；
   镜头序列 全景→中景→特写；空间词（中央/背景/左侧）落位一致。
3. 记录 `previs_control_level` 降级级别。

## 执行

agent 判读用例（走 LLM 叙事链路，无硬断言）；结论写入 `results/3d-previs-runlog.md`。
横切前置与降级语义见 `plans/3d-previs-plan.md`。
