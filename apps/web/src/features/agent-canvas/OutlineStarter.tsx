/**
 * OutlineStarter — 从一句话开始（Flow B 的入口，2026-09-29 简约好用分支）。
 *
 * 写一条纲领 → 展开成镜（LLM）→ 审一眼 → 开始生成（设定图 + 成片节点 +
 * 一次 run）。作者看不见 script 节点 / 分镜阶段 / provider 词汇。
 */

import { useCallback, useState } from "react";

interface OutlineShot {
  summary: string;
  visual: string;
  duration_seconds: number;
  on_screen_text: string;
}

type Busy = "idle" | "expand" | "build";

export function OutlineStarter({ workflowId }: { workflowId: string }) {
  const [outline, setOutline] = useState("");
  const [shots, setShots] = useState<OutlineShot[]>([]);
  const [busy, setBusy] = useState<Busy>("idle");
  const [error, setError] = useState<string | null>(null);
  const [status, setStatus] = useState<string | null>(null);

  const expand = useCallback(async () => {
    setBusy("expand");
    setError(null);
    try {
      const response = await fetch("/api/v1/creation/expand-outline", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ outline }),
      });
      const body = (await response.json().catch(() => null)) as {
        success?: boolean;
        shots?: OutlineShot[];
        error?: string;
      } | null;
      if (!body?.success) throw new Error(body?.error || "展开失败");
      setShots(body.shots ?? []);
    } catch (err) {
      setError(err instanceof Error ? err.message : "展开失败");
    } finally {
      setBusy("idle");
    }
  }, [outline]);

  const build = useCallback(async () => {
    setBusy("build");
    setError(null);
    setStatus("搭建中…");
    try {
      const response = await fetch("/api/v1/creation/build-from-outline", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ workflow_id: workflowId, outline, shots }),
      });
      const body = (await response.json().catch(() => null)) as {
        success?: boolean;
        error?: string;
      } | null;
      if (!response.ok || !body?.success) {
        throw new Error(body?.error || `搭建失败 (HTTP ${response.status})`);
      }
      setStatus("已开画（设定图与成片镜头生成中，节点上可见进度）");
    } catch (err) {
      setError(err instanceof Error ? err.message : "搭建失败");
      setStatus(null);
    } finally {
      setBusy("idle");
    }
  }, [outline, shots, workflowId]);

  return (
    <div className="agent-canvas-outline-starter">
      <b>从一句话开始</b>
      <p>写一条创作纲领，展开成镜后一键生成——不必先懂节点。</p>
      <textarea
        value={outline}
        onChange={(event) => setOutline(event.target.value)}
        placeholder="例如：一条 20 秒的红苹果清晨广告——果园阳光、切开慢动作、家人分享"
        rows={3}
      />
      <div className="agent-canvas-outline-starter__actions">
        <button type="button" onClick={() => void expand()} disabled={busy !== "idle" || !outline.trim()}>
          {busy === "expand" ? "展开中…" : shots.length ? "重新展开" : "展开分镜"}
        </button>
        {shots.length > 0 && (
          <button
            type="button"
            className="agent-canvas-outline-starter__primary"
            onClick={() => void build()}
            disabled={busy !== "idle"}
          >
            {busy === "build" ? "生成中…" : `开始生成（${shots.length} 镜）`}
          </button>
        )}
      </div>
      {error && <div className="agent-canvas-outline-starter__error">{error}</div>}
      {status && <div className="agent-canvas-outline-starter__status">{status}</div>}
      {shots.length > 0 && (
        <ol className="agent-canvas-outline-starter__shots">
          {shots.map((shot, index) => (
            <li key={`${shot.summary}-${index}`}>
              <b>{shot.summary}</b>
              <span>（{shot.duration_seconds.toFixed(0)}s）</span>
              <p>{shot.visual}</p>
            </li>
          ))}
        </ol>
      )}
    </div>
  );
}
