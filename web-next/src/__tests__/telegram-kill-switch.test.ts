/**
 * Regression tests for the site-side Telegram master kill switch.
 *
 * Telegram was paused 2026-07-08 via a default-off env gate
 * (TELEGRAM_ALERTS_ENABLED) inside sendTelegram — the single choke
 * point every outbound message (alerts, admin notifications, webhook
 * replies) flows through. These tests pin that the switch is off by
 * default, parses truthy values, and short-circuits the network send.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { sendTelegram, telegramAlertsEnabled } from "@/lib/telegram";

const ORIG = process.env.TELEGRAM_ALERTS_ENABLED;

beforeEach(() => {
  delete process.env.TELEGRAM_ALERTS_ENABLED;
  process.env.TELEGRAM_BOT_TOKEN = "dummy-token";
});

afterEach(() => {
  if (ORIG === undefined) delete process.env.TELEGRAM_ALERTS_ENABLED;
  else process.env.TELEGRAM_ALERTS_ENABLED = ORIG;
  vi.restoreAllMocks();
});

describe("telegramAlertsEnabled", () => {
  it("is off by default (env unset)", () => {
    expect(telegramAlertsEnabled()).toBe(false);
  });

  it("is off for falsey values", () => {
    for (const v of ["", "0", "false", "no", "off"]) {
      process.env.TELEGRAM_ALERTS_ENABLED = v;
      expect(telegramAlertsEnabled()).toBe(false);
    }
  });

  it("is on for truthy values", () => {
    for (const v of ["1", "true", "TRUE", "Yes", " on "]) {
      process.env.TELEGRAM_ALERTS_ENABLED = v;
      expect(telegramAlertsEnabled()).toBe(true);
    }
  });
});

describe("sendTelegram", () => {
  it("skips the network and reports disabled when off", async () => {
    const fetchSpy = vi.spyOn(globalThis, "fetch");
    const res = await sendTelegram("123", "hi");
    expect(res).toEqual({ ok: false, reason: "disabled" });
    expect(fetchSpy).not.toHaveBeenCalled();
  });

  it("attempts the send once re-enabled", async () => {
    process.env.TELEGRAM_ALERTS_ENABLED = "1";
    const fetchSpy = vi
      .spyOn(globalThis, "fetch")
      .mockResolvedValue(new Response("{}", { status: 200 }));
    const res = await sendTelegram("123", "hi");
    expect(res).toEqual({ ok: true });
    expect(fetchSpy).toHaveBeenCalledOnce();
  });
});
