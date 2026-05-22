/**
 * Sync guard — settings/alerts/page.tsx 의 CATEGORIES 와
 * api/alert-preferences/route.ts 의 FIELDS 가 같은 키 집합인지 확인
 * (회고 #4). 한쪽만 변경되면 toggle 이 silently 무시되거나 (form 에 있는데
 * API 가 모름) 또는 DB 에 안 들어감 (API 가 fetch 하는데 form 이 안 보여줌).
 */
import { describe, it, expect } from "vitest";
import fs from "node:fs";
import path from "node:path";


function extractFieldKeys(filePath: string, listName: string): Set<string> {
  const src = fs.readFileSync(filePath, "utf8");
  // Match `key: "..."` inside arrays or objects after the listName declaration.
  const block = src.split(listName).slice(1).join(listName);
  const keys = new Set<string>();
  for (const m of block.matchAll(/key:\s*["']([a-z_0-9]+)["']/g)) {
    keys.add(m[1]);
  }
  return keys;
}

function extractApiFields(): Set<string> {
  const src = fs.readFileSync(
    path.resolve(
      __dirname, "..", "app", "api", "alert-preferences", "route.ts",
    ),
    "utf8",
  );
  // Parse `const FIELDS = [\n  "a", "b", ...\n] as const;`
  const m = src.match(/const\s+FIELDS\s*=\s*\[([^\]]+)\]/);
  if (!m) throw new Error("FIELDS array not found");
  const out = new Set<string>();
  for (const fm of m[1].matchAll(/["']([a-z_0-9]+)["']/g)) {
    out.add(fm[1]);
  }
  return out;
}

describe("alert-preferences FIELDS ↔ CATEGORIES key set sync", () => {
  it("every category field key has a matching FIELDS entry", () => {
    const formKeys = extractFieldKeys(
      path.resolve(
        __dirname, "..", "app", "(app)", "settings", "alerts", "page.tsx",
      ),
      "CATEGORIES",
    );
    const apiKeys = extractApiFields();
    // The bedrest_mode is in FIELDS but NOT in CATEGORIES (it's a
    // separate top-level toggle in the form). So we only check
    // form-keys are subset of API-keys.
    const orphans = [...formKeys].filter((k) => !apiKeys.has(k));
    expect(
      orphans,
      `form has toggle keys that the API doesn't accept: ${orphans.join(", ")}`,
    ).toEqual([]);
  });

  it("FIELDS contains bedrest_mode (separate from per-toggle keys)", () => {
    const apiKeys = extractApiFields();
    expect(apiKeys.has("bedrest_mode"), "bedrest_mode must be in FIELDS").toBe(true);
  });

  it("no orphan API field — every FIELDS key is either in form or is bedrest_mode", () => {
    const formKeys = extractFieldKeys(
      path.resolve(
        __dirname, "..", "app", "(app)", "settings", "alerts", "page.tsx",
      ),
      "CATEGORIES",
    );
    const apiKeys = extractApiFields();
    // Known "out of CATEGORIES" keys — these are accepted by API but
    // displayed in dedicated UI (bedrest standalone) or kept for
    // backward compat (enable_daily_top5).
    const allowed_outside_categories = new Set([
      "bedrest_mode", "enable_daily_top5",
    ]);
    const orphans = [...apiKeys].filter(
      (k) => !formKeys.has(k) && !allowed_outside_categories.has(k),
    );
    expect(
      orphans,
      `API has fields no form toggle / standalone uses: ${orphans.join(", ")}`,
    ).toEqual([]);
  });
});
