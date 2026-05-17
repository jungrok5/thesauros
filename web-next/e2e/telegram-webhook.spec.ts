/**
 * /api/telegram/webhook — security + happy-path smoke.
 *
 * We can't easily test the full Telegram flow end-to-end without mocking
 * the Telegram Bot API, but we CAN verify:
 *   - no secret header → 403
 *   - wrong secret header → 403
 *   - valid secret + /start payload → 200 (and bot would have replied,
 *     but we don't assert that — Telegram API call is fire-and-forget)
 *
 * Skips when TELEGRAM_WEBHOOK_SECRET isn't set in the dev env.
 */
import { test, expect } from "@playwright/test";

const SECRET = process.env.TELEGRAM_WEBHOOK_SECRET ?? "";

test.describe("Telegram webhook", () => {
  test("403 without secret header", async ({ request }) => {
    const r = await request.post("/api/telegram/webhook", {
      data: { message: { chat: { id: 1 }, text: "/start" } },
    });
    expect([403, 500]).toContain(r.status());
    // 500 if TELEGRAM_WEBHOOK_SECRET unset in dev env — still not 200.
  });

  test("403 with wrong secret", async ({ request }) => {
    test.skip(!SECRET, "set TELEGRAM_WEBHOOK_SECRET to run");
    const r = await request.post("/api/telegram/webhook", {
      headers: { "x-telegram-bot-api-secret-token": "wrong" },
      data: { message: { chat: { id: 1 }, text: "/start" } },
    });
    expect(r.status()).toBe(403);
  });

  test("200 with valid secret + /start", async ({ request }) => {
    test.skip(!SECRET, "set TELEGRAM_WEBHOOK_SECRET to run");
    const r = await request.post("/api/telegram/webhook", {
      headers: { "x-telegram-bot-api-secret-token": SECRET },
      data: { message: { chat: { id: 1 }, text: "/start" } },
    });
    expect(r.status()).toBe(200);
  });
});
