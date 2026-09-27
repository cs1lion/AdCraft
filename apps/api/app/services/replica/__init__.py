"""拉片复刻（Replica）服务包。

当前最小可用切片：**参考片拉片拆解**（teardown）——把用户上传的参考视频
拆解成结构化拆解报告（整片解读 / 结构 Beats / 镜头表 / 节奏 / 视觉系统），
并生成一份可直接进入正常创作流的"复刻分镜草稿"。

- ``teardown.py``：参考视频 → 多模态读片 → 结构化拆解报告 + 复刻分镜草稿；
- ``blueprint.py``：拆解报告 → 可编辑复刻蓝图（槽位/锚点/实例化计划）；
- ``adreplica.py``：蓝图 ↔ ``.adreplica`` 标记文本（hypit "文件即真相源"）。

设计理念借鉴 hypit（github.com/hypit-ai/hypit）：
- 读片 = 整片读法 + 细节读法互相修正（hypit skill: references/creation/reference-video.md）；
- 产出 = 可编辑的结构而非一次性描述（hypit 的 Script/组件化思想）；
- 复刻"关系"而非"像素"：镜头边界与运动为基于稀疏抽帧的推断值。

完整方案论证见 docs/plans/hypit-replica-research.md。
"""
