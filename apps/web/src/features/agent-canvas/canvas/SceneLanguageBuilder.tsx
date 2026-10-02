/**
 * 语言搭建组件（2026-09-29 简约好用分支）。
 * 说一句“加一张桌子在左边”——预览实时长出来。快捷 chips 给最常见的实体。
 * 关键词没命中的句子不进死胡同：出「交给 AI 试试」，走 /language-fallback
 * （白模 LLM → ops 批 → 同一闸门），applied 脚本回填同一条 draft 管道。
 */

import { useState } from "react";

import { QUICK_ADDS, parseSceneLanguage } from "./sceneLanguageOps.ts";
import { requestLanguageFallback } from "./directorOperationsClient.ts";
import type { SceneScriptRoot } from "../../../types/scene-script";

interface SceneLanguageBuilderProps {
  script: SceneScriptRoot;
  onChange: (script: SceneScriptRoot) => void;
  disabled?: boolean;
}

export function SceneLanguageBuilder({ script, onChange, disabled }: SceneLanguageBuilderProps) {
  const [text, setText] = useState("");
  const [hint, setHint] = useState<string | null>(null);
  const [aiBusy, setAiBusy] = useState(false);
  // The sentence the keyword map missed, kept so the AI fallback can use it
  // (and retry it after a coded failure).
  const [unparsed, setUnparsed] = useState<string | null>(null);

  const apply = (input: string) => {
    const count =
      script.props.length + script.environment.length + script.characters.length;
    const op = parseSceneLanguage(input, count);
    if (!op) {
      setHint("没听懂——试试：桌子/椅子/树/墙/窗户/人物……");
      setUnparsed(input.trim());
      return;
    }
    setUnparsed(null);
    const next: SceneScriptRoot = {
      ...script,
      props: op.kind === "prop" ? [...script.props, op as never] : script.props,
      environment:
        op.kind === "environment" ? [...script.environment, op as never] : script.environment,
      characters:
        op.kind === "character"
          ? [...script.characters, { id: op.id, appearance: {}, keyframes: [], position: op.position } as never]
          : script.characters,
    };
    onChange(next);
    setHint(`✓ 已添加${op.kind === "prop" ? "道具" : op.kind === "environment" ? "环境" : "人物"}：${input.trim()}`);
    setText("");
  };

  const askAi = async () => {
    if (!unparsed || aiBusy) return;
    setAiBusy(true);
    setHint(`AI 正在搭「${unparsed}」……可能要十几秒`);
    try {
      const result = await requestLanguageFallback(script, unparsed);
      if (result.ok && result.appliedSceneScript) {
        onChange(result.appliedSceneScript);
        setHint(`✓ AI 已按「${unparsed}」更新场景（${result.operationCount ?? 0} 个操作）`);
        setText("");
        setUnparsed(null);
      } else {
        setHint(`AI 没搭出来：${result.error ?? "未知原因"}`);
      }
    } catch (error) {
      setHint(`AI 兜底请求失败：${error instanceof Error ? error.message : String(error)}`);
    } finally {
      setAiBusy(false);
    }
  };

  return (
    <div className="scene-language-builder" data-testid="scene-language-builder">
      <div className="scene-language-builder__row">
        <input
          value={text}
          onChange={(event) => setText(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === "Enter" && text.trim() && !aiBusy) {
              event.preventDefault();
              apply(text);
            }
          }}
          placeholder="加一张桌子在左边 / 加一棵树 / 加一个人物……"
          disabled={disabled || aiBusy}
        />
        <button type="button" onClick={() => apply(text)} disabled={disabled || aiBusy || !text.trim()}>
          添加
        </button>
      </div>
      <div className="scene-language-builder__chips">
        {QUICK_ADDS.map((chip) => (
          <button
            key={chip}
            type="button"
            onClick={() => apply(chip)}
            disabled={disabled || aiBusy}
          >
            {chip}
          </button>
        ))}
      </div>
      {hint && (
        <div className="scene-language-builder__hint">
          {hint}
          {unparsed && !aiBusy && (
            <button
              type="button"
              className="scene-language-builder__ai"
              data-testid="scene-language-ai-fallback"
              onClick={askAi}
              disabled={disabled}
            >
              交给 AI 试试
            </button>
          )}
        </div>
      )}
    </div>
  );
}
