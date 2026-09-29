/**
 * Scene3DRenderControls — E6: 3D 线的渲染入口（接 scene-3d render/async 家族）。
 *
 * 后端 RenderJobManager 早就有进度与协作式取消，工作台却没有任何渲染按钮
 * （渲染只走节点执行器，用户看不到进度、中断不了）。本组件补上这一环：
 * 提交 → job_id → 轮询进度 → 完成出片 / 失败原文 / 取消真的取消。
 *
 * 与直出（ReplicaBlueprintPanel）的分工：那是复刻半场的零模型费直出；
 * 这是 3D 半场走 Blender 的预演渲染（要 Blender，见 D4 的不可用提示）。
 */

import { useCallback, useEffect, useRef, useState } from "react";

import { buildMediaUrl } from "../../../api/workflowNormalizers.ts";
import {
  cancelScene3DRender,
  fetchScene3DRenderJob,
  submitScene3DRender,
} from "./directorOperationsClient.ts";
import type { SceneScriptRoot } from "../../../types/scene-script";

// 2s × 150 = 5 分钟轮询上限：超时明确失败，不无限等
const POLL_LIMIT = 150;

export interface Scene3DRenderControlsProps {
  sceneScript: SceneScriptRoot;
  disabled?: boolean;
}

export function Scene3DRenderControls({ sceneScript, disabled }: Scene3DRenderControlsProps) {
  const [jobId, setJobId] = useState<string | null>(null);
  const [status, setStatus] = useState<string | null>(null);
  const [progress, setProgress] = useState(0);
  const [elapsed, setElapsed] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [videoUrl, setVideoUrl] = useState<string | null>(null);
  const [warnings, setWarnings] = useState<string[]>([]);
  const abortRef = useRef<AbortController | null>(null);

  const inFlight = status === "pending" || status === "running";

  // 秒级计时（在途期间）
  useEffect(() => {
    if (!inFlight) return;
    setElapsed(0);
    const startedAt = Date.now();
    const timer = window.setInterval(() => {
      setElapsed(Math.floor((Date.now() - startedAt) / 1000));
    }, 1000);
    return () => window.clearInterval(timer);
  }, [inFlight]);

  // 卸载即停轮询
  useEffect(() => () => abortRef.current?.abort(), []);

  const submit = useCallback(async () => {
    setStatus("pending");
    setProgress(0);
    setError(null);
    setNotice(null);
    setVideoUrl(null);
    setWarnings([]);
    try {
      const nextJobId = await submitScene3DRender(sceneScript);
      setJobId(nextJobId);
    } catch (err) {
      setStatus("failed");
      setError(err instanceof Error ? err.message : "渲染提交失败");
    }
  }, [sceneScript]);

  // 轮询任务状态（pending/running 才继续；终态落结果）
  useEffect(() => {
    if (!jobId || !inFlight) return;
    const controller = new AbortController();
    abortRef.current = controller;
    let attempts = 0;
    const tick = async () => {
      attempts += 1;
      try {
        const job = await fetchScene3DRenderJob(jobId);
        if (controller.signal.aborted) return;
        setStatus(job.status);
        if (typeof job.progress === "number") setProgress(job.progress);
        if (job.status === "completed") {
          const path = job.result?.video_path ?? job.result?.animatic_video_path ?? null;
          setVideoUrl(path ? buildMediaUrl(path) : null);
          setWarnings(Array.isArray(job.result?.warnings) ? job.result!.warnings! : []);
        } else if (job.status === "failed") {
          setError(job.error || "渲染失败");
        } else if (job.status === "cancelled") {
          // 口径对齐 D8：协作式取消——后端只把任务标记取消并请求渲染线程在
          // 阶段间隙停，当前阶段的 Blender 子进程可能还在收尾。不说"渲染已
          // 停止"（endpoint 的原文也只是 "Cancellation requested."）。
          setNotice("已取消：后端已接受取消请求，渲染将在阶段边界停止。");
        } else if (attempts >= POLL_LIMIT) {
          setError("渲染轮询超时（5 分钟）——任务可能仍在后台进行，请稍后重新提交查看。");
        }
      } catch (err) {
        if (controller.signal.aborted) return;
        setError(err instanceof Error ? err.message : "渲染状态查询失败");
      }
    };
    void tick();
    const timer = window.setInterval(() => void tick(), 2000);
    return () => {
      controller.abort();
      window.clearInterval(timer);
    };
  }, [jobId, inFlight]);

  const cancel = useCallback(async () => {
    if (!jobId) return;
    abortRef.current?.abort();
    try {
      await cancelScene3DRender(jobId);
      setStatus("cancelled");
      setNotice("已取消：后端已接受取消请求，渲染将在阶段边界停止。");
    } catch (err) {
      // 取消失败不假装成功：任务可能仍在跑，如实说
      setError(
        `取消失败：${err instanceof Error ? err.message : "未知错误"}——任务可能仍在后台进行`,
      );
    }
  }, [jobId]);

  return (
    <div className="scene-script-3d-editor__render-controls" data-testid="scene-3d-render-controls">
      <div style={{ display: "flex", gap: 6, alignItems: "center", flexWrap: "wrap" }}>
        <button
          type="button"
          onClick={() => void submit()}
          disabled={disabled || inFlight}
          title="用 Blender 渲染当前场景脚本（需要本机 Blender 可用）"
          style={{
            background: disabled || inFlight ? "#2a2a4a" : "#3a5a8a",
            border: "none",
            color: disabled || inFlight ? "#666" : "#fff",
            padding: "4px 12px",
            borderRadius: 3,
            cursor: disabled || inFlight ? "default" : "pointer",
            fontSize: 10,
          }}
        >
          {inFlight ? "⏳ 渲染中…" : "🎬 预览渲染"}
        </button>
        {inFlight && (
          <>
            <span style={{ fontSize: 10, color: "#8cf" }} data-testid="scene-3d-render-progress">
              {Math.round(progress * 100)}% · 已进行 {elapsed}s
            </span>
            <button
              type="button"
              onClick={() => void cancel()}
              style={{
                background: "transparent",
                border: "1px solid #678",
                color: "#9bd",
                borderRadius: 3,
                fontSize: 10,
                padding: "0 8px",
                cursor: "pointer",
              }}
            >
              ⏹ 取消渲染
            </button>
          </>
        )}
      </div>
      {error && (
        <p className="scene-script-3d-editor__error" data-testid="scene-3d-render-error">
          ⚠ {error}
        </p>
      )}
      {notice && (
        <p className="scene-script-3d-editor__note" data-testid="scene-3d-render-notice">
          {notice}
        </p>
      )}
      {status === "completed" && (
        <div data-testid="scene-3d-render-result">
          <p className="scene-script-3d-editor__note">✓ 渲染完成</p>
          {videoUrl ? (
            <video
              src={videoUrl}
              controls
              style={{ width: "100%", maxWidth: 240, borderRadius: 3, background: "#000" }}
            />
          ) : (
            <p className="scene-script-3d-editor__note">（未产出视频文件——可查看关键帧输出）</p>
          )}
          {warnings.map((warning) => (
            <p key={warning} className="scene-script-3d-editor__note">
              · {warning}
            </p>
          ))}
        </div>
      )}
    </div>
  );
}
