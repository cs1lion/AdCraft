import { useEffect, useState } from "react";

import { api } from "../../../api/client.ts";
import type { ProviderModelSummaryV1 } from "../../../api/providerRegistry.ts";
import type { ModelDefaultPurpose } from "../../../api/providerRegistry.ts";
import type { AgentCanvasWorkflowV2, CanvasNodeV2 } from "../../../types-v2.ts";

const MODEL_PICKER_NODE_TYPES = new Set<CanvasNodeV2["node_type"]>([
  "text",
  "script",
  "image",
  "video",
  "audio",
  "editing",
]);

const DEFAULT_PURPOSE_BY_NODE_TYPE: Partial<Record<CanvasNodeV2["node_type"], ModelDefaultPurpose>> = {
  text: "text",
  script: "text",
  image: "image",
  video: "video",
  audio: "audio",
};

/**
 * The backend filters its catalog by the complete node/input contract. The
 * canvas intentionally never reconstructs provider compatibility locally.
 */
export function useAgentCanvasProviderModels(
  _workflow: AgentCanvasWorkflowV2 | null,
  node: CanvasNodeV2 | null,
) {
  const [models, setModels] = useState<ProviderModelSummaryV1[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [defaultModelRef, setDefaultModelRef] = useState<string | null>(null);
  const nodeType = node && MODEL_PICKER_NODE_TYPES.has(node.node_type)
    ? node.node_type
    : null;
  const defaultPurpose = nodeType ? DEFAULT_PURPOSE_BY_NODE_TYPE[nodeType] ?? null : null;

  useEffect(() => {
    if (!nodeType || !defaultPurpose) {
      setModels([]);
      setLoading(false);
      setError(null);
      setDefaultModelRef(null);
      return undefined;
    }
    let cancelled = false;
    setLoading(true);
    setError(null);
    setDefaultModelRef(null);
    void Promise.allSettled([
      api.listProviderModels({
        node_type: nodeType as "text" | "script" | "image" | "video" | "audio" | "editing",
        include_unavailable: true,
      }),
      api.getModelDefaults(),
    ]).then(([catalogResult, defaultsResult]) => {
      if (cancelled) return;
      if (catalogResult.status === "fulfilled") {
        setModels(catalogResult.value.items);
      } else {
        setModels([]);
      }
      if (defaultsResult.status === "fulfilled") {
        setDefaultModelRef(defaultsResult.value.defaults[defaultPurpose] ?? null);
      } else {
        setDefaultModelRef(null);
      }
      if (catalogResult.status === "rejected") {
        const catalogError = catalogResult.reason;
        setError(catalogError instanceof Error
          ? catalogError.message
          : "Compatible models could not be loaded.");
      } else if (defaultsResult.status === "rejected") {
        setError("Default model could not be loaded.");
      } else {
        setError(null);
      }
      setLoading(false);
    });
    return () => {
      cancelled = true;
    };
  }, [nodeType, defaultPurpose]);

  return { models, loading, error, defaultModelRef };
}
