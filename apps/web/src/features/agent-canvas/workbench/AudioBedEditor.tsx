/**
 * Audio Bed Editor — the voice-cast node's unified-audio authoring surface.
 *
 * One screen to compose a finished audio bed the way a sound director would
 * brief it: roles (who speaks, and how), scripts (lines and [sfx/ambience/
 * bgm] cues in performance order), and an instruction that sets the room's
 * mood. Save PATCHes the node's structured_content (merging — other keys
 * survive) and the node's unified mode generates the bed in one call.
 *
 * Validation mirrors the backend rules exactly (audioBedConfig), so the
 * editor never lets a save through that the executor would reject; the
 * char-budget readout surfaces the documented provider limits before the
 * request, not as a 400 afterwards.
 */

import { useCallback, useEffect, useMemo, useState } from "react";

import type { CanvasNodeV2 } from "../../../types-v2.ts";
import type { PatchNode } from "./workbenchTypes.ts";
import {
  AUDIO_BED_CONTENT_KEY,
  AUDIO_BED_MAX_EMOTION_CHARS,
  AUDIO_BED_RESPONSE_FORMATS,
  audioBedCharBudget,
  emptyAudioBedConfig,
  parseAudioBedConfig,
  serializeAudioBedConfig,
  validateAudioBedConfig,
  type AudioBedConfig,
  type AudioBedRole,
  type AudioBedScript,
  type AudioBedIssue,
} from "./audioBedConfig.ts";
import "./audio-bed-workbench.css";

export interface AudioBedEditorProps {
  node: CanvasNodeV2;
  patchNode?: PatchNode;
}

export function AudioBedEditor({ node, patchNode }: AudioBedEditorProps) {
  const persistedRaw = useMemo(
    () => node.structured_content?.[AUDIO_BED_CONTENT_KEY],
    [node],
  );
  const persisted = useMemo(() => parseAudioBedConfig(persistedRaw), [persistedRaw]);
  const [config, setConfig] = useState<AudioBedConfig>(
    () => persisted ?? emptyAudioBedConfig(),
  );
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Upstream changes (rerun/replace) re-seed the draft, but never clobber
  // unsaved local edits.
  useEffect(() => {
    if (!persisted) return;
    setConfig((current) =>
      JSON.stringify(current) === JSON.stringify(persisted) ? current : persisted,
    );
  }, [persisted]);

  if (!patchNode) return null;

  const issues: AudioBedIssue[] = validateAudioBedConfig(config);
  const serialized = serializeAudioBedConfig(config);
  // Like with like: the serialized payload (what a save would write)
  // against the raw persisted block (what is on the node now).
  const dirty = JSON.stringify(serialized) !== JSON.stringify(persistedRaw ?? {});
  const budget = audioBedCharBudget(config);
  const roleNames = config.roles
    .map((role) => role.name.trim())
    .filter((name) => name.length > 0);

  const save = async () => {
    setSaving(true);
    setError(null);
    try {
      await patchNode(node.node_id, {
        // Merge, never replace: prompt and other keys must survive.
        structured_content: {
          ...node.structured_content,
          [AUDIO_BED_CONTENT_KEY]: serialized,
        },
      });
    } catch (saveError) {
      setError(saveError instanceof Error ? saveError.message : "保存失败，请重试。");
    } finally {
      setSaving(false);
    }
  };

  return (
    <section className="audio-bed" aria-label="音频床编辑器">
      <div className="audio-bed__hint">
        <strong>音频床（unified）</strong>
        <span>
          roles 定义音色，scripts 按表演顺序写台词与 [音效/环境音/BGM]；一次调用生成整段音频。
          床音<strong>不包含逐句时间戳</strong>——镜头级唇形对齐需另外生成逐句语音。
        </span>
      </div>

      <fieldset className="audio-bed__roles">
        <legend>
          角色音色 <span className="audio-bed__count">{roleNames.length}</span>
        </legend>
        {config.roles.length === 0 && (
          <p className="audio-bed__empty">还没有角色。纯 BGM/音效床可以不加角色。</p>
        )}
        {config.roles.map((role, index) => (
          <div className="audio-bed__role-row" key={`role-${index}`}>
            <input
              aria-label={`角色 ${index + 1} 名称`}
              placeholder="名称（如：林澈）"
              value={role.name}
              onChange={(event) => updateRole(setConfig, index, { name: event.target.value })}
            />
            <input
              aria-label={`角色 ${index + 1} 音色描述`}
              placeholder="音色描述（如：二十多岁男性，嗓音低沉冷静）"
              value={role.description}
              onChange={(event) =>
                updateRole(setConfig, index, { description: event.target.value })
              }
            />
            <input
              className="audio-bed__role-character"
              aria-label={`角色 ${index + 1} 场景角色 ID`}
              placeholder="场景角色 ID（可选，台词驱动唇形用）"
              title="bed 只存 name/description；这个 ID 是本地的桥：台词对齐时把该角色的话映射到场景里的同名角色"
              value={role.character_id}
              onChange={(event) =>
                updateRole(setConfig, index, { character_id: event.target.value })
              }
            />
            <button
              type="button"
              aria-label={`删除角色 ${index + 1}`}
              onClick={() =>
                setConfig((current) => ({
                  ...current,
                  roles: current.roles.filter((_, i) => i !== index),
                }))
              }
            >
              ×
            </button>
          </div>
        ))}
        <button
          type="button"
          className="audio-bed__add"
          onClick={() =>
            setConfig((current) => ({
              ...current,
              roles: [...current.roles, { name: "", description: "", character_id: "" }],
            }))
          }
        >
          + 角色
        </button>
        <p className={budget.rolesChars > budget.rolesLimit ? "audio-bed__budget is-over" : "audio-bed__budget"}>
          name+description 合计 {budget.rolesChars}/{budget.rolesLimit} 字符
        </p>
      </fieldset>

      <fieldset className="audio-bed__scripts">
        <legend>
          脚本 <span className="audio-bed__count">{config.scripts.length}</span>
        </legend>
        {config.scripts.map((script, index) => (
          <div className="audio-bed__script-row" key={`script-${index}`}>
            <select
              aria-label={`脚本 ${index + 1} 说话人`}
              value={script.speaker}
              onChange={(event) =>
                updateScript(setConfig, index, { speaker: event.target.value })
              }
            >
              <option value="">[音效/BGM]</option>
              {roleNames.map((name) => (
                <option key={name} value={name}>
                  {name}
                </option>
              ))}
            </select>
            <textarea
              aria-label={`脚本 ${index + 1} 内容`}
              placeholder="台词或 [环境音/BGM 描述]（情绪写在右侧一栏，不要再用括号）"
              value={script.text}
              onChange={(event) =>
                updateScript(setConfig, index, { text: event.target.value })
              }
            />
            {/* 表演层 (§14.7): 每一句都能带情绪。写成字段而不是让作者手打
                括号，是因为手打约定没人用，而且两种写法同时在时 provider
                会把注释读两遍——上面那行校验就是为这个存在的。 */}
            <input
              className="audio-bed__script-row__emotion"
              aria-label={`脚本 ${index + 1} 情绪`}
              placeholder="情绪（如：压低声音）"
              maxLength={AUDIO_BED_MAX_EMOTION_CHARS}
              value={script.emotion}
              onChange={(event) =>
                updateScript(setConfig, index, { emotion: event.target.value })
              }
            />
            <div className="audio-bed__script-row__buttons">
              <button
                type="button"
                aria-label={`上移脚本 ${index + 1}`}
                disabled={index === 0}
                onClick={() => moveScript(setConfig, index, -1)}
              >
                ↑
              </button>
              <button
                type="button"
                aria-label={`下移脚本 ${index + 1}`}
                disabled={index === config.scripts.length - 1}
                onClick={() => moveScript(setConfig, index, 1)}
              >
                ↓
              </button>
              <button
                type="button"
                aria-label={`删除脚本 ${index + 1}`}
                onClick={() =>
                  setConfig((current) => ({
                    ...current,
                    scripts: current.scripts.filter((_, i) => i !== index),
                  }))
                }
              >
                ×
              </button>
            </div>
          </div>
        ))}
        <button
          type="button"
          className="audio-bed__add"
          onClick={() =>
            setConfig((current) => ({
              ...current,
              scripts: [...current.scripts, { speaker: "", text: "", emotion: "" }],
            }))
          }
        >
          + 脚本行
        </button>
        <p className={budget.scriptsChars > budget.scriptsLimit ? "audio-bed__budget is-over" : "audio-bed__budget"}>
          scripts 合计 {budget.scriptsChars}/{budget.scriptsLimit} 字符
        </p>
      </fieldset>

      <div className="audio-bed__fields">
        <label className="audio-bed__instruction">
          <span>全局指导（instruction）</span>
          <textarea
            aria-label="全局指导"
            placeholder="环境、BGM 与情绪基调（如：废弃地下研究所，悬疑氛围）"
            value={config.instruction}
            onChange={(event) =>
              setConfig((current) => ({ ...current, instruction: event.target.value }))
            }
          />
        </label>
        <p className={budget.instructionChars > budget.instructionLimit ? "audio-bed__budget is-over" : "audio-bed__budget"}>
          instruction {budget.instructionChars}/{budget.instructionLimit} 字符
        </p>
        <label className="audio-bed__format">
          <span>格式</span>
          <select
            aria-label="音频格式"
            value={config.response_format}
            onChange={(event) =>
              setConfig((current) => ({
                ...current,
                response_format: event.target.value as AudioBedConfig["response_format"],
              }))
            }
          >
            {AUDIO_BED_RESPONSE_FORMATS.map((format) => (
              <option key={format} value={format}>
                {format}
              </option>
            ))}
          </select>
        </label>
      </div>

      {issues.length > 0 && (
        <ul className="audio-bed__issues" aria-label="配置问题">
          {issues.map((issue) => (
            <li key={issue.code} data-issue-code={issue.code}>
              {issue.message}
            </li>
          ))}
        </ul>
      )}
      {budget.scriptsChars > budget.scriptsLimit && (
        <ul className="audio-bed__issues" aria-label="长度超限">
          <li data-issue-code="audio_bed_scripts_over_budget">
            scripts 超出 {budget.scriptsChars - budget.scriptsLimit} 字符，provider 会拒绝（HTTP 400）。
          </li>
        </ul>
      )}

      <footer className="audio-bed__footer">
        <span className={dirty ? "audio-bed__dirty is-dirty" : "audio-bed__dirty"}>
          {dirty ? "有未保存修改" : "已保存"}
        </span>
        <button type="button" onClick={() => setConfig(persisted ?? emptyAudioBedConfig())} disabled={!dirty || saving}>
          撤销修改
        </button>
        <button
          type="button"
          className="audio-bed__save"
          disabled={!dirty || saving || issues.length > 0 || budget.scriptsChars > budget.scriptsLimit}
          onClick={() => void save()}
        >
          {saving ? "保存中…" : "保存音频床配置"}
        </button>
      </footer>
      {error && <p className="audio-bed__error">{error}</p>}
    </section>
  );
}

function updateRole(
  setConfig: (update: (current: AudioBedConfig) => AudioBedConfig) => void,
  index: number,
  patch: Partial<AudioBedRole>,
) {
  setConfig((current) => ({
    ...current,
    roles: current.roles.map((role, i) => (i === index ? { ...role, ...patch } : role)),
  }));
}

function updateScript(
  setConfig: (update: (current: AudioBedConfig) => AudioBedConfig) => void,
  index: number,
  patch: Partial<AudioBedScript>,
) {
  setConfig((current) => ({
    ...current,
    scripts: current.scripts.map((script, i) => (i === index ? { ...script, ...patch } : script)),
  }));
}

function moveScript(
  setConfig: (update: (current: AudioBedConfig) => AudioBedConfig) => void,
  index: number,
  direction: -1 | 1,
) {
  const target = index + direction;
  setConfig((current) => {
    if (target < 0 || target >= current.scripts.length) return current;
    const scripts = [...current.scripts];
    const [moved] = scripts.splice(index, 1);
    scripts.splice(target, 0, moved);
    return { ...current, scripts };
  });
}
