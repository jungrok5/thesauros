import { test, expect, request } from "@playwright/test";

const BACKEND = process.env.BACKEND_URL ?? "http://127.0.0.1:8001";

/**
 * Backend smoke tests — hit the FastAPI endpoints directly from Playwright
 * to verify the surface area the web app depends on.
 */
test.describe("FastAPI backend", () => {
  test("health endpoint returns ok", async () => {
    const api = await request.newContext();
    const res = await api.get(`${BACKEND}/api/health`);
    expect(res.ok()).toBeTruthy();
    const body = await res.json();
    expect(body.ok).toBe(true);
  });

  test("macro snapshot has regime + indicators", async () => {
    const api = await request.newContext();
    const res = await api.get(`${BACKEND}/api/macro`);
    expect(res.ok()).toBeTruthy();
    const body = await res.json();
    expect(body.regime).toBeDefined();
    expect(body.regime.regime).toMatch(/^[A-Z_]+$/);
    expect(body.indicators).toBeDefined();
    expect(Object.keys(body.indicators).length).toBeGreaterThan(0);
  });

  test("book analyze returns book-rule output", async () => {
    const api = await request.newContext();
    const res = await api.get(
      `${BACKEND}/api/book/analyze?ticker=AAPL&years=5`,
    );
    expect(res.ok()).toBeTruthy();
    const body = await res.json();
    expect(body.ticker).toBe("AAPL");
    expect(["STRONG_BUY", "BUY", "HOLD", "SELL", "SELL_OR_SHORT", "AVOID"])
      .toContain(body.action);
    expect(body.trend).toBeDefined();
    expect(Array.isArray(body.patterns)).toBe(true);
  });

  test("book screen returns a candidate list", async () => {
    // Screening the full US universe (~500 tickers) takes ~90s.
    test.setTimeout(180_000);
    const api = await request.newContext({ timeout: 180_000 });
    const res = await api.get(
      `${BACKEND}/api/book/screen?market=us&min_score=0.95&top=10`,
    );
    expect(res.ok()).toBeTruthy();
    const body = await res.json();
    expect(body.market).toBe("us");
    expect(Array.isArray(body.items)).toBe(true);
    expect(body.total_scanned).toBeGreaterThan(0);
  });

  test("book backtest returns trade history", async () => {
    const api = await request.newContext();
    const res = await api.post(`${BACKEND}/api/book/backtest`, {
      data: { ticker: "AAPL", strategy: "monthly_10ma" },
    });
    expect(res.ok()).toBeTruthy();
    const body = await res.json();
    expect(body.ticker).toBe("AAPL");
    expect(body.n_trades).toBeGreaterThan(0);
    expect(Array.isArray(body.trades)).toBe(true);
  });
});
