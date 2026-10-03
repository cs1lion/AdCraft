import React, { useEffect, useState, useCallback, useRef } from "react";
import { agentCanvasApi } from "../../../api/agentCanvasApi.ts";
import type {
  CreationFlowAssessmentResponse,
  CreationFlowStageStatus,
} from "../../../types-v2";
import "./creation-flow-guidance.css";

interface CreationFlowGuidanceProps {
  workflowId: string;
  /** Poll interval in ms. Default 5000. Set 0 to disable polling. */
  pollInterval?: number;
  /** Whether to show the detailed stage list. Default true. */
  showDetails?: boolean;
  /** Callback when assessment is loaded. */
  onAssessment?: (assessment: CreationFlowAssessmentResponse) => void;
}

/**
 * Creation flow guidance component.
 *
 * Shows the 6-stage structured-derivation 3D previs creation flow:
 * world_setting → script → storyboard → scene_3d → binding → render
 *
 * Displays progress bar, current stage, next action, and per-stage status.
 * Powers the guided creation-flow UX (P4).
 */
export const CreationFlowGuidance: React.FC<CreationFlowGuidanceProps> = ({
  workflowId,
  pollInterval = 5000,
  showDetails = true,
  onAssessment,
}) => {
  const [assessment, setAssessment] = useState<CreationFlowAssessmentResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [expandedStage, setExpandedStage] = useState<string | null>(null);

  const onAssessmentRef = useRef(onAssessment);
  const generationRef = useRef(0);
  const requestRef = useRef(0);
  const retryRef = useRef<(() => void) | null>(null);

  useEffect(() => {
    onAssessmentRef.current = onAssessment;
  }, [onAssessment]);

  // Keep the retry handler stable; callback changes must not restart polling.
  const fetchAssessment = useCallback(() => retryRef.current?.(), []);

  useEffect(() => {
    const generation = ++generationRef.current;
    let cancelled = false;
    let inFlight = false;
    let timer: ReturnType<typeof setTimeout> | undefined;
    setAssessment(null);
    setError(null);
    setExpandedStage(null);
    setLoading(true);

    const fetchCurrentAssessment = async () => {
      if (cancelled || inFlight) return;
      clearTimeout(timer);
      inFlight = true;
      const request = ++requestRef.current;
      const isCurrent = () => !cancelled
        && generationRef.current === generation
        && requestRef.current === request;
      setLoading(true);
      try {
        const result = await agentCanvasApi.getCreationFlowAssessment(workflowId);
        if (!isCurrent()) return;
        setAssessment(result);
        setError(null);
        onAssessmentRef.current?.(result);
      } catch {
        if (!isCurrent()) return;
        setError("Unable to refresh creation flow. Please try again.");
      } finally {
        if (isCurrent()) {
          inFlight = false;
          setLoading(false);
          // Schedule only after settling, so slow requests never overlap.
          if (pollInterval > 0) {
            timer = setTimeout(() => { void fetchCurrentAssessment(); }, pollInterval);
          }
        }
      }
    };

    retryRef.current = () => { void fetchCurrentAssessment(); };
    void fetchCurrentAssessment();
    return () => {
      cancelled = true;
      retryRef.current = null;
      clearTimeout(timer);
    };
  }, [workflowId, pollInterval]);

  if (loading && !assessment) {
    return (
      <div className="creation-flow-guidance creation-flow-loading">
        <div className="creation-flow-spinner" />
        <span>Loading creation flow...</span>
      </div>
    );
  }

  if (error && !assessment) {
    return (
      <div className="creation-flow-guidance creation-flow-error">
        <span className="creation-flow-error-icon">⚠</span>
        <span>{error}</span>
        <button onClick={fetchAssessment} className="creation-flow-retry-btn">
          Retry
        </button>
      </div>
    );
  }

  if (!assessment) return null;

  const {
    current_stage,
    progress_percent,
    next_action,
    next_action_detail,
    blockers,
    warnings,
    is_complete,
    stage_statuses,
  } = assessment;

  return (
    <div className="creation-flow-guidance">
      {error && (
        <div className="creation-flow-error" role="status">
          <span>
            {loading
              ? "Showing the last update. Retrying…"
              : "Showing the last update. Creation flow may be out of date."}
          </span>
          <button
            onClick={fetchAssessment}
            className="creation-flow-retry-btn"
            disabled={loading}
          >
            {loading ? "Retrying…" : "Retry"}
          </button>
        </div>
      )}
      {/* Header */}
      <div className="creation-flow-header">
        <div className="creation-flow-title">
          <span className="creation-flow-title-icon">🎬</span>
          <span>Creation Flow</span>
          {is_complete && <span className="creation-flow-complete-badge">Complete</span>}
        </div>
        <div className="creation-flow-progress-text">{progress_percent.toFixed(0)}%</div>
      </div>

      {/* Progress bar */}
      <div className="creation-flow-progress-bar">
        <div
          className="creation-flow-progress-fill"
          style={{ width: `${progress_percent}%` }}
        />
        <div className="creation-flow-stage-markers">
          {stage_statuses.map((stage, idx) => (
            <div
              key={stage.stage}
              className={`creation-flow-stage-marker ${
                stage.completed ? "completed" : stage.stage === current_stage ? "current" : "pending"
              }`}
              style={{ left: `${(idx / (stage_statuses.length - 1)) * 100}%` }}
              title={stage.display_name}
            >
              {stage.completed ? "✓" : idx + 1}
            </div>
          ))}
        </div>
      </div>

      {/* Current stage + next action */}
      <div className="creation-flow-current">
        <div className="creation-flow-current-stage">
          <span className="creation-flow-label">Current:</span>
          <span className="creation-flow-stage-name">{stage_statuses.find(s => s.stage === current_stage)?.display_name || current_stage}</span>
        </div>
        <div className="creation-flow-next-action">
          <span className="creation-flow-label">Next:</span>
          <span className="creation-flow-action-text">{next_action}</span>
        </div>
        {next_action_detail && (
          <div className="creation-flow-action-detail">{next_action_detail}</div>
        )}
      </div>

      {/* Blockers */}
      {blockers.length > 0 && (
        <div className="creation-flow-blockers">
          <div className="creation-flow-blockers-title">
            <span>⚠</span> Blockers ({blockers.length})
          </div>
          <ul className="creation-flow-blocker-list">
            {blockers.slice(0, 3).map((blocker, idx) => (
              <li key={idx} className="creation-flow-blocker-item">{blocker}</li>
            ))}
          </ul>
          {blockers.length > 3 && (
            <details className="creation-flow-blocker-more" key={`blockers-${workflowId}`}>
              <summary>Show {blockers.length - 3} more blockers</summary>
              <ul className="creation-flow-blocker-list">
                {blockers.slice(3).map((blocker, idx) => (
                  <li key={idx} className="creation-flow-blocker-item">{blocker}</li>
                ))}
              </ul>
            </details>
          )}
        </div>
      )}

      {/* Warnings */}
      {warnings.length > 0 && (
        <div className="creation-flow-warnings">
          {warnings.slice(0, 3).map((warning, idx) => (
            <div key={idx} className="creation-flow-warning-item">
              <span>💡</span> {warning}
            </div>
          ))}
          {warnings.length > 3 && (
            <details className="creation-flow-warning-more" key={`warnings-${workflowId}`}>
              <summary>Show {warnings.length - 3} more warnings</summary>
              {warnings.slice(3).map((warning, idx) => (
                <div key={idx} className="creation-flow-warning-item">
                  <span>💡</span> {warning}
                </div>
              ))}
            </details>
          )}
        </div>
      )}

      {/* Detailed stage list */}
      {showDetails && (
        <div className="creation-flow-stages">
          {stage_statuses.map((stage) => (
            <StageStatusCard
              key={stage.stage}
              stage={stage}
              isCurrent={stage.stage === current_stage}
              expanded={expandedStage === stage.stage}
              onToggle={() => setExpandedStage(expandedStage === stage.stage ? null : stage.stage)}
            />
          ))}
        </div>
      )}
    </div>
  );
};

// ---------------------------------------------------------------------------
// Stage status card sub-component
// ---------------------------------------------------------------------------

interface StageStatusCardProps {
  stage: CreationFlowStageStatus;
  isCurrent: boolean;
  expanded: boolean;
  onToggle: () => void;
}

const StageStatusCard: React.FC<StageStatusCardProps> = ({
  stage,
  isCurrent,
  expanded,
  onToggle,
}) => {
  const statusClass = stage.completed ? "completed" : isCurrent ? "current" : "pending";

  return (
    <div className={`creation-flow-stage-card ${statusClass}`}>
      <button
        className="creation-flow-stage-header"
        onClick={onToggle}
        aria-expanded={expanded}
      >
        <span className={`creation-flow-stage-icon ${statusClass}`}>
          {stage.completed ? "✓" : isCurrent ? "●" : "○"}
        </span>
        <span className="creation-flow-stage-name">{stage.display_name}</span>
        <span className="creation-flow-stage-count">
          {stage.ready_nodes}/{stage.total_nodes} ready
        </span>
        <span className="creation-flow-stage-chevron">{expanded ? "▲" : "▼"}</span>
      </button>

      {expanded && (
        <div className="creation-flow-stage-detail">
          <p className="creation-flow-stage-desc">{stage.description}</p>
          {stage.blockers.length > 0 && (
            <div className="creation-flow-stage-blockers">
              <span className="creation-flow-stage-blockers-label">Blockers:</span>
              <ul>
                {stage.blockers.map((blocker, idx) => (
                  <li key={idx}>{blocker}</li>
                ))}
              </ul>
            </div>
          )}
          {stage.completed && stage.blockers.length === 0 && (
            <div className="creation-flow-stage-complete-msg">✓ Stage complete</div>
          )}
        </div>
      )}
    </div>
  );
};

export default CreationFlowGuidance;
