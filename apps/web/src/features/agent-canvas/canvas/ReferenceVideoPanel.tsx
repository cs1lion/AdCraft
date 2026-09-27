/**
 * Reference Video Panel - upload and manage reference videos for video model conditioning.
 *
 * Supports:
 * - Drag-and-drop video upload
 * - Upload progress and validation feedback
 * - Video preview and metadata display
 * - Keyframe extraction preview
 * - Reference mode selection (Blender previs vs uploaded video)
 */

import { useState, useRef, useCallback } from "react";

import { ReplicaTeardown } from "./ReplicaTeardown.tsx";

interface VideoMetadata {
  duration_seconds: number;
  width: number;
  height: number;
  frame_rate: number;
  frame_count: number;
  codec_name: string;
  file_size_bytes: number;
}

interface UploadResult {
  success: boolean;
  asset_id: string;
  file_path: string;
  file_name: string;
  file_size_bytes: number;
  metadata: VideoMetadata;
  keyframes_dir: string | null;
  keyframe_count: number;
}

interface DepthEstimationResult {
  success: boolean;
  asset_id: string;
  input_video_path: string;
  output_video_path: string;
  output_width: number;
  output_height: number;
  frame_count: number;
  duration_seconds: number;
  fps: number;
  model_type: string;
  colormap: string;
  keyframes_dir: string | null;
  keyframe_count: number;
  processing_time_seconds: number;
}

interface ReferenceVideoPanelProps {
  onVideoSelected?: (result: UploadResult | null) => void;
  onDepthExtracted?: (result: DepthEstimationResult | null) => void;
  height?: number;
  /** 当前工作流：拉片复刻创建蓝图节点用。 */
  workflowId?: string | null;
}

const MAX_FILE_SIZE_MB = 100;
// 60s：与后端 reference_upload 的上限对齐——拉片复刻面向 15-30s 广告片，
// 10s 会把核心场景直接挡在上传关卡（后端同步放宽为 60s）。
const MAX_DURATION_SECONDS = 60;
const ALLOWED_EXTENSIONS = [".mp4", ".webm", ".mov", ".m4v"];

export function ReferenceVideoPanel({
  onVideoSelected,
  onDepthExtracted,
  height = 320,
  workflowId = null,
}: ReferenceVideoPanelProps) {
  const [uploading, setUploading] = useState(false);
  const [uploadProgress, setUploadProgress] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<UploadResult | null>(null);
  const [dragOver, setDragOver] = useState(false);
  const [extractingDepth, setExtractingDepth] = useState(false);
  const [depthResult, setDepthResult] = useState<DepthEstimationResult | null>(null);
  const [depthError, setDepthError] = useState<string | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const validateFile = useCallback((file: File): string | null => {
    const ext = "." + file.name.split(".").pop()?.toLowerCase();
    if (!ALLOWED_EXTENSIONS.includes(ext)) {
      return `Unsupported format: ${ext}. Allowed: ${ALLOWED_EXTENSIONS.join(", ")}`;
    }
    if (file.size > MAX_FILE_SIZE_MB * 1024 * 1024) {
      return `File too large: ${(file.size / (1024 * 1024)).toFixed(1)} MB. Max: ${MAX_FILE_SIZE_MB} MB`;
    }
    return null;
  }, []);

  const handleFile = useCallback(
    async (file: File) => {
      setError(null);
      setResult(null);

      const validationError = validateFile(file);
      if (validationError) {
        setError(validationError);
        return;
      }

      setUploading(true);
      setUploadProgress(0);

      try {
        const formData = new FormData();
        formData.append("file", file);
        formData.append("extract_keyframes", "true");
        formData.append("num_keyframes", "5");

        const xhr = new XMLHttpRequest();
        xhr.open("POST", "/api/v1/scene-3d/upload-reference");

        xhr.upload.onprogress = (event) => {
          if (event.lengthComputable) {
            setUploadProgress(Math.round((event.loaded / event.total) * 100));
          }
        };

        const response = await new Promise<{ status: number; body: string }>(
          (resolve, reject) => {
            xhr.onload = () =>
              resolve({ status: xhr.status, body: xhr.responseText });
            xhr.onerror = () => reject(new Error("Network error"));
            xhr.send(formData);
          }
        );

        if (response.status !== 200) {
          const errorData = JSON.parse(response.body);
          const detail = errorData.detail;
          if (typeof detail === "object" && detail.error) {
            throw new Error(detail.error);
          }
          throw new Error(typeof detail === "string" ? detail : "Upload failed");
        }

        const data: UploadResult = JSON.parse(response.body);
        setResult(data);
        onVideoSelected?.(data);
      } catch (err) {
        setError(err instanceof Error ? err.message : "Upload failed");
      } finally {
        setUploading(false);
        setUploadProgress(0);
      }
    },
    [validateFile, onVideoSelected]
  );

  const extractDepth = useCallback(async () => {
    if (!result) return;
    setExtractingDepth(true);
    setDepthError(null);
    setDepthResult(null);

    try {
      const response = await fetch("/api/v1/scene-3d/extract-depth", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          input_video_path: result.file_path,
          model_type: "DPT_Hybrid",
          colormap: "grayscale",
          output_width: 960,
          output_height: 540,
          extract_keyframes: true,
          num_keyframes: 5,
        }),
      });

      if (!response.ok) {
        const errorData = await response.json();
        const detail = errorData.detail;
        if (typeof detail === "object" && detail.error) {
          throw new Error(detail.error);
        }
        throw new Error(typeof detail === "string" ? detail : "Depth extraction failed");
      }

      const data: DepthEstimationResult = await response.json();
      setDepthResult(data);
      onDepthExtracted?.(data);
    } catch (err) {
      setDepthError(err instanceof Error ? err.message : "Depth extraction failed");
    } finally {
      setExtractingDepth(false);
    }
  }, [result, onDepthExtracted]);

  const handleDrop = useCallback(
    (e: React.DragEvent) => {
      e.preventDefault();
      setDragOver(false);
      const file = e.dataTransfer.files[0];
      if (file) handleFile(file);
    },
    [handleFile]
  );

  const handleFileInput = useCallback(
    (e: React.ChangeEvent<HTMLInputElement>) => {
      const file = e.target.files?.[0];
      if (file) handleFile(file);
    },
    [handleFile]
  );

  const formatSize = (bytes: number): string => {
    if (bytes < 1024) return `${bytes} B`;
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
    return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
  };

  return (
    <div
      style={{
        padding: 10,
        overflow: "auto",
        height: "100%",
        color: "#ccc",
        fontSize: 11,
        fontFamily: "monospace",
      }}
    >
      {/* Upload area */}
      <div
        role="button"
        tabIndex={0}
        onDragOver={(e) => {
          e.preventDefault();
          setDragOver(true);
        }}
        onDragLeave={() => setDragOver(false)}
        onDrop={handleDrop}
        onClick={() => fileInputRef.current?.click()}
        onKeyDown={(e) => {
          if (e.key === "Enter" || e.key === " ") {
            e.preventDefault();
            fileInputRef.current?.click();
          }
        }}
        style={{
          border: `2px dashed ${dragOver ? "#4a9eff" : "#3a3a5a"}`,
          borderRadius: 6,
          padding: 20,
          textAlign: "center",
          cursor: "pointer",
          background: dragOver ? "#1a2a4a" : "#16162a",
          transition: "all 0.2s",
          marginBottom: 10,
        }}
      >
        <input
          ref={fileInputRef}
          type="file"
          accept=".mp4,.webm,.mov,.m4v,video/mp4,video/webm"
          onChange={handleFileInput}
          style={{ display: "none" }}
        />
        {uploading ? (
          <div>
            <div style={{ color: "#4a9eff", marginBottom: 6 }}>
              Uploading... {uploadProgress}%
            </div>
            <div
              style={{
                width: "100%",
                height: 6,
                background: "#2a2a4a",
                borderRadius: 3,
                overflow: "hidden",
              }}
            >
              <div
                style={{
                  width: `${uploadProgress}%`,
                  height: "100%",
                  background: "#4a9eff",
                  transition: "width 0.1s",
                }}
              />
            </div>
          </div>
        ) : (
          <div>
            <div style={{ fontSize: 24, marginBottom: 6 }}>📹</div>
            <div style={{ color: "#888", marginBottom: 4 }}>
              Drop a reference video here, or click to browse
            </div>
            <div style={{ color: "#555", fontSize: 10 }}>
              MP4/WebM/MOV · Max {MAX_FILE_SIZE_MB}MB · Max {MAX_DURATION_SECONDS}s
            </div>
          </div>
        )}
      </div>

      {/* Error display */}
      {error && (
        <div
          style={{
            background: "#3a1a1a",
            border: "1px solid #5a2a2a",
            borderRadius: 4,
            padding: "6px 10px",
            color: "#f88",
            marginBottom: 10,
          }}
        >
          ⚠ {error}
        </div>
      )}

      {/* Upload result */}
      {result && (
        <div>
          <div
            style={{
              background: "#1a2a1a",
              border: "1px solid #2a4a2a",
              borderRadius: 4,
              padding: "8px 10px",
              marginBottom: 10,
            }}
          >
            <div style={{ color: "#4f4", marginBottom: 6, fontWeight: "bold" }}>
              ✓ Upload successful
            </div>
            <div style={{ color: "#888", fontSize: 10, marginBottom: 2 }}>
              Asset ID: <span style={{ color: "#aaf" }}>{result.asset_id}</span>
            </div>
            <div style={{ color: "#888", fontSize: 10, marginBottom: 2 }}>
              File: {result.file_name} ({formatSize(result.file_size_bytes)})
            </div>
          </div>

          {/* Metadata */}
          <div
            style={{
              background: "#16162a",
              border: "1px solid #2a2a4a",
              borderRadius: 4,
              padding: "8px 10px",
              marginBottom: 10,
            }}
          >
            <div style={{ color: "#888", marginBottom: 6, fontSize: 10 }}>
              VIDEO METADATA
            </div>
            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 4 }}>
              <MetadataRow label="Duration" value={`${result.metadata.duration_seconds.toFixed(2)}s`} />
              <MetadataRow label="Resolution" value={`${result.metadata.width}×${result.metadata.height}`} />
              <MetadataRow label="Frame Rate" value={`${result.metadata.frame_rate.toFixed(1)} fps`} />
              <MetadataRow label="Frames" value={String(result.metadata.frame_count)} />
              <MetadataRow label="Codec" value={result.metadata.codec_name} />
              <MetadataRow label="Keyframes" value={String(result.keyframe_count)} />
            </div>
          </div>

          {/* Keyframes preview */}
          {result.keyframe_count > 0 && (
            <div>
              <div style={{ color: "#888", marginBottom: 6, fontSize: 10 }}>
                EXTRACTED KEYFRAMES ({result.keyframe_count})
              </div>
              <div
                style={{
                  display: "flex",
                  gap: 4,
                  flexWrap: "wrap",
                }}
              >
                {Array.from({ length: result.keyframe_count }).map((_, i) => (
                  <div
                    key={i}
                    style={{
                      width: 80,
                      height: 45,
                      background: "#2a2a4a",
                      borderRadius: 3,
                      display: "flex",
                      alignItems: "center",
                      justifyContent: "center",
                      color: "#666",
                      fontSize: 10,
                    }}
                  >
                    KF {i + 1}
                  </div>
                ))}
              </div>
              <div style={{ color: "#555", fontSize: 9, marginTop: 4 }}>
                Keyframes saved to: {result.keyframes_dir}
              </div>
            </div>
          )}

          {/* Depth extraction (white model) */}
          <div style={{ marginTop: 12, paddingTop: 10, borderTop: "1px solid #2a2a4a" }}>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 8 }}>
              <span style={{ color: "#888", fontSize: 10 }}>WHITE MODEL (DEPTH MAP)</span>
              <button
                onClick={extractDepth}
                disabled={extractingDepth}
                style={{
                  background: extractingDepth ? "#2a2a4a" : "#3a5a3a",
                  border: "none",
                  color: extractingDepth ? "#666" : "#fff",
                  padding: "4px 10px",
                  borderRadius: 3,
                  cursor: extractingDepth ? "default" : "pointer",
                  fontSize: 10,
                }}
              >
                {extractingDepth ? "⏳ Extracting..." : "🎭 Extract White Model"}
              </button>
            </div>

            {depthError && (
              <div style={{ background: "#3a1a1a", border: "1px solid #5a2a2a", borderRadius: 4, padding: "6px 10px", color: "#f88", marginBottom: 8, fontSize: 10 }}>
                ⚠ {depthError}
              </div>
            )}

            {depthResult && (
              <div>
                <div style={{ background: "#1a2a1a", border: "1px solid #2a4a2a", borderRadius: 4, padding: "6px 10px", marginBottom: 8 }}>
                  <div style={{ color: "#4f4", marginBottom: 4, fontSize: 10, fontWeight: "bold" }}>
                    ✓ White model extracted
                  </div>
                  <div style={{ color: "#888", fontSize: 9, marginBottom: 2 }}>
                    Asset ID: <span style={{ color: "#aaf" }}>{depthResult.asset_id}</span>
                  </div>
                  <div style={{ color: "#888", fontSize: 9 }}>
                    Output: {depthResult.output_width}×{depthResult.output_height}, {depthResult.frame_count} frames, {depthResult.duration_seconds.toFixed(2)}s
                  </div>
                  <div style={{ color: "#888", fontSize: 9, marginTop: 2 }}>
                    Model: {depthResult.model_type} | Colormap: {depthResult.colormap} | Time: {depthResult.processing_time_seconds.toFixed(1)}s
                  </div>
                </div>

                {depthResult.keyframe_count > 0 && (
                  <div>
                    <div style={{ color: "#888", marginBottom: 4, fontSize: 10 }}>
                      DEPTH KEYFRAMES ({depthResult.keyframe_count})
                    </div>
                    <div style={{ display: "flex", gap: 4, flexWrap: "wrap" }}>
                      {Array.from({ length: depthResult.keyframe_count }).map((_, i) => (
                        <div key={i} style={{ width: 80, height: 45, background: "linear-gradient(135deg, #1a1a1a 0%, #4a4a4a 50%, #ffffff 100%)", borderRadius: 3, display: "flex", alignItems: "center", justifyContent: "center", color: "#fff", fontSize: 9, textShadow: "0 0 3px #000" }}>
                          Depth {i + 1}
                        </div>
                      ))}
                    </div>
                    <div style={{ color: "#555", fontSize: 9, marginTop: 4 }}>
                      Saved to: {depthResult.keyframes_dir}
                    </div>
                  </div>
                )}
              </div>
            )}

            {!depthResult && !extractingDepth && !depthError && (
              <div style={{ color: "#555", fontSize: 9, lineHeight: 1.5 }}>
                Extract a depth-map "white model" from the uploaded video. Uses MiDaS monocular depth estimation. Closer objects appear brighter, giving the video model a sense of 3D space and camera movement.
              </div>
            )}
          </div>

          {/* 拉片复刻（hypit 理念 MVP 切片）：拆解参考片结构 → 复刻分镜草稿 */}
          <div style={{ marginTop: 12, paddingTop: 10, borderTop: "1px solid #2a2a4a" }}>
            <ReplicaTeardown
              assetId={result.asset_id}
              workflowId={workflowId}
              height={height - 32}
            />
          </div>
        </div>
      )}

      {/* Usage hint */}
      {!result && !uploading && !error && (
        <div
          style={{
            background: "#16162a",
            border: "1px solid #2a2a4a",
            borderRadius: 4,
            padding: "8px 10px",
            color: "#666",
            fontSize: 10,
            lineHeight: 1.5,
          }}
        >
          <div style={{ color: "#888", marginBottom: 4 }}>HOW IT WORKS</div>
          1. Upload a reference video with the camera movement and composition you want.<br />
          2. The system extracts evenly-spaced keyframes automatically.<br />
          3. Use the reference video (or keyframes) to condition the video model.<br />
          4. For models that don't support reference video, keyframes are used as fallback.<br />
          5. 想复刻这条片子的结构？上传后到下方「🎬 拉片复刻」拆解它 → 创建蓝图 →
          在画布复刻蓝图节点里替换槽位并生成复刻工作流。
        </div>
      )}
    </div>
  );
}

function MetadataRow({ label, value }: { label: string; value: string }) {
  return (
    <div style={{ display: "flex", justifyContent: "space-between", padding: "1px 0" }}>
      <span style={{ color: "#666" }}>{label}:</span>
      <span style={{ color: "#ccc" }}>{value}</span>
    </div>
  );
}
