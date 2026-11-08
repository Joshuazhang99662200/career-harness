import assert from "node:assert/strict";
import { createElement } from "react";
import { renderToString } from "react-dom/server";

// No fake location/history globals: embedding must work without a browser.
const { MusePanel } = await import("../muse-lib/muse.js");
const muse = renderToString(createElement(MusePanel, { actions: {} }));
assert.ok(muse.includes("muse-space"));
assert.ok(muse.includes("读取求职队列中"));
console.log("Muse panel SSR smoke passed without browser globals.");
