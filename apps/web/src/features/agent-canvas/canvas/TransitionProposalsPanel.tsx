/**
 * TransitionProposalsPanel — the Scene A → Scene B 衔接方案 picker.
 *
 * V0.2's #1 ask (§4.2/§13): two individually good shots do not make a good
 * cut, so the product should propose how to get from A to B and let the
 * creator choose. The backend proposes (six readings, each priced honestly),
 * this panel presents, and applying a proposal replays it through the SAME
 * preset libraries the inspector uses.
 *
 * "不自动修改" is written into the surface on purpose: the creator keeps the
 * chair (V0.2 §6.3).
 *
 * The speech-aware readings (声音桥 / 说完再切 / 时间跳跃) need the speech
 * timeline, so the panel forwards the segments the lip-sync run actually
 * applied — never a re-estimate (captions and mouths must not drift). An
 * advisory in the lip-sync panel can jump here with `autoFetchShotId`: the
 * playhead moves to the boundary shot and the readings for THAT pair load,
 * which is the "把顾问接到提案" wire from V0.2 §15.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import type { SceneScriptRoot } from "../../../types/scene-script";
import {
  applyTransitionOperations,
  type TransitionProposalPayload,
} from "./transitionProposals";
import { setShotTransitionIntent } from "./sceneScriptEditModel";
import {
  MAX_TRANSITION_VARIANTS,
  nextVariantLabel,
  type TransitionVariant,
} from "./transitionVariants";

/** One speech segment as the applied lip-sync run measured it. */
export interface TransitionSpeechSegment {
  segment_id?: string;
  character_id: string;
  text: string;
  /** Seconds. */
  start_time: number;
  /** Seconds. */
  end_time: number;
}

/**
 * Whether a shot's DECLARED entry reading still holds for the pair on screen
 * (V0.2 §13 第 5 问). ``holds`` is ``null`` when nothing is declared — that
 * is not a defect.
 */
export interface TransitionIntentAudit {
  declared: string | null;
  holds: boolean | null;
  label: string | null;
  reason: string | null;
  remedy: string | null;
}

export interface TransitionProposalsPanelProps {
  sceneScript: SceneScriptRoot;
  /**
   * The workflow and node ids that back this node in the agent-canvas DB.
   * Forwarded to the backend so retained_reading_ids can be persisted on
   * the node across sessions (V0.2 §14.5 known boundary).
   */
  workflowId?: string | null;
  nodeId?: string | null;
  /**
   * Reading ids already persisted on the node
   * (structured_content.retained_reading_ids). Used as the initial value
   * for engagedIds so a page refresh restores multi-round memory without
   * the LLM re-pitching its old ideas.
   */
  initialEngagedIds?: readonly string[];
  /** Shot the playhead is currently inside (the outgoing shot). */
  currentShotId: string | null;
  onChange: (next: SceneScriptRoot) => void;
  disabled?: boolean;
  /**
   * Speech segments measured by the applied lip-sync run. Forwarded to the
   * backend so the pause-based readings are priced against the real
   * timeline; without them those readings degrade to "infeasible" WITH a
   * reason (never silently).
   */
  speechSegments?: readonly TransitionSpeechSegment[];
  /**
   * Jump-here signal (V0.2 §15): the shot id an advisory pointed at. When it
   * arrives — and the pair has caught up to it — the readings for that pair
   * fetch once, so "看看怎么接" is one click, not three.
   */
  autoFetchShotId?: string | null;
  /**
   * Saved variants (V0.2 §9 局部分叉). The panel snapshots the current script
   * so readings can be compared instead of overwritten; the parent persists
   * them on the node the way the dialogue lines ride along.
   */
  variants?: readonly TransitionVariant[];
  onVariantsChange?: (variants: TransitionVariant[]) => void;
}
const LABEL_ORDER = [
  "continuous_motion",
  "gaze_closeup",
  "sound_bridge",
  "cut_after_line",
  "time_jump",
  "angle_switch",
];

export function TransitionProposalsPanel({
  sceneScript,
  workflowId = null,
  nodeId = null,
  initialEngagedIds = [],
  currentShotId,
  onChange,
  disabled = false,
  speechSegments = [],
  autoFetchShotId = null,
  variants = [],
  onVariantsChange,
}: TransitionProposalsPanelProps) {
  const [proposals, setProposals] = useState<TransitionProposalPayload[] | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [note, setNote] = useState<string | null>(null);
  // The LLM narrative layer (V0.2 §6.2/§15): off by default — the rule
  // narratives are the honest baseline, and an LLM call should be a choice.
  const [polish, setPolish] = useState(false);
  // The LLM proposal layer (§15 deepening): off by default too — proposed
  // readings are validated on the backend, but they are still the machine's
  // imagination and the author opts in.
  const [propose, setPropose] = useState(false);
  // Multi-round memory: readings the author APPLIED (they became the cut) or
  // DISMISSED (not wanted here). Both are reserved on the next fetch, so the
  // LLM is asked for something new instead of re-pitching its old ideas.
  const [engagedIds, setEngagedIds] = useState<string[]>(initialEngagedIds as string[]);
  const [narrativeSource, setNarrativeSource] = useState<string | null>(null);
  const [warnings, setWarnings] = useState<string[]>([]);
  // The declared entry reading, checked against this pair (§13 第 5 问).
  const [intentAudit, setIntentAudit] = useState<TransitionIntentAudit | null>(null);
  const autoFetchedShotRef = useRef<string | null>(null);

  // The pair: the current shot and the one that follows it in time.
  const pair = useMemo(() => {
    const ordered = [...sceneScript.shots].sort((a, b) => a.start_frame - b.start_frame);
    if (ordered.length < 2) return null;
    const index = currentShotId
      ? ordered.findIndex((shot) => shot.id === currentShotId)
      : 0;
    const from = ordered[index >= 0 ? index : 0];
    const to = ordered[(index >= 0 ? index : 0) + 1];
    return to ? { from, to } : { from, to: null };
  }, [sceneScript.shots, currentShotId]);

  const fetchProposals = useCallback(async () => {
    if (!pair?.to) return;
    setLoading(true);
    setError(null);
    setNote(null);
    try {
      const response = await fetch("/api/v1/scene-3d/transition-proposals", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          scene_script: sceneScript,
          shot_a_id: pair.from.id,
          shot_b_id: pair.to.id,
          // The segments the lip-sync run measured — the speech-aware
          // readings are priced against the same timeline the mouths ride.
          segments: speechSegments.map((segment) => ({
            segment_id: segment.segment_id,
            character_id: segment.character_id,
            text: segment.text,
            start_time: segment.start_time,
            end_time: segment.end_time,
          })),
          // Optional LLM narrative layer: only the prose, never the ops.
          polish_narratives: polish,
          // Optional LLM proposal layer: new readings, validated on the
          // backend against the operation vocabulary and the scene.
          propose_readings: propose,
          // Multi-round memory (V0.2 §15): what the author already engaged
          // with is reserved, so round 2 builds on round 1.
          exclude_reading_ids: engagedIds,
          // V0.2 §14.5 known boundary: persist engaged ids on the node so
          // a refresh restores multi-round memory.
          retained_reading_ids: engagedIds,
          ...(workflowId && nodeId
            ? { workflow_id: workflowId, node_id: nodeId }
            : {}),
        }),
      });
      const body = await response.json().catch(() => null);
      if (response.status !== 200 || !body) {
        const detail = body?.detail;
        throw new Error(
          (typeof detail === "object" && detail?.message) ||
            `衔接方案获取失败 (HTTP ${response.status})`,
        );
      }
      const list = (body.proposals ?? []) as TransitionProposalPayload[];
      list.sort(
        (a, b) => LABEL_ORDER.indexOf(a.id) - LABEL_ORDER.indexOf(b.id),
      );
      setProposals(list);
      setNarrativeSource(typeof body.narrative_source === "string" ? body.narrative_source : null);
      setWarnings(Array.isArray(body.warnings) ? body.warnings : []);
      const audit = body.intent_audit;
      setIntentAudit(
        audit && typeof audit === "object"
          ? {
              declared: typeof audit.declared === "string" ? audit.declared : null,
              holds: typeof audit.holds === "boolean" ? audit.holds : null,
              label: typeof audit.label === "string" ? audit.label : null,
              reason: typeof audit.reason === "string" ? audit.reason : null,
              remedy: typeof audit.remedy === "string" ? audit.remedy : null,
            }
          : null,
      );
    } catch (fetchError) {
      setError(fetchError instanceof Error ? fetchError.message : "衔接方案获取失败。");
    } finally {
      setLoading(false);
    }
  }, [pair, sceneScript, speechSegments, polish, propose, engagedIds]);

  // The advisory jump: fetch once per arriving signal, and only once the
  // pair has caught up with the shot the advisory pointed at (the playhead
  // seek and the pair recompute are separate renders). A spent signal
  // re-arms so the same boundary can be jumped to again later.
  useEffect(() => {
    if (!autoFetchShotId) {
      autoFetchedShotRef.current = null;
      return;
    }
    if (!pair?.to) return;
    if (autoFetchedShotRef.current === autoFetchShotId) return;
    if (pair.from.id !== autoFetchShotId) return;
    autoFetchedShotRef.current = autoFetchShotId;
    void fetchProposals();
  }, [autoFetchShotId, pair, fetchProposals]);

  const apply = useCallback(
    (proposal: TransitionProposalPayload) => {
      if (!proposal.feasible) return;
      // An applied reading is engaged: reserve it for the next round.
      setEngagedIds((current) =>
        current.includes(proposal.id) ? current : [...current, proposal.id],
      );
      const result = applyTransitionOperations(
        sceneScript,
        proposal,
        sceneScript.scene.frame_rate,
      );
      // The applied reading is also RECORDED as this shot's entry (V0.2 §13
      // 第 5 问). "Apply" means "this is the cut we chose", so the relation
      // must outlive the click: it shows on the shot strip and the boundary
      // can be checked against it. Declaring inside the same object keeps
      // script and label one atomic edit (no frame where the cut is applied
      // but the label is stale).
      const recorded = pair?.to
        ? setShotTransitionIntent(result.sceneScript, pair.to.id, proposal.id)
        : result.sceneScript;
      if (recorded !== result.sceneScript) onChange(recorded);
      else if (result.applied > 0) onChange(result.sceneScript);
      if (proposal.operations.length === 0) {
        // A zero-operation reading (声音桥) confirms intent; say so instead
        // of reporting a fake "applied 0 steps".
        setNote(
          `此读法无需修改——保留当前剪切即是有意的选择，已登记为 ${pair?.to?.id ?? ""} 的入镜读法。`,
        );
        return;
      }
      const parts = [`已应用 ${result.applied} 步`, "并登记入镜读法"];
      if (result.deferred.length > 0) {
        parts.push(`${result.deferred.length} 步需在视口完成（${result.deferred[0].reason}）`);
      }
      if (result.errors.length > 0) parts.push(result.errors[0]);
      setNote(parts.join(" · "));
    },
    [onChange, pair, sceneScript],
  );

  /** Record the relation only (V0.2 §13 第 5 问). */
  const recordIntent = useCallback(
    (proposal: TransitionProposalPayload) => {
      if (!pair?.to) return;
      onChange(setShotTransitionIntent(sceneScript, pair.to.id, proposal.id));
      setNote(`已登记 ${pair.to.id} 的入镜读法：${proposal.label}`);
    },
    [onChange, pair, sceneScript],
  );


  if (!pair || !pair.to) {
    return (
      <p className="transition-proposals__hint">
        至少需要两个镜头才能表达 A → B 的衔接。
      </p>
    );
  }

  // Save the current script as a comparable variant (V0.2 §9 局部分叉).
  const saveVariant = (proposalId: string | null) => {
    if (!onVariantsChange) return;
    const label = nextVariantLabel(variants);
    const variant: TransitionVariant = {
      id: `variant_${Date.now().toString(36)}`,
      label,
      proposal_id: proposalId,
      // The WHOLE script: the readings differ in camera and character
      // keyframes alike, so a partial snapshot would mix two readings.
      scene_script: sceneScript as unknown as Record<string, unknown>,
    };
    onVariantsChange([...variants, variant].slice(-MAX_TRANSITION_VARIANTS));
  };

  const removeVariant = (id: string) => {
    if (!onVariantsChange) return;
    onVariantsChange(variants.filter((variant) => variant.id !== id));
  };

  return (
    <section className="transition-proposals" data-testid="transition-proposals">
      <header className="transition-proposals__head">
        <strong>
          衔接方案 · {pair.from.id} → {pair.to.id}
        </strong>
        <button
          type="button"
          data-testid="transition-proposals-fetch"
          disabled={disabled || loading}
          onClick={() => void fetchProposals()}
        >
          {loading ? "生成中…" : proposals ? "重新生成" : "🎬 生成衔接方案"}
        </button>
      </header>
      <p className="transition-proposals__hint">
        六个读法由系统提出、由你选择；应用只写入运动预设，不自动修改镜头结构。
      </p>
      <label className="transition-proposals__polish">
        <input
          type="checkbox"
          data-testid="transition-proposals-polish"
          checked={polish}
          disabled={disabled}
          onChange={(event) => setPolish(event.target.checked)}
        />
        ✨ 让 LLM 解释每个读法（只改叙事理由，不改操作）
      </label>
      <label className="transition-proposals__polish">
        <input
          type="checkbox"
          data-testid="transition-proposals-propose"
          checked={propose}
          disabled={disabled}
          onChange={(event) => setPropose(event.target.checked)}
        />
        ✨ 让 LLM 补充新读法（每个读法都必须通过操作词表与场景校验）
      </label>
      {narrativeSource === "llm" && (
        <p className="transition-proposals__hint" data-testid="transition-proposals-llm">
          叙事由 LLM 解释；每条读法的操作不变。
        </p>
      )}
      {warnings.map((warning) => (
        <p key={warning} className="transition-proposals__infeasible">
          {warning}
        </p>
      ))}
      {error && <p className="transition-proposals__error">{error}</p>}
      {intentAudit?.declared && (
        <p
          className={`transition-proposals__intent-audit${
            intentAudit.holds === false ? " is-stale" : ""
          }`}
          data-testid="transition-intent-audit"
          data-holds={intentAudit.holds === null ? "unknown" : String(intentAudit.holds)}
        >
          {intentAudit.holds === false ? "⚠ " : "✓ "}
          {pair.to.id} 登记的入镜读法「{intentAudit.label ?? intentAudit.declared}」
          {intentAudit.holds === false ? " 已不成立" : " 仍然成立"}
          {intentAudit.holds === false && intentAudit.reason ? `：${intentAudit.reason}` : ""}
          {intentAudit.holds === false && intentAudit.remedy ? ` → ${intentAudit.remedy}` : ""}
        </p>
      )}
      {note && (
        <p className="transition-proposals__note" data-testid="transition-proposals-note">
          {note}
        </p>
      )}
      {/* Engaged readings leave the picker: an applied one is now in the
          script, a dismissed one is not wanted here. Both stay reserved for
          the next round, so the LLM builds on them instead of repeating. */}
      {proposals
        ?.filter((proposal) => !engagedIds.includes(proposal.id))
        .map((proposal) => (
        <article
          key={proposal.id}
          className="transition-proposals__item"
          data-feasible={proposal.feasible ? "true" : "false"}
        >
          <header>
            <strong>{proposal.label}</strong>
            {proposal.origin === "llm" && (
              // The author must always be able to tell which readings the
              // machine invented (V0.2 §6.3: LLM proposes, the creator chooses).
              <span className="transition-proposals__origin" data-testid={`transition-origin-${proposal.id}`}>
                LLM 补充
              </span>
            )}
            <button
              type="button"
              data-testid={`transition-apply-${proposal.id}`}
              disabled={disabled || !proposal.feasible}
              onClick={() => apply(proposal)}
            >
              应用
            </button>
            {/* §13 第 5 问: declare the relation without replaying it. The
                author may know how the cut works before the keyframes are
                authored, and a declaration that only exists at apply time is
                a relation nobody can state up front. */}
            <button
              type="button"
              className="transition-proposals__intent"
              data-testid={`transition-intent-${proposal.id}`}
              disabled={disabled || !pair?.to}
              title={`把这条读法登记为 ${pair?.to?.id ?? ""} 的入镜读法（不改关键帧）`}
              onClick={() => recordIntent(proposal)}
            >
              登记入镜读法
            </button>
            {proposal.origin === "llm" && (
              <button
                type="button"
                className="transition-proposals__dismiss"
                data-testid={`transition-dismiss-${proposal.id}`}
                disabled={disabled}
                title="不再看这条读法（下一轮不再提出）"
                onClick={() =>
                  setEngagedIds((current) =>
                    current.includes(proposal.id) ? current : [...current, proposal.id],
                  )
                }
              >
                ×
              </button>
            )}
          </header>
          <p className="transition-proposals__narrative">{proposal.narrative}</p>
          {!proposal.feasible && (
            <p className="transition-proposals__infeasible">
              暂不可用：{proposal.infeasible_reason ?? "条件不足"}
            </p>
          )}
          {proposal.feasible && proposal.operations.length === 0 && (
            <p className="transition-proposals__noop" data-testid={`transition-noop-${proposal.id}`}>
              此读法无需修改：声音跨过画面切换本来就是成立的做法（V0.2 §14.13「声音先到」）。
            </p>
          )}
          {proposal.feasible && proposal.operations.length > 0 && (
            <ul className="transition-proposals__ops">
              {proposal.operations.map((operation, index) => (
                <li key={`${proposal.id}-${index}`}>{operation.rationale}</li>
              ))}
            </ul>
          )}
          {/* Keep this reading beside the others instead of overwriting it
              (V0.2 §9: 播放多个版本，而不是反复覆盖同一个结果). */}
          {onVariantsChange && (
            <button
              type="button"
              className="transition-proposals__save-variant"
              data-testid={`transition-save-variant-${proposal.id}`}
              disabled={disabled}
              title="把当前脚本存为一个方案，稍后与别的读法对比"
              onClick={() => saveVariant(proposal.id)}
            >
              存为方案
            </button>
          )}
        </article>
      ))}

      {/* The kept versions: restore one to bring it back as the draft (the
          dirty/save machinery then decides whether it hits the node), or
          drop it. The cap is stated, not silently enforced — the research's
          own warning is that branches explode. */}
      {onVariantsChange && (
        <div className="transition-proposals__variants" data-testid="transition-variants">
          <span className="dialogue-lipsync__advisories-title">
            已存方案（{variants.length}/{MAX_TRANSITION_VARIANTS}，可对比后恢复）
          </span>
          {variants.map((variant) => (
            <div
              key={variant.id}
              className="transition-proposals__variant"
              data-testid={`transition-variant-${variant.id}`}
            >
              <strong>{variant.label}</strong>
              <button
                type="button"
                data-testid={`transition-variant-restore-${variant.id}`}
                disabled={disabled}
                title="把这个方案恢复为当前草稿（随后可保存到节点）"
                onClick={() =>
                  onChange(variant.scene_script as unknown as SceneScriptRoot)
                }
              >
                恢复
              </button>
              <button
                type="button"
                className="transition-proposals__dismiss"
                data-testid={`transition-variant-remove-${variant.id}`}
                disabled={disabled}
                title="删除这个方案"
                onClick={() => removeVariant(variant.id)}
              >
                ×
              </button>
            </div>
          ))}
          {variants.length === 0 && (
            <p className="transition-proposals__hint">
              应用一个读法后点「存为方案」，即可把不同衔接并排比较。
            </p>
          )}
        </div>
      )}
    </section>
  );
}
