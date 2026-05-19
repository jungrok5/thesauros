"""Catalog of macro indicators from the book.

Each indicator entry contains:
  - key:        short slug used in DB / API
  - name_kr:    Korean display name
  - source:     "FRED" or "yfinance" (latter is a legacy tag — the actual
                fetcher calls Yahoo's v8 chart endpoint directly, since
                the yfinance lib blocks cloud-IP traffic on GH Actions)
  - series_id:  FRED series ID or Yahoo Finance symbol
  - unit:       display unit ("%", "$", "index", "bps")
  - category:   one of {policy, liquidity, growth, inflation, sentiment, commodity, fx, breadth}
  - book_ref:   page citation in the book
  - desc:       one-line interpretation
  - thresholds: dict that drives state classifier (see state.py)
"""
from __future__ import annotations

from typing import Dict, List


INDICATORS: List[Dict] = [
    # ----- 정책/금리 (Fed) -----
    {
        "key": "fed_funds_rate",
        "name_kr": "미 연방기금금리",
        "source": "FRED", "series_id": "DFF",
        "unit": "%", "category": "policy",
        "book_ref": "1부 3장, 6장",
        "desc": "Fed 기준금리. 책: 단 하나의 경제 지표를 꼽으라면 미국 금리.",
        "thresholds": {
            "type": "level_yoy",
            "yoy_up": 0.5, "yoy_down": -0.5,  # rate of change (pct points)
            "bull_level_max": 3.0,             # 낮을수록 자산우호
        },
    },
    {
        "key": "tips_breakeven_10y",
        "name_kr": "10년 기대 인플레이션 (TIPS spread)",
        "source": "FRED", "series_id": "T10YIE",
        "unit": "%", "category": "inflation",
        "book_ref": "1부 6장",
        "desc": "명목 10Y - TIPS 10Y. Fed가 가장 민감하게 보는 시장 인플레 기대치.",
        "thresholds": {"type": "band", "low": 1.5, "mid_low": 2.0, "mid_high": 2.5, "high": 3.0},
    },
    {
        "key": "real_rate_10y",
        "name_kr": "10년 실질금리",
        "source": "FRED", "series_id": "DFII10",
        "unit": "%", "category": "policy",
        "book_ref": "1부 3장, 6장",
        "desc": "명목 - 인플레. 책: 투자자가 봐야 할 진짜 수익률.",
        "thresholds": {"type": "band", "low": -1.0, "mid_low": 0.0, "mid_high": 1.5, "high": 2.5},
    },
    {
        "key": "yield_curve_10y_2y",
        "name_kr": "수익률곡선 10Y-2Y",
        "source": "FRED", "series_id": "T10Y2Y",
        "unit": "%", "category": "policy",
        "book_ref": "1부 4장, 6장",
        "desc": "역전(<0)되면 18~24개월 내 경기침체 예고. 책 핵심 선행지표.",
        "thresholds": {"type": "sign", "inverted_warn": 0.0, "flattening_warn": 0.3},
    },
    {
        "key": "yield_curve_10y_3m",
        "name_kr": "수익률곡선 10Y-3M",
        "source": "FRED", "series_id": "T10Y3M",
        "unit": "%", "category": "policy",
        "book_ref": "1부 6장",
        "desc": "10년 - 3개월 스프레드 (Fed가 선호하는 침체 지표).",
        "thresholds": {"type": "sign", "inverted_warn": 0.0, "flattening_warn": 0.3},
    },

    # ----- 유동성 -----
    {
        "key": "m2_supply",
        "name_kr": "M2 통화공급량",
        "source": "FRED", "series_id": "M2SL",
        "unit": "$B", "category": "liquidity",
        "book_ref": "1부 1장, 5장, 6장",
        "desc": "시중 통화량. 책 MV=PQ 핵심. YoY 증가 → 자산 가격 상승 압력.",
        "thresholds": {"type": "yoy_pct", "bear": -1.0, "weak": 2.0, "neutral": 5.0, "bull": 8.0},
    },
    {
        "key": "fed_balance_sheet",
        "name_kr": "Fed 자산 (대차대조표)",
        "source": "FRED", "series_id": "WALCL",
        "unit": "$B", "category": "liquidity",
        "book_ref": "1부 1장",
        "desc": "Fed 자산 규모. QE 시 증가, QT 시 감소. 자산 가격과 연동.",
        "thresholds": {"type": "yoy_pct", "bear": -5.0, "weak": 0.0, "neutral": 5.0, "bull": 10.0},
    },

    # ----- 인플레/소비 -----
    {
        "key": "cpi",
        "name_kr": "소비자물가지수 (CPI YoY)",
        "source": "FRED", "series_id": "CPIAUCSL",
        "unit": "index", "category": "inflation",
        "book_ref": "1부 5장, 6장",
        "desc": "소비자 물가. Fed 타겟 2%. 책: 동행지수.",
        "thresholds": {"type": "yoy_pct_optimal", "optimal_low": 1.5, "optimal_high": 2.5,
                       "warn_high": 4.0, "danger_high": 6.0,
                       "warn_low": 0.5, "danger_low": -0.5},
    },
    {
        "key": "core_pce",
        "name_kr": "핵심 PCE",
        "source": "FRED", "series_id": "PCEPILFE",
        "unit": "index", "category": "inflation",
        "book_ref": "1부 5장",
        "desc": "Fed가 인플레이션 타겟으로 사용하는 지표. 식품/에너지 제외.",
        "thresholds": {"type": "yoy_pct_optimal", "optimal_low": 1.8, "optimal_high": 2.2,
                       "warn_high": 3.0, "danger_high": 4.5,
                       "warn_low": 0.5, "danger_low": -0.5},
    },
    {
        "key": "ppi",
        "name_kr": "생산자물가지수 (PPI YoY)",
        "source": "FRED", "series_id": "PPIACO",
        "unit": "index", "category": "inflation",
        "book_ref": "1부 5장, 6장",
        "desc": "생산자 물가. 책: CPI의 선행지수.",
        "thresholds": {"type": "yoy_pct", "bear": -3.0, "weak": 0.0, "neutral": 3.0, "bull": 6.0},
    },

    # ----- 고용/성장 -----
    {
        "key": "unemployment",
        "name_kr": "실업률",
        "source": "FRED", "series_id": "UNRATE",
        "unit": "%", "category": "growth",
        "book_ref": "1부 5장, 6장",
        "desc": "Fed가 금리 결정 시 보는 1순위 고용 지표.",
        "thresholds": {"type": "level", "good_max": 4.5, "warn_max": 5.5, "bad_max": 6.5},
    },
    {
        "key": "industrial_production",
        "name_kr": "산업생산 지수 (YoY)",
        "source": "FRED", "series_id": "INDPRO",
        "unit": "index", "category": "growth",
        "book_ref": "1부 4장, 6장",
        "desc": "산업 활동 척도 (책의 ISM PMI 대체). YoY 양수=확장, 음수=수축.",
        "thresholds": {"type": "yoy_pct", "bear": -3.0, "weak": 0.0, "neutral": 2.0, "bull": 4.0},
    },
    {
        "key": "manufacturing_new_orders",
        "name_kr": "제조업 신규 수주",
        "source": "FRED", "series_id": "AMTMNO",
        "unit": "$M", "category": "growth",
        "book_ref": "1부 6장",
        "desc": "제조업 신규 수주 YoY. 책: 수주출하 비율의 대용.",
        "thresholds": {"type": "yoy_pct", "bear": -5.0, "weak": -1.0, "neutral": 2.0, "bull": 6.0},
    },

    # ----- 환율/원자재 -----
    {
        "key": "dxy",
        "name_kr": "DXY 달러 지수",
        "source": "yfinance", "series_id": "DX-Y.NYB",
        "unit": "index", "category": "fx",
        "book_ref": "1부 2장",
        "desc": "달러 강도. 강달러 = 신흥국/원자재 압박.",
        "thresholds": {"type": "level_yoy", "bull_level_max": 100.0, "yoy_up": 5.0, "yoy_down": -5.0},
    },
    {
        "key": "gold",
        "name_kr": "금 (Gold spot)",
        "source": "yfinance", "series_id": "GC=F",
        "unit": "$", "category": "commodity",
        "book_ref": "1부 2장, 6장",
        "desc": "안전자산, 달러 역상관. 책: 달러 대척점.",
        "thresholds": {"type": "yoy_pct", "bear": -10.0, "weak": 0.0, "neutral": 10.0, "bull": 20.0},
    },
    {
        "key": "copper",
        "name_kr": "구리 (Dr. Copper)",
        "source": "yfinance", "series_id": "HG=F",
        "unit": "$", "category": "commodity",
        "book_ref": "1부 6장",
        "desc": "산업 활동의 척도. 책: 닥터 쿠퍼.",
        "thresholds": {"type": "yoy_pct", "bear": -15.0, "weak": -5.0, "neutral": 5.0, "bull": 15.0},
    },
    {
        "key": "wti_oil",
        "name_kr": "WTI 원유",
        "source": "yfinance", "series_id": "CL=F",
        "unit": "$", "category": "commodity",
        "book_ref": "1부 5장",
        "desc": "에너지 가격, 인플레/지정학 시그널.",
        "thresholds": {"type": "yoy_pct", "bear": -20.0, "weak": -10.0, "neutral": 10.0, "bull": 25.0},
    },
    {
        "key": "usdjpy",
        "name_kr": "USD/JPY 환율",
        "source": "yfinance", "series_id": "JPY=X",
        "unit": "JPY", "category": "fx",
        "book_ref": "1부 3장",
        "desc": "엔케리 트레이드 추적. 급락 시 글로벌 리스크 오프.",
        "thresholds": {"type": "yoy_pct", "bear": -10.0, "weak": -3.0, "neutral": 5.0, "bull": 10.0},
    },

    # ----- 시장 심리/공포 -----
    {
        "key": "vix",
        "name_kr": "VIX (CBOE 변동성지수)",
        "source": "yfinance", "series_id": "^VIX",
        "unit": "index", "category": "sentiment",
        "book_ref": "1부 6장",
        "desc": "S&P500 30일 IV. 책: 공포지수.",
        "thresholds": {"type": "level", "calm_max": 15.0, "warn_min": 20.0, "panic_min": 30.0},
    },
    {
        "key": "credit_spread_ig",
        "name_kr": "IG 회사채 스프레드 (BAML)",
        "source": "FRED", "series_id": "BAMLC0A0CM",
        "unit": "%", "category": "sentiment",
        "book_ref": "1부 6장",
        "desc": "투자등급 회사채 - 국채. 신용 경색 지표.",
        "thresholds": {"type": "level", "calm_max": 1.5, "warn_min": 2.0, "panic_min": 3.0},
    },
    {
        "key": "credit_spread_hy",
        "name_kr": "HY 정크채 스프레드",
        "source": "FRED", "series_id": "BAMLH0A0HYM2",
        "unit": "%", "category": "sentiment",
        "book_ref": "1부 6장",
        "desc": "정크 채권 스프레드. 위기 시 급등.",
        "thresholds": {"type": "level", "calm_max": 4.0, "warn_min": 6.0, "panic_min": 8.0},
    },

    # ----- 시장 breadth/지수 -----
    {
        "key": "sp500",
        "name_kr": "S&P 500",
        "source": "yfinance", "series_id": "^GSPC",
        "unit": "index", "category": "breadth",
        "book_ref": "2부 7장",
        "desc": "대표 미국 지수. 책의 탑다운 1단계 분석.",
        "thresholds": {"type": "trend_ma200"},  # custom (handled in state.py)
    },
    {
        "key": "nasdaq",
        "name_kr": "NASDAQ Composite",
        "source": "yfinance", "series_id": "^IXIC",
        "unit": "index", "category": "breadth",
        "book_ref": "2부 7장",
        "desc": "기술주 중심 지수. 글로벌 리스크 자산 선행.",
        "thresholds": {"type": "trend_ma200"},
    },
    {
        "key": "kospi",
        "name_kr": "KOSPI",
        "source": "yfinance", "series_id": "^KS11",
        "unit": "index", "category": "breadth",
        "book_ref": "2부 7장",
        "desc": "한국 대형주 지수.",
        "thresholds": {"type": "trend_ma200"},
    },
    {
        "key": "kosdaq",
        "name_kr": "KOSDAQ",
        "source": "yfinance", "series_id": "^KQ11",
        "unit": "index", "category": "breadth",
        "book_ref": "2부 7장",
        "desc": "한국 중소형주 지수.",
        "thresholds": {"type": "trend_ma200"},
    },

    # ============================================================
    # 책 1부 6장 추가 지표 (2026-05-15 audit)
    # ============================================================
    # ----- 소비 지표 -----
    {
        "key": "vehicle_sales",
        "name_kr": "자동차 판매 (TOTALSA)",
        "source": "FRED", "series_id": "TOTALSA",
        "unit": "M units", "category": "growth",
        "book_ref": "1부 6장 p170-171",
        "desc": "월간 차량 판매 (annualized). 책: 개인소비 핵심 지표.",
        "thresholds": {"type": "level", "good_max": 18.0, "warn_max": 15.0, "bad_max": 12.0},
    },
    {
        "key": "consumer_sentiment",
        "name_kr": "소비자심리 (Michigan)",
        "source": "FRED", "series_id": "UMCSENT",
        "unit": "index", "category": "sentiment",
        "book_ref": "1부 6장 p172-173",
        "desc": "미시간대 소비자 신뢰지수. 책: 소비심리 척도.",
        "thresholds": {"type": "level", "good_max": 90.0, "warn_max": 70.0, "bad_max": 60.0},
    },
    {
        "key": "housing_starts",
        "name_kr": "주택 착공 (HOUST)",
        "source": "FRED", "series_id": "HOUST",
        "unit": "K units", "category": "growth",
        "book_ref": "1부 6장 p174-175",
        "desc": "신규 주택 착공 (annualized). 책: 경기 선행 지표.",
        "thresholds": {"type": "level_yoy", "bull_level_max": 1500.0, "yoy_up": 5.0, "yoy_down": -10.0},
    },
    {
        "key": "new_home_sales",
        "name_kr": "신규주택 판매 (HSN1F)",
        "source": "FRED", "series_id": "HSN1F",
        "unit": "K units", "category": "growth",
        "book_ref": "1부 6장 p184-185",
        "desc": "단독주택 신규 판매. 책: 자산 + 소비 결합 지표.",
        "thresholds": {"type": "level_yoy", "bull_level_max": 700.0, "yoy_up": 5.0, "yoy_down": -10.0},
    },

    # ----- 고용 지표 (추가) -----
    {
        "key": "underemployment_u6",
        "name_kr": "불완전고용 U6 (U6RATE)",
        "source": "FRED", "series_id": "U6RATE",
        "unit": "%", "category": "growth",
        "book_ref": "1부 6장 p172-173",
        "desc": "광의 실업률 (단시간 + 한계근로자 포함). 책: 진짜 고용 척도.",
        "thresholds": {"type": "level", "good_max": 7.0, "warn_max": 9.0, "bad_max": 11.0},
    },
    {
        "key": "initial_claims",
        "name_kr": "주간 실업수당 청구 (ICSA)",
        "source": "FRED", "series_id": "ICSA",
        "unit": "K", "category": "growth",
        "book_ref": "1부 6장 p186-187 (주간 선행)",
        "desc": "주간 실업수당 신규 청구. 매주 발표 = 가장 빠른 고용 선행.",
        "thresholds": {"type": "level", "good_max": 250.0, "warn_max": 350.0, "bad_max": 450.0},
    },

    # ----- 기업 활동 -----
    {
        "key": "durable_goods_orders",
        "name_kr": "내구재 수주 (DGORDER)",
        "source": "FRED", "series_id": "DGORDER",
        "unit": "$M", "category": "growth",
        "book_ref": "1부 6장 p174-175",
        "desc": "내구재 신규 수주 (자본재 포함). 책: 기업투자 척도.",
        "thresholds": {"type": "yoy_pct", "bear": -8.0, "weak": -2.0, "neutral": 3.0, "bull": 8.0},
    },
    {
        "key": "philly_fed_mfg",
        "name_kr": "필라델피아 연준 제조업 (PHCM)",
        "source": "FRED", "series_id": "GACDFSA066MSFRBPHI",
        "unit": "index", "category": "growth",
        "book_ref": "1부 6장 p184-185",
        "desc": "필라델피아 지역 제조업 활동. 양수=확장.",
        "thresholds": {"type": "level", "good_max": 10.0, "warn_max": 0.0, "bad_max": -10.0},
    },

    # ----- 선행지수 -----
    {
        "key": "leading_index",
        "name_kr": "미국 경기선행지수 (USSLIND)",
        "source": "FRED", "series_id": "USSLIND",
        "unit": "%", "category": "growth",
        "book_ref": "1부 6장 p186-187 (주간 선행)",
        "desc": "Conference Board 종합 선행지수. 책: 경기 회복/침체 사전 감지.",
        "thresholds": {"type": "level", "good_max": 1.0, "warn_max": 0.0, "bad_max": -1.5},
    },

    # ----- 인플레이션/세금/통화 (추가) -----
    {
        "key": "import_price_index",
        "name_kr": "수입물가 (IR)",
        "source": "FRED", "series_id": "IR",
        "unit": "index", "category": "inflation",
        "book_ref": "1부 5장 p152-153 (수출입물가)",
        "desc": "수입물가지수 YoY. 책: 인플레이션 압력 선행.",
        "thresholds": {"type": "yoy_pct", "bear": -5.0, "weak": 0.0, "neutral": 3.0, "bull": 8.0},
    },

    # ----- 신용/리스크 (추가) -----
    {
        "key": "stlouis_fin_stress",
        "name_kr": "St.Louis 금융스트레스 (STLFSI3)",
        "source": "FRED", "series_id": "STLFSI4",
        "unit": "z-score", "category": "sentiment",
        "book_ref": "1부 6장 p190-191 (TED/스프레드 대안)",
        "desc": "18가지 금융지표 종합 스트레스 (TED 폐지 후 대용). 0=평상, +1=경고, +2=위기.",
        "thresholds": {"type": "level", "calm_max": 0.0, "warn_min": 1.0, "panic_min": 2.0},
    },
]


def get_indicator(key: str) -> Dict:
    for ind in INDICATORS:
        if ind["key"] == key:
            return ind
    raise KeyError(key)


def by_category(category: str) -> List[Dict]:
    return [i for i in INDICATORS if i["category"] == category]


CATEGORY_ORDER = ["policy", "liquidity", "inflation", "growth",
                  "sentiment", "fx", "commodity", "breadth"]
CATEGORY_LABEL_KR = {
    "policy":    "금리·정책",
    "liquidity": "유동성",
    "inflation": "물가",
    "growth":    "경기·고용",
    "sentiment": "시장 심리",
    "fx":        "환율",
    "commodity": "원자재",
    "breadth":   "지수",
}
