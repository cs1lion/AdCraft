# Dialogue / speech track (native fusion of project B's dialogue pipeline)

## Context

Fusion goal (grilled 2026-09-10): give AdCraft a dialogue-driven capability — voice casting, speech audio, subtitle handling — shared by `ad` and `short_film` content kinds (ADR 0002). Project B (piagent-glm video-agent) has a proven dialogue pipeline (voice cast → TTS → lip-sync clips → dubOver → subtitle burn → two-pass loudness) but ships it as a standalone Node seven-stage pipeline. We rejected importing that pipeline: AdCraft's Workflow v2 stays canonical and B's logic is translated into it natively.

Feasibility was verified against the codebase: AdCraft already has a complete local ffmpeg foundation — `app/tools/ffmpeg.py`, capability fingerprinting (`ready/degraded/unsupported`), encoder allow-lists, filter-graph compilation (`v2_final_composition_filters.py`), and the final composition renderer (normalize → concat → mix). Missing pieces are speech mixing and subtitle burn-in only.

## Decisions

1. **Native fusion.** New node type `voice-cast`, new asset type `speech_audio`, new slots — no second pipeline, no new service.
2. **Dual duration coupling.** Shot dialogue carries `duration_mode: bound | free`. `bound`: the TTS-measured duration drives the shot's timing. `free`: the speech track is arranged independently. The schema ships both from day one.
3. **Subtitle dual mode.** Preview/candidate stages use a soft subtitle track (srt/ass asset, player-rendered). Burn-in (drawtext/ass filter) happens only at final export. `final_composition_subtitle_font_path` already exists as the font hook.
4. **Full local processing.** Speech enters the filter graph as its own track with sidechain ducking of BGM; two-pass loudness normalization (measure with ebur128, then compensate — port of B's export semantics); line-duration estimation (~4 chars/second) and subtitle segmentation rules are ported as pure functions.
5. **QA registry, not ad-hoc checks.** A registry of automated pre-commit checks runs before an execution result commits back to selected asset versions. Phase-1 entries are pure ffmpeg probes (no LLM): TTS duration sanity, loudness targets, `bound`-mode speech-vs-shot duration comparison. The interface reserves a slot for B's plan-vs-actual shot-state verification (unscheduled; see appendix).
6. **Observable degradation.** Speech failure falls back to a subtitle-only composition and must emit a queryable event/marker. Silent fallbacks are forbidden. A's existing `fallback_class` / `recovery_mode` machinery is untouched; this is a speech-track-local backup path.

## Withdrawn candidates (recorded honestly)

- **Quota ledger (reserve/settle/release).** AdCraft has no metered billing surface; its existing "budgets" (`thinking_budget_tokens`, provider-conformance budgets) are agent compute budgets, not media spend. Deferred until multi-user quotas or cost dashboards become real requirements.
- **Confirmation gates.** Already covered: the `guidance_awaiting` kinds (`clarification`, `concept_selection`, `media_review`, `manual_node_run`, `milestone_idle`) plus `required_deferred_final_review` are a superset of B's two gates.
- B's LLM visual QA loop and the dual-gate follow-read check (envelope + ASR) stay phase 2 — a different magnitude of engineering than the speech track.

## 实施状态（2026-09-26 回填）

- **已落地**：`voice-cast` 节点（`CanvasNodeTypeV2` 成员）与 `speech_audio` 资产；SceneScript `speech_bindings` 的 `bound/free` 双模（bound 由 TTS 实测时长驱动镜头时序）；逐句 TTS（stepfun/fish_audio 引擎工厂）与 **unified 音频床**（StepAudio 3 Gen：roles+scripts+instruction 一次生成多角色对白/音效/环境音/BGM，`app/tools/step_audio_gen.py`）；**强制对齐**（WhisperX 词级 + 确定性估算回退，`speech_alignment.py`，`POST /scene-3d/align-speech`，置信度可查询）；**台词→唇形闭环**（`dialogue_lipsync_service.py`：实测/对齐/估算三源时长，summary 声明来源）；**字幕**（软轨 SRT/ASS + 成片 ASS 烧录 + 按唇形同一边界上字幕轨、幂等替换；2026-09-26 起 cues 随唇形应用同手势发布，重发布仍是替换）；**混音闪避**（随 ADR 0007 时间线落地）；3D 视口台词浮层 + 唇形可见 + animatic 音频。
- ****§5 第二半（推广到其它模态）已落地**（2026-09-27）：`QaSubject` 扩展 image/video 路径，`services/dialogue/media_qa_checks.py` 四条内容检查（图像短边下限 / 近乎纯色 FAIL / 视频短边下限 / 成片时长 vs 请求时长：不足一半 FAIL、偏差超 25% WARN、无法比较 WARN），由 `MediaNodeExecutor._media_qa_gate` 在节点 ready 前跑——跑不动的检查降级为 WARN 并说明原因（跳过 ≠ 通过）；audio 故意不走这条（它的提交前检查是语音 registry）。registry 本身永不决定阻塞：它报告，拥有提交的一方把裁决变成决定。
- QA registry 已建**（2026-09-26，决策 §5 的第一半）：`app/services/dialogue/v2_qa_registry.py`（有序注册、重名响亮失败、pass/warn/fail + 结构化 details）+ `speech_qa_checks.py` 四条 phase-1 条目（时长合理性 / bound 台词 vs 镜头 / 时间线一致性收编 / 真实 ebur128 响度），报告经 `qa_report` 发布在唇形 summary（可查询）。**§14.7 五层可编辑性**：内容层（B 模式重测）/ 时间层（起句时间）/ 同步层（词级唇形）/ 结构层（行序对调）// 表演层已补完（2026-09-27）：`audio_bed` 逐行 `emotion` 字段贯通（后端 `build_step_audio_gen_payload` 渲染成 provider 的 `(情绪)` 注释并校验歧义/括号/长度，前端 `AudioBedEditor` 每行一个情绪输入、`validateAudioBedConfig` 与后端逐条对应）——"这一句是哭着的"有了去处。**逐句路径已落地**（2026-09-27）：`dialogue/voice_cast_lines.py`（逐行 Audio Event + 内容寻址缓存 + `regenerate_line_ids`）与 `audio_concat.py`（拼接/探时长，均为 seam）+ 执行器 `_run_per_line_dialogue`：改动一句只重做那一句（未动的句子沿用已有录音，不重复计费），每行时长与起点随 `dialogue_line_manifest` 发布（量不到的那行之后 offset 不再声称已知）；前端 `VoiceCastDialogueLines` 在保存前就把"几句沿用、几句重做"说清楚。§14.7 五层至此全部有入口
**提交前阻断钩子已接**（2026-09-26）：`VoiceCastNodeExecutor` 在返回执行结果前对引擎写出的音频跑登记处——fail（新增响度 fail 档：整体响度 < -60 LUFS = 这一轨几乎是静音，不是可提交的录音）→ `voicecast_qa_failed` coded error 带整份报告；warn → `voicecast_qa_report` 发布为可查询标记；全过 → 无声。mock fixture 不探测（说明见代码）。**仍开放**：把同一钩子推广到 v2 生产链其他模态的提交路径（跨管线行为变更，需单独评审）；音素级唇形——已从音节级节拍器升级为**词级唇形**（whisperX 词级时间戳驱动，`word_mouth_frames`；无词级数据时保持节拍器，严格增量）；真音素级 viseme 仍是开放项。**低置信对齐句的 B 模式自动重生成已落地**（2026-09-26：`regenerate_low_confidence_segments`——保留对齐起句、逐句重测时长、钳制防重叠、来源 measured/estimated 可查询；端点默认开启、可 opt-out；对齐面板有汇总与逐句徽章）。
- 施工分解见 `docs/plans/blender-mcp-white-model-mode-and-audio-collaboration.md`（P1–P5 逐项带勾选）。

## Provider layer support

The speech track's TTS provider (first choice: stepfun `stepaudio-2.5-tts`, openai-compatible) is registered in the trusted model catalog, and the provider layer adopts B's pool patterns: multi-key pools, per-key concurrency, min-interval rate limiting, a unified poll-protocol template, global concurrency cap, and attempt-bounded retries. Credentials live only in the config center / environment.

## Appendix (recorded, unscheduled): stateful storyboard (P5)

Project B's storyboard design treats a storyboard as "a shot sequence with state records". Worth re-evaluating after phase 1, specifically for `short_film`:

- Three-layer separation: fixed setup (asset references) / **mutable state** (position, holder, door open/closed, hand occupancy, mood) / cinematography. AdCraft has the fixed layer (asset references + must-use bindings) and cinematography fields, but no mutable-state layer.
- Explicit shot-relation enums: temporal (continue / overlap / elide / flashback), spatial (same-location re-angle / follow migration / location switch), action, and sound relations.
- Plan-vs-actual dual track: the scripted end-state is a claim to verify against generated keyframes; conflicts are regenerated before the error propagates. This is the storyboard-shaped instance of the QA-registry entry reserved in decision 5.
- Epistemic clauses (occlusion ≠ disappearance; screen position ≠ world position) as prompt-contract lines.
- UI: editing an upstream shot marks affected downstream shots for user-confirmed propagation.