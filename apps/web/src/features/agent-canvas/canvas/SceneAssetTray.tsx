/**
 * Scene asset tray — the low-poly vocabulary, one click from the scene.
 *
 * The palette IS the SceneScript primitive vocabulary (environment + prop
 * kinds, imported from the generated enums so a kind the backend adds is
 * immediately addable here). Clicking an entry appends the object at a
 * deterministic spiral position; the user drags it where they want (the
 * viewport's ground-plane drag is the placement precision tool — see
 * SceneScript3DPreview's edit mode).
 *
 * The color swatch mirrors SCENE_SCRIPT_ASSET_COLORS so what the palette
 * promises is what the preview and the Blender render show.
 */

import { useState } from "react";

import {
  ENVIRONMENT_TYPES,
  PROP_TYPES,
  SCENE_SCRIPT_ASSET_COLORS,
  type EnvironmentTypeName,
  type PropTypeName,
} from "../../../types/scene-script.generated";
import "../workbench/scene-3d-workbench.css";

export interface SceneAssetTrayProps {
  /** Add an environment-kind object to the scene. */
  onAddEnvironment: (kind: EnvironmentTypeName) => void;
  /** Add a prop-kind object to the scene. */
  onAddProp: (kind: PropTypeName) => void;
  /** Disabled while a save is in flight (the tray mutates the draft). */
  disabled?: boolean;
}

const KIND_LABELS: Record<string, string> = {
  // Environment
  wall: "墙",
  pillar: "柱",
  floor: "地面",
  gable_roof: "坡顶",
  flat_roof: "平顶",
  door: "门",
  window: "窗",
  stairs: "楼梯",
  platform: "平台",
  tree: "树",
  rock: "岩石",
  fence: "栅栏",
  ground: "地表",
  // Props
  round_table: "圆桌",
  rect_table: "方桌",
  chair: "椅子",
  stool: "凳子",
  lantern: "灯笼",
  box: "箱子",
  crate: "板条箱",
  vase: "花瓶",
  weapon: "武器",
  scroll: "卷轴",
  book: "书",
  cup: "杯",
};

export function SceneAssetTray({
  onAddEnvironment,
  onAddProp,
  disabled = false,
}: SceneAssetTrayProps) {
  const [openGroups, setOpenGroups] = useState({
    environment: true,
    prop: true,
  });

  // Each group is rendered explicitly (not mapped): the two kinds enums are
  // different string unions, and mapping a heterogeneous array would union
  // them into `never` at the add-callback call site.
  return (
    <aside className="scene-asset-tray" aria-label="低模资产托盘">
      <div className="scene-asset-tray__title">低模资产</div>

      <section className="scene-asset-tray__group">
        <button
          type="button"
          className="scene-asset-tray__group-toggle"
          aria-expanded={openGroups.environment}
          onClick={() =>
            setOpenGroups((current) => ({ ...current, environment: !current.environment }))
          }
        >
          {openGroups.environment ? "▾" : "▸"} 环境（{ENVIRONMENT_TYPES.length}）
        </button>
        {openGroups.environment && (
          <div className="scene-asset-tray__items">
            {ENVIRONMENT_TYPES.map((kind) => (
              <button
                key={kind}
                type="button"
                className="scene-asset-tray__item"
                data-tray-kind={kind}
                disabled={disabled}
                title={`添加${KIND_LABELS[kind] ?? kind}到场景`}
                onClick={() => onAddEnvironment(kind)}
              >
                <span
                  className="scene-asset-tray__swatch"
                  style={{ background: SCENE_SCRIPT_ASSET_COLORS[kind] ?? "#888" }}
                />
                {KIND_LABELS[kind] ?? kind}
              </button>
            ))}
          </div>
        )}
      </section>

      <section className="scene-asset-tray__group">
        <button
          type="button"
          className="scene-asset-tray__group-toggle"
          aria-expanded={openGroups.prop}
          onClick={() =>
            setOpenGroups((current) => ({ ...current, prop: !current.prop }))
          }
        >
          {openGroups.prop ? "▾" : "▸"} 道具（{PROP_TYPES.length}）
        </button>
        {openGroups.prop && (
          <div className="scene-asset-tray__items">
            {PROP_TYPES.map((kind) => (
              <button
                key={kind}
                type="button"
                className="scene-asset-tray__item"
                data-tray-kind={kind}
                disabled={disabled}
                title={`添加${KIND_LABELS[kind] ?? kind}到场景`}
                onClick={() => onAddProp(kind)}
              >
                <span
                  className="scene-asset-tray__swatch"
                  style={{ background: SCENE_SCRIPT_ASSET_COLORS[kind] ?? "#888" }}
                />
                {KIND_LABELS[kind] ?? kind}
              </button>
            ))}
          </div>
        )}
      </section>

      <p className="scene-asset-tray__hint">点击添加到场景，再到视口拖拽定位</p>
    </aside>
  );
}
