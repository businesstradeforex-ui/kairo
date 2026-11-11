import test from "node:test";
import assert from "node:assert/strict";
import { badgeDelta, isUp, segments, sliceRange } from "../kairo/static/js/chart-math.js";
import { scoutCounts } from "../kairo/static/js/mappers.js";

test("full range badge matches starting capital, not the last step", () => {
  const pts = [{ t: 1, equity: 1000 }, { t: 2, equity: 1000.01 }, { t: 3, equity: 995.35 }];
  assert.ok(Math.abs(badgeDelta(pts, "all", 1000) - (995.35 - 1000)) < 1e-9);
  assert.equal(isUp(pts, "all", 1000), false);
  assert.ok(Math.abs(badgeDelta(pts, "1h", 1000) - (995.35 - 1000)) < 1e-9);
});

test("a hole is not one straight segment", () => {
  const now = 10_000_000;
  const pts = [
    { t: now - 3_600_000, equity: 100 },
    { t: now - 3_000_000, equity: 110 },
    { t: now - 200_000, equity: 90 },
    { t: now, equity: 91 },
  ];
  const segs = segments(sliceRange(pts, "1h", now), "1h");
  assert.ok(segs.length >= 2);
});

test("scout counts stay unknown when the agent has not reported", () => {
  assert.deepEqual(scoutCounts({}, {}), { pairs: null, scanned: null });
  assert.deepEqual(scoutCounts({ counters: { candidates: 12, mints_seen: 59 } }, {}), { pairs: 12, scanned: 59 });
});
