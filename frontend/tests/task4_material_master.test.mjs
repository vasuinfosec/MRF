import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";

const screen = readFileSync(
  new URL("../app/material-master.tsx", import.meta.url), "utf8",
);
const masters = readFileSync(new URL("../app/masters.tsx", import.meta.url), "utf8");
const mrfCreate = readFileSync(new URL("../app/mrf/create.tsx", import.meta.url), "utf8");
const backend = readFileSync(
  new URL("../../backend/routers/material_master.py", import.meta.url), "utf8",
);

test("renders material, category, UOM and classification controls", () => {
  for (const label of [
    "Materials",
    "Categories",
    "UOM controls",
    "Classification",
  ]) {
    assert.ok(screen.includes(label), `missing screen section: ${label}`);
  }
  assert.match(screen, /Category → item → specification/);
});

test("wires all Task 4 lifecycle endpoints without delete operations", () => {
  for (const endpoint of [
    "/admin/material-master/categories",
    "/admin/material-master/uoms",
    "/admin/material-master/materials",
    "/admin/material-master/settings",
    "/status",
  ]) {
    assert.ok(screen.includes(endpoint), `missing endpoint contract: ${endpoint}`);
  }
  assert.doesNotMatch(screen, /method:\s*["']DELETE["']/);
  assert.doesNotMatch(backend, /@api\.delete\("\/admin\/material-master/);
});

test("material form covers linked identity and 100-word description", () => {
  for (const field of [
    "category_id",
    "item",
    "specification",
    "description",
    "make",
    "model",
    "uom_id",
  ]) {
    assert.ok(screen.includes(field), `missing material field: ${field}`);
  }
  assert.match(screen, /words > 100/);
  assert.match(screen, /DESCRIPTION · .*\/100 WORDS/);
  assert.match(screen, /material_uid/);
});

test("UOM controls include approved units and safe packaging conversion", () => {
  assert.match(screen, /"nos", "metre", "kg", "litre", "set", "box", "lot"/);
  assert.match(screen, /<Choice label="other"/);
  assert.match(screen, /Box\/lot requires a base UOM and conversion greater than zero/);
  assert.match(screen, /conversion_quantity/);
  assert.match(screen, /base_uom_id/);
});

test("classification keeps fasteners traceable and preserves AMC billing", () => {
  assert.match(backend, /FASTENER_TERMS/);
  assert.match(backend, /fastener\s+or/);
  assert.match(screen, /Low-value consumable candidate/);
  assert.match(screen, /Force traceability \/ reconciliation/);
  assert.match(screen, /AMC material/);
  assert.match(screen, /\["billed", "not_billed", "either"\]/);
  assert.match(screen, /low_value_threshold_inr/);
});

test("Admin authorization uses roles array and handles required states", () => {
  assert.match(screen, /user\?\.roles\?\.length/);
  assert.match(screen, /actorRoles\.includes\("admin"\)/);
  assert.match(screen, /user\?\.is_active/);
  assert.match(masters, /actorRoles\.includes\("admin"\)/);
  for (const phrase of [
    "Loading Material Master",
    "Permission denied",
    "Unable to load Material Master",
    "No materials",
  ]) {
    assert.ok(screen.includes(phrase), `missing UI state: ${phrase}`);
  }
});

test("responsive desktop and mobile behavior is implemented", () => {
  assert.match(screen, /useWindowDimensions/);
  assert.match(screen, /width < 760/);
  assert.match(screen, /pageCompact/);
  assert.match(screen, /formRowCompact/);
  assert.match(screen, /materialTopCompact/);
});

test("existing MRF material and unit contracts remain compatible", () => {
  assert.match(mrfCreate, /\/materials\?status=approved/);
  assert.match(mrfCreate, /unit:/);
  assert.match(backend, /"unit": uom\.get\("name"/);
  assert.match(backend, /"status": "approved"/);
  assert.match(backend, /"category": category\.get\("name"/);
});

test("screen includes lifecycle confirmation and no sample records", () => {
  assert.match(screen, /Historical MRF\/PO\/GRN\/DC records will remain unchanged/);
  assert.match(screen, /Deactivation never deletes historical material/i);
  assert.doesNotMatch(screen, /sample material|test material|example material/i);
});
