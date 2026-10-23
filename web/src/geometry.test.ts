import { describe, expect, it } from "vitest";
import { fitViewport, hitTest, niceTick, screenToSheet, sheetToScreen, snapCenter, zoomAt, type Placed } from "./geometry";

const views: Placed[] = [
  { name: "front", center: [100, 100], box: [-40, -20, 56, 36] },
  { name: "top", center: [100.8, 200], box: [-40, -25, 56, 36] },
  { name: "iso", center: [300, 200], box: [-30, -30, 30, 30] },
];

describe("viewport", () => {
  it("round-trips sheet <-> screen", () => {
    const vp = { z: 2.5, ox: 40, oy: 30 };
    const p = screenToSheet(vp, 297, sheetToScreen(vp, 297, [123, 45]));
    expect(p[0]).toBeCloseTo(123);
    expect(p[1]).toBeCloseTo(45);
  });

  it("fits an A3 page inside the area and centres it", () => {
    const vp = fitViewport({ w: 1000, h: 700 }, [420, 297], { left: 18, top: 18, right: 0, bottom: 0 }, 24);
    expect(vp.z * 420).toBeLessThanOrEqual(1000);
    expect(vp.z * 297).toBeLessThanOrEqual(700);
    expect(vp.ox).toBeGreaterThanOrEqual(18 + 24);
  });

  it("zoom keeps the anchored sheet point fixed", () => {
    const vp = { z: 2, ox: 50, oy: 60 };
    const anchor: [number, number] = [300, 200];
    const before = screenToSheet(vp, 297, anchor);
    const after = screenToSheet(zoomAt(vp, anchor, 1.7), 297, anchor);
    expect(after[0]).toBeCloseTo(before[0]);
    expect(after[1]).toBeCloseTo(before[1]);
  });
});

describe("hitTest", () => {
  it("finds the view under a point, including its dimension area", () => {
    expect(hitTest(views, [120, 110])).toBe("front");
    expect(hitTest(views, [150, 130])).toBe("front"); // inside box, in the dimension margin
    expect(hitTest(views, [0, 0])).toBeNull();
  });
  it("prefers the smaller box when boxes overlap", () => {
    const overlap: Placed[] = [
      { name: "big", center: [50, 50], box: [-50, -50, 50, 50] },
      { name: "small", center: [50, 50], box: [-5, -5, 5, 5] },
    ];
    expect(hitTest(overlap, [50, 50])).toBe("small");
  });
});

describe("snapCenter", () => {
  it("snaps x to align the top view over the front view", () => {
    const s = snapCenter("top", [101.5, 150], views, 2);
    expect(s.center[0]).toBe(100);
    expect(s.guideX).toBe(100);
  });
  it("leaves the position alone beyond the threshold", () => {
    const s = snapCenter("top", [110, 150], views, 2);
    expect(s.center).toEqual([110, 150]);
    expect(s.guideX).toBeNull();
    expect(s.guideY).toBeNull();
  });
  it("never snaps to itself", () => {
    const s = snapCenter("front", [100, 100], [views[0]], 2);
    expect(s.guideX).toBeNull();
    expect(s.guideY).toBeNull();
  });
});

describe("niceTick", () => {
  it("returns 1/2/5 x 10^n steps", () => {
    for (const z of [0.5, 1, 2.2, 6, 30]) {
      const t = niceTick(z);
      const m = t / Math.pow(10, Math.floor(Math.log10(t)));
      expect([1, 2, 5]).toContain(Math.round(m));
    }
  });
});
