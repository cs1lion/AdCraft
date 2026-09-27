/**
 * What "这个" means (V0.2 §8.2: 空间指向会减少语言歧义).
 *
 * A pointer only reduces ambiguity if the language layer can NAME it — so the
 * label and the prompt token are one phrase, defined once here rather than
 * re-derived by each surface that shows it. They are pure functions in their
 * own module on purpose: the 3D editor is lazy-loaded and mocked in tests,
 * and a workbench that cannot name the pointer because its editor is a mock
 * would be a workbench that stops naming it in production too.
 */

import type { SceneObjectRef } from "./sceneScriptEditModel.ts";

const OBJECT_KIND_LABELS: Record<SceneObjectRef["kind"], string> = {
  character: "角色",
  prop: "道具",
  environment: "环境",
  camera: "相机",
};

/** "角色 char_a" — the object the author currently points at. */
export function describeObjectPointer(
  ref: SceneObjectRef | null | undefined,
): string | null {
  if (!ref?.id) return null;
  return `${OBJECT_KIND_LABELS[ref.kind] ?? ref.kind} ${ref.id}`;
}

/**
 * The explicit token appended to a prompt when the author points with words:
 * 【指向：角色 char_a】. Written INTO the prompt (visible) rather than sent
 * beside it (invisible), so the author sees exactly what the system will read.
 */
export function objectPointerToken(
  ref: SceneObjectRef | null | undefined,
): string | null {
  const label = describeObjectPointer(ref);
  return label ? `【指向：${label}】` : null;
}
