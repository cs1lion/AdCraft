# 终极演示运行：测试方法与教训（2026-10-09 会话浓缩）

> 范围：`ultimate-demo-20261009` 这一轮测试的执行方法、可取之处、必须汲取的教训。写给后续继续本项目测试的人（人或 agent）。
> 原则沿用《终极演示》：真实数据支撑结论，失败与替代不隐藏，不把编码成功当产品链路成功。

## 1. 前因后果（这一轮在做什么）

任务：验证 myAdcraft 产品能完成"两人群互动剧本 V1→V2 局部修改 → 白模预演 → AI 成片"全链路，分两组平行场景（S1 酒庐推筹码 / S2 庭院点名），每组 V1/V2 各 10 秒 300 帧。第一阶段只交付白模对比视频，第二阶段才生成 AI 成片。

上一会话在正式 native 渲染途中被 provider 流 429 打断，且它启动的隔离服务随会话一起死亡。本会话从"服务全断、执行器误报失败"的状态恢复，最终：6/6 正式渲染 READY、Q05 复现字节级一致、输入门槛通过、三段白模对比视频装配并通过技术验收、Root 观片确认（PHASE1_PASS）。第二阶段用 `agnes-video-2.5-flash` 跑成片时，节点/绑定/提示词就绪，但 provider 视频队列持续满（503 video_queue_full），三次有界重试均失败，成片生成暂停待队列恢复。

## 2. 可取的地方（继续这样做）

1. **可恢复的证据驱动工具链**：执行器从输出目录的 ledger 续跑；每个论断挂在哈希证据上；失败Attempt 逐个留痕（`failure-attempt-N.json`）。中断不可怕，可怕的是不能从中断点诚实恢复。
2. **机器可验与人工验收分离**：能脚本判定的（帧数、血缘、语义 diff、持久化）全部脚本判定；必须人看的（视频观感、截图内容）明确标记 PENDING 并记录 Root 原话与范围，从不互相冒充。
3. **先证明确定性再解读差异**：Q05 用同一冻结场景重渲，300/300 字节一致后才分析 V1/V2 差异——由此识别出 53–89 帧约 61dB 的差异只是 x264 前视量化噪声，没有误判成"锁定段被破坏"。
4. **校验器误报先证事实再改校验**：两处校验器误判（终态事件载荷、同值 1.0/1）都是先确认产品侧事实无误，再把校验器修到能识别产品真实行为，并补/跑单测（19+18 全过），不是放宽门槛。
5. **缺口如实记录不粉饰**：S1 Q06 界面采集、S1-V1 可读截图因前端画布反复不可用而未完成，作为 P3 记录项写进报告，不影响 PHASE1_PASS 判定但绝不删除。
6. **flash 严格串行**：视频生成节点逐个提交、就绪后再下一个（30s 间隔），避免 429 和节点卡 working。

## 3. 必须汲取的教训

1. **会话启动的服务随会话死亡**。任何中断后第一步是查端口（8010/5190/8770）并用本 run 的 `start-isolated.py --start` 重启；运行时数据在 `00-admin/runtime-data`，项目/资产/执行不丢。不要看到"API 连不上"就怀疑产品坏了。重启后按 run 纪律建新 evidence 目录 + `restart-input-delta.json`，并确认渲染配置逐项一致。
2. **校验器会对产品的真实行为误报，两类已遇到**：
   - 终态事件有两种真实载荷（reconcile 路径 `payload.after_status`、result-commit 路径 `payload.execution_status`），只认一种会把已成功的执行误报失败；
   - UI 保存会把同值 `1.0` 序列化成 `1`、`-0.0` 成 `0`，裸 `json.dumps` 比较会误报"身份/外观变化"（仓库 `scene-semantic-compat.py` 有明文约定）。
   教训：checker 拒绝时，先用产品自身事实（节点状态、事件、值相等性）证伪/证实，再决定改哪里；改校验器必须让它识别产品全部真实形态并留测试。
3. **不要发明带凭证形状后缀的元数据键**。绑定 metadata 里的 `source_formal_key` 以 `_key` 结尾，被 run-intent snapshot 校验器按后缀身份拦截（只有 `*_id` 和 `design_key` 豁免），整个 run 提交 500。用 `formal_version` 这类中性名；已建的绑定用 `PATCH .../bindings/{id}` 修补。
4. **建节点前先读该角色的内容 schema**。`storyboard_video` 要求 `VideoSegmentContentV2`（segment_summary/duration_seconds/storyboard_content/style…），schema 是 `extra=forbid`，自定义字段直接 422。风格指令放 `style.style_prompt` + `negative_style_constraints`，这是产品的正式位置。
5. **Provider 容量是一等失败模式**。agnes 视频队列满时返回 503 `video_queue_full`（"safe to retry as-is"）。对策：有界重试（本次 3 次）+ 退避（150s/300s）+ 每次失败留痕；不要 tight-loop。批量提交前先探队列；持续满时换时段或换 SKU（非 flash 的 `agnes-video-2.5` 接受 videos 参数，flash 只接受 images）。
6. **flash 的 `reference_limits.video=0` 是设计事实不是 bug**。预演片段会被 ADR 0017 机制替换为≤5 张已发布关键帧（images_only，`previs_clip_keyframes_substituted` 可查询）。提示词必须把风格写足（关键帧只管构图），否则出片带白模质感——这是既往实测经验。
7. **前端画布会反复进入"节点未测量"状态**（xyflow 对无 measured 尺寸的节点设 visibility:hidden，全部不可点）。可靠恢复只有两条：点 "Organize canvas"，或等时间线加载后点视频轨预演片段进焦点视图。UI 证据采集要有降级路径：DOM 状态 + API 语义核验 + 明确声明截图内容待 Root 复核。
8. **验收 JSON 是 Root 的权威，只能填实际发生的事**。本轮的填写方式：逐字段挂 Root 原话（记录时间、范围）与机器证据哈希；模板的 PENDING 状态不被复制成 PASS。用户一句"可以推进了/效果 ok"要连同范围一起记录，不扩大解释。

## 4. 当前状态与下一步（2026-10-09 收工处）

- 第一阶段：**PHASE1_PASS**（Root 确认）。三段交付视频在 `05-evidence/phase1-delivery-v4/`（S1/S2 各 40s + 80s 合集，1080p/30fps，1200/1200/2400 帧，解码零错误）。
- 第二阶段：4 个 FINAL 视频节点已建并绑定正式预演片段（node id 见 `05-evidence/phase2-finals-v4/phase2-ledger.json`），提示词/参数（10s/720p/16:9/无音频）就绪；S1-V1 三次提交均因 provider 视频队列满失败，S1-V2/S2-V1/S2-V2 尚未提交。
- 继续方式：队列恢复后重跑 `phase2-final-executor.py`（幂等：已 READY 的 job 跳过，failed 节点走 retry_failed 有界重试）；每次重跑都要核对 provider 实际消费（resolved input manifest 应显示 5 张关键帧走 images 通道）。四段成片到齐后做预演-成片一致性初验（事件时刻、互动方向、身份稳定），再按手册决定 T12–T15。
