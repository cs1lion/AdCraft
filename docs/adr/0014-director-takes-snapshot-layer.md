# ADR 0014 — 导演 takes 快照层（V3）

## 状态

Accepted（V3 take 快照层已落地）

## 背景

V3 阶段要支持"先拍给你看、再比选"的导演工作方式：同一个口令链可能产出多条候选
（take），导演用"用左边那个"选定，而不是一次性答题。需要一个轻量快照层，
让每条口令链的当前场景状态可被保存、对比、恢复。

## 决策

- 新增 `apps/api/app/services/scene3d/director_takes.py` 与前端
  `apps/web/src/features/agent-canvas/canvas/directorTakes.ts`（镜像模型）：
  `DirectorTake` = `{id, label, scene_script（整脚本 JSON）, operations（ops diff）, frame}`。
- 上限 4 条（与 transition variants 同量级，take 是"对比"而非"版本控制"）。
- 持久化在节点 `structured_content["director_takes"]`，沿用 transition variants 的
  `parseXxx/serializeXxx + patchNode({coalesce: true})` 模式。
- 前端 `SceneScript3DEditor` 增加 `takes` / `onSaveTake` 属性：工具栏"存 take"按钮
  把当前 `sceneScript` + 播放头帧存为一条 take；take 列表提供"恢复"按钮，
  直接 `onChange(take.scene_script)` 整脚本回写。
- 解析容错：缺 `scene_script` 的 take 直接跳过（恢复空白场景比丢一条 take 更糟）。

## 不变式（与 ADR 0012 一致）

LLM/对话层只吐 ops 补丁 + 可选澄清，从不吐自由脚本；take 是 UI 侧的快照记录，
整脚本快照是"可回滚基线"，ops diff 是"可回放记录"——两者并存，恢复走整脚本，
重演走 ops diff。

## 后果

- 正面：导演可"先拍再比选"，恢复/对比零成本；take 上限小，节点体积可控。
- 代价：整脚本快照冗余（4 × 场景大小），但白模场景 JSON 体量小，可接受。
