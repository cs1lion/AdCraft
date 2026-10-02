/**
 * 词汇表跨边界契约（F5/P3）。
 *
 * 四套词汇表共用一个枢纽——后端 schema 枚举（经 scene-script.generated.ts
 * 生成到前端）：
 * 1. 语言搭建关键词（VOCAB/ANCHOR_WORDS）映射的目标类型必须存在于 schema，
 *    否则 ops 批在 apply-operations 闸门被拒（object_type_unsupported）；
 * 2. 工作台运动预设表必须与后端 /director-motion 能展开的预设 id 完全一致：
 *    UI 显示但后端不认识的预设会在闸门失败，只有后端有的预设是用户永远
 *    看不见的死能力。
 * 生成器：python -m app.cli.generate_scene_script_preview_contract。
 */

import { describe, expect, it } from "vitest";

import {
  DIRECTOR_CAMERA_MOTION_PRESET_IDS,
  DIRECTOR_CHARACTER_MOTION_PRESET_IDS,
  ENVIRONMENT_TYPES,
  PROP_TYPES,
} from "../../../types/scene-script.generated";
import { CAMERA_MOTION_PRESETS } from "./cameraMotionPresets.ts";
import { CHARACTER_MOTION_PRESETS } from "./characterMotionPresets.ts";
import { ANCHOR_WORDS, VOCAB } from "./sceneLanguageOps.ts";

describe("language-builder keyword vocabulary", () => {
  it("only maps keywords to types the backend schema declares", () => {
    const props = new Set<string>(PROP_TYPES);
    const environments = new Set<string>(ENVIRONMENT_TYPES);
    for (const entry of [...VOCAB, ...ANCHOR_WORDS]) {
      // 角色类型是自由形（schema 里 "lowpoly_human" | string），不锁
      if (entry.kind === "character") continue;
      const allowed = entry.kind === "prop" ? props : environments;
      expect(allowed.has(entry.type), `${entry.pattern} maps to unknown type "${entry.type}"`).toBe(
        true,
      );
    }
  });
});

describe("director motion preset tables", () => {
  it("camera presets match the backend-generated id list", () => {
    expect(CAMERA_MOTION_PRESETS.map((preset) => preset.id).sort()).toEqual(
      [...DIRECTOR_CAMERA_MOTION_PRESET_IDS].sort(),
    );
  });

  it("character presets match the backend-generated id list", () => {
    expect(CHARACTER_MOTION_PRESETS.map((preset) => preset.id).sort()).toEqual(
      [...DIRECTOR_CHARACTER_MOTION_PRESET_IDS].sort(),
    );
  });
});
