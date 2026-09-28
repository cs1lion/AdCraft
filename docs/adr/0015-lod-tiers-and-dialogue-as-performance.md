# ADR 0015 — 场景精细度阶梯（LOD）与台词即表演（V3 ④）

## 状态

Accepted（V3 ④ LOD + dialogue-as-performance 已落地）

## 背景

V3 计划里的最后两块：让白模场景"动起来"而不依赖骨骼动画，以及让"说"和"演"共用一条
时间线。之前的对话即只产生唇形（`talk` 关键帧），身体的表演（抬手/前倾/摇头）没有
任何可复用的程序化路径；对象的粗细（LOD）也没有在 Schema 里留下任何可查询的痕迹。

## 决策

- **LOD 阶梯**（`scene_fidelity.py`）：`rough / standard / detailed` 三档，`rough` 在
  预览里降级为单个原语。`camera_view_candidates` 用每个镜头中点处的相机视锥做纯
  几何筛选（无渲染、无资产），返回"离相机近且在镜头里"的对象——即"值得细化"的
  候选。该函数可放在预览、闸门或渲染前任意位置调用。
- **台词即表演**（`gesture_performance.py`）：`apply_gestures=True` 传给
  `/dialogue-lipsync` 时，把 `SpeechSegment` 的语调/情绪包络翻译成程序化手势关键帧
  （`gesture` 动作）：
  - 强烈情绪（angry/sad/fear 等）→ 句头 +15° 前倾、句尾复位
  - 否定/强调词（不/别/no/don't 等）→ 句中 3 帧摇头（−12°/+12°/0°）
  - 手势关键帧走与唇形完全相同的插值/合并机制（`_interpolated_pose_at`），
    只"叠在已写好的路径上"，绝不改变走位/朝向。
  - 预览里 `LowPolyHuman` 读 `gesture` 动作把整个头 group 向前倾斜 ≈15°；
    唇形（`talk`）与手势（`gesture`）两个动作在视觉上分开。
- **单一事实源**：手势和唇形共用同一份 `SpeechTimeline`/`SpeechSegment` 列表，
  "说多久 → 演多长"与"说多久 → 唇形多长"共用一套算术，不另起炉灶。

## 不变式

LLM/对话层只吐 ops 补丁，从不吐自由脚本（ADR 0012）。`set_lod_tier` 是新的
ops 词汇表条目；手势关键帧走 `add_keyframe`（action=`gesture`），全部在闸门
之后应用。整场景快照（takes）与 ops diff 并存（ADR 0014）——"恢复这个版本"
走整脚本快照，"重演这条口令"走 ops diff，两者的契约不变。

## 后果

- 正面：白模场景在台词驱动下第一次有"身体在演"的能力（抬手/前倾/摇头），
  且完全由数据驱动，不需要任何骨骼/模型升级；LOD 让"哪个对象值得细化"
  变成一个可查询的几何答案而不是经验判断。
- 代价：手势关键帧会增大 keyframe 列表（每段台词最多 +5 帧），但白模场景
  关键帧体量本来就小，可接受。`camera_view_candidates` 是每镜头 30°-120° 视锥
  的纯点积筛选，无渲染开销。
