import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";

const screen = readFileSync(
  new URL("../app/access-console.tsx", import.meta.url), "utf8",
);
const more = readFileSync(new URL("../app/more.tsx", import.meta.url), "utf8");
const auth = readFileSync(new URL("../src/auth.tsx", import.meta.url), "utf8");
const api = readFileSync(new URL("../src/api.ts", import.meta.url), "utf8");

test("renders the three required access sections", () => {
  for (const id of [
    "pending-requests-section",
    "invited-inactive-section",
    "active-users-section",
  ]) {
    assert.match(screen, new RegExp(`testID="${id}"`));
  }
});

test("wires every Task 3B backend operation", () => {
  for (const endpoint of [
    "/admin/access/pending-requests",
    "/admin/access/invitations",
    "/admin/access/pending-users",
    "/admin/access/users",
    "/activate",
    "/deactivate",
    "/roles",
    "/sessions/revoke",
    "/history",
    "/reject",
    "/invite",
  ]) {
    assert.ok(screen.includes(endpoint), `missing endpoint contract: ${endpoint}`);
  }
});

test("supports multi-role assignment and Director restrictions", () => {
  assert.match(screen, /selectedRoles/);
  assert.match(screen, /toggleRole/);
  assert.match(screen, /role !== "director" \|\| actorIsDirector/);
  assert.match(screen, /canMutateDirector/);
  assert.match(screen, /target\.user_id === user\?\.user_id/);
  assert.match(screen, /Backend policy remains authoritative/);
});

test("handles responsive and all required UI states", () => {
  assert.match(screen, /useWindowDimensions/);
  assert.match(screen, /width < 760/);
  for (const id of [
    "access-console-loading",
    "access-console-denied",
    "access-console-error",
    "access-console-success",
  ]) {
    assert.match(screen, new RegExp(`testID="${id}"`));
  }
  assert.match(screen, /<Empty /);
});

test("console is feature-detected and hidden when V2 is unavailable", () => {
  assert.match(more, /\/admin\/access\/permissions\/me/);
  assert.match(more, /accessConsoleEnabled \?/);
  assert.match(more, /router\.push\("\/access-console"\)/);
  assert.match(more, /isAdmin && !accessConsoleEnabled/);
});

test("frontend authorization supports roles array and active state", () => {
  assert.match(auth, /roles\?: string\[\]/);
  assert.match(more, /user\?\.roles\?\.length/);
  assert.match(more, /user\?\.is_active/);
  assert.match(screen, /actorRoles\.includes\("admin"\)/);
  assert.match(screen, /actorRoles\.includes\("director"\)/);
});

test("API surfaces structured backend security messages", () => {
  assert.match(api, /detail\?\.message/);
  assert.match(api, /detail\?\.error/);
});

test("console contains no hard-coded sample or test users", () => {
  assert.doesNotMatch(screen, /@vasu\.dev|@example\.|sample user|test user/i);
});
