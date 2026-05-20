/**
 * Pure functions for investor-intel card "💡 action line" copy.
 *
 * Kept in lib (not the component) so a vitest can exercise the
 * bucket boundaries without rendering React. The component imports
 * these and only handles layout.
 */

import type { InstitutionalOwnershipRow } from "./stock-context";

export function consensusActionLine(
  targetPrice: number | null | undefined,
  lastClose: number | null | undefined,
): string {
  if (
    targetPrice == null ||
    lastClose == null ||
    !Number.isFinite(targetPrice) ||
    !Number.isFinite(lastClose) ||
    lastClose <= 0
  ) {
    return "애널리스트들이 보는 향후 1년 시각. 참고용 — 책 정신은 어쨌든 추세를 따라가는 것.";
  }
  const upside = ((targetPrice - lastClose) / lastClose) * 100;
  if (upside > 30) {
    return `현재가가 목표가 대비 ${upside.toFixed(0)}% 낮음 → 애널리스트들은 “저평가” 라고 봄. 단 그게 함정일 수도 있어서 차트 추세 같이 확인.`;
  }
  if (upside > 0) {
    return `현재가가 목표가에 ${(-upside).toFixed(0)}% 못 미침 → 컨센은 “조금 더 오를 여지” 본다는 정도.`;
  }
  if (upside > -10) {
    return `이미 목표가 근접 (${(-upside).toFixed(0)}% 위) — 컨센 입장에서는 “지금쯤 차익실현해도 되는 자리”.`;
  }
  return `현재가가 목표가를 ${(-upside).toFixed(0)}% 초과 — 컨센보다 시장이 더 흥분 중. 추격은 신중.`;
}

export function holdersActionLine(rows: InstitutionalOwnershipRow[]): string {
  const hasNps = rows.some((r) => r.holder_type === "NPS");
  // 외부 큰손만 합산 — 계열사 cross-holding 은 따라할 의미가 없으니 제외.
  const externalPct = rows
    .filter((r) => r.holder_type !== "AFFILIATE")
    .reduce((s, r) => s + (r.share_pct ?? 0), 0);
  const affiliatePct = rows
    .filter((r) => r.holder_type === "AFFILIATE")
    .reduce((s, r) => s + (r.share_pct ?? 0), 0);

  if (hasNps && externalPct >= 20) {
    return "국민연금이 들어와 있고 외부 큰손 합산 비중도 두꺼움 → 기관 매물 부담은 작고, 폭락장에서도 어느 정도 받쳐주는 종목.";
  }
  if (hasNps) {
    return "국민연금이 들고 있는 종목 — 운용 관점에서 “안전 후보”. 다만 국민연금이 지분 줄이기 시작하면 (정기보고서로 확인 가능) 단기 약세 신호.";
  }
  if (affiliatePct >= 20 && externalPct < 10) {
    return "보유 큰손의 대부분이 그룹 계열사 — cross-holding 으로 잠긴 지분. 외부 기관/펀드 유입은 작은 종목이라 모멘텀은 약할 수 있음.";
  }
  if (externalPct >= 30) {
    return "외부 큰손 합산 30% 이상 — 유통주식 비중이 작아 변동성 크고, 한 명이 던지면 흔들릴 수 있음.";
  }
  return "5% 이상 보유한 큰손 명단. 큰손이 많이 들고 있는 종목은 자금 흐름이 단단해서 변동성이 조금 작다.";
}

export function earningsActionLine(daysUntilNext: number): string {
  if (daysUntilNext >= 0 && daysUntilNext <= 14) {
    return `발표일까지 ${daysUntilNext} 일 남음 — 새 진입은 발표 후로 미루는 게 안전. 발표 결과로 흐름이 바뀔 수 있음.`;
  }
  if (daysUntilNext >= 0 && daysUntilNext <= 45) {
    return `${daysUntilNext} 일 뒤 발표 → 그전에 컨센과 큰 괴리가 보이면 미리 비중 조절. 발표가 가까울수록 변동성 ↑.`;
  }
  return "실적 발표 직전·직후는 변동성이 크다. 추세 안 잡힌 종목이라면 발표 통과 후 진입하는 게 안전.";
}

/** UTC-stable: server may render in any timezone but the diff is
 * always against UTC midnight today, so deterministic per test run. */
export function daysFromToday(iso: string, now: Date = new Date()): number {
  const t = new Date(iso + "T00:00:00Z").getTime();
  return Math.round((t - now.getTime()) / 86400000);
}
