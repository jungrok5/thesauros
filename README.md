# AI 퀀트 v2 — PIT + LightGBM

S&P 500 대상 **진짜 PIT(point-in-time) ML 퀀트 시스템**. 무료 데이터만 사용:

- **SEC EDGAR Company Facts API** — 분기별 재무 데이터 with `filed_date` (진정한 PIT)
- **yfinance** — 일별 OHLCV 10년치
- **Wikipedia + SEC ticker→CIK** — S&P 500 종목 + 섹터 매핑

학습: **LightGBM regressor + PurgedKFold + Embargo** (López de Prado AFML §7).
백테스트: **워크포워드 재학습** with 거래비용/슬리피지.

> ⚠️ **면책**: 학습/연구 도구. 실거래 결과를 보장하지 않습니다.
> 투자 판단과 손익은 본인 책임.

## 아키텍처

```
SEC EDGAR Company Facts ─┐
                         ├─→ DuckDB (PIT) ─→ Feature Pipeline ─→ LightGBM ─→ Walk-Forward Backtest
yfinance Adjusted OHLCV ─┘                       │                  │
                                                 │                  └─→ Recommendations
                                                 └─→ Cross-sectional ranks
```

## 무엇이 다른가 (v1 → v2)

| 항목 | v1 | v2 |
|------|-----|-----|
| 펀더멘털 | yfinance `.info` (현재시점) | SEC EDGAR Company Facts (filed_date 그대로) |
| 룩어헤드 | 위험 있음 | **PurgedKFold + 21일 embargo로 차단** |
| 모델 | 휴리스틱 z-score 합산 | **LightGBM 회귀 모델** (50+ 피처) |
| 검증 | OOS 검증 없음 | OOS Spearman IC, fold별 측정 |
| 데이터 | API 호출 시 1-3분 대기 | **DuckDB 로컬 DB**, 즉시 |
| 유니버스 | 100개 큐레이트 | **S&P 500 동적** |

## 디렉토리 구조

```
finance/
├── app/
│   ├── data/                # DuckDB PIT layer
│   │   ├── pit_db.py
│   │   ├── universe.py      # S&P 500 + ticker→CIK
│   │   ├── ingest_sec.py    # SEC EDGAR Company Facts
│   │   └── ingest_prices.py # yfinance bulk
│   ├── features/
│   │   ├── fundamentals.py  # PIT-correct: filtered by filed_date ≤ asof
│   │   ├── technical.py
│   │   └── pipeline.py      # 50+ features × all (date, ticker)
│   ├── model/
│   │   ├── purged_cv.py     # PurgedKFold + Embargo
│   │   └── lgbm.py          # LightGBM training, save/load
│   ├── backtest/
│   │   └── walkforward.py   # Per-rebalance retrain, costs, IR
│   ├── api/server.py        # FastAPI v2
│   ├── train.py             # CLI training
│   └── config.py
├── web/                     # Tailwind + Plotly UI
├── data/pit.duckdb          # ← 모든 PIT 데이터
├── models_store/            # ← 학습된 모델
├── requirements.txt
└── run.bat / install.bat
```

## 빠른 시작

### 1) 의존성 설치 + 데이터 적재

```powershell
.\install.bat        # venv + 패키지 설치
.\ingest.bat         # 유니버스 + SEC 펀더멘털 + 10년 가격 (~10분)
```

### 2) 모델 학습

```powershell
.\train.bat
```

또는 웹 UI의 **모델 정보** 탭에서 "모델 재학습" 버튼.

### 3) 서버 실행

```powershell
.\run.bat
```

브라우저 자동 오픈 → http://127.0.0.1:8000

## 피처 (50+)

### 펀더멘털 (PIT, TTM 기반)
- 수익성: ROA, ROE, gross/operating/net margin
- 레버리지: debt/equity, liabilities/assets, current ratio, cash ratio
- 효율: asset turnover
- 성장: revenue YoY, earnings YoY
- 가치: P/E, P/B, P/S, EV/Revenue, EV/EBITDA proxy, FCF yield
- 사이즈: log market cap

### 기술적 (가격 기반)
- 모멘텀: 1M, 3M, 6M, 12-1M, 12M
- 변동성: 20D, 60D
- 추세: P/SMA50, P/SMA200, SMA50/SMA200, drawdown 252
- 오실레이터: RSI(14), MACD histogram, 5d reversal

각 피처는 **횡단면 랭크 퍼센타일**(`*_rk`) 형태로도 함께 제공 — 시점별 분포 차이에 강건.

## 모델 + 검증

- **타깃**: 21일 (~1개월) 후 forward 수익률
- **알고리즘**: LightGBM regression
- **검증**: PurgedKFold(5) + 21-day embargo
  - 각 폴드 테스트 블록의 ±21일 학습 샘플 제거
  - 학습 라벨 윈도우가 테스트 영역과 겹치면 제거
- **메트릭**: Fold별 Spearman IC (cross-sectional), 평균/표준편차 보고

## 백테스트 흐름

```
for t in rebalance_dates:
  1. cutoff = t - 42일 (embargo + horizon)
  2. train ← panel[date <= cutoff, with target]
  3. test ← panel[date == t]
  4. fit LightGBM(train)
  5. predict scores for test
  6. portfolio ← top-K equal-weight long-only
  7. apply turnover * (cost+slippage)
  8. hold N days, then repeat
```

벤치마크: 동일 유니버스 동일가중 보유.

## API

| 엔드포인트 | 메서드 | 용도 |
|-----------|--------|------|
| `/api/health` | GET | 헬스체크 |
| `/api/data/stats` | GET | DB 통계 |
| `/api/universe` | GET | S&P 500 + 섹터 |
| `/api/recommend?top_k=20` | GET | 최신 모델 예측 상위 K |
| `/api/analyze?ticker=AAPL` | GET | 단일 종목 풀 분석 |
| `/api/prices?ticker=&start=` | GET | 일별 OHLCV |
| `/api/backtest` | POST | 워크포워드 백테스트 |
| `/api/train` | POST | 모델 재학습 (백그라운드) |
| `/api/train/status` | GET | 학습 진행 |
| `/api/model/info` | GET | 피처 중요도, OOF IC |

## 한계 및 다음 단계 (Phase 2)

- **유니버스 = 현재 S&P 500** (생존자 편향): 과거 편입/제외 이력 필요
- **한국 시장 미지원**: DART OpenAPI 통합 필요 (Phase 2)
- **Sector neutralization 미구현**: 섹터별 z-score 정규화 후 합치기
- **포트폴리오 최적화**: 현재 동일가중 → CVXPY 평균-분산 / 위험 패리티
- **레짐 감지**: 변동성/추세 강도로 모델 가중치 동적 조정
- **실거래 연동**: Alpaca / KIS Developers API
