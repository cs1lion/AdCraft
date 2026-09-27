/**
 * Scene image intake — "drop an image in, get an editable 3D blockout".
 *
 * The frontend entry for the design doc's core scenario (§3.3/§4.5): a
 * dropped panorama or reference photo goes to ``POST /scene-3d/analyze-image``
 * (multimodal LLM analysis; equirect panoramas are sliced into cubic faces
 * server-side) and the returned SceneScript lands in the workbench draft —
 * instantly previewable and manually editable, the same state the tray,
 * placement tools and camera gizmos work on.
 *
 * Mirrors the ReferenceVideoPanel interaction contract (drag-drop + file
 * picker + progress + error surface) so the two intakes feel identical.
 */

import { useCallback, useRef, useState } from "react";

import type { SceneScriptRoot } from "../../../types/scene-script";
import "../workbench/scene-3d-workbench.css";

const ALLOWED_EXTENSIONS = [".png", ".jpg", ".jpeg", ".webp", ".bmp"];
const MAX_FILE_SIZE_MB = 20;
const MAX_IMAGES = 6;

export interface SceneImageAnalysis {
  scene_script: Record<string, unknown> | null;
  summary: Record<string, unknown>;
  image_analyses: Record<string, unknown>[];
  image_count: number;
  analyzed_image_count: number;
  panorama_image_indices: number[];
  warnings: string[];
}

export interface SceneImageIntakeProps {
  /** Called with the analyzed SceneScript (the workbench loads it as the draft). */
  onSceneScriptGenerated: (script: SceneScriptRoot, analysis: SceneImageAnalysis) => void;
  disabled?: boolean;
}

export function SceneImageIntake({
  onSceneScriptGenerated,
  disabled = false,
}: SceneImageIntakeProps) {
  const [analyzing, setAnalyzing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [dragOver, setDragOver] = useState(false);
  const [analysis, setAnalysis] = useState<SceneImageAnalysis | null>(null);
  const [withDepth, setWithDepth] = useState(false);
  const [depthUrl, setDepthUrl] = useState<string | null>(null);
  const [orbitUrl, setOrbitUrl] = useState<string | null>(null);
  const [orbitRunning, setOrbitRunning] = useState(false);
  const lastFileRef = useRef<File | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const validateFile = useCallback((file: File): string | null => {
    const ext = "." + (file.name.split(".").pop()?.toLowerCase() ?? "");
    if (!ALLOWED_EXTENSIONS.includes(ext)) {
      return `不支持的格式: ${ext}. 允许: ${ALLOWED_EXTENSIONS.join(", ")}`;
    }
    if (file.size > MAX_FILE_SIZE_MB * 1024 * 1024) {
      return `文件过大: ${(file.size / (1024 * 1024)).toFixed(1)} MB. 上限: ${MAX_FILE_SIZE_MB} MB`;
    }
    return null;
  }, []);

  const analyze = useCallback(
    async (files: File[]) => {
      setError(null);
      setAnalysis(null);
      setOrbitUrl(null);
      lastFileRef.current = files[0] ?? null;
      if (files.length === 0) return;
      if (files.length > MAX_IMAGES) {
        setError(`一次最多 ${MAX_IMAGES} 张图片。`);
        return;
      }
      for (const file of files) {
        const validationError = validateFile(file);
        if (validationError) {
          setError(validationError);
          return;
        }
      }

      setAnalyzing(true);
      try {
        const formData = new FormData();
        for (const file of files) {
          formData.append("files", file);
        }
        const response = await fetch("/api/v1/scene-3d/analyze-image", {
          method: "POST",
          body: formData,
        });
        const body = await response.json().catch(() => null);
        if (response.status !== 200 || !body) {
          const detail = body?.detail;
          throw new Error(
            (typeof detail === "object" && detail?.error) ||
              (typeof detail === "string" && detail) ||
              `图片分析失败 (HTTP ${response.status})`,
          );
        }
        const parsed: SceneImageAnalysis = {
          scene_script: body.scene_script ?? null,
          summary: body.summary ?? {},
          image_analyses: body.image_analyses ?? [],
          image_count: body.image_count ?? files.length,
          analyzed_image_count: body.analyzed_image_count ?? files.length,
          panorama_image_indices: body.panorama_image_indices ?? [],
          warnings: body.warnings ?? [],
        };
        setAnalysis(parsed);
        if (parsed.scene_script) {
          onSceneScriptGenerated(
            parsed.scene_script as unknown as SceneScriptRoot,
            parsed,
          );
        }

        // Optional depth white model (composition-fidelity control signal).
        // A failure here is a warning on the result, not a failed analysis:
        // the blockout is already usable.
        setDepthUrl(null);
        if (withDepth) {
          try {
            const depthForm = new FormData();
            depthForm.append("file", files[0]);
            const depthResponse = await fetch("/api/v1/scene-3d/extract-depth-image", {
              method: "POST",
              body: depthForm,
            });
            const depthBody = await depthResponse.json().catch(() => null);
            if (depthResponse.status === 200 && depthBody?.depth_url) {
              setDepthUrl(depthBody.depth_url);
            } else {
              const detail = depthBody?.detail;
              parsed.warnings = [
                ...parsed.warnings,
                `深度白模提取失败: ${
                  (typeof detail === "object" && detail?.error) || "provider unavailable"
                }`,
              ];
            }
          } catch {
            parsed.warnings = [...parsed.warnings, "深度白模提取失败: network error"];
          }
        }
      } catch (analyzeError) {
        setError(
          analyzeError instanceof Error ? analyzeError.message : "图片分析失败，请重试。",
        );
      } finally {
        setAnalyzing(false);
      }
    },
    [onSceneScriptGenerated, validateFile, withDepth],
  );

  // 2.5D orbit preview over the last analyzed image (back-projection onto
  // MiDaS depth, virtual camera swing). Disocclusion warnings ride along.
  const renderOrbit = useCallback(async () => {
    const file = lastFileRef.current;
    if (!file) return;
    setOrbitRunning(true);
    setError(null);
    try {
      const formData = new FormData();
      formData.append("file", file);
      formData.append("num_frames", "48");
      formData.append("sweep_degrees", "36");
      const response = await fetch("/api/v1/scene-3d/render-depth-orbit", {
        method: "POST",
        body: formData,
      });
      const body = await response.json().catch(() => null);
      if (response.status === 200 && body?.video_url) {
        setOrbitUrl(body.video_url);
      } else {
        const detail = body?.detail;
        setError(
          (typeof detail === "object" && detail?.error) ||
            "环绕预览生成失败（需要 MiDaS 深度估计依赖）。",
        );
      }
    } catch {
      setError("环绕预览生成失败: network error");
    } finally {
      setOrbitRunning(false);
    }
  }, []);

  return (
    <div className="scene-image-intake">
      {/* eslint-disable-next-line jsx-a11y/no-static-element-interactions -- File DROP ZONE: the drag-and-drop gesture has no native HTML semantics; the accessible activation path is the file-picker button inside (keyboard/touch users), and dropping is a progressive enhancement on top. */}
      <div
        className={`scene-image-intake__drop${dragOver ? " is-dragover" : ""}`}
        data-testid="scene-image-intake-drop"
        onDragOver={(event) => {
          event.preventDefault();
          if (!disabled && !analyzing) setDragOver(true);
        }}
        onDragLeave={() => setDragOver(false)}
        onDrop={(event) => {
          event.preventDefault();
          setDragOver(false);
          if (disabled || analyzing) return;
          const dropped = Array.from(event.dataTransfer?.files ?? []);
          if (dropped.length > 0) void analyze(dropped);
        }}
      >
        <button
          type="button"
          className="scene-image-intake__button"
          disabled={disabled || analyzing}
          onClick={() => fileInputRef.current?.click()}
        >
          {analyzing ? "分析中…" : "🖼 从图片生成场景"}
        </button>
        <label className="scene-image-intake__depth-toggle">
          <input
            type="checkbox"
            checked={withDepth}
            disabled={disabled || analyzing}
            onChange={(event) => setWithDepth(event.target.checked)}
          />
          同时提取深度白模（MiDaS 灰度深度图，构图保真参考）
        </label>
        <span className="scene-image-intake__hint">
          拖入全景图或参考照片（2:1 全景自动切 6 面分析），LLM 转为可编辑的 3D blockout
        </span>
        <input
          ref={fileInputRef}
          type="file"
          accept={ALLOWED_EXTENSIONS.join(",")}
          multiple
          hidden
          onChange={(event) => {
            const picked = Array.from(event.target.files ?? []);
            if (picked.length > 0) void analyze(picked);
            event.target.value = "";
          }}
        />
      </div>

      {analysis && (
        <div className="scene-image-intake__result" data-testid="scene-image-intake-result">
          <strong>已生成场景 blockout</strong>
          <span>
            分析 {analysis.analyzed_image_count} 张视角
            {analysis.panorama_image_indices.length > 0 && "（含全景切面）"}
            {" · "}
            {String(analysis.summary?.scene_overview ?? "")}
          </span>
          {depthUrl && (
            <img
              className="scene-image-intake__depth"
              src={depthUrl}
              alt="深度白模（grayscale depth map）"
              data-testid="scene-image-intake-depth"
            />
          )}
          <button
            type="button"
            className="scene-image-intake__button"
            disabled={disabled || orbitRunning}
            onClick={() => void renderOrbit()}
          >
            {orbitRunning ? "渲染中…" : "🎥 生成深度环绕预览"}
          </button>
          {orbitUrl && (
            <video
              className="scene-image-intake__orbit"
              src={orbitUrl}
              controls
              loop
              muted
              data-testid="scene-image-intake-orbit"
            />
          )}
          {analysis.warnings.length > 0 && (
            <ul className="scene-image-intake__warnings">
              {analysis.warnings.map((warning) => (
                <li key={warning}>{warning}</li>
              ))}
            </ul>
          )}
        </div>
      )}
      {error && <p className="scene-image-intake__error">{error}</p>}
    </div>
  );
}

