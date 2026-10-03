import type { CanvasNodeV2 } from "../../../types-v2.ts";

const ROLE_OVERRIDES: Partial<Record<CanvasNodeV2["creative_role"], string>> = {
  // The generic title-caser renders this "Scene 3d Previs Clip"; the canvas
  // elsewhere says "3D Previs" (nodeDefaults), so keep the family label.
  scene_3d_previs_clip: "3D Previs Clip",
};

export function creativeRoleDisplayName(role: CanvasNodeV2["creative_role"]): string {
  const override = ROLE_OVERRIDES[role];
  if (override) return override;
  return role
    .split("_")
    .map((part) => part.toLowerCase() === "bgm"
      ? "BGM"
      : `${part.slice(0, 1).toUpperCase()}${part.slice(1).toLowerCase()}`)
    .join(" ");
}
