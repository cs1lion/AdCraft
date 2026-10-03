"""Shared policy for Canvas authoring metadata that never reaches providers."""

from __future__ import annotations


NON_PROVIDER_NODE_PARAMETER_KEYS = frozenset(
    {
        "requested_run",
        "source_option_id",
        "source_proposal_id",
        "stage_draft_key",
        # Replica shot ownership is Canvas bookkeeping, not a model input.
        "replica_node_id",
    }
)
