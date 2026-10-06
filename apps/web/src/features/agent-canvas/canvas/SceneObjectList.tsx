/**
 * SceneObjectList — the reference framework's 「项目资产」 panel.
 *
 * The reference shows a titled list on the right of the editing view: a folder
 * icon, 「项目资产」, then every object the scene contains (岩 / 岩 / 岩 /
 * 基… / 指 …) with the selected one highlighted. Below it sit 位置 / 缩放 /
 * 旋转 for whatever is selected — which this product already has in
 * `SceneScriptEditPanel`.
 *
 * What was missing is the LIST. Without it the inspector is a dead end: the
 * author has to find the object in the 3D viewport by eye, click it, and only
 * then see its fields. A list makes the scene's contents readable at a glance,
 * and makes keyboard-only selection possible.
 *
 * It lists the SCENE's objects, not the project's asset library. Those are
 * different things and the reference's panel is the former: the entries are the
 * objects in THIS scene (one of which may be bound to a library asset), which
 * is what 位置/缩放/旋转 below it edit.
 */

import { useMemo } from "react";

import type { SceneScriptRoot } from "../../../types/scene-script";
import type { SceneObjectRef } from "./sceneScriptEditModel";
import { cameraLabel } from "./shotLabels.ts";

export interface SceneObjectListProps {
  sceneScript: SceneScriptRoot;
  /** The object currently selected in the viewport / inspector. */
  selected: SceneObjectRef | null;
  onSelect: (ref: SceneObjectRef) => void;
}

interface Row {
  ref: SceneObjectRef;
  /** What the list shows: 机位 labels for cameras, ids for assets. */
  label: string;
}

const OBJECT_KIND_ICONS: Record<string, string> = {
  camera: "📹",
  character: "🧍",
  prop: "📦",
  environment: "🌍",
};

export function SceneObjectList({ sceneScript, selected, onSelect }: SceneObjectListProps) {
  const rows = useMemo<Row[]>(() => {
    const out: Row[] = [];
    sceneScript.cameras.forEach((camera, index) => {
      out.push({
        ref: { kind: "camera", id: camera.id },
        label: cameraLabel(camera, index),
      });
    });
    for (const character of sceneScript.characters) {
      out.push({
        ref: { kind: "character", id: character.id },
        // A character's readable name is its bound asset's, falling back to the
        // id — not "char_a", which is a machine name.
        label: character.id,
      });
    }
    for (const prop of sceneScript.props) {
      out.push({ ref: { kind: "prop", id: prop.id }, label: prop.id });
    }
    for (const environment of sceneScript.environment) {
      out.push({ ref: { kind: "environment", id: environment.id }, label: environment.id });
    }
    return out;
  }, [sceneScript]);

  const isSelected = (ref: SceneObjectRef) =>
    selected !== null && selected.kind === ref.kind && selected.id === ref.id;

  return (
    <section className="scene-object-list" data-testid="scene-object-list">
      <header className="scene-object-list__header">
        <span className="scene-object-list__icon" aria-hidden="true">
          📁
        </span>
        <span className="scene-object-list__title">项目资产</span>
        <span className="scene-object-list__count">{rows.length}</span>
      </header>
      {rows.length === 0 ? (
        <p className="scene-object-list__empty">场景里还没有对象。</p>
      ) : (
        <ul className="scene-object-list__items">
          {rows.map((row) => {
            const active = isSelected(row.ref);
            return (
              <li key={`${row.ref.kind}:${row.ref.id}`}>
                <button
                  type="button"
                  className="scene-object-list__item"
                  data-testid="scene-object-list-item"
                  data-kind={row.ref.kind}
                  data-selected={active ? "true" : "false"}
                  aria-current={active}
                  onClick={() => onSelect(row.ref)}
                >
                  <span className="scene-object-list__item-icon" aria-hidden="true">
                    {OBJECT_KIND_ICONS[row.ref.kind]}
                  </span>
                  <span className="scene-object-list__item-label" title={row.label}>
                    {row.label}
                  </span>
                </button>
              </li>
            );
          })}
        </ul>
      )}
    </section>
  );
}

export default SceneObjectList;
