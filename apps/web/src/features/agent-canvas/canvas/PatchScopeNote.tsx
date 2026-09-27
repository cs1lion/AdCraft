/**
 * PatchScopeNote — the sentence ADR 0009 demands be SAID.
 *
 * After an edit the author's real question is "what did I just affect?". The
 * backend answers it on every patch (the scope report); this surface repeats
 * the answer out loud. An unspoken "no neighbours affected" reads as "the
 * system didn't check" — which is exactly why the empty case gets the louder
 * message.
 *
 * Renders the LAST patch's report, optionally filtered to one node (the
 * workbench passes its own node so an unrelated patch elsewhere doesn't
 * narrate itself here).
 */

import { useLastPatchScopeReport, scopeSummary } from "./patchScopeReport.ts";

export interface PatchScopeNoteProps {
  /** Show only reports belonging to this node (omit to show the last one). */
  nodeId?: string | null;
}

export function PatchScopeNote({ nodeId = null }: PatchScopeNoteProps) {
  const record = useLastPatchScopeReport();
  if (!record) return null;
  if (nodeId && record.nodeId !== nodeId) return null;

  const { headline, detail } = scopeSummary(record);
  const affected = (record.report.affected_neighbours ?? []).length > 0;

  return (
    <p
      className="patch-scope-note"
      data-testid="patch-scope-note"
      data-affected={affected ? "true" : "false"}
    >
      <strong>{headline}</strong>
      {detail && <span className="patch-scope-note__detail">{detail}</span>}
    </p>
  );
}
