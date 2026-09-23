# F1: 语音轨道落地主工作流 - 实施计划

> 基于 ADR 0003 (dialogue-speech-track) 的分阶段实施计划

## 现状分析

### 已有基础（scene3d 模块）
- ✅ `speech_orchestration.py` - SpeechSegment / SpeechTimeline / LipSyncGenerator
- ✅ `stepfun_tts.py` - StepFun TTS 引擎
- ✅ `fish_audio_tts.py` - Fish Audio TTS 引擎
- ✅ `tts_engine_factory.py` - TTS 引擎工厂
- ✅ SceneScript 中的 `speech_bindings` 字段

### 缺失部分（主工作流集成）
- ❌ `voice-cast` 节点类型（后端 schema + executor）
- ❌ `speech_audio` 资产类型
- ❌ 前端 `voice-cast` 节点 UI 和 workbench
- ❌ 语音混音到最终视频
- ❌ 字幕生成和烧录

## 实施阶段

### 阶段 1: 数据模型和节点类型（后端）
**目标**：创建 voice-cast 节点类型和 speech_audio 资产类型的基础 schema

1. **Schema 定义**
   - `VoiceCastNodeV2` - 节点数据（角色列表、台词、语音设置）
   - `SpeechAudioAssetV2` - 语音资产（音频文件、时长、说话人、情绪）
   - `SpeechSegmentV2` - 单段台词（角色、文本、开始时间、结束时间、情绪）

2. **节点类型注册**
   - `agent_canvas.py` 添加 `voice-cast` 到 `CanvasNodeTypeV2`
   - `agent_canvas_ad_media.py` 添加 `voice_cast` 角色定义
   - `nodeDefaults.ts` 添加前端默认配置

3. **连接策略**
   - `agent_canvas_connection_policy.py` 添加 voice-cast 的输入输出规则
   - 输入：script（text_context）、character（image_reference）
   - 输出：speech_audio（audio_reference）

### 阶段 2: TTS 生成 Executor（后端）
**目标**：实现 voice-cast 节点的执行逻辑，调用 TTS 生成语音

1. **Executor 实现**
   - `agent_canvas_node_execution.py` 添加 `execute_voice_cast`
   - 解析节点中的台词列表
   - 调用 TTS 引擎生成每段语音
   - 合并多段语音为单个音频文件
   - 保存为 speech_audio 资产

2. **TTS 引擎集成**
   - 复用现有的 `tts_engine_factory.py`
   - 支持多角色多音色（通过 voice 参数）
   - 支持情绪提示（通过 SSML 或 prompt）

3. **时长计算**
   - 生成后测量每段语音的实际时长
   - 支持 `bound` 模式（TTS 时长驱动分镜时长）
   - 支持 `free` 模式（语音轨道独立排列）

### 阶段 3: 前端 UI 和 Workbench（前端）
**目标**：用户可以在画布上创建和编辑 voice-cast 节点

1. **节点卡片**
   - `AgentCanvasNode.tsx` 支持 voice-cast 类型
   - 显示角色列表和台词数量
   - 显示音频播放控件

2. **Workbench**
   - 创建 `VoiceCastWorkbench.tsx`
   - 台词列表编辑器（添加/删除/编辑台词）
   - 角色和音色选择
   - 情绪选择
   - 试听按钮
   - 生成按钮

3. **音频播放器**
   - 复用现有的 `AgentCanvasAudioPlayer.tsx`
   - 支持分段播放和时间轴

### 阶段 4: 语音混音和字幕（渲染管线）
**目标**：将语音轨道混合到最终视频，支持字幕

1. **语音混音**
   - `v2_final_composition_filters.py` 添加语音轨道
   - 支持 BGM 闪避（sidechain ducking）
   - 响度归一化（EBU R128）

2. **字幕生成**
   - 从 speech_audio 资产生成 SRT/ASS 字幕
   - 支持软字幕（播放器渲染）和硬字幕（烧录）
   - `final_composition_subtitle_font_path` 已存在

3. **导出选项**
   - 导出时选择是否烧录字幕
   - 导出时选择是否包含语音轨道

### 阶段 5: 3D 预演集成（可选）
**目标**：语音驱动口型同步

1. **LipSync 集成**
   - 复用 `speech_orchestration.py` 中的 `LipSyncGenerator`
   - 将语音关键帧合并到 SceneScript
   - Blender 渲染时应用口型动画

2. **音素级同步**
   - 支持 Rhubarb Lip Sync 或 Oculus LipSync
   - 替代当前的音节级同步

## 优先级和依赖关系

```
阶段 1 (数据模型) → 阶段 2 (TTS Executor) → 阶段 3 (前端 UI)
                                          ↓
                                    阶段 4 (混音字幕)
                                          ↓
                                    阶段 5 (3D 口型，可选)
```

## 验收标准

### 阶段 1
- [ ] 可以通过 API 创建 voice-cast 节点
- [ ] 节点可以保存和读取
- [ ] 连接策略正确（script→voice-cast→video）

### 阶段 2
- [ ] voice-cast 节点可以执行（调用 TTS）
- [ ] 生成的语音保存为资产
- [ ] 多段语音可以合并

### 阶段 3
- [ ] 前端可以创建 voice-cast 节点
- [ ] Workbench 可以编辑台词
- [ ] 可以试听生成的语音

### 阶段 4
- [ ] 最终视频包含语音轨道
- [ ] 支持字幕烧录
- [ ] BGM 闪避正常工作

## 风险和注意事项

1. **TTS API 配额**：TTS 生成可能消耗大量配额，需要限流和缓存
2. **音频格式兼容**：不同 TTS 引擎返回的音频格式可能不同，需要统一转码
3. **时长同步**：bound 模式下语音时长会影响分镜时长，需要和视频生成协调
4. **多角色音色**：需要维护角色到音色的映射，支持用户自定义
5. **字幕时间轴**：字幕时间轴需要和语音精确对齐，可能需要强制对齐（forced alignment）

## 当前进度

- [x] 阶段 1: 数据模型和节点类型（后端schema + 前端类型 + 节点默认配置 + 图标）
- [x] 阶段 2: TTS 生成 Executor（execute_voice_cast函数 + dispatcher集成 + 连接策略 + 角色注册）
- [ ] 阶段 3: 前端 UI 和 Workbench
- [ ] 阶段 4: 语音混音和字幕
- [ ] 阶段 5: 3D 预演集成（可选）
