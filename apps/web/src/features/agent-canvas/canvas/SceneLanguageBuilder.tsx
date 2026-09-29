/**
 * 语言搭建组件（2026-09-29 简约好用分支）。
 * 说一句“加一张桌子在左边”——预览实时长出来。快捷 chips 给最常见的实体。
 */

import { useState } from "react";

import { QUICK_ADDS, parseSceneLanguage } from "./sceneLanguageOps.ts";
import type { SceneScriptRoot } from "../../../types/scene-script";

interface SceneLanguageBuilderProps {
  script: SceneScriptRoot;
  onChange: (script: SceneScriptRoot) => void;
  disabled?: boolean;
}

export function SceneLanguageBuilder({ script, onChange, disabled }: SceneLanguageBuilderProps) {
  const [text, setText] = useState("");
  const [hint, setHint] = useState<string | null>(null);

  const apply = (input: string) => {
    const count =
      script.props.length + script.environment.length + script.characters.length;
    const op = parseSceneLanguage(input, count);
    if (!op) {
      setHint("没听懂——试试：桌子/椅子/树/墙/窗户/人物……");
      return;
    }
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

  return (
    <div className="scene-language-builder" data-testid="scene-language-builder">
      <div className="scene-language-builder__row">
        <input
          value={text}
          onChange={(event) => setText(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === "Enter" && text.trim()) {
              event.preventDefault();
              apply(text);
            }
          }}
          placeholder="加一张桌子在左边 / 加一棵树 / 加一个人物……"
          disabled={disabled}
        />
        <button type="button" onClick={() => apply(text)} disabled={disabled || !text.trim()}>
          添加
        </button>
      </div>
      <div className="scene-language-builder__chips">
        {QUICK_ADDS.map((chip) => (
          <button
            key={chip}
            type="button"
            onClick={() => apply(chip)}
            disabled={disabled}
          >
            {chip}
          </button>
        ))}
      </div>
      {hint && <div className="scene-language-builder__hint">{hint}</div>}
    </div>
  );
}
