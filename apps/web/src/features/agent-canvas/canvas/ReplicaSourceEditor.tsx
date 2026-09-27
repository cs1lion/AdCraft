/**
 * ReplicaSourceEditor — `.adreplica` 源码原位高亮编辑器（零依赖 underlay）。
 *
 * 经典"高亮下衬层 + 透明文本区"结构：`<pre>` 负责着色与锚点标记，
 * `<textarea>` 负责编辑（文字透明、光标可见）；两者共享同一套等宽字体
 * 度量与 `white-space: pre`（不换行 + 双向滚动同步），保证字符严格对齐。
 *
 * 行内词锚 `@{id}`（含闭合 `@{/id}`）在衬层里高亮为可点击标记——点击
 * 即回调 `onAnchorClick(eventId)` 跳转锚点列表；反向定位由
 * `jumpToEventId` 驱动（滚动到首个 `@{id}` 并选中它）。
 *
 * 词汇表着色对齐 hypit SVML 语法基因：标签/属性/值/行内锚四类。
 */

import { useCallback, useEffect, useMemo, useRef } from "react";

type TokenKind = "tag" | "attr" | "value" | "anchor" | "punct" | "text";

interface SourceToken {
  text: string;
  kind: TokenKind;
  anchorId?: string;
}

const TOKEN_RE =
  /(<\/?[A-Za-z_][\w.:-]*)|([A-Za-z_][\w.:-]+(?==))|("[^"]*")|(@\{\/?[^\s{}@]+\})|([<>/?=])/g;

const ANCHOR_ID_RE = /^@\{\/?([^\s{}@]+)\}$/;

const KIND_COLOR: Record<TokenKind, string> = {
  tag: "#6ab0f3",
  attr: "#fc8",
  value: "#8f8",
  anchor: "#f6c",
  punct: "#6ab0f3",
  text: "#ccc",
};

export function tokenizeAdreplica(text: string): SourceToken[] {
  const tokens: SourceToken[] = [];
  let last = 0;
  for (const match of text.matchAll(TOKEN_RE)) {
    const index = match.index ?? 0;
    if (index > last) {
      tokens.push({ text: text.slice(last, index), kind: "text" });
    }
    const raw = match[0];
    if (raw.startsWith("@{")) {
      const anchorId = ANCHOR_ID_RE.exec(raw)?.[1];
      tokens.push({ text: raw, kind: "anchor", anchorId });
    } else if (raw.startsWith("<") || raw === ">" || raw === "/>" || raw === "</") {
      tokens.push({ text: raw, kind: "tag" });
    } else if (raw.startsWith('"')) {
      tokens.push({ text: raw, kind: "value" });
    } else if (raw === "<" || raw === ">" || raw === "/" || raw === "?" || raw === "=") {
      tokens.push({ text: raw, kind: "punct" });
    } else {
      tokens.push({ text: raw, kind: "attr" });
    }
    last = index + raw.length;
  }
  if (last < text.length) {
    tokens.push({ text: text.slice(last), kind: "text" });
  }
  return tokens;
}

export interface ReplicaSourceEditorProps {
  value: string;
  onChange: (next: string) => void;
  /** 点击行内词锚（跳转锚点列表）。 */
  onAnchorClick?: (eventId: string) => void;
  /** 反向定位：外部请求滚动并选中该事件的行内锚（处理后回调 onJumpHandled）。 */
  jumpToEventId?: string | null;
  onJumpHandled?: () => void;
  height?: number;
}

const SHARED_METRICS: React.CSSProperties = {
  margin: 0,
  padding: 8,
  border: "1px solid #2a2a4a",
  fontFamily: "monospace",
  fontSize: 10,
  lineHeight: 1.6,
  whiteSpace: "pre",
  overflowWrap: "normal",
  tabSize: 2,
};

export function ReplicaSourceEditor({
  value,
  onChange,
  onAnchorClick,
  jumpToEventId = null,
  onJumpHandled,
  height = 220,
}: ReplicaSourceEditorProps) {
  const textareaRef = useRef<HTMLTextAreaElement | null>(null);
  const highlightRef = useRef<HTMLPreElement | null>(null);

  const tokens = useMemo(() => tokenizeAdreplica(value), [value]);

  const syncScroll = useCallback(() => {
    const textarea = textareaRef.current;
    const highlight = highlightRef.current;
    if (!textarea || !highlight) return;
    highlight.scrollTop = textarea.scrollTop;
    highlight.scrollLeft = textarea.scrollLeft;
  }, []);

  // 反向定位：滚动到该事件的行内锚并选中之
  useEffect(() => {
    if (!jumpToEventId) return;
    const textarea = textareaRef.current;
    if (!textarea) return;
    const marker = `@{${jumpToEventId}}`;
    const offset = value.indexOf(marker);
    if (offset < 0) {
      onJumpHandled?.();
      return;
    }
    const lineIndex = value.slice(0, offset).split("\n").length - 1;
    const lineHeight = 16; // fontSize 10 * lineHeight 1.6
    textarea.scrollTop = Math.max(0, lineIndex * lineHeight - height / 3);
    syncScroll();
    textarea.focus();
    textarea.setSelectionRange(offset, offset + marker.length);
    onJumpHandled?.();
  }, [jumpToEventId, value, height, onJumpHandled, syncScroll]);

  return (
    <div style={{ position: "relative" }}>
      <pre
        ref={highlightRef}
        aria-hidden="true"
        data-testid="source-highlight-layer"
        style={{
          ...SHARED_METRICS,
          height,
          overflow: "hidden",
          color: KIND_COLOR.text,
          pointerEvents: "none",
          boxSizing: "border-box",
        }}
      >
        {tokens.map((token, index) => {
          if (token.kind === "text") {
            return <span key={index}>{token.text}</span>;
          }
          if (token.kind === "anchor") {
            // 只有开标记 @{id} 可点击跳转；闭合 @{/id} 仅着色。
            // 可点击者用无样式 button（键盘可达，jsx-a11y），度量与文本一致。
            const isCloseMarker = token.text.startsWith("@{/");
            const interactive = Boolean(token.anchorId && !isCloseMarker && onAnchorClick);
            return (
              <button
                key={index}
                type="button"
                data-testid={
                  token.anchorId && !isCloseMarker
                    ? `source-anchor-${token.anchorId}`
                    : undefined
                }
                title={interactive ? `跳转到锚点 ${token.anchorId}` : undefined}
                style={{
                  color: KIND_COLOR.anchor,
                  fontWeight: "bold",
                  textDecoration: "underline",
                  font: "inherit",
                  background: "none",
                  border: "none",
                  padding: 0,
                  textAlign: "left",
                  whiteSpace: "pre",
                  cursor: interactive ? "pointer" : "default",
                  pointerEvents: interactive ? "auto" : "none",
                }}
                onClick={
                  interactive && onAnchorClick
                    ? () => onAnchorClick(token.anchorId as string)
                    : undefined
                }
              >
                {token.text}
              </button>
            );
          }
          return (
            <span key={index} style={{ color: KIND_COLOR[token.kind] }}>
              {token.text}
            </span>
          );
        })}
      </pre>
      <textarea
        ref={textareaRef}
        value={value}
        onChange={(event) => onChange(event.target.value)}
        onScroll={syncScroll}
        spellCheck={false}
        placeholder="点「导出当前蓝图」生成 .adreplica 文本；或把外部编辑过的文本粘贴到这里，点「导入重编译」写回节点。"
        style={{
          ...SHARED_METRICS,
          position: "absolute",
          inset: 0,
          height,
          overflow: "auto",
          background: "transparent",
          color: "transparent",
          caretColor: "#fff",
          resize: "none",
          boxSizing: "border-box",
        }}
      />
    </div>
  );
}
