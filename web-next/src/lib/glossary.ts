/**
 * Plain-Korean glossary for the UI tooltips.
 *
 * Each entry: { title, body, link? }. Keys are stable slugs the UI can
 * reference by string. Definitions are intentionally self-contained — no
 * references to outside sources beyond optional public encyclopedia links.
 */

export type GlossaryEntry = {
  title: string;
  body: string;
  link?: { href: string; label?: string };
};

export const GLOSSARY: Record<string, GlossaryEntry> = {
  // ─────────── Chart patterns ───────────
  ssang_badak: {
    title: "쌍바닥 (Double Bottom)",
    body:
      "비슷한 가격대에서 두 번 바닥을 찍고 반등하는 W 모양 패턴.\n" +
      "두 번째 바닥이 첫 번째보다 살짝 낮거나 같으면 신뢰도가 올라가고, " +
      "두 바닥을 잇는 저항선(목선)을 거래량과 함께 돌파하면 추세 전환 신호로 본다.",
    link: {
      href: "https://en.wikipedia.org/wiki/Double_top_and_double_bottom",
      label: "Wikipedia (영문) →",
    },
  },
  cup_with_handle: {
    title: "원형바닥 (Cup with Handle)",
    body:
      "주가가 U자(컵) 모양으로 천천히 바닥을 다진 뒤, 컵 우측 끝에서 " +
      "짧고 얕은 조정(손잡이)을 거쳐 다시 상승하는 패턴.\n" +
      "손잡이의 조정 폭이 작을수록 신뢰도가 높다. 미국식 성장주 매수 시점으로 " +
      "널리 쓰인다.",
    link: {
      href: "https://en.wikipedia.org/wiki/Cup_and_handle",
      label: "Wikipedia (영문) →",
    },
  },
  dolbanji_240ma: {
    title: "돌반지 (240MA 돌파-지지-반등)",
    body:
      "240일 이동평균선(약 1년 평균가)을 위로 돌파한 뒤 → 다시 240MA 근처까지 " +
      "눌렸다가 → 그 자리에서 지지를 받아 반등하는 3단계 시퀀스.\n" +
      "장기 추세 전환 후 첫 번째 눌림목 매수 자리로 본다.",
  },
  short_term_double_bottom: {
    title: "단기 쌍바닥",
    body:
      "쌍바닥 중 두 바닥 사이 간격이 며칠~몇 주로 짧은 형태. " +
      "단타/스윙 매매에서 매수 시점으로 활용된다.",
  },
  reverse_h_and_s: {
    title: "역헤드앤숄더 (Inverse H&S)",
    body:
      "왼쪽 어깨 - 머리(더 깊은 저점) - 오른쪽 어깨 형태로 세 번 바닥을 만든 뒤, " +
      "목선을 돌파하면 상승 추세로 전환되는 패턴. 하락에서 상승으로 가는 대표 반전형.",
    link: {
      href: "https://en.wikipedia.org/wiki/Head_and_shoulders_(chart_pattern)",
      label: "Wikipedia (영문) →",
    },
  },
  flag: {
    title: "깃발형 (Flag)",
    body:
      "강한 상승(깃대) 후 짧고 좁은 박스권(깃발)을 만들며 잠시 쉬는 패턴. " +
      "박스 상단을 돌파하면 직전 상승폭만큼 한 번 더 가는 경우가 많아 계속형(continuation) 패턴으로 분류된다.",
  },
  ascending_triangle: {
    title: "상승 삼각형 (Ascending Triangle)",
    body:
      "저점은 계속 높아지고 고점은 일정한 저항선을 만드는 삼각수렴. " +
      "저항선을 거래량 동반 돌파 시 상승 지속 신호.",
    link: {
      href: "https://en.wikipedia.org/wiki/Triangle_(chart_pattern)",
      label: "Wikipedia (영문) →",
    },
  },

  // ─────────── Candle / zone terms ───────────
  yangbong: {
    title: "양봉 (상승 캔들)",
    body: "종가가 시가보다 높은 캔들 — 그 날(또는 기간) 매수세가 우세했음을 의미한다.",
  },
  eumbong: {
    title: "음봉 (하락 캔들)",
    body: "종가가 시가보다 낮은 캔들 — 그 날(또는 기간) 매도세가 우세했음을 의미한다.",
  },
  jangdae_yangbong: {
    title: "장대양봉",
    body:
      "몸통이 평균보다 훨씬 긴 양봉. 강한 매수 유입을 시사하며, 추세 시작 또는 " +
      "재가속의 신호로 본다. 다만 고점에서 나타나면 단기 과열 후 조정 가능성도 있다.",
  },
  nunsseop_candle: {
    title: "눈썹 캔들",
    body:
      "위쪽 꼬리(윗그림자)가 몸통보다 훨씬 긴 캔들. " +
      "상승 시도 후 매물에 눌려 종가가 다시 내려간 모습 → 단기 매도 압력을 의미한다.",
  },
  safe_zone_75: {
    title: "4등분선 75% 안전지대",
    body:
      "최근 캔들의 시가–고가–저가–종가 범위를 4등분 했을 때, " +
      "종가가 위쪽 75% 구간 안에 들어와 있는 상태.\n" +
      "그 날 중·상위권에서 마감했다는 뜻으로, 매수세가 살아 있다는 시그널로 활용한다.",
  },

  // ─────────── Timeframes ───────────
  tf_daily: {
    title: "DAILY (일봉)",
    body: "캔들 1개 = 하루. 단기 매매 / 진입·이탈 타이밍을 보는 시간 단위.",
  },
  tf_weekly: {
    title: "WEEKLY (주봉)",
    body:
      "캔들 1개 = 1주일. 중기 추세 판단에 사용. " +
      "일봉 노이즈를 걸러 큰 흐름을 보고 싶을 때 본다.",
  },
  tf_monthly: {
    title: "MONTHLY (월봉)",
    body:
      "캔들 1개 = 1개월. 장기 추세 판단에 사용. " +
      "수년에 걸친 사이클·바닥권 확인에 유용.",
  },

  // ─────────── Volume cases ───────────
  // ─────────── 거래량 11+1 케이스 (책 p364) ───────────
  volume_case_0: {
    title: "Case 0 · 분류 불명확",
    body:
      "거래량 패턴이 명확한 책 시그널과 매칭 안 되는 상태. 거의 모든 케이스에 " +
      "soft fallback이 있어 case 0는 OHLCV가 결손인 경우 정도에만 발생.",
  },
  volume_case_1: {
    title: "Case 1 · 가격대 + 거래량 횡보",
    body:
      "박스권 정체 — 큰 상승 신호 없이 분산 상태. 책 권고: 매매 보류, 다음 봉 관찰. " +
      "추세 방향성이 잡힐 때까지 진입 X.",
  },
  volume_case_2: {
    title: "Case 2 · 거래량 감소 횡보 (죽은 차트)",
    body:
      "상투권 + 횡보 + 거래량 감소. 매수세 증발 = 책 표현 \"죽은 차트\". " +
      "추세 사망, 회피.",
  },
  volume_case_3: {
    title: "Case 3 · 바닥권 거래량 폭증 ⭐",
    body:
      "바닥권에서 평균 대비 3배 이상 거래량 폭증. 책의 가장 강한 매수 신호 중 하나 — " +
      "추세 반전이 시작되는 자리. 거래량이 \"숨길 수 없는 진짜 시그널\".",
  },
  volume_case_4: {
    title: "Case 4 · 바닥권 급락 + 거래량 감소",
    body:
      "바닥권에서 가격 하락 + 거래량 감소. 받쳐주는 물량은 적지만 매도세도 " +
      "지친 상태. 단기 반등은 가능하지만 큰 신호 X.",
  },
  volume_case_5: {
    title: "Case 5 · 바닥권 급락 + 거래량 증가",
    body:
      "바닥권 + 하락 + 거래량 증가. 우량주면 매수 기회, 부실주면 대주주 매물 " +
      "출회. 책 권고: 종목 질로 판단.",
  },
  volume_case_6: {
    title: "Case 6 · 상승 초기 거래량 폭증",
    body:
      "중간 가격대에서 상승 초기 + 거래량 폭증. 책: 개인에게 떠넘기는 자리일 수 있음, " +
      "신중히 진입.",
  },
  volume_case_7: {
    title: "Case 7 · 급등 중 거래량 감소 ⭐",
    body:
      "상승 추세 중 거래량 감소. 책: 세력이 매집을 끝내고 물량을 들고 있는 상태 — " +
      "강한 손이 매수해서 손바뀜 없이 그대로 가격이 올라가는 모습. 좋은 신호.",
  },
  volume_case_8: {
    title: "Case 8 · 상투권 거래량 감소 (세력 위임)",
    body:
      "상투권 + 거래량 감소. 세력이 개인에게 시장을 맡긴 상태. 다음 움직임 관찰.",
  },
  volume_case_9: {
    title: "Case 9 · 상투권 거래량 폭증 (세력 털기) ⚠",
    body:
      "이미 많이 오른 자리(상투권)에서 거래량이 평균 대비 3배 이상 증가.\n" +
      "기관·세력이 보유 물량을 개인에게 넘기는 \"분산\" 가능성 — 단기 약세 경계.\n" +
      "위꼬리 거부 캔들 동반 시 \"세력 털기 확정\" 강한 매도 신호.",
  },
  volume_case_10: {
    title: "Case 10 · 상투 후 급락 시작",
    body:
      "상투권 직후 하락 시작 + 거래량 증가. 책: 세력 설거지 의심. 청산 + 신규 매수 X.",
  },
  volume_case_11: {
    title: "Case 11 · 상투 후 급락 + 거래량 감소",
    body:
      "상투 이후 하락 진행 중 거래량 감소. 세력 떠나고 개미만 남은 상태 = 회피.",
  },
  volume_case_12: {
    title: "Case 12 · 수렴기 거래량 감소 ⭐",
    body:
      "중간/바닥권에서 가격 횡보 + 거래량 감소 (\"빨래 널기\" / \"기간 조정\").\n" +
      "책 정신: 개미는 뜸 들이다 떨어져 나가고, 매물이 소진되는 단계. " +
      "포킹 발사 (장대양봉 + 거래량 증가) 직전 자리일 가능성. 매복 대기.",
  },
  volume_case_generic: {
    title: "거래량 분류 (책 11+1 케이스)",
    body:
      "현재 구간(저점/중간/고점)과 추세 방향, 그리고 평균 대비 거래량 비율을 조합해 " +
      "책의 12가지 패턴 중 하나로 분류한 결과. " +
      "각 Case 는 신뢰도(%)와 방향(bullish/bearish/neutral)을 함께 가진다.",
  },

  // ─────────── RSI / MACD ───────────
  rsi: {
    title: "RSI (Relative Strength Index)",
    body:
      "최근 14주 동안의 상승/하락 비율로 모멘텀을 0~100 사이 숫자로 표현.\n" +
      "30 미만 = oversold(과매도), 70 초과 = overbought(과매수).\n" +
      "책 정신: RSI는 보조 신호. 추세가 강세면 oversold는 \"눌림목 매수 자리 후보\", " +
      "추세가 약세면 oversold는 \"하락 지속\". 단독으로는 매매 시그널 X.",
    link: {
      href: "https://en.wikipedia.org/wiki/Relative_strength_index",
      label: "Wikipedia →",
    },
  },
  macd: {
    title: "MACD (Moving Average Convergence Divergence)",
    body:
      "12주 EMA와 26주 EMA의 차이(MACD line) + 9주 EMA로 다시 평활화한 signal line.\n" +
      "골든크로스 (MACD가 signal 위로) = 상승 모멘텀 시작, 데드크로스 = 하락 모멘텀.\n" +
      "책 정신: MACD 골든크로스 + 후킹 캔들 = 강한 매수, 데드크로스 + 저승사자 = 청산. " +
      "단독 매매 X, 캔들/가격과 corroboration용.",
    link: {
      href: "https://en.wikipedia.org/wiki/MACD",
      label: "Wikipedia →",
    },
  },
  macd_divergence: {
    title: "MACD 다이버전스 (Divergence)",
    body:
      "가격은 신고가 만드는데 MACD는 더 낮은 고점 (약세 다이버전스) → 매수세 약화.\n" +
      "가격은 신저점인데 MACD는 더 높은 저점 (강세 다이버전스) → 매도세 소진.\n" +
      "다이버전스 단독 X, 캔들 반전 신호와 함께 사용.",
  },

  // ─────────── 책 어휘 ───────────
  hooking_candle: {
    title: "후킹 캔들 (Hooking Candle)",
    body:
      "주봉/월봉 10MA를 강하게 뚫는 장대양봉. 책에서 쌍바닥/역H&S/삼중바닥 패턴이 " +
      "\"완성\"되는 결정적 캔들. 거래량이 동반되어야 진짜 (매물 소화 확인). " +
      "후킹 캔들 직후가 매수 자리.",
  },
  reaper_candle: {
    title: "저승사자 캔들 (Reaper Candle)",
    body:
      "주봉/월봉 10MA를 강하게 깨는 장대음봉. 책에서 쌍봉/H&S 패턴이 \"완성\"되는 " +
      "결정적 캔들. \"10원이라도 뚫리면\" 90% 하락 확정 — 즉시 청산.",
  },
  jangdae_eumbong: {
    title: "장대음봉",
    body:
      "한 봉에서 시초 대비 종가 5%+ 하락한 큰 음봉. 책: 매도 압력 시그널. " +
      "주봉 10MA를 동시에 깨면 \"저승사자 캔들\"로 격상 → 청산.",
  },
  gura_candle: {
    title: "구라캔들 (Fake Candle)",
    body:
      "큰 봉인데 거래량이 평균 대비 부족 (≤ 0.7배). 책: \"거래량은 숨길 수 없다\" — " +
      "거래량 없는 큰 봉은 세력 의도 부재 = 가짜 신호 의심.",
  },
  yangpalbong: {
    title: "양팔봉",
    body:
      "위·아래 꼬리 모두 큰 캔들 + 작은 몸통. 매수·매도 힘이 강하게 부딪힌 자리. " +
      "방향 미정 — 다음 봉 갭상승/하락 보고 결정.",
  },
  hidden_jangdae: {
    title: "은둔형 장대양봉",
    body:
      "작은 양봉 3개가 누적 5%+ 상승. 한 봉에 다 안 보이지만 세력이 분할 매집 중. " +
      "책: 은밀한 매집 신호 = 매수 후보.",
  },
  jugobatgo_candle: {
    title: "주고받고 캔들",
    body:
      "장대양봉 다음 봉이 작은 음봉인데 그 양봉의 75% 안전지대 안에서 마감. " +
      "정상 소화 = 추세 계속, 매수 자리 유지.",
  },
  catalyst_candle: {
    title: "장대양봉 catalyst",
    body:
      "이전 12주 동안 15%+ 하락 + 큰 양봉 (body 10%+) + 거래량 2.5배+ 폭증 + " +
      "직전 바닥 근처에서 출발. 책: 추세 반전을 시작하는 결정적 봉. " +
      "이 봉의 4등분선이 향후 매매 결정 기준.",
  },

  // ─────────── 4등분선 zones ───────────
  quarter_safe75: {
    title: "4등분선 75% 안전지대",
    body:
      "직전 장대양봉 catalyst의 몸통(시가→종가)을 4등분했을 때, " +
      "현재 가격이 75% 이상 자리. 책: 매집 살아있음 = 추가 매수 OK. " +
      "다음 봉 상승 확률 75%.",
  },
  quarter_warn50: {
    title: "4등분선 50~75% 관찰",
    body:
      "안전지대(75%) 살짝 이탈. 조정 진행 중이지만 catalyst 살아있음. 보유 OK, " +
      "추가 매수 신중.",
  },
  quarter_danger25: {
    title: "4등분선 25~50% 매입원가 영역",
    body:
      "catalyst의 매입원가 (50%) 근처. 책 표현 \"적신호\". 청산 시점 임박. " +
      "다음 봉 하락 시 25% 절대자리 이탈 위험.",
  },
  quarter_broken: {
    title: "4등분선 25% 절대자리 깨짐",
    body:
      "catalyst의 25% 절대자리 아래. 책: catalyst가 부정됨 = 매도 자리. " +
      "추세 사망.",
  },

  // ─────────── Analyzer-stamped reasons ───────────
  stretch_reason: {
    title: "추세 유효 · 자리 지남",
    body:
      "추세는 살아있지만 신규 매수 자리는 한참 지남. 세 가지 게이트 중 하나 이상 fire:\n" +
      "  ① 8주 트레일링 +50% (책 +50% 룰 위반)\n" +
      "  ② 240MA 대비 +100% 위 (cycle MA 한참 위)\n" +
      "  ③ 52주 위치 ≥ 85% + 8주 +30%\n" +
      "  ④ 손절 폭 > 15% (책 -10% 룰 초과)\n" +
      "보유는 OK, 신규 매수는 X.",
  },
  pattern_invalidation: {
    title: "패턴 무효화 (Invalidation)",
    body:
      "쌍바닥/삼중바닥 등 완성된 패턴이라도 가격이 책의 무효 기준 (전저점, " +
      "네크라인, 4등분선 25%)을 깨면 자동 무효 처리.\n" +
      "무효화된 패턴은 매수 신호로 사용 X. 책 p254 — \"쌍바닥은 쉽게 배신하는 패턴, " +
      "전저점 깨지면 첫 매수세 + 실망 매물로 패턴 자체가 사라짐\".",
  },

  // ─────────── 책 안전 게이트 ───────────
  rally_8w: {
    title: "8주 트레일링 수익률",
    body:
      "최근 8주봉 동안의 수익률. 책 +50% 룰: 추세 시작부 +50% 안에서만 신규 매수. " +
      "+50% 초과면 \"자리 한참 지남\" — 보유 평가용.",
  },
  pos_52w: {
    title: "52주 위치 (range)",
    body:
      "52주 고점-저점 사이에서 현재가의 상대 위치. 0% = 52주 저점, " +
      "100% = 52주 고점.\n" +
      "≥ 85% = 추세 후반부, 신규 매수 신중. ≤ 30% = 바닥권, " +
      "반전 신호와 함께 매수 후보.",
  },
  ma_240_distance: {
    title: "240MA 대비 거리",
    body:
      "현재가가 240주 이평선 대비 몇 % 위/아래인가. 책의 cycle MA 거리.\n" +
      "+100% 위 = 추세 한참 진행 → 책 정신상 신규 매수 자리에서 벗어남.\n" +
      "-10% 이내 = 240MA 부근 안전지대.",
  },

  // ─────────── 절세·연금 (한국 2026 세법) ───────────
  tax_pension_30: {
    title: "퇴직소득세 30% 감면",
    body:
      "퇴직금을 일시금으로 받으면 퇴직소득세 100% 부과. 55세 이상 + 5년 이상 가입 + " +
      "연금 형태로 분할 수령 시 퇴직소득세의 70%만 부과 (30% 감면).\n" +
      "퇴직금은 IRP 계좌로 받아 그대로 운용 가능.",
  },
  tax_credit_pension: {
    title: "연금 세액공제 (연금저축 + IRP)",
    body:
      "연금저축 연 600만원 + IRP 추가 300만원 = 합산 연 900만원까지 세액공제.\n" +
      "총급여 5,500만원 이하: 16.5% (지방세 포함) → 900만원 풀 납입 시 148.5만원 환급.\n" +
      "총급여 5,500만원 초과: 13.2% → 118.8만원 환급.\n" +
      "55세 이전 중도 해지 시 16.5% 기타소득세 + 세공 반환.",
  },
  isa_tax: {
    title: "ISA 비과세 + 분리과세",
    body:
      "ISA 안에서 발생한 이익(매매차익 + 배당 + 이자) 200만원까지 비과세.\n" +
      "서민형/농어민형은 400만원까지 비과세.\n" +
      "초과분은 9.9% 분리과세 (일반계좌 15.4%보다 5.5%p 절감).\n" +
      "3년 의무 가입, 연 2,000만원 / 총 1억원 한도.",
  },
  tax_isa_to_pension: {
    title: "ISA → 연금저축 이전 보너스",
    body:
      "ISA 만기 후 연금저축으로 이전 시 추가 300만원 세액공제 (1회성, 약 40만원 환급).\n" +
      "꿀팁: 3년 풍차돌리기로 매 3년마다 만기 ISA를 연금이전 → 누적 절세.",
  },
  reverse_accumulation: {
    title: "역매집 (Reverse Accumulation)",
    body:
      "장중 저점을 반복적으로 지지받으며 거래량은 늘어나는데 가격은 크게 빠지지 않는 모습.\n" +
      "큰손이 조용히 물량을 쓸어 담는다고 추정되는 구간이라 바닥 시그널로 본다.",
  },

  // ─────────── Macro dial axes ───────────
  macro_liquidity: {
    title: "통화·유동성",
    body:
      "시중에 풀린 돈의 양과 흐름. 통화량(M2), 본원통화, 신용 증가율 등으로 측정. " +
      "유동성이 풍부하면 위험자산(주식)으로 자금이 더 잘 흘러들어와 강세장이 형성되기 쉽다.",
    link: { href: "https://ko.wikipedia.org/wiki/통화량", label: "위키 통화량 →" },
  },
  macro_rate: {
    title: "금리",
    body:
      "기준금리·국채금리 수준. 금리가 낮을수록 자금 조달 비용이 싸지고 주식의 상대적 매력이 올라간다.\n" +
      "다만 금리 하락이 급격하면 경기 둔화 신호일 수 있어 단순히 낮다고 좋은 것은 아니다.",
    link: { href: "https://ko.wikipedia.org/wiki/기준금리", label: "위키 기준금리 →" },
  },
  macro_cycle: {
    title: "경기",
    body:
      "실물 경제 사이클. ISM 제조업/서비스 PMI, 산업생산, 소매판매, 고용 등으로 측정.\n" +
      "확장 국면일수록 기업 이익이 늘어 주가에 긍정적.",
    link: { href: "https://ko.wikipedia.org/wiki/경기변동", label: "위키 경기변동 →" },
  },
  macro_price: {
    title: "물가",
    body:
      "인플레이션(CPI, PPI, 기대 인플레) 수준. " +
      "완만한 인플레는 자산 가격에 우호적이지만, 너무 높으면 금리 인상을 유발해 주식에 부정적.",
    link: { href: "https://ko.wikipedia.org/wiki/인플레이션", label: "위키 인플레이션 →" },
  },
  macro_fear: {
    title: "시장 심리",
    body:
      "공포·탐욕 지수, 변동성지수(VIX), 풋콜비율 등으로 측정한 투자자 심리.\n" +
      "극단적 공포 구간은 역설적으로 매수 기회가 되는 경우가 많다(역발상 지표).",
    link: { href: "https://ko.wikipedia.org/wiki/VIX", label: "위키 VIX →" },
  },

  // ─────────── Regime ───────────
  regime_hope: {
    title: "HOPE — 본격 상승",
    body:
      "경기 회복 + 유동성 풍부 + 심리 우호. 다수 종목이 동반 상승하는 강세장 국면. " +
      "추세 추종 매수에 가장 우호적인 환경.",
  },
  regime_fear: {
    title: "FEAR — 공포 (위기=기회)",
    body:
      "지표는 약하지만 극단적 매도세로 가격이 과도하게 빠진 구간. " +
      "장기적으로는 매수 기회가 되는 경우가 많아 분할매수 시점으로 본다.",
  },
  regime_despair: {
    title: "DESPAIR — 침체",
    body: "경기 + 유동성 + 심리 모두 약세. 현금 비중 늘리고 보수적으로 운용.",
  },

  // ─────────── Macro indicators ───────────
  mv_pq: {
    title: "MV=PQ 시그널",
    body:
      "화폐수량설(MV=PQ)에 기반한 자산가격 환경 평가.\n" +
      "M(통화량) × V(유통속도) = P(물가) × Q(실질생산)\n" +
      "M, V 가 늘어나면 자산 가격(P) 으로 압력이 가해진다는 단순 모델. " +
      "유동성/물가 흐름이 자산시장에 우호적인지를 한눈에 평가하는 데 쓴다.",
    link: { href: "https://ko.wikipedia.org/wiki/화폐수량설", label: "위키 화폐수량설 →" },
  },
  tips_spread: {
    title: "TIPS spread (기대 인플레이션)",
    body:
      "일반 국채 수익률 - 물가연동국채(TIPS) 수익률.\n" +
      "시장이 향후 10년 평균 인플레이션을 얼마로 보는지를 가격에 반영한 지표. " +
      "2~3% 안팎이 정상, 4% 이상이면 인플레이션 우려.",
    link: { href: "https://en.wikipedia.org/wiki/Treasury_inflation-protected_security", label: "Wikipedia TIPS →" },
  },
  ppi_yoy: {
    title: "PPI YoY (생산자물가 전년대비)",
    body:
      "기업이 출하하는 도매단계 물가의 전년 동월 대비 변화율. " +
      "원자재·중간재 가격을 빨리 반영해 CPI(소비자물가) 보다 1~3개월 선행하는 경우가 많다.",
    link: { href: "https://ko.wikipedia.org/wiki/생산자물가지수", label: "위키 PPI →" },
  },
  cpi_yoy: {
    title: "CPI YoY (소비자물가 전년대비)",
    body:
      "소비자가 실제 구매하는 상품·서비스 가격의 전년 동월 대비 변화율. " +
      "중앙은행 통화정책 결정의 핵심 지표. 미국 기준 2% 부근을 목표로 한다.",
    link: { href: "https://ko.wikipedia.org/wiki/소비자물가지수", label: "위키 CPI →" },
  },
  vix_state: {
    title: "VIX 상태",
    body:
      "S&P 500 옵션의 30일 내재변동성. '공포 지수'로 불린다.\n" +
      "20 미만 = 평온, 20~30 = 경계, 30 이상 = 패닉. " +
      "급등 후 빠르게 안정되면 바닥 시그널로 본다.",
    link: { href: "https://ko.wikipedia.org/wiki/VIX", label: "위키 VIX →" },
  },
  yield_curve: {
    title: "수익률곡선 (Yield Curve)",
    body:
      "단기 국채 vs 장기 국채 금리의 차이. " +
      "정상: 장기 > 단기. 역전: 장기 < 단기 → 경기 침체를 12~18개월 선행한 사례가 많아 주요 경계 시그널.",
    link: { href: "https://en.wikipedia.org/wiki/Yield_curve", label: "Wikipedia (영문) →" },
  },

  // ─────────── Actions ───────────
  action_strong_buy: {
    title: "STRONG BUY",
    body:
      "여러 시간프레임(일/주/월봉)에서 상승 정배열 + 책 17종 매수 패턴 중 다수가 동시에 발현된 최강 매수 시그널.\n" +
      "엔트리/스탑/타겟이 함께 산정된다.",
  },
  action_buy: {
    title: "BUY",
    body:
      "추세와 패턴이 모두 매수 우호로 정렬되었지만 STRONG BUY 만큼의 다중 확인은 부족한 상태.\n" +
      "기본적인 진입 자리로 본다.",
  },
  action_avoid: {
    title: "AVOID",
    body:
      "추세 약화 + 거래량 패턴(예: 상투권 분산) + 단기 매도 캔들 등 부정적 시그널이 우세한 종목.\n" +
      "보유는 가능해도 신규 매수는 권장하지 않는다.",
  },
  action_sell: {
    title: "SELL",
    body:
      "매도 우위 시그널. 손절 라인 이탈, 추세 종료, 약세 패턴 완성 등이 겹친 상태.",
  },
  action_hold: {
    title: "HOLD",
    body: "특별한 매수/매도 우위 시그널이 없는 중립 상태.",
  },

  // ─────────── 펀더멘털 단일 지표 ───────────
  per: {
    title: "PER (주가수익비율)",
    body:
      "Price / Earnings Ratio. 주가 ÷ 주당순이익(EPS).\n" +
      "'1년치 이익을 몇 년 모아야 시가총액이 되는가' 라는 개념. 낮을수록 싸다고 본다.\n" +
      "한국 KOSPI 평균 PER 은 보통 10~15 사이. 성장주는 30+, 가치주는 5~10.",
    link: {
      href: "https://ko.wikipedia.org/wiki/주가수익비율",
      label: "위키 PER →",
    },
  },
  pbr: {
    title: "PBR (주가순자산비율)",
    body:
      "Price / Book Ratio. 주가 ÷ 주당순자산(BPS).\n" +
      "'회사의 청산가치 대비 주가가 몇 배인가'. 1 미만이면 청산가치보다 싸게 거래되는 것.\n" +
      "금융주/철강주는 보통 1 미만, 성장주/IT 는 5+ 흔함. PBR 하나로 비싸다/싸다 단정 X.",
    link: {
      href: "https://ko.wikipedia.org/wiki/주가순자산비율",
      label: "위키 PBR →",
    },
  },
  roe: {
    title: "ROE (자기자본이익률)",
    body:
      "Return on Equity. 당기순이익 ÷ 자기자본.\n" +
      "'주주가 맡긴 돈으로 1년에 몇 % 벌었는가' 라는 수익성 지표. 높을수록 자본을 잘 굴리는 기업.\n" +
      "한국 평균 ROE 는 8~10% 정도. 워런 버핏은 15% 이상 꾸준한 기업을 선호.",
    link: {
      href: "https://ko.wikipedia.org/wiki/자기자본이익률",
      label: "위키 ROE →",
    },
  },

  // ─────────── Factor gates (학계/유명 전략) ───────────
  gate_kang_value: {
    title: "강환국 가치 (PBR<1.5 & ROE>10%)",
    body:
      "한국의 가치투자 저자 강환국이 백테스트로 검증한 단순 가치 스크리닝.\n" +
      "PBR(주가순자산비율)이 1.5 미만(저평가) + ROE(자기자본이익률)가 10% 초과(수익성 양호)인 종목을 사면 " +
      "장기적으로 시장을 이긴다는 룰.",
  },
  gate_graham: {
    title: "그레이엄 (PER<15 & 부채비율<50%)",
    body:
      "현대 가치투자의 아버지 벤저민 그레이엄이 제시한 안전마진 스크리닝의 단순화 버전.\n" +
      "PER(주가수익비율) 15 미만(저평가) + 부채비율 50% 미만(재무 건전성) 종목을 사 모으는 전략.",
    link: { href: "https://ko.wikipedia.org/wiki/벤저민_그레이엄", label: "위키 그레이엄 →" },
  },
  gate_magic_formula: {
    title: "마법공식 (PER<12 & 영업이익률>10%)",
    body:
      "조엘 그린블라트의 '주식 시장을 이기는 작은 책' 에 나온 마법공식의 단순화 버전.\n" +
      "원래 공식: 자본이익률(ROC) + 이익수익률(EBIT/EV) 상위 종목. 여기서는 비슷한 의미의 " +
      "PER 12 미만(싸고) + 영업이익률 10% 초과(잘 버는) 으로 근사.",
    link: { href: "https://en.wikipedia.org/wiki/Magic_formula_investing", label: "Wikipedia →" },
  },
  gate_buffett: {
    title: "버핏형 (ROE>15% & 부채비율<50%)",
    body:
      "워런 버핏이 강조한 '꾸준히 높은 자본수익률 + 보수적 재무구조' 기준의 근사.\n" +
      "ROE 15% 이상(자본을 잘 굴리는 기업) + 부채비율 50% 미만(재무 건전) 으로 필터.",
    link: { href: "https://ko.wikipedia.org/wiki/워런_버핏", label: "위키 버핏 →" },
  },

  // ─────────── Factor axes ───────────
  axis_value: {
    title: "가치 (Value)",
    body: "PER, PBR 등 '얼마나 싼가' 지표 종합 점수 (10점 만점). 낮은 PER/PBR 일수록 점수 높음.",
  },
  axis_growth: {
    title: "성장 (Growth)",
    body: "매출 성장률, 이익 성장률 등 '얼마나 빠르게 크고 있나' 종합 점수 (10점 만점).",
  },
  axis_safety: {
    title: "안전 (Safety)",
    body: "부채비율, 유동비율 등 '재무가 얼마나 튼튼한가' 종합 점수 (10점 만점). 부채 낮을수록 높음.",
  },
  axis_quality: {
    title: "수익 (Quality)",
    body: "ROE, ROA, 영업이익률 등 '자본을 얼마나 잘 굴리는가' 종합 점수 (10점 만점).",
  },
};

export function getGlossary(term: string): GlossaryEntry | null {
  return GLOSSARY[term] ?? null;
}
