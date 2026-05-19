/**
 * Naver's weekly bars carry the Friday week-ending date as their
 * `bar_date`. Mid-week (e.g. on Tuesday), the latest bar's date is
 * therefore *this Friday* — i.e. a future date — even though the
 * close value is the latest actual trading day. The UI showing a
 * future date confuses users ("최종 종가 5월 22일?"). We clamp the
 * displayed date to today.
 *
 * Inputs are plain `YYYY-MM-DD` strings, not Dates — that's what
 * Supabase returns for DATE columns and the API hands to the client.
 * String comparison works because ISO-8601 dates sort lexicographically.
 */
export function clampAsOfToToday(
  barDate: string,
  todayIso: string,
): string {
  return barDate > todayIso ? todayIso : barDate;
}
