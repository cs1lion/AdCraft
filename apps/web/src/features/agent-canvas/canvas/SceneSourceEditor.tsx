import { useId, useState } from "react";
import { createPortal } from "react-dom";

import type { SceneScriptRoot } from "../../../types/scene-script";

/** Applies a complete authored document after server schema validation. */
export function SceneSourceEditor({
  sceneScript,
  onChange,
  disabled = false,
}: {
  sceneScript: SceneScriptRoot;
  onChange: (script: SceneScriptRoot) => void;
  disabled?: boolean;
}) {
  const id = useId();
  const [open, setOpen] = useState(false);
  const [source, setSource] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const apply = async () => {
    setBusy(true);
    setError(null);
    try {
      const parsed: unknown = JSON.parse(source);
      if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
        throw new Error("场景数据必须是一个 JSON 对象。");
      }
      const document = parsed as Record<string, unknown>;
      if (["characters", "props", "environment", "cameras", "shots", "speech_bindings"]
        .some((key) => !Array.isArray(document[key]))) {
        throw new Error("请导入完整 SceneScript JSON，包含人物、道具、环境、相机、镜头和语音绑定数组。");
      }
      // This endpoint validates the entire document without generating media or
      // changing tracks. apply-operations rejects empty operation batches.
      const response = await fetch("/api/v1/scene-3d/consistency-check", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ scene_script: parsed }),
      });
      const result = await response.json() as {
        success?: boolean;
        detail?: { error?: string } | string;
        error?: string;
      };
      if (!response.ok || !result.success) {
        const detail = typeof result.detail === "string" ? result.detail : result.detail?.error;
        throw new Error(detail ?? result.error ?? `场景校验失败（HTTP ${response.status}）。`);
      }
      // Preserve authored values, camera names and every track exactly as
      // submitted. Consistency findings are advisory; schema failures reject.
      onChange(parsed as SceneScriptRoot);
      setOpen(false);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "场景校验失败。");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div>
      <button type="button" disabled={disabled || busy} onClick={() => {
        setSource(JSON.stringify(sceneScript));
        setError(null);
        setOpen(true);
      }}>导入场景数据</button>
      {open && createPortal(
        <div role="dialog" aria-modal="false" aria-labelledby={`${id}-title`}
          style={{ position: "fixed", inset: "8% 12%", zIndex: 1000, padding: 20,
            background: "#171a23", color: "#f1f3f7", border: "1px solid #596174",
            borderRadius: 12, display: "flex", flexDirection: "column", gap: 12 }}>
          <h2 id={`${id}-title`}>导入场景数据</h2>
          <p>校验后应用到当前草稿；点击“保存场景”后可在项目中恢复。</p>
          <label htmlFor={`${id}-source`}>SceneScript JSON</label>
          <textarea id={`${id}-source`} value={source} disabled={busy}
            onChange={(event) => setSource(event.target.value)}
            spellCheck={false} style={{ flex: 1, minHeight: 180, resize: "none",
              fontFamily: "monospace", background: "#0b0f17", color: "#d8e6ef", padding: 12 }} />
          {error && <p role="alert">{error}</p>}
          <div style={{ display: "flex", gap: 12 }}>
            <button type="button" disabled={busy} onClick={() => { void apply(); }}>
              {busy ? "校验中…" : "校验并应用"}
            </button>
            <button type="button" disabled={busy} onClick={() => setOpen(false)}>取消</button>
          </div>
        </div>,
        document.body,
      )}
    </div>
  );
}
