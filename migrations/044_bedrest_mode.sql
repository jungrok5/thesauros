-- 044 — alert_preferences.bedrest_mode: 책의 와병투자 정신
--
-- 책 2부 3장: "한달 내내 누워있다 말일 1회만 확인" — 매매는 안 할수록
-- 좋고, 매일 보면 매매 자주 하게 되고 손실 가능성 늘어남. 이 모드는
-- 사용자가 explicit ON 하면 평소 모든 알림을 끄고 주 1회 통합 요약만
-- 받음. 손가락이 자꾸 가는 사람을 위한 책-순응형 안전장치.
--
-- telegram_worker 가 bedrest_mode=true 인 사용자에게는 enter / pyramid
-- / warn / exit / target / stop / disclosure / ma240 / quarter_25
-- 어떤 alert 도 보내지 않음. 별도 weekly digest 만 발송 (구현 후속).

ALTER TABLE alert_preferences
  ADD COLUMN IF NOT EXISTS bedrest_mode BOOLEAN NOT NULL DEFAULT false;

COMMENT ON COLUMN alert_preferences.bedrest_mode IS
  '와병투자 모드 — true 면 모든 즉시 알림 OFF, 주 1회 요약만. '
  '책 2부 3장 정신.';
