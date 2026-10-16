import { describe, expect, it } from "vitest";

import { normalizeV2AssetVersionListResponse } from "./v2Normalizers.ts";

// Locks the asset-version list projection. What matters here is that a missing
// field never becomes `undefined` in the result (the UI would render "undefined"
// or crash on a comparison), and that an unrecognised status is treated as
// "ready" rather than passed through as a bogus literal.

function version(overrides: Record<string, unknown> = {}) {
  return {
    version_id: "version-1",
    asset_id: "asset-1",
    version_no: 2,
    storage_key: "assets/asset-1/v2.png",
    sha256: "a".repeat(64),
    size_bytes: 2048,
    mime_type: "image/png",
    width: 1024,
    height: 768,
    duration_seconds: null,
    status: "ready",
    created_at: "2026-07-28T10:06:00Z",
    ...overrides,
  };
}

describe("normalizeV2AssetVersionListResponse", () => {
  it("returns an empty list for a non-object", () => {
    expect(normalizeV2AssetVersionListResponse(null)).toEqual({ versions: [] });
    expect(normalizeV2AssetVersionListResponse("nope")).toEqual({ versions: [] });
    expect(normalizeV2AssetVersionListResponse({})).toEqual({ versions: [] });
  });

  it("projects a complete version", () => {
    const result = normalizeV2AssetVersionListResponse({ versions: [version()] });
    expect(result.versions).toHaveLength(1);
    expect(result.versions[0]).toMatchObject({
      version_id: "version-1",
      asset_id: "asset-1",
      version_no: 2,
      size_bytes: 2048,
      mime_type: "image/png",
      width: 1024,
      height: 768,
      status: "ready",
    });
  });

  it("never leaves a required string as undefined", () => {
    const result = normalizeV2AssetVersionListResponse({ versions: [{}] });
    const projected = result.versions[0];
    expect(projected.version_id).toBe("");
    expect(projected.asset_id).toBe("");
    expect(projected.storage_key).toBe("");
    expect(projected.sha256).toBe("");
    expect(projected.mime_type).toBe("");
    expect(projected.created_at).toBe("");
    expect(projected.version_no).toBe(0);
    expect(projected.size_bytes).toBe(0);
  });

  it("keeps nullable numbers as null rather than zero", () => {
    const result = normalizeV2AssetVersionListResponse({ versions: [version()] });
    expect(result.versions[0].width).toBe(1024);
    expect(result.versions[0].duration_seconds).toBeNull();
  });

  it("treats an unrecognised status as ready", () => {
    const ready = normalizeV2AssetVersionListResponse({
      versions: [version({ status: "ready" })],
    });
    const odd = normalizeV2AssetVersionListResponse({
      versions: [version({ status: "banana" })],
    });
    const gone = normalizeV2AssetVersionListResponse({
      versions: [version({ status: "unavailable" })],
    });
    expect(ready.versions[0].status).toBe("ready");
    expect(odd.versions[0].status).toBe("ready");
    expect(gone.versions[0].status).toBe("unavailable");
  });

  it("defaults quality to null and metadata to an empty object", () => {
    const result = normalizeV2AssetVersionListResponse({ versions: [version()] });
    expect(result.versions[0].quality).toBeNull();
    expect(result.versions[0].metadata).toEqual({});
  });

  it("projects every entry in the list", () => {
    const result = normalizeV2AssetVersionListResponse({
      versions: [version({ version_id: "v1" }), version({ version_id: "v2" })],
    });
    expect(result.versions.map((entry) => entry.version_id)).toEqual(["v1", "v2"]);
  });
});
