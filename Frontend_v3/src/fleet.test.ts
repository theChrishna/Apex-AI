import { describe, expect, it } from "vitest";
import { errShare, layout, riskTone } from "./fleet";

const e = (source: string, destination: string) => ({ source, destination });

describe("layout: any mesh", () => {
  it("puts services in columns by call depth (longest path from the entry)", () => {
    const l = layout(["lg", "frontend", "cart", "checkout", "payment"], [
      e("lg", "frontend"), e("frontend", "cart"), e("frontend", "checkout"), e("checkout", "cart"), e("checkout", "payment"),
    ]);
    expect(l.level).toEqual({ lg: 0, frontend: 1, checkout: 2, cart: 3, payment: 3 });   // cart is deeper via checkout
    expect(l.columns).toBe(4);
    expect(l.rows).toBe(2);
  });

  it("works for Online Boutique's 11 services without overlapping cards", () => {
    const svcs = ["loadgenerator", "frontend", "adservice", "cartservice", "checkoutservice", "currencyservice", "emailservice",
      "paymentservice", "productcatalogservice", "recommendationservice", "shippingservice"];
    const edges = [e("loadgenerator", "frontend"), ...["adservice", "cartservice", "checkoutservice", "currencyservice", "productcatalogservice",
      "recommendationservice", "shippingservice"].map((d) => e("frontend", d)), e("recommendationservice", "productcatalogservice"),
      ...["cartservice", "currencyservice", "emailservice", "paymentservice", "productcatalogservice", "shippingservice"].map((d) => e("checkoutservice", d))];
    const l = layout(svcs, edges);
    const cells = svcs.map((s) => `${l.level[s]}:${l.row[s]}`);
    expect(new Set(cells).size).toBe(svcs.length);                                      // every card has its own cell
    for (const x of edges) expect(l.level[x.destination]).toBeGreaterThan(l.level[x.source]);   // edges point right
  });

  it("survives a cycle and ignores edges to unknown services", () => {
    const l = layout(["a", "b"], [e("a", "b"), e("b", "a"), e("a", "ghost")]);
    expect(Object.keys(l.level).sort()).toEqual(["a", "b"]);
    expect(Math.max(...Object.values(l.level))).toBeLessThan(2);
  });

  it("handles a single service with no edges", () => {
    expect(layout(["solo"], [])).toMatchObject({ columns: 1, rows: 1, level: { solo: 0 } });
  });
});

describe("tones and error share", () => {
  it("uses the controller's thresholds", () => {
    expect([riskTone(0.2), riskTone(0.6), riskTone(0.85)]).toEqual(["ok", "warn", "crit"]);
  });
  it("prefers caller-side counts, which see injected and pre-pod failures", () => {
    expect(errShare({ source: "a", destination: "b", request_rate: 1, error_rate: 0, latency_p95: 5, src_request_rate: 2, src_error_rate: 1 })).toBe(0.5);
    expect(errShare({ source: "a", destination: "b", request_rate: 2, error_rate: 0.5, latency_p95: 5 })).toBe(0.25);
    expect(errShare({ source: "a", destination: "b", request_rate: 0, error_rate: 0, latency_p95: 0 })).toBe(0);
  });
});
