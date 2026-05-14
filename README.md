# Thesauros

> 마태복음 6:20 — "보물을 하늘에 쌓아 두라(θησαυρός)."

저자 『추세추종 매매 룰』(출판사, 2026)의 모든 룰을
자동화하고, **PIT 데이터 기반 LightGBM 랭킹**과 융합한 개인용 quant 시스템.

```
거시(FRED + yfinance) ──┐
                        │
SEC EDGAR 펀더멘털 ─────┼──► DuckDB (PIT) ──┬──► LightGBM 랭킹 ──┐
                        │                  │                    │
yfinance / pykrx 가격 ──┘                  └──► 책 룰 엔진 ──────┴──► FastAPI ──► Next.js Web
                                                  (추세/패턴/거래량)              + Google Auth
                                                                                  + 다크/라이트
```

| 컴포넌트 | 위치 |
|---|---|
| Python 백엔드 | `app/` (FastAPI + 책 룰 + LightGBM + 거시) |
| Next.js 프론트 | `web-next/` (App Router + Auth.js v5 + Tailwind v4) |
| 책 본문 / 차트 | `book_images/` (1부 + 2부 transcript + SUMMARY) |
| E2E 테스트 | `web-next/e2e/` (Playwright) |
| 학습 결과물 | `models_store/` |

> ⚠️ **면책**: 학습/연구 도구입니다. 실거래 결과를 보장하지 않습니다.
> 모든 매매 판단과 손익은 본인 책임입니다. 자동매매는 의도적으로 미구현 — 분석 신뢰가 충분히 쌓인 뒤에 활성화 예정.

---

## 빠른 시작

### 1) 의존성 + 데이터

```powershell
.\install.bat                                    # venv + Python 패키지
copy .env.example .env                           # 키 채우기 (FRED, SEC, KIS, …)
.\.venv\Scripts\python.exe -m app.cli ingest-us  # S&P 500 가격 (~10분)
.\.venv\Scripts\python.exe -m app.cli ingest-macro
.\.venv\Scripts\python.exe -m app.cli ingest-krx --years 5     # (선택, 한국 종목)
cd web-next && npm install && cd ..
```

### 2) 개발 서버 (백엔드 + 프론트 동시)

```powershell
.\run-web.bat
```

브라우저 자동 오픈 → http://localhost:3000

종료: 런처 창에서 아무 키.

### 3) 종목/거시 단발 조회 (CLI)

```powershell
.\.venv\Scripts\python.exe -m app.cli macro                          # 거시 스냅샷
.\.venv\Scripts\python.exe -m app.cli analyze AAPL                   # 책 룰 전체 분석
.\.venv\Scripts\python.exe -m app.cli analyze 005930.KS              # 한국 종목
.\.venv\Scripts\python.exe -m app.cli backtest AAPL                  # 18년 백테스트
.\.venv\Scripts\python.exe -m app.cli book-cases                     # 책 사례 자동 검증
.\.venv\Scripts\python.exe -m app.cli screen --market us             # 책 점수 상위 후보
.\.venv\Scripts\python.exe -m app.cli screen-and-backtest --market us --top 30
```

---

## 1. 책 룰 엔진 (`app/book/`)

저자 책의 **2부 (캔들/패턴/추세/이평선/거래량)**를 코드로 옮긴 결정론적 룰 엔진.
ML 모델과는 독립적이며, ML 출력의 해석 narrative 와 진입/청산 가드레일을
제공한다.

### 추세 (`trend.py`)

책의 핵심 결론은 **월봉/주봉 10MA가 "진정한 추세선"**이라는 것. 이 룰을 그대로 구현:

- 일/주/월봉 각각에 대해 10/20/60/120/240 MA 산출
- `TrendState`: `above_ma_10`, `above_ma_240`, `ma_10_slope_up`, `alignment_score [-1, +1]`,
  `overall_score [-1, +1]`, `label ∈ {강세, 약세, 혼조, 데드}`
- `MultiTrend`: 세 timeframe 종합 + 책 시그널 (`BUY` / `HOLD` / `SELL` / `AVOID`)
- 책 절대 규칙: **월봉 240MA 아래 = AVOID** (죽은 차트, 매수 금지) /
  **월봉 10MA 하향 이탈 = SELL** (저승사자 캔들, 무조건 청산)

### 캔들 (`candles.py`)

- 5대 분석기 (시가/종가, 몸통, 꼬리, 거래량, 위치)
- **4등분선 75% 안전지대** (책 시그니처) — 양봉 종가가 `low + 0.75·(high-low)` 이상이면
  다음 봉 상승 확률 책 주장 ~75%
- 자동 분류 tag: 장대양/음봉, 망치/역망치/교수형/유성형, 도지/드래곤플라이/그레이브스톤,
  눈썹 캔들, 구라캔들 의심, 대거래

### 패턴 (`patterns.py`) — 10가지 자동 감지

`scipy.signal.argrelextrema` 로 swing high/low 추출 후, 책 규칙에 맞춰 패턴 검증:

| 종류 | 책 페이지 | 감지 조건 요약 |
|---|---|---|
| 쌍바닥 (W) | p254-259 | 두 저점 ±5%, 전저점 보존, 10MA 후킹 시 완성 |
| 쌍봉 (M) | p260-267 | 두 고점 ±5%, 둘째 거래량 ↓, 10MA 하향 시 완성 |
| H&S | p266-269 | 머리>어깨, 거래량 A>C>E, 네크라인 하향 돌파 |
| 역H&S | p269-271 | H&S 거꾸로, 저점 거래량 점증, 신뢰도 +α |
| 삼중바닥 | p276-279 | 세 저점, 거래량 우상향이면 가점 (SAMG +450% 사례) |
| 삼고점 | p273-275 | 세 고점, 거래량 감소 시 가점 |
| Cup w/ Handle | p280-281 | U자 (60-260봉) + 작은 V 핸들, 240MA 동시 돌파 시 가점 |
| 240MA 돌파 | p350-353 | 240MA 밑 따개비 + 거래량 적은 양봉 돌파 (책의 옥석) |
| 돌반지 | p344-345 | 돌파-지지-반등 시퀀스 (10MA / 240MA) |
| 포킹 | p336-339 | 이평선 수렴 + 장대양봉 돌파 |

각 패턴은 `Pattern` 객체로 반환: `kind`, `direction`, `confidence`,
`completed`, `entry/stop/target`, `reason` (한국어 설명) + 일/주/월봉 timeframe 정보.

### 되돌림 (`reversals.py`) — 4가지

책 p292-301 "사부의 비기" — 패턴이 패턴을 상쇄해 더 강한 시그널을 만드는 패턴:

1. **동종**: 쌍봉↔쌍바닥 / H&S↔역H&S
2. **이종**: 쌍봉 → 역H&S (책: "반드시 진입")
3. **캔들 1개 반전**: 큰 패턴을 장대양봉 1개로 상쇄 (2023-01 NASDAQ 사례)
4. (4번은 쐐기 수렴 — `patterns.detect_forking()` 이 담당)

### 거래량 (`volume.py`)

책 p364 의 **11가지 가격대별 거래량 케이스 분류표**를 그대로 구현:

| Case | 상황 | 책 의미 |
|---|---|---|
| 3 | 바닥권 + 거래량 3배+ | **추세 반전 매수** ⭐ |
| 7 | 급등 중 거래량 감소 | 세력 매집 완료 |
| 9 | 상투권 거래량 증가 | 세력 털기 위험 |
| 11 | 상투 후 급락 거래량 감소 | 죽은 차트 |
| … | (8가지 추가) | |

추가로 **역매집 캔들** (긴 위꼬리 역망치 반복) — 책 p368-369 "심봤다" 신호.

### Orchestrator (`analyzer.py`)

위 모듈을 합쳐 단일 함수로:

```python
from app.book.analyzer import analyze_ticker, load_ticker_data
df = load_ticker_data("AAPL")
result = analyze_ticker("AAPL", df)
# → action, book_score, trend (일/주/월), patterns (timeframe별 정렬),
#   reversals, volume_case, reverse_accumulation, entry_plan
```

책의 우선순위 그대로:
1. **거시 → 추세 → 패턴 → 진입자리** (탑다운)
2. 월봉 10MA 깨짐은 다른 어떤 패턴 시그널보다 우선 (AVOID/SELL override)
3. completed bullish 패턴 + 강세 추세 → `STRONG_BUY`
4. 진입 플랜 자동 계산 (top completed pattern 의 entry/stop/target,
   또는 10MA fallback stop)

### 백테스트 엔진 (`backtest.py`)

월봉/주봉 10MA crossover 전략을 과거 데이터에 적용해 책 주장을 데이터로 검증.

```python
from app.book.backtest import backtest_ticker
report = backtest_ticker("AAPL", df, strategy="monthly_10ma")
# → win_rate, total_return_pct, buy_and_hold_return_pct, max_drawdown,
#   trades: List[Trade] (entry/exit date+price, return, reason)
```

**책 사례 자동 검증** (`BOOK_CASES`): AAPL, MSFT, 삼성전자, 카카오, 피에스케이홀딩스,
SAMG엔터 — 책의 헤드라인 수익률 주장을 시스템 룰로 재현.

### 일괄 스크리닝 리포트 (`screen-and-backtest`)

전체 유니버스를 스캔 → 책 점수 상위 N개 → 각 후보 18년 백테스트 →
`.md` / `.json` / `.csv` 단일 리포트 자동 생성:

```
models_store/screen_backtest_us_20260515_0101.md
```

US 30개 종목 첫 실행 결과:
- 평균 총 수익률 **+2223%** (vs B&H 평균 +3713%)
- 평균 최악 단일 거래 **-15%**
- NVDA +40705%, AMD +9200%, AAPL +4842%, EME +926% …

책의 정확한 주장 — **"수익은 크게, 손실은 작게"** — 가 데이터로 검증됨
(룰이 B&H 누적 수익률을 압도하진 않지만 위험 통제는 우월).

---

## 2. LightGBM ML 스택 (`app/model/`, `app/features/`)

### 데이터 (`app/data/`)

| 모듈 | 역할 |
|---|---|
| `pit_db.py` | DuckDB 스키마: `universe`, `prices`, `fundamentals`, `macro`, `insider_transactions`, `paper_trades`, `meta` |
| `universe.py` | S&P 500 동적 (Wikipedia + SEC ticker→CIK 매핑) |
| `ingest_sec.py` | SEC EDGAR Company Facts (분기/연간 + `filed_date` 보존) |
| `ingest_insiders.py` | SEC Form 4 인사이더 거래 XML 파싱 (P3) |
| `ingest_prices.py` | yfinance 일별 OHLCV bulk |
| `ingest_krx.py` | **FinanceDataReader + pykrx fallback** (KOSPI 923 + KOSDAQ 1778) |
| `ingest_dart.py` | DART OpenAPI — 한국 펀더멘탈 (corpCode + fnlttSinglAcnt) |
| `kis.py` | KIS OpenAPI 클라이언트 (실시간 시세, 잔고; 자동매매는 미구현) |

**PIT (Point-in-Time)** — SEC 데이터는 `filed_date` 그대로 저장. "as-of t" 쿼리는
모두 `filed_date <= t` 로 필터링 → 룩어헤드 차단.

### 피처 파이프라인 v3 (`features/pipeline_v3.py`)

50+ 피처. 모든 피처는 **섹터 중립 z-score** (`*_sn`, 클립 ±3) +
**횡단면 랭크 퍼센타일** (`*_rk`) 두 가지 형태로 함께 제공.

**펀더멘털 (PIT, TTM 기반):**
- 수익성: ROA, ROE, gross/operating/net margin
- 레버리지: debt/equity, liabilities/assets, current/cash ratio, leverage
- 효율: asset turnover, sales/assets
- 성장: revenue YoY, earnings YoY
- 가치: P/E, P/B, P/S, EV/Revenue, FCF yield, earnings yield
- 캐시 흐름: FCF/assets, OCF/assets
- 사이즈/구조: log market cap, tangibility, R&D proxy

**팩터 동물원** (`features/factor_zoo.py`):
- **Piotroski F-score** (9 컴포넌트, YoY 사용) — 회계 품질
- **Mohanram G-score** (8 컴포넌트) — 성장주 품질
- **Beneish M-score** 프록시 — 회계 조작 위험
- **Asness Quality** — Profitability + Growth + Safety + Payout
- **Value composite** — P/E, P/B, P/S, EV/EBITDA, FCF yield 통합

**거시 피처 (P1, `features/macro_features.py`)** — 레짐 조건부 학습용:
- `macro_vix`, `macro_yield_curve`, `macro_real_rate`, `macro_credit_spread`,
  `macro_fed_funds`, `macro_dxy_yoy`, `macro_copper_yoy`, `macro_m2_yoy`
- 같은 날짜면 모든 종목에 동일 값 (sector neutralization 안 함)
- LightGBM 이 "VIX 30+ 환경에서는 가치주, VIX 15 환경에서는 모멘텀" 같은
  레짐 조건부 패턴을 자동 학습

**인사이더 피처 (P3, `features/insider_features.py`)** — Form 4 기반:
- `insider_buy_value_90d`, `insider_sell_value_90d`, `insider_net_buy_90d`,
  `insider_n_buyers_90d`, `insider_ceo_buy_30d`, `insider_cluster`
- 학계 근거: Cohen-Malloy-Pomorski (2012) cluster buy → +6%/yr alpha

**기술적 (가격 기반):**
- 모멘텀: 1M, 3M, 6M, **12-1M** (모멘텀 reversal 제외), 12M, **Chande(14)**
- 변동성: 20D, 60D, drawdown 252
- 추세: P/SMA50, P/SMA200, SMA50/SMA200
- 오실레이터: RSI(14), MACD histogram, 5D reversal
- **12개월 consistency** (월간 양수 비율 — Asness 후속 연구)

### 학습 (`model/lgbm.py`)

**타깃**:
- `y_fwd` — 21일 (~1개월) 후 raw forward return
- `y_rank` — date 내 cross-sectional percentile rank (decile target) ⭐ v3 default

**알고리즘**: LightGBM regressor
```python
params = {
    "objective": "regression", "metric": "rmse",
    "learning_rate": 0.05, "num_leaves": 63,
    "min_data_in_leaf": 100, "feature_fraction": 0.8,
    "bagging_fraction": 0.8, "bagging_freq": 5,
    "lambda_l2": 1.0, "verbose": -1,
}
```

**검증** — `model/purged_cv.py` (López de Prado AFML §7):

```
PurgedKFold(5) + 21-day embargo
─────────────────────────────────
fold k:
  test  = sorted_dates[ k * n / 5 : (k+1) * n / 5 ]
  guard = [test_start - 21d, test_end + 21d + 21d]    # embargo + label horizon
  train = ¬test, drop samples whose [d, d+21d] overlaps guard
```

**메트릭**: fold 별 **Spearman cross-sectional IC** + 평균/표준편차 + OOF IC by date.
일반 회귀 RMSE 도 보고하지만 결정은 IC 기준.

### 백테스트 (`backtest/walkforward_v3.py`)

워크포워드 재학습 — 매 rebalance 시점에 panel을 재학습하고 top-K 종목 선정.

핵심 옵션 (v3 default):
- `rebalance_n = 21` (월 1회 rebalance)
- `top_k = 20`
- `sector_cap = 0.30` — 한 섹터에 전체 자본의 30% 한도 (Communist hyperparameter sweep 결과)
- `drawdown_brake = -0.10` — 누적 MDD -10% 도달 시 노출 50% 축소 (트리거 보수적)
- `cost_bps = 10`, `slippage_bps = 5` — 회당 양면 15bp 비용
- `boost_rounds = 300`, `feature_suffix = "_sn"` (섹터 중립 피처 사용)

**포트폴리오 구성** — `_sector_cap_weights()`:
- 스코어 내림차순으로 top-K 채우되, 섹터 weight 합이 cap 초과시 skip & 다음 후보
- **3가지 가중 방식 지원** (P2):
  - `equal` — 1/N (baseline)
  - **`inverse_vol`** — weight ∝ 1/σ_60d (책 권장, 변동성 큰 종목 비중 ↓)
  - `risk_parity` — equal risk contribution (현재 inverse_vol 과 동일 근사)

**Drawdown brake**:
- equity curve 의 현재 drawdown 계산
- `dd < drawdown_brake` 면 다음 rebalance 부터 노출을 0.5x
- 회복 시 자동 정상화

**레짐 cash trigger (P1)**:
- `regime_cash_trigger=True` 시 macro_regime() == "FEAR" 이면 100% 현금
- 단순하지만 위기 자동 회피 (2008, 2020 같은 시나리오)

**현실적 세금 시뮬레이션 (P7)**:
- `tax_short_term_pct` / `tax_long_term_pct`
- 매도 시점에 entry_log 의 보유 일수 산출 → 단기/장기 세율 적용
- 한국 거주자 미국 주식 케이스: `tax_short_term=tax_long_term=0.22`
- 결과: `tax_paid_total_pct` + `tax_events` 리스트

### Hyperparameter sweep (`sweep_v3.py`)

7가지 (drawdown_brake × sector_cap) 조합을 walk-forward 백테스트하고 결과 비교
(`models_store/hyperparam_sweep.json`):

```
baseline   (no brake, no cap)   alpha +4.83%   Sharpe 0.44   MDD -23.0%
v3 default (-15%, 0.25)         alpha +0.29%   Sharpe 0.36   MDD -20.2%
tighter    (-10%, 0.30)         ← 현재 채택 (Sharpe 최고 + 보수적 MDD)
…
```

### Multi-horizon 앙상블 (P5, `backtest/multi_horizon.py`)

단일 21d 호라이즌 대신 **5d/21d/63d 세 호라이즌**을 동시에 학습 + 가중평균:

```python
from app.backtest.multi_horizon import train_ensemble, predict_ensemble
bundle = train_ensemble(panel, feature_cols)
scores = predict_ensemble(test_panel, bundle)
# horizon_weights default = {5: 0.20, 21: 0.55, 63: 0.25}
```

각 모델 예측을 cross-sectional percentile rank 로 정규화 후 가중평균 →
단일 호라이즌 IS 변동성에 덜 휘둘리는 안정된 시그널.

### Paper-trading 모드 (P4, `app/paper/trader.py`)

**가장 정직한 OOS 검증** — 실거래 X, 추천만 매일 기록.

```python
from app.paper.trader import record_snapshot, evaluate_open_trades, paper_metrics
record_snapshot(items, source="book_rules")   # 매일 장 마감 후
evaluate_open_trades()                          # 매일 STOP/TARGET/TIMEOUT 체크
paper_metrics()                                  # 누적 통계
```

테이블 스키마 (`paper_trades`):
- snapshot_date / ticker / source (복합 PK — 같은 종목 다른 시그널 소스 가능)
- action, book_score, entry_price, stop_price, target_price, based_on
- closed (Boolean), close_date, close_price, close_reason, realized_pct

CLI: `paper-snapshot`, `paper-evaluate`, `paper-stats`.

### 학습된 모델 출력

`models_store/` 에 저장:
- `lgbm_v3.pkl` — 학습된 LightGBM bundle (model + feature_cols + oof_ic_mean)
- `feature_panel_v3.parquet` — 학습용 패널 (~600MB)
- `feature_importance_v3.csv` — gain/split 기준 상위 피처
- `oof_ic_v3.csv` — OOF IC by date (모델 성능 시계열)
- `comparison_v2_vs_v3.json` — v2 vs v3 alpha/Sharpe 비교

상위 피처 (gain 기준, v3 sector-neutral):
```
log_market_cap_sn  48.3   (size factor)
asset_turnover_sn  41.0
mom_1m_sn          32.4
vol_60_sn          29.7
consistency_12m_sn 28.7
dd_252_sn          26.7
mom_3m_sn          26.3
rev_5d_sn          25.6   (5-day reversal)
liab_to_assets_sn  24.8
mohanram_g_sn      19.8   (factor zoo 진입 확인)
pe_sn              18.1
```

---

## 3. 거시 레이어 (`app/macro/`)

책 1부 거시 지표 25개를 FRED + yfinance 에서 수집하고 자동 상태 분류:

| 카테고리 | 지표 |
|---|---|
| **정책** | Fed Funds Rate, 10년 실질금리, TIPS 기대인플레, 수익률곡선 10Y-2Y, 10Y-3M |
| **유동성** | M2 통화공급량, Fed 대차대조표 |
| **물가** | CPI, Core PCE, PPI |
| **경기/고용** | 실업률, 산업생산, 제조업 신규 수주 |
| **심리** | VIX, IG 회사채 스프레드, HY 정크 스프레드 |
| **환율** | DXY, USD/JPY |
| **원자재** | 금, 구리(Dr. Copper), WTI 원유 |
| **지수** | S&P500, NASDAQ, KOSPI, KOSDAQ |

각 지표마다 `state ∈ {BULL, NEUTRAL, CAUTION, BEAR}` + 한국어 verdict
("YoY +4.6% — 우호적 흐름", "역전됨 → 18~24개월 내 침체 가능" 등) 자동 생성.

**시장 레짐**: 책의 4단계 심리 사이클(공포 / 기대반의심반 / 희망 / 확신)을
지표들의 종합 점수로 추정.

```python
from app.macro.state import market_regime, categorized
print(market_regime())   # {"regime": "HOPE", "score": 0.52, "note": "본격 상승 단계"}
```

`fredapi` 와 `yfinance` 사용, `FRED_API_KEY` 환경변수 필요
(https://fred.stlouisfed.org/ 무료 등록).

---

## 4. FastAPI 백엔드 (`app/api/`)

| 엔드포인트 | 메서드 | 용도 |
|---|---|---|
| `/api/health` | GET | 헬스체크 |
| `/api/data/stats` | GET | DB 통계 |
| `/api/universe` | GET | S&P 500 + 섹터 |
| `/api/recommend?top_k=20` | GET | LightGBM 예측 상위 K |
| `/api/analyze?ticker=AAPL` | GET | ML 분석 (펀더 + 기술 + 매매플랜) |
| `/api/prices?ticker=&start=` | GET | 일별 OHLCV |
| `/api/backtest_v3` | POST | v3 walk-forward 백테스트 |
| `/api/train` | POST | LightGBM 재학습 (백그라운드) |
| `/api/model/info` | GET | 피처 중요도, OOF IC |
| **`/api/book/analyze?ticker=…`** | GET | **책 룰 전체 분석** |
| **`/api/book/screen`** | GET | 책 점수 스크리닝 |
| **`/api/book/backtest`** | POST | 책 룰 백테스트 |
| **`/api/book/cases`** | GET | 책 헤드라인 사례 자동 검증 |
| **`/api/macro`** | GET | 25지표 + 레짐 |
| **`/api/macro/regime`** | GET | 레짐만 |
| **`/api/macro/series/{key}`** | GET | 단일 지표 시계열 |

---

## 5. Next.js 프론트엔드 (`web-next/`)

**Stack**: Next.js 16 (App Router) + React 19 + TypeScript + Tailwind v4 +
Auth.js v5 + next-themes + lucide-react.

### 페이지

| 경로 | 내용 |
|---|---|
| `/login` | Google OAuth — 이메일 화이트리스트 검증 |
| `/dashboard` | 거시 25지표 + 시장 레짐 + 책 해석 narrative |
| `/stocks` | 종목 검색 (US/KR 자동 정규화) |
| `/stocks/[ticker]` | 책 룰 전체 분석 UI: 추세 3 타임프레임, 패턴 카드, 거래량 케이스, 역매집, 매매 플랜 (진입/손절/목표) |
| `/recommendations` | 스크리닝 결과 테이블 — 시장/점수/Top N 필터, 행 클릭 시 종목 상세로 |
| `/backtest` | 단일 종목 백테스트 + **책 사례 자동 검증 테이블** (책 주장 vs 실측) |
| `/settings` | 계정 정보 |

### 인증

`web-next/src/auth.ts` — Auth.js v5 (NextAuth) + Google provider.

`signIn` callback 에서 `AUTH_ALLOWED_EMAILS` (env) 와 대조:
- **허용 목록 비어 있음** → production 거부 / development 만 허용
- **허용 목록 있음** → 명시된 Gmail 만 통과

`src/proxy.ts` (Next.js 16 에서 `middleware.ts` 의 후속 이름) 가 미인증
요청을 `/login` 으로 리다이렉트.

### 테마

`next-themes` + Tailwind v4 `@custom-variant dark` + shadcn 스타일 HSL
시멘틱 토큰 (`--background`, `--foreground`, `--muted`, `--card`,
`--border`, `--accent`). 헤더 우측 sun/moon 토글.

`<html suppressHydrationWarning>` — next-themes 와 브라우저 확장
(Wappalyzer 등) 이 hydration 직전 DOM 을 건드려서 발생하는 경고 무음 처리.

### Google OAuth 설정

1. https://console.cloud.google.com/apis/credentials → "OAuth 2.0 Client ID"
2. Authorized redirect URI: `http://localhost:3000/api/auth/callback/google`
3. `web-next/.env.local`:
   ```env
   BACKEND_URL=http://127.0.0.1:8001
   AUTH_SECRET=<openssl rand -base64 32>
   AUTH_GOOGLE_ID=...
   AUTH_GOOGLE_SECRET=...
   AUTH_ALLOWED_EMAILS=you@gmail.com
   ```

---

## 6. KIS API 연동 (`app/data/kis.py`)

한국투자증권 OpenAPI 클라이언트 — 실시간 시세 + 잔고 조회.

```python
from app.data.kis import KISClient
c = KISClient()
print(c.current_price("005930"))    # 삼성전자
print(c.ohlcv_daily("005930"))      # 일봉 100개
print(c.balance())                  # 계좌 보유 종목
```

- OAuth 토큰 발급 + 24h cache (`.cache/kis_token_*.json`)
- `KIS_ENV=real` → 실거래 / `KIS_ENV=vts` → 모의투자 엔드포인트
- **주문 (매수/매도) 엔드포인트는 의도적으로 미구현** — 분석 신뢰 충분히 쌓인 뒤 활성화 예정

`.env` 에 `KIS_APP_KEY`, `KIS_APP_SECRET`, `KIS_ACCOUNT_NO` 등록 필요
(apiportal.koreainvestment.com 가입 후 발급).

---

## 7. 디렉토리 구조

```
finance/
├── app/
│   ├── api/                       FastAPI
│   │   ├── server.py              v3 ML 엔드포인트
│   │   └── book_api.py            책 룰 + 거시 엔드포인트
│   ├── book/                      책 룰 엔진 (v3 NEW)
│   │   ├── trend.py               월/주/일봉 10MA 추세
│   │   ├── candles.py             4등분선 + 캔들 분류
│   │   ├── patterns.py            10가지 패턴
│   │   ├── reversals.py           되돌림 4유형
│   │   ├── volume.py              11유형 거래량 + 역매집
│   │   ├── analyzer.py            orchestrator
│   │   ├── backtest.py            룰 백테스트
│   │   └── _swings.py             swing high/low (scipy)
│   ├── macro/                     거시 (v3 NEW)
│   │   ├── indicators.py          25개 지표 카탈로그
│   │   ├── fetch.py               FRED + yfinance 수집
│   │   └── state.py               상태 분류 + 시장 레짐
│   ├── data/
│   │   ├── pit_db.py              DuckDB 스키마 (universe, prices, fundamentals,
│   │   │                                          macro, insider_transactions, paper_trades)
│   │   ├── universe.py            S&P 500 동적
│   │   ├── ingest_sec.py          SEC EDGAR (Company Facts)
│   │   ├── ingest_insiders.py     SEC Form 4 (P3, 인사이더 거래 XML)
│   │   ├── ingest_prices.py       yfinance
│   │   ├── ingest_krx.py          FinanceDataReader + pykrx fallback (P6)
│   │   ├── ingest_dart.py         DART OpenAPI (P6, 한국 펀더멘탈)
│   │   └── kis.py                 한투 API (실시간 시세 + 잔고)
│   ├── features/
│   │   ├── pipeline_v3.py         50+ 피처 + 섹터 중립 + 멀티-호라이즌 target
│   │   ├── factor_zoo.py          Piotroski / Mohanram / Beneish / Asness
│   │   ├── macro_features.py      거시 8피처 (P1, 레짐 conditioning)
│   │   ├── insider_features.py    인사이더 6피처 (P3)
│   │   ├── fund_vec.py            펀더멘털 PIT 벡터화
│   │   ├── fundamentals.py        TTM 계산
│   │   └── technical.py           가격 기반 피처
│   ├── model/
│   │   ├── purged_cv.py           PurgedKFold + Embargo
│   │   └── lgbm.py                LightGBM 학습/저장
│   ├── backtest/
│   │   ├── walkforward.py         v1 (raw target)
│   │   ├── walkforward_v3.py      v3 — rank target + sector cap + DD brake +
│   │   │                          inverse-vol + regime cash trigger + 세금 sim
│   │   └── multi_horizon.py       5d/21d/63d 앙상블 (P5)
│   ├── paper/                     Paper-trading (P4)
│   │   └── trader.py              record_snapshot / evaluate / metrics
│   ├── cli/__main__.py            typer CLI (15+개 명령)
│   ├── train.py                   학습 CLI 진입
│   └── config.py                  경로 + .env loader
│
├── web-next/                      Next.js 16 + Auth.js (v3 NEW)
│   ├── src/
│   │   ├── app/
│   │   │   ├── (app)/             인증 필요 라우트
│   │   │   │   ├── dashboard/     거시 대시보드
│   │   │   │   ├── stocks/[ticker]/
│   │   │   │   ├── recommendations/
│   │   │   │   ├── backtest/
│   │   │   │   └── settings/
│   │   │   ├── login/
│   │   │   ├── api/auth/[...nextauth]/
│   │   │   ├── layout.tsx
│   │   │   └── globals.css        Tailwind v4 + 다크/라이트 토큰
│   │   ├── components/            sidebar, theme-toggle, analysis-view, …
│   │   ├── lib/                   api client + utils
│   │   ├── auth.ts                Auth.js v5
│   │   └── proxy.ts               미인증 가드
│   ├── e2e/                       Playwright (8 tests)
│   │   ├── public.spec.ts         라우트 가드 (3)
│   │   └── backend.spec.ts        API surface (5)
│   ├── playwright.config.ts
│   └── package.json
│
├── book_images/                   원본 책 transcripts
│   ├── 0/                         0부
│   ├── 1/                         1부 (서문 + 6장)
│   │   ├── SUMMARY_1부.md
│   │   └── transcripts/p090-091_…
│   └── 2/                         2부 (1~7장)
│       ├── SUMMARY_2부.md
│       └── transcripts/
│
├── data/pit.duckdb                ML + 가격 + 거시 PIT DB
├── models_store/                  학습 결과물 + 리포트
│   ├── lgbm_v3.pkl
│   ├── feature_panel_v3.parquet
│   ├── feature_importance_v3.csv
│   ├── oof_ic_v3.csv
│   └── screen_backtest_*.{md,json,csv}
│
├── .env / .env.example            FRED, SEC, KIS 키
├── .gitattributes                 *.bat eol=crlf 강제
├── run-web.bat                    백+프론트 동시 실행 + 종료
├── install.bat / ingest.bat / train.bat / run.bat
└── requirements.txt
```

---

## 8. 테스트

### Playwright E2E (`web-next/e2e/`)

```powershell
cd web-next
npm run test:e2e          # 전체 (8 tests, ~2분)
npm run test:e2e:public   # 라우트 가드 (3 tests, ~3초)
npm run test:e2e:backend  # API surface (5 tests, ~2분)
```

전제: 백엔드 (`:8001`) + 프론트 (`:3000`) 모두 띄워져 있어야 함.
간단히 `run-web.bat` 실행해두고 별도 터미널에서 위 명령.

`backend.spec.ts` 의 screening 테스트는 S&P 500 전체 스캔으로 ~90초 소요 (180s 타임아웃 부여).

### Smoke tests (CLI)

```powershell
.\.venv\Scripts\python.exe -m app.cli stats        # DB 통계
.\.venv\Scripts\python.exe -m app.cli analyze AAPL # 종합 분석
.\.venv\Scripts\python.exe -m app.data.kis         # KIS 토큰 + 시세
```

---

## 9. 현재 상태 (M5 직전)

| 마일스톤 | 상태 |
|---|---|
| **M1**: CLI 백엔드 (트렌드 + 캔들 + 패턴 + 거시 + 백테스트) | ✅ |
| **M2**: Next.js 셸 + Auth + 거시 대시보드 | ✅ |
| **M2.5**: 다크/라이트 테마 | ✅ |
| **M3**: 종목 상세 + 추천 페이지 | ✅ |
| **M4**: 백테스트 페이지 | ✅ |
| 추가: 일괄 스크리닝 리포트 (.md/.json/.csv) | ✅ |
| 추가: KIS API stub (현재가/잔고) | ✅ |
| 추가: Playwright E2E 8/8 | ✅ |
| **M5**: GitHub Actions 크론 + 텔레그램 봇 | 🔧 다음 |

### 다음 (M5+)

- **GitHub Actions 크론**: 금요일 미국장 마감 후 (주봉 분석),
  매월 말일 (월봉 분석), 매일 아침 (일봉 리스크 시그널 알림)
- **텔레그램 봇**: 진입/청산 시그널 + 거시 레짐 변화 (VIX 30+, 수익률곡선 역전 등) 알림
- **자동매매 활성화** (사용자 명시 시): KIS 주문 API 통합
- **Vercel 배포** + 한 호스트로 백엔드 (Railway/Fly.io)
- **한국 종목 데이터 추가 적재**: 현재 CLI 만 — `ingest-krx --full` 로 KOSPI/KOSDAQ 전체

---

## 10. 책 1·2부 transcript 저장소

`book_images/`:
- 0부 (책 시작) + 1부 6개 장 + 2부 7개 장 모두 vision-read 로 검색 가능 텍스트화
- 챕터별 SUMMARY.md (1부 46개 / 2부 101개 transcript)

이 책 본문이 이 프로젝트의 모든 룰의 출처. 책 인용 (`book_ref: "2부 4장, p344"`)
이 거시 지표 + 패턴 정의 곳곳에 박혀 있음.

---

## 라이선스 / 감사

- 책: 저자 『추세추종 매매 룰』(출판사, 2026)
- 코드: 개인 학습 프로젝트. 비공개 (private GitHub repo).
- 무료 데이터 출처: SEC EDGAR, FRED, yfinance, pykrx, KIS OpenAPI
