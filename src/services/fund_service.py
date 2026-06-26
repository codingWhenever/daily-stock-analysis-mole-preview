# -*- coding: utf-8 -*-
"""公募基金池、净值跟踪与规则化分析服务。"""

from __future__ import annotations

import logging
import math
import re
import time
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from threading import RLock, Thread
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from src.repositories.intelligence_repo import IntelligenceRepository
from src.repositories.fund_repo import FUND_LEDGER_PROFILE_FIELDS, FUND_LEDGER_PROFILE_LIMITS, FundRepository
from src.storage import FundPoolItem

logger = logging.getLogger(__name__)


FUND_CODE_RE = re.compile(r"^\d{6}$")
_CACHE_TTL_SECONDS = 600
_REMOTE_HTTP_TIMEOUT_SECONDS = 12
_REMOTE_HTTP_TIMEOUT_LOCK = RLock()
_REMOTE_HTTP_TIMEOUT_INSTALLED = False
FUND_RETURN_COLUMNS = [
    ("近1周", "1w"),
    ("近1月", "1m"),
    ("近3月", "3m"),
    ("近6月", "6m"),
    ("近1年", "1y"),
    ("近2年", "2y"),
    ("近3年", "3y"),
    ("今年来", "ytd"),
    ("成立来", "since_inception"),
]
FUND_PROFILE_SCHEMA_VERSION = "fund_profile_v2"
FUND_METRIC_PROFILE_SCHEMA_VERSION = "fund_metric_profile_v1"
FUND_DATA_QUALITY_SCHEMA_VERSION = "fund_data_quality_v1"
FUND_SIGNAL_MODEL_VERSION = "fund_signal_rule_v3_contextual"
MARKET_CONTEXT_SCHEMA_VERSION = "fund_market_context_v1"
FUND_BACKTEST_ENGINE_VERSION = "fund_nav_walk_forward_v1"
FUND_LEDGER_THEME_COLORS = ["#06B6D4", "#22C55E", "#F59E0B", "#EF4444", "#8B5CF6", "#EC4899", "#14B8A6"]
FUND_BACKTEST_BULLISH_ACTIONS = {"buy", "dca"}
FUND_BACKTEST_DEFENSIVE_ACTIONS = {"pause_buy", "reduce", "sell_watch"}
FUND_ACTION_LABELS = {
    "buy": "分批申购",
    "dca": "定投跟踪",
    "watch": "观望",
    "pause_buy": "暂停申购",
    "reduce": "暂停定投/减仓",
    "sell_watch": "赎回观察",
}
FUND_BACKTEST_OUTCOME_LABELS = {
    "win": "命中",
    "loss": "失误",
    "neutral": "中性",
    "unavailable": "不可评估",
}

REFERENCE_INDEX_PRESETS: Dict[str, List[str]] = {
    "active_equity": ["沪深300", "中证500", "创业板50"],
    "index_beta": ["沪深300", "中证500", "中证1000"],
    "bond_income": ["沪深300"],
    "qdii_global": [],
    "fof_allocation": ["沪深300", "中证500"],
    "general_fund": ["沪深300", "中证500"],
}

STYLE_REFERENCE_INDEX: Dict[str, str] = {
    "沪深300": "沪深300",
    "中证500": "中证500",
    "中证1000": "中证1000",
    "小盘": "中证1000",
    "成长": "创业板50",
    "科技": "创业板50",
    "半导体": "创业板50",
    "新能源": "创业板50",
    "消费": "沪深300",
    "医药": "创业板50",
    "红利": "上证红利",
}

STRATEGY_POLICY_PRESETS: Dict[str, Dict[str, Any]] = {
    "active_equity": {
        "label": "主动权益初始参数",
        "risk_baseline": 30.0,
        "volatility_floor_pct": 8.0,
        "drawdown_alert_pct": -20.0,
        "drawdown_stop_pct": -32.0,
        "risk_gate": 70.0,
        "return_weights": {"3m": 0.8, "6m": 0.35, "1y": 0.18, "peer_1y": 0.22},
        "trend_bonus": {"uptrend": 8.0, "downtrend": -10.0, "sideways": 0.0},
        "risk_weights": {"volatility": 1.4, "drawdown": 1.1, "recent_loss": 10.0},
        "action_thresholds": {"buy": 72.0, "dca": 58.0, "watch": 45.0, "reduce": 30.0},
        "execution_notes": ["适合长期资金分批跟踪", "需要结合权益市场周期和风格拥挤度校准"],
    },
    "index_beta": {
        "label": "指数 beta 初始参数",
        "risk_baseline": 28.0,
        "volatility_floor_pct": 10.0,
        "drawdown_alert_pct": -22.0,
        "drawdown_stop_pct": -35.0,
        "risk_gate": 72.0,
        "return_weights": {"3m": 0.55, "6m": 0.35, "1y": 0.22, "peer_1y": 0.16},
        "trend_bonus": {"uptrend": 7.0, "downtrend": -9.0, "sideways": 0.0},
        "risk_weights": {"volatility": 1.2, "drawdown": 1.0, "recent_loss": 8.0},
        "action_thresholds": {"buy": 70.0, "dca": 56.0, "watch": 44.0, "reduce": 30.0},
        "execution_notes": ["更依赖跟踪指数估值和趋势", "需要接入跟踪误差、费率和规模后再校准"],
    },
    "bond_income": {
        "label": "固收收益初始参数",
        "risk_baseline": 20.0,
        "volatility_floor_pct": 3.0,
        "drawdown_alert_pct": -5.0,
        "drawdown_stop_pct": -10.0,
        "risk_gate": 58.0,
        "return_weights": {"3m": 0.45, "6m": 0.32, "1y": 0.24, "peer_1y": 0.18},
        "trend_bonus": {"uptrend": 5.0, "downtrend": -8.0, "sideways": 0.0},
        "risk_weights": {"volatility": 2.4, "drawdown": 3.0, "recent_loss": 6.0},
        "action_thresholds": {"buy": 68.0, "dca": 55.0, "watch": 45.0, "reduce": 34.0},
        "execution_notes": ["对回撤更敏感", "需要接入利率周期、信用利差和债券指数趋势"],
    },
    "money_market": {
        "label": "货币流动性参数待接入",
        "risk_baseline": 12.0,
        "volatility_floor_pct": 1.0,
        "drawdown_alert_pct": -1.0,
        "drawdown_stop_pct": -2.0,
        "risk_gate": 40.0,
        "return_weights": {"3m": 0.0, "6m": 0.0, "1y": 0.0, "peer_1y": 0.0},
        "trend_bonus": {"uptrend": 0.0, "downtrend": 0.0, "sideways": 0.0},
        "risk_weights": {"volatility": 1.0, "drawdown": 1.0, "recent_loss": 0.0},
        "action_thresholds": {"buy": 90.0, "dca": 75.0, "watch": 0.0, "reduce": 0.0},
        "execution_notes": ["必须接入七日年化、万份收益、规模和流动性后再生成买入建议"],
    },
    "qdii_global": {
        "label": "海外资产初始参数",
        "risk_baseline": 36.0,
        "volatility_floor_pct": 12.0,
        "drawdown_alert_pct": -24.0,
        "drawdown_stop_pct": -38.0,
        "risk_gate": 74.0,
        "return_weights": {"3m": 0.55, "6m": 0.32, "1y": 0.2, "peer_1y": 0.18},
        "trend_bonus": {"uptrend": 6.0, "downtrend": -9.0, "sideways": 0.0},
        "risk_weights": {"volatility": 1.1, "drawdown": 0.95, "recent_loss": 8.0},
        "action_thresholds": {"buy": 72.0, "dca": 58.0, "watch": 46.0, "reduce": 32.0},
        "execution_notes": ["需要海外指数、汇率和申赎状态共同校准", "QDII 可能存在额度和时差边界"],
    },
    "fof_allocation": {
        "label": "FOF 配置初始参数",
        "risk_baseline": 24.0,
        "volatility_floor_pct": 6.0,
        "drawdown_alert_pct": -12.0,
        "drawdown_stop_pct": -22.0,
        "risk_gate": 64.0,
        "return_weights": {"3m": 0.48, "6m": 0.34, "1y": 0.22, "peer_1y": 0.18},
        "trend_bonus": {"uptrend": 5.0, "downtrend": -7.0, "sideways": 0.0},
        "risk_weights": {"volatility": 1.4, "drawdown": 1.5, "recent_loss": 6.0},
        "action_thresholds": {"buy": 68.0, "dca": 55.0, "watch": 44.0, "reduce": 32.0},
        "execution_notes": ["需要底层基金风格和大类资产暴露后再细化"],
    },
    "general_fund": {
        "label": "通用基金初始参数",
        "risk_baseline": 30.0,
        "volatility_floor_pct": 8.0,
        "drawdown_alert_pct": -20.0,
        "drawdown_stop_pct": -32.0,
        "risk_gate": 70.0,
        "return_weights": {"3m": 0.7, "6m": 0.3, "1y": 0.18, "peer_1y": 0.2},
        "trend_bonus": {"uptrend": 6.0, "downtrend": -9.0, "sideways": 0.0},
        "risk_weights": {"volatility": 1.2, "drawdown": 1.0, "recent_loss": 8.0},
        "action_thresholds": {"buy": 72.0, "dca": 58.0, "watch": 45.0, "reduce": 30.0},
        "execution_notes": ["类型识别不足时使用保守通用参数"],
    },
}


def normalize_fund_code(code: str) -> str:
    normalized = (code or "").strip()
    if not FUND_CODE_RE.fullmatch(normalized):
        raise ValueError("基金代码应为 6 位数字")
    return normalized


def normalize_fund_ledger_color(color: str) -> str:
    text = (color or "").strip()
    if text in FUND_LEDGER_THEME_COLORS:
        return text
    if re.fullmatch(r"#[0-9A-Fa-f]{6}", text):
        return text.upper()
    if re.fullmatch(r"#[0-9A-Fa-f]{3}", text):
        return text.upper()
    return FUND_LEDGER_THEME_COLORS[0]


def normalize_fund_ledger_profile(updates: Dict[str, Any]) -> Dict[str, Optional[str]]:
    normalized: Dict[str, Optional[str]] = {}
    for field in FUND_LEDGER_PROFILE_FIELDS:
        if field not in updates:
            continue
        value = updates[field]
        if value is None:
            normalized[field] = None
            continue
        text = str(value).strip()
        normalized[field] = text or None
        limit = FUND_LEDGER_PROFILE_LIMITS[field]
        if normalized[field] is not None and len(normalized[field] or "") > limit:
            raise ValueError(f"{field} 不能超过 {limit} 个字符")
    return normalized


def _to_float(value: Any) -> Optional[float]:
    if value is None:
        return None
    if isinstance(value, str):
        text = value.strip().replace(",", "").replace("%", "")
        if not text or text in {"---", "--", "nan", "NaN"}:
            return None
        value = text
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    if math.isnan(result) or math.isinf(result):
        return None
    return result


def _latest_column(columns: List[str], suffix: str) -> Optional[str]:
    candidates = [col for col in columns if col.endswith(suffix)]
    return sorted(candidates, reverse=True)[0] if candidates else None


def _safe_percent(value: Optional[float]) -> Optional[float]:
    if value is None:
        return None
    return round(value, 2)


def _compact_strings(items: List[Optional[str]]) -> List[str]:
    return [item for item in items if item]


def _compact_unique_strings(items: List[Optional[str]]) -> List[str]:
    return list(dict.fromkeys(item for item in items if item))


def _iso_date(value: Any) -> Optional[str]:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    try:
        parsed = pd.to_datetime(value, errors="coerce")
    except (TypeError, ValueError):
        return None
    if pd.isna(parsed):
        return None
    return parsed.date().isoformat()


def _date_age_days(value: Any) -> Optional[int]:
    iso_value = _iso_date(value)
    if not iso_value:
        return None
    try:
        parsed = datetime.strptime(iso_value, "%Y-%m-%d").date()
    except ValueError:
        return None
    return max((date.today() - parsed).days, 0)


def _future_date_days(value: Any) -> Optional[int]:
    iso_value = _iso_date(value)
    if not iso_value:
        return None
    try:
        parsed = datetime.strptime(iso_value, "%Y-%m-%d").date()
    except ValueError:
        return None
    days = (parsed - date.today()).days
    return days if days > 0 else None


def _latest_iso_date(values: List[Any]) -> Optional[str]:
    parsed_values: List[date] = []
    for value in values:
        iso_value = _iso_date(value)
        if not iso_value:
            continue
        try:
            parsed_values.append(datetime.strptime(iso_value, "%Y-%m-%d").date())
        except ValueError:
            continue
    if not parsed_values:
        return None
    return max(parsed_values).isoformat()


def _quality_factor(status: str) -> float:
    return {
        "ok": 1.0,
        "partial": 0.65,
        "estimated": 0.45,
        "stale": 0.35,
        "missing": 0.0,
    }.get(status, 0.0)


def _install_requests_default_timeout(timeout: int = _REMOTE_HTTP_TIMEOUT_SECONDS) -> None:
    """Apply a conservative process-wide default timeout to requests-based pages."""
    global _REMOTE_HTTP_TIMEOUT_INSTALLED
    import requests

    with _REMOTE_HTTP_TIMEOUT_LOCK:
        if _REMOTE_HTTP_TIMEOUT_INSTALLED:
            return
        original_request = requests.sessions.Session.request

        def request_with_timeout(session, method, url, **kwargs):
            if kwargs.get("timeout") is None:
                kwargs["timeout"] = timeout
            return original_request(session, method, url, **kwargs)

        requests.sessions.Session.request = request_with_timeout
        _REMOTE_HTTP_TIMEOUT_INSTALLED = True


def _call_with_timeout(label: str, loader, timeout: int = _REMOTE_HTTP_TIMEOUT_SECONDS):
    result: Dict[str, Any] = {}
    errors: Dict[str, BaseException] = {}

    def run() -> None:
        try:
            result["value"] = loader()
        except BaseException as exc:  # noqa: BLE001
            errors["error"] = exc

    thread = Thread(target=run, name=f"fund-provider:{label}", daemon=True)
    thread.start()
    thread.join(timeout)
    if thread.is_alive():
        raise TimeoutError(f"{label} 获取超时（>{timeout}s）")
    if "error" in errors:
        raise errors["error"]
    return result.get("value")


@dataclass
class FundMetadata:
    code: str
    name: Optional[str] = None
    fund_type: Optional[str] = None
    source: str = "akshare"


@dataclass
class FundLatestQuote:
    code: str
    name: Optional[str] = None
    unit_nav: Optional[float] = None
    accumulated_nav: Optional[float] = None
    previous_unit_nav: Optional[float] = None
    daily_growth_pct: Optional[float] = None
    purchase_status: Optional[str] = None
    redemption_status: Optional[str] = None
    fee: Optional[str] = None
    nav_date: Optional[date] = None
    source: str = "akshare"


class AkshareFundProvider:
    """AKShare 公募基金数据适配器。"""

    def __init__(self):
        self._cache: Dict[str, Tuple[float, pd.DataFrame]] = {}

    def _cached(self, key: str, loader) -> pd.DataFrame:
        now = time.time()
        cached = self._cache.get(key)
        if cached and now - cached[0] < _CACHE_TTL_SECONDS:
            return cached[1].copy()
        _install_requests_default_timeout()
        df = loader()
        self._cache[key] = (now, df.copy())
        return df

    def fund_names(self) -> pd.DataFrame:
        import akshare as ak

        return self._cached("fund_name_em", ak.fund_name_em)

    def open_fund_daily(self) -> pd.DataFrame:
        import akshare as ak

        return self._cached("fund_open_fund_daily_em", ak.fund_open_fund_daily_em)

    def open_fund_rank(self, symbol: str) -> pd.DataFrame:
        import akshare as ak

        return self._cached(f"fund_open_fund_rank_em:{symbol}", lambda: ak.fund_open_fund_rank_em(symbol=symbol))

    def etf_spot(self) -> pd.DataFrame:
        import akshare as ak

        return self._cached("fund_etf_spot_em", ak.fund_etf_spot_em)

    def exchange_fund_rank(self) -> pd.DataFrame:
        import akshare as ak

        return self._cached("fund_exchange_rank_em", ak.fund_exchange_rank_em)

    def nav_history(self, code: str) -> pd.DataFrame:
        import akshare as ak

        _install_requests_default_timeout(20)
        return ak.fund_open_fund_info_em(symbol=code, indicator="单位净值走势", period="成立来")

    def individual_analysis(self, code: str) -> Optional[Dict[str, Any]]:
        """Return direct risk metrics when the public provider covers the fund."""
        import akshare as ak

        _install_requests_default_timeout(12)
        df = ak.fund_individual_analysis_xq(symbol=code, timeout=10)
        if df.empty or "周期" not in df.columns:
            return None
        row = df[df["周期"].astype(str) == "近1年"]
        if row.empty:
            row = df.head(1)
        item = row.iloc[0]
        max_drawdown = _to_float(item.get("最大回撤"))
        return {
            "period": str(item.get("周期") or ""),
            "peer_risk_return_ratio": _to_float(item.get("较同类风险收益比")),
            "peer_anti_volatility": _to_float(item.get("较同类抗风险波动")),
            "volatility_1y_pct": _to_float(item.get("年化波动率")),
            "sharpe_1y": _to_float(item.get("年化夏普比率")),
            "max_drawdown_1y_pct": -abs(max_drawdown) if max_drawdown is not None else None,
            "source": "fund_individual_analysis_xq",
        }

    def index_pe(self, symbol: str) -> pd.DataFrame:
        import akshare as ak

        return self._cached(f"stock_index_pe_lg:{symbol}", lambda: ak.stock_index_pe_lg(symbol=symbol))

    def index_pb(self, symbol: str) -> pd.DataFrame:
        import akshare as ak

        return self._cached(f"stock_index_pb_lg:{symbol}", lambda: ak.stock_index_pb_lg(symbol=symbol))

    def fund_industry_allocation(self, code: str, year: str) -> pd.DataFrame:
        import akshare as ak

        return self._cached(
            f"fund_portfolio_industry_allocation_em:{code}:{year}",
            lambda: ak.fund_portfolio_industry_allocation_em(symbol=code, date=year),
        )

    def fund_stock_holdings(self, code: str, year: str) -> pd.DataFrame:
        import akshare as ak

        return self._cached(
            f"fund_portfolio_hold_em:{code}:{year}",
            lambda: ak.fund_portfolio_hold_em(symbol=code, date=year),
        )

    def fund_reports(self, code: str) -> pd.DataFrame:
        import akshare as ak

        return self._cached(
            f"fund_announcement_report_em:{code}",
            lambda: ak.fund_announcement_report_em(symbol=code),
        )

    def fund_fee(self, code: str, indicator: str) -> pd.DataFrame:
        import akshare as ak

        return self._cached(
            f"fund_fee_em:{code}:{indicator}",
            lambda: ak.fund_fee_em(symbol=code, indicator=indicator),
        )

    def fund_purchase_table(self) -> pd.DataFrame:
        import akshare as ak

        return self._cached("fund_purchase_em", ak.fund_purchase_em)

    def get_metadata(self, code: str) -> FundMetadata:
        df = self.fund_names()
        if df.empty or "基金代码" not in df.columns:
            return FundMetadata(code=code)
        row = df[df["基金代码"].astype(str).str.zfill(6) == code]
        if row.empty:
            return FundMetadata(code=code)
        item = row.iloc[0]
        return FundMetadata(
            code=code,
            name=str(item.get("基金简称") or "") or None,
            fund_type=str(item.get("基金类型") or "") or None,
        )

    def search_funds(self, query: str, limit: int = 20) -> List[FundMetadata]:
        keyword = (query or "").strip()
        if not keyword:
            return []
        df = self.fund_names()
        if df.empty or "基金代码" not in df.columns:
            return []
        frame = df.copy()
        frame["基金代码"] = frame["基金代码"].astype(str).str.zfill(6)
        lowered = keyword.lower()
        code_mask = frame["基金代码"].str.contains(keyword, na=False, regex=False)
        name_mask = frame.get("基金简称", pd.Series("", index=frame.index)).astype(str).str.contains(keyword, case=False, na=False, regex=False)
        pinyin_mask = frame.get("拼音缩写", pd.Series("", index=frame.index)).astype(str).str.lower().str.contains(lowered, na=False, regex=False)
        full_pinyin_mask = frame.get("拼音全称", pd.Series("", index=frame.index)).astype(str).str.lower().str.contains(lowered, na=False, regex=False)
        matches = frame[code_mask | name_mask | pinyin_mask | full_pinyin_mask].copy()
        if matches.empty:
            return []

        def _score(row: pd.Series) -> int:
            code = str(row.get("基金代码") or "")
            name = str(row.get("基金简称") or "")
            pinyin = str(row.get("拼音缩写") or "").lower()
            if code == keyword:
                return 0
            if code.startswith(keyword):
                return 1
            if name == keyword:
                return 2
            if name.startswith(keyword):
                return 3
            if pinyin.startswith(lowered):
                return 4
            return 5

        matches["_score"] = matches.apply(_score, axis=1)
        matches = matches.sort_values(["_score", "基金代码"]).head(limit)
        return [
            FundMetadata(
                code=str(row.get("基金代码") or "").zfill(6),
                name=str(row.get("基金简称") or "") or None,
                fund_type=str(row.get("基金类型") or "") or None,
            )
            for _, row in matches.iterrows()
        ]

    def get_latest_quote(self, code: str) -> Optional[FundLatestQuote]:
        df = self.open_fund_daily()
        if df.empty or "基金代码" not in df.columns:
            return None
        rows = df[df["基金代码"].astype(str).str.zfill(6) == code]
        if rows.empty:
            return None
        row = rows.iloc[0]
        columns = list(df.columns)
        unit_col = _latest_column(columns, "单位净值")
        acc_col = _latest_column(columns, "累计净值")
        prev_unit_cols = [col for col in columns if col.endswith("单位净值") and col != unit_col]
        prev_unit_col = sorted(prev_unit_cols, reverse=True)[0] if prev_unit_cols else None
        nav_date = None
        if unit_col:
            try:
                nav_date = datetime.strptime(unit_col.split("-单位净值")[0], "%Y-%m-%d").date()
            except ValueError:
                nav_date = None
        return FundLatestQuote(
            code=code,
            name=str(row.get("基金简称") or "") or None,
            unit_nav=_to_float(row.get(unit_col)) if unit_col else None,
            accumulated_nav=_to_float(row.get(acc_col)) if acc_col else None,
            previous_unit_nav=_to_float(row.get(prev_unit_col)) if prev_unit_col else None,
            daily_growth_pct=_to_float(row.get("日增长率")),
            purchase_status=str(row.get("申购状态") or "") or None,
            redemption_status=str(row.get("赎回状态") or "") or None,
            fee=str(row.get("手续费") or "") or None,
            nav_date=nav_date,
        )

    def get_nav_records(self, code: str) -> List[Dict[str, Any]]:
        df = self.nav_history(code)
        if df.empty:
            return []
        records = []
        for row in df.to_dict(orient="records"):
            raw_date = row.get("净值日期") or row.get("date")
            if not raw_date:
                continue
            records.append(
                {
                    "date": raw_date,
                    "unit_nav": _to_float(row.get("单位净值")),
                    "accumulated_nav": _to_float(row.get("累计净值")),
                    "daily_growth_pct": _to_float(row.get("日增长率")),
                }
            )
        return records

    def get_peer_snapshot(self, code: str, fund_type: Optional[str]) -> Optional[Dict[str, Any]]:
        symbol = classify_rank_symbol(fund_type)
        if not symbol:
            return None
        df = self.open_fund_rank(symbol)
        if df.empty or "基金代码" not in df.columns:
            return None
        df = df.copy()
        df["基金代码"] = df["基金代码"].astype(str).str.zfill(6)
        row = df[df["基金代码"] == code]
        if row.empty:
            return {
                "category": symbol,
                "sample_size": int(len(df)),
                "rank": None,
                "percentiles": {},
                "data_quality": "partial",
                "message": "同类榜单中未找到该基金",
            }
        item = row.iloc[0]
        latest = {
            "unit_nav": _to_float(item.get("单位净值")),
            "accumulated_nav": _to_float(item.get("累计净值")),
            "daily_growth_pct": _to_float(item.get("日增长率")),
            "nav_date": str(item.get("日期") or ""),
            "fee": str(item.get("手续费") or "") or None,
        }
        percentiles: Dict[str, Optional[float]] = {}
        raw_returns: Dict[str, Optional[float]] = {}
        for col, key in FUND_RETURN_COLUMNS:
            if col not in df.columns:
                continue
            series = df[col].map(_to_float).dropna() if col in df.columns else pd.Series(dtype=float)
            value = _to_float(item.get(col)) if col in df.columns else None
            raw_returns[key] = value
            if value is None or series.empty:
                percentiles[key] = None
                continue
            below_or_equal = float((series <= value).sum())
            percentiles[key] = round(below_or_equal / float(len(series)) * 100, 1)
        rank = int(item.get("序号")) if _to_float(item.get("序号")) is not None else None
        return {
            "category": symbol,
            "sample_size": int(len(df)),
            "rank": rank,
            "percentiles": percentiles,
            "returns": raw_returns,
            "latest": latest,
            "date": str(item.get("日期") or ""),
            "data_quality": "ok",
        }


def classify_rank_symbol(fund_type: Optional[str]) -> Optional[str]:
    if not fund_type:
        return "全部"
    if "货币" in fund_type or "理财" in fund_type:
        return None
    if "指数" in fund_type:
        return "指数型"
    if "股票" in fund_type:
        return "股票型"
    if "混合" in fund_type:
        return "混合型"
    if "债券" in fund_type:
        return "债券型"
    if "QDII" in fund_type.upper():
        return "QDII"
    if "FOF" in fund_type.upper():
        return "FOF"
    return "全部"


def infer_fund_taxonomy(name: Optional[str], fund_type: Optional[str]) -> Dict[str, Any]:
    """Infer a coarse fund taxonomy for explainable screening and future backtests."""
    text = f"{name or ''} {fund_type or ''}".upper()
    fund_type_text = fund_type or ""
    asset_class = "unknown"
    strategy_family = "general_fund"
    holding_horizon = "unknown"
    market_context_needs = ["同类基金收益分位", "基金自身净值趋势"]
    style_tags: List[str] = []

    if "货币" in fund_type_text or "理财" in fund_type_text:
        asset_class = "cash"
        strategy_family = "money_market"
        holding_horizon = "liquidity"
        market_context_needs = ["七日年化收益", "万份收益", "流动性约束", "规模稳定性"]
        style_tags.append("现金管理")
    elif "QDII" in text:
        asset_class = "global_asset"
        strategy_family = "qdii_global"
        holding_horizon = "1y+"
        market_context_needs = ["海外市场趋势", "汇率变化", "申赎额度", "海外估值分位"]
        style_tags.append("海外资产")
    elif "FOF" in text:
        asset_class = "multi_asset"
        strategy_family = "fof_allocation"
        holding_horizon = "1y+"
        market_context_needs = ["资产配置比例", "底层基金风格", "大类资产周期", "组合回撤"]
        style_tags.append("组合配置")
    elif "债券" in fund_type_text:
        asset_class = "fixed_income"
        strategy_family = "bond_income"
        holding_horizon = "6m+"
        market_context_needs = ["利率周期", "信用利差", "债券指数趋势", "回撤修复速度"]
        style_tags.append("固收")
    elif "指数" in fund_type_text or "ETF" in text or "ETF联接" in text:
        asset_class = "equity_beta"
        strategy_family = "index_beta"
        holding_horizon = "1y+"
        market_context_needs = ["跟踪指数估值分位", "跟踪误差", "费率与规模", "宽基/行业趋势"]
        style_tags.append("指数")
    elif "股票" in fund_type_text or "混合" in fund_type_text:
        asset_class = "active_equity"
        strategy_family = "active_equity"
        holding_horizon = "2y+"
        market_context_needs = ["权益市场趋势", "成长/价值风格轮动", "行业景气", "估值分位"]
        style_tags.append("主动权益")

    name_text = name or ""
    style_keywords = [
        ("成长", "成长"),
        ("价值", "价值"),
        ("红利", "红利"),
        ("消费", "消费"),
        ("医药", "医药"),
        ("新能源", "新能源"),
        ("科技", "科技"),
        ("半导体", "半导体"),
        ("量化", "量化"),
        ("小盘", "小盘"),
        ("港股", "港股"),
        ("美股", "美股"),
        ("纳斯达克", "纳指"),
        ("沪深300", "沪深300"),
        ("中证500", "中证500"),
        ("中证1000", "中证1000"),
    ]
    for keyword, tag in style_keywords:
        if keyword in name_text and tag not in style_tags:
            style_tags.append(tag)

    return {
        "asset_class": asset_class,
        "strategy_family": strategy_family,
        "holding_horizon": holding_horizon,
        "style_tags": style_tags[:8],
        "market_context_needs": market_context_needs,
    }


def build_strategy_policy(taxonomy: Dict[str, Any]) -> Dict[str, Any]:
    """Return the current transparent, unvalidated parameter preset for this fund type."""
    family = str(taxonomy.get("strategy_family") or "general_fund")
    preset = STRATEGY_POLICY_PRESETS.get(family, STRATEGY_POLICY_PRESETS["general_fund"])
    policy = {
        **preset,
        "strategy_family": family,
        "policy_version": FUND_SIGNAL_MODEL_VERSION,
        "source": "bootstrap_type_preset",
        "validation_status": "heuristic_unvalidated",
        "requires_calibration": True,
    }
    return policy


def _metric_value_status(value: Any, *, estimated: bool = False) -> str:
    if value is None:
        return "missing"
    return "estimated" if estimated else "ok"


def _metric_item(
    *,
    key: str,
    label: str,
    status: str,
    value: Any,
    source: Optional[str],
    interpretation: str,
    applicability: str,
) -> Dict[str, Any]:
    return {
        "key": key,
        "label": label,
        "status": status,
        "value": value,
        "source": source,
        "interpretation": interpretation,
        "applicability": applicability,
    }


def _missing_specialized_metric(
    *,
    key: str,
    label: str,
    reason: str,
    required_for: str,
) -> Dict[str, str]:
    return {
        "key": key,
        "label": label,
        "reason": reason,
        "required_for": required_for,
    }


def build_metric_profile(
    *,
    taxonomy: Dict[str, Any],
    metrics: Dict[str, Any],
    peer: Optional[Dict[str, Any]],
    latest_quote: Optional[FundLatestQuote],
    risk_analysis: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    """Declare the metric set that is appropriate for the inferred fund type."""
    family = str(taxonomy.get("strategy_family") or "general_fund")
    asset_class = str(taxonomy.get("asset_class") or "unknown")
    returns = metrics.get("returns") if isinstance(metrics.get("returns"), dict) else {}
    metric_sources = metrics.get("metric_sources") if isinstance(metrics.get("metric_sources"), dict) else {}
    peer_percentiles = peer.get("percentiles") if isinstance(peer, dict) and isinstance(peer.get("percentiles"), dict) else {}
    risk_source = metric_sources.get("risk")
    risk_is_estimated = not isinstance(risk_analysis, dict)
    primary_metrics: List[Dict[str, Any]] = []
    not_applicable_metrics: List[Dict[str, str]] = []
    missing_specialized_metrics: List[Dict[str, str]] = []

    def add_primary(
        key: str,
        label: str,
        value: Any,
        source: Optional[str],
        interpretation: str,
        applicability: str,
        *,
        estimated: bool = False,
    ) -> None:
        primary_metrics.append(
            _metric_item(
                key=key,
                label=label,
                status=_metric_value_status(value, estimated=estimated),
                value=value,
                source=source,
                interpretation=interpretation,
                applicability=applicability,
            )
        )

    def add_missing(key: str, label: str, reason: str, required_for: str) -> None:
        missing_specialized_metrics.append(
            _missing_specialized_metric(
                key=key,
                label=label,
                reason=reason,
                required_for=required_for,
            )
        )

    if family == "money_market":
        add_primary(
            "seven_day_annualized_yield",
            "七日年化收益率",
            None,
            None,
            "货币基金的核心收益观察项，不能用股票型阶段涨跌幅替代。",
            "required_for_signal",
        )
        add_primary(
            "income_per_10k",
            "万份收益",
            None,
            None,
            "反映每万份基金份额的日收益，是现金管理体验的基础指标。",
            "required_for_signal",
        )
        add_primary(
            "fund_size_liquidity",
            "规模/流动性",
            None,
            None,
            "用于观察申赎承压和流动性稳定性，当前公开底座未接入。",
            "required_for_signal",
        )
        add_missing("seven_day_annualized_yield", "七日年化收益率", "当前 provider 未接入货币基金收益专项接口", "货币基金观察/比较")
        add_missing("income_per_10k", "万份收益", "当前 provider 未接入每日万份收益字段", "货币基金收益解释")
        add_missing("fund_size_liquidity", "规模/流动性", "当前未接入货币基金规模、申赎流动性和偏离度指标", "货币基金风险边界")
        not_applicable_metrics.extend([
            {
                "key": "active_equity_return_momentum",
                "label": "主动权益多周期收益动量",
                "reason": "货币基金以现金管理和流动性为主，不应据股票/混合基金收益动量生成买卖建议。",
            },
            {
                "key": "active_equity_drawdown_stop",
                "label": "主动权益回撤止损阈值",
                "reason": "货币基金净值/收益呈现方式不同，回撤止损阈值不能替代七日年化、万份收益和流动性检查。",
            },
        ])
    elif family == "bond_income":
        add_primary(
            "max_drawdown_1y_pct",
            "近 1 年最大回撤",
            metrics.get("max_drawdown_1y_pct"),
            risk_source,
            "债基需优先观察回撤修复和净值稳定性。",
            "core",
            estimated=risk_is_estimated and metrics.get("max_drawdown_1y_pct") is not None,
        )
        add_primary(
            "volatility_1y_pct",
            "近 1 年年化波动",
            metrics.get("volatility_1y_pct"),
            risk_source,
            "固收产品的波动阈值应显著低于权益基金。",
            "core",
            estimated=risk_is_estimated and metrics.get("volatility_1y_pct") is not None,
        )
        add_primary(
            "one_year_return_pct",
            "近 1 年收益",
            returns.get("1y"),
            metric_sources.get("returns"),
            "收益只作为票息/资本利得结果，不足以解释久期和信用暴露。",
            "supporting",
        )
        add_missing("duration", "久期", "当前未接入组合久期或重仓债券期限结构", "利率风险解释")
        add_missing("credit_risk", "信用风险", "当前未接入债券评级、信用利差或违约风险暴露", "信用风险解释")
        add_missing("interest_rate_risk", "利率风险", "当前未接入利率曲线、债券指数或久期敏感度", "债基择时/风控")
        not_applicable_metrics.append({
            "key": "active_equity_industry_rotation",
            "label": "主动权益行业轮动",
            "reason": "债基核心风险来自利率、信用和久期，不能用权益行业景气替代。",
        })
    elif family == "index_beta":
        add_primary(
            "tracking_error",
            "跟踪误差",
            None,
            None,
            "指数/ETF/联接基金需要确认净值相对标的指数的偏离。",
            "required_for_signal",
        )
        add_primary(
            "tracked_index_name",
            "跟踪指数名称",
            None,
            None,
            "需要明确标的指数后，才能解释估值、行业暴露和 beta 风格。",
            "required_for_signal",
        )
        add_primary(
            "index_valuation_percentile",
            "指数估值分位",
            None,
            None,
            "指数基金更依赖标的指数估值，而不是基金经理主动选股分位。",
            "required_for_signal",
        )
        add_primary(
            "one_year_return_pct",
            "近 1 年收益",
            returns.get("1y"),
            metric_sources.get("returns"),
            "用于观察 beta 暴露结果，但不能替代跟踪误差和指数估值。",
            "supporting",
        )
        add_missing("tracking_error", "跟踪误差", "当前未接入基金净值相对标的指数的偏离序列", "ETF/联接质量检查")
        add_missing("tracked_index_name", "跟踪指数名称", "当前未接入招募说明书/基金合同中的标的指数结构化字段", "指数估值与风格解释")
        add_missing("index_valuation_percentile", "指数估值分位", "当前未把具体标的指数映射到估值分位", "指数择时解释")
        not_applicable_metrics.append({
            "key": "active_manager_alpha",
            "label": "主动管理 alpha",
            "reason": "指数基金目标是跟踪标的指数，应优先解释 beta、估值和跟踪误差。",
        })
    elif family == "qdii_global":
        add_primary(
            "global_market_exposure",
            "海外市场暴露",
            None,
            None,
            "QDII 需要知道主要海外市场/资产类别，才能解释涨跌来源。",
            "required_for_signal",
        )
        add_primary(
            "fx_exposure",
            "汇率暴露",
            None,
            None,
            "人民币汇率变化会影响 QDII 净值解释。",
            "required_for_signal",
        )
        add_primary(
            "nav_delay_status",
            "净值延迟",
            None,
            None,
            "跨市场交易日和时区会造成净值确认延迟。",
            "required_for_signal",
        )
        add_primary(
            "max_drawdown_1y_pct",
            "近 1 年最大回撤",
            metrics.get("max_drawdown_1y_pct"),
            risk_source,
            "仅作为净值结果风险，不能替代海外市场与汇率解释。",
            "supporting",
            estimated=risk_is_estimated and metrics.get("max_drawdown_1y_pct") is not None,
        )
        add_missing("global_market_exposure", "海外市场暴露", "当前未接入 QDII 标的市场/资产配置结构化字段", "海外市场解释")
        add_missing("fx_exposure", "汇率暴露", "当前未接入汇率影响或币种暴露", "QDII 风险解释")
        add_missing("nav_delay_status", "净值延迟", "当前未接入跨境净值确认延迟和交易日差异", "QDII 新鲜度边界")
        add_missing("qdii_subscription_quota", "申赎额度/额度限制", "当前未接入 QDII 申购额度、赎回限制或额度耗尽状态", "QDII 申赎可执行性边界")
        not_applicable_metrics.append({
            "key": "domestic_equity_peer_rank_only",
            "label": "单纯境内权益同类分位",
            "reason": "QDII 需要叠加海外市场、汇率和净值时差，不能只按境内主动权益分位解释。",
        })
    elif family == "fof_allocation":
        add_primary(
            "underlying_fund_lookthrough",
            "底层基金穿透",
            None,
            None,
            "FOF 需要穿透底层基金，才能判断真实资产和风格暴露。",
            "required_for_signal",
        )
        add_primary(
            "manager_allocation",
            "管理人配置",
            None,
            None,
            "FOF 的解释重点是管理人如何做大类资产和基金筛选配置。",
            "required_for_signal",
        )
        add_primary(
            "max_drawdown_1y_pct",
            "近 1 年最大回撤",
            metrics.get("max_drawdown_1y_pct"),
            risk_source,
            "组合回撤是结果指标，但不足以解释底层持仓来源。",
            "core",
            estimated=risk_is_estimated and metrics.get("max_drawdown_1y_pct") is not None,
        )
        add_missing("underlying_fund_lookthrough", "底层基金穿透", "当前未接入 FOF 持有基金明细、权重和风格", "FOF 配置解释")
        add_missing("manager_allocation", "管理人配置", "当前未接入管理人大类资产配置与调仓记录", "FOF 风险来源解释")
        add_missing("asset_allocation_exposure", "资产配置比例/大类资产暴露", "当前未接入 FOF 大类资产配置比例、区域或风格暴露", "FOF 配置解释")
        not_applicable_metrics.append({
            "key": "single_fund_stock_holdings",
            "label": "单基金重仓股解释",
            "reason": "FOF 首先需要底层基金穿透，不能直接套用普通主动权益重仓股解释。",
        })
    else:
        add_primary(
            "three_month_return_pct",
            "近 3 月收益",
            returns.get("3m"),
            metric_sources.get("returns"),
            "主动权益/混合基金用于观察中短期收益动量。",
            "core",
        )
        add_primary(
            "one_year_return_pct",
            "近 1 年收益",
            returns.get("1y"),
            metric_sources.get("returns"),
            "主动权益/混合基金用于观察较长周期收益质量。",
            "core",
        )
        add_primary(
            "max_drawdown_1y_pct",
            "近 1 年最大回撤",
            metrics.get("max_drawdown_1y_pct"),
            risk_source,
            "主动权益/混合基金用于衡量净值下行风险。",
            "core",
            estimated=risk_is_estimated and metrics.get("max_drawdown_1y_pct") is not None,
        )
        add_primary(
            "volatility_1y_pct",
            "近 1 年年化波动",
            metrics.get("volatility_1y_pct"),
            risk_source,
            "主动权益/混合基金用于衡量持有体验和仓位波动。",
            "core",
            estimated=risk_is_estimated and metrics.get("volatility_1y_pct") is not None,
        )
        add_primary(
            "peer_one_year_percentile",
            "同类近 1 年分位",
            peer_percentiles.get("1y"),
            "fund_open_fund_rank_em" if isinstance(peer, dict) else None,
            "主动权益/混合基金用于确认相对同类表现。",
            "core",
        )
        if family == "general_fund":
            add_missing("fund_type_taxonomy", "基金类型识别", "当前无法稳定识别基金策略族", "选择专属指标模板")

    for item in primary_metrics:
        if item.get("status") == "missing" and item.get("applicability") == "required_for_signal":
            key = str(item.get("key"))
            if not any(missing.get("key") == key for missing in missing_specialized_metrics):
                add_missing(key, str(item.get("label") or key), "当前公开字段未覆盖该专项指标", "生成分类型信号")

    missing_labels = [item["label"] for item in missing_specialized_metrics]
    limitations = [
        f"缺少专项指标：{', '.join(missing_labels)}" if missing_labels else None,
        "指标画像仅声明适用边界，不自动改写当前信号评分阈值",
    ]
    if family == "money_market":
        limitations.append("货币基金专项收益/流动性未接入前，只能保持 watch，不生成买入/卖出建议")

    return {
        "schema_version": FUND_METRIC_PROFILE_SCHEMA_VERSION,
        "fund_category": family,
        "strategy_family": family,
        "asset_class": asset_class,
        "primary_metrics": primary_metrics,
        "not_applicable_metrics": not_applicable_metrics,
        "missing_specialized_metrics": missing_specialized_metrics,
        "limitations": _compact_strings(limitations),
        "source": "taxonomy_metric_profile_rule_v1",
        "latest_quote_available": bool(latest_quote),
    }


def _percentile_rank(series: pd.Series, latest: Optional[float]) -> Optional[float]:
    if latest is None:
        return None
    values = pd.to_numeric(series, errors="coerce").dropna()
    if values.empty:
        return None
    return round(float((values <= latest).sum()) / float(len(values)) * 100, 1)


def _latest_sorted_frame(df: pd.DataFrame, date_col: str = "日期") -> pd.DataFrame:
    if df.empty or date_col not in df.columns:
        return pd.DataFrame()
    frame = df.copy()
    frame[date_col] = pd.to_datetime(frame[date_col], errors="coerce")
    frame = frame.dropna(subset=[date_col]).sort_values(date_col)
    return frame


def _series_return_pct(frame: pd.DataFrame, value_col: str, periods: int) -> Optional[float]:
    if frame.empty or value_col not in frame.columns or len(frame) <= periods:
        return None
    values = pd.to_numeric(frame[value_col], errors="coerce").dropna()
    if len(values) <= periods:
        return None
    latest = _to_float(values.iloc[-1])
    start = _to_float(values.iloc[-periods - 1])
    if latest is None or start is None or start <= 0:
        return None
    return round((latest / start - 1) * 100, 2)


def select_reference_indices(taxonomy: Dict[str, Any]) -> List[str]:
    family = str(taxonomy.get("strategy_family") or "general_fund")
    symbols = list(REFERENCE_INDEX_PRESETS.get(family, REFERENCE_INDEX_PRESETS["general_fund"]))
    for tag in taxonomy.get("style_tags") or []:
        mapped = STYLE_REFERENCE_INDEX.get(str(tag))
        if mapped and mapped not in symbols:
            symbols.insert(0, mapped)
    return symbols[:3]


def build_index_context(symbol: str, pe_df: pd.DataFrame, pb_df: pd.DataFrame) -> Dict[str, Any]:
    pe_frame = _latest_sorted_frame(pe_df)
    pb_frame = _latest_sorted_frame(pb_df)
    latest_pe = pe_frame.iloc[-1] if not pe_frame.empty else None
    latest_pb = pb_frame.iloc[-1] if not pb_frame.empty else None
    pe_ttm = _to_float(latest_pe.get("滚动市盈率")) if latest_pe is not None else None
    pb = _to_float(latest_pb.get("市净率")) if latest_pb is not None else None
    index_level = _to_float(latest_pe.get("指数")) if latest_pe is not None else None
    pe_percentile = _percentile_rank(pe_frame.tail(1260).get("滚动市盈率", pd.Series(dtype=float)), pe_ttm)
    pb_percentile = _percentile_rank(pb_frame.tail(1260).get("市净率", pd.Series(dtype=float)), pb)
    valuation_percentiles = [value for value in [pe_percentile, pb_percentile] if value is not None]
    valuation_percentile = round(sum(valuation_percentiles) / len(valuation_percentiles), 1) if valuation_percentiles else None
    valuation_state = "unknown"
    if valuation_percentile is not None:
        if valuation_percentile <= 30:
            valuation_state = "low"
        elif valuation_percentile >= 70:
            valuation_state = "high"
        else:
            valuation_state = "neutral"
    return {
        "symbol": symbol,
        "latest_date": latest_pe.get("日期").date().isoformat() if latest_pe is not None and pd.notna(latest_pe.get("日期")) else None,
        "index_level": round(index_level, 2) if index_level is not None else None,
        "return_20d_pct": _series_return_pct(pe_frame, "指数", 20),
        "return_60d_pct": _series_return_pct(pe_frame, "指数", 60),
        "pe_ttm": round(pe_ttm, 2) if pe_ttm is not None else None,
        "pe_percentile_5y": pe_percentile,
        "pb": round(pb, 2) if pb is not None else None,
        "pb_percentile_5y": pb_percentile,
        "valuation_percentile_5y": valuation_percentile,
        "valuation_state": valuation_state,
        "source": ["stock_index_pe_lg", "stock_index_pb_lg"],
    }


def build_style_rotation(indices: List[Dict[str, Any]]) -> Dict[str, Any]:
    ranked = [
        item for item in indices
        if _to_float(item.get("return_20d_pct")) is not None
    ]
    ranked.sort(key=lambda item: _to_float(item.get("return_20d_pct")) or -999, reverse=True)
    if not ranked:
        return {"status": "missing", "leader": None, "dispersion_20d_pct": None}
    returns = [_to_float(item.get("return_20d_pct")) for item in ranked if _to_float(item.get("return_20d_pct")) is not None]
    dispersion = round(max(returns) - min(returns), 2) if len(returns) >= 2 else 0.0
    return {
        "status": "ok",
        "leader": ranked[0].get("symbol"),
        "leader_return_20d_pct": ranked[0].get("return_20d_pct"),
        "dispersion_20d_pct": dispersion,
        "ranking": [
            {
                "symbol": item.get("symbol"),
                "return_20d_pct": item.get("return_20d_pct"),
                "return_60d_pct": item.get("return_60d_pct"),
            }
            for item in ranked
        ],
    }


def normalize_industry_allocation(df: pd.DataFrame) -> Dict[str, Any]:
    if df.empty or "行业类别" not in df.columns:
        return {"status": "missing", "items": [], "source": "fund_portfolio_industry_allocation_em"}
    frame = df.copy()
    if "截止时间" in frame.columns:
        frame["截止时间"] = pd.to_datetime(frame["截止时间"], errors="coerce")
        latest_date = frame["截止时间"].dropna().max()
        if pd.notna(latest_date):
            frame = frame[frame["截止时间"] == latest_date]
    else:
        latest_date = None
    frame["占净值比例"] = frame.get("占净值比例", pd.Series(dtype=float)).map(_to_float)
    frame = frame.dropna(subset=["占净值比例"]).sort_values("占净值比例", ascending=False)
    items = [
        {
            "industry": str(row.get("行业类别") or ""),
            "nav_ratio_pct": round(float(row.get("占净值比例") or 0), 2),
        }
        for _, row in frame.head(5).iterrows()
        if row.get("行业类别")
    ]
    return {
        "status": "ok" if items else "missing",
        "latest_date": latest_date.date().isoformat() if latest_date is not None and pd.notna(latest_date) else None,
        "items": items,
        "source": "fund_portfolio_industry_allocation_em",
    }


def normalize_stock_holdings(df: pd.DataFrame) -> Dict[str, Any]:
    if df.empty or "股票名称" not in df.columns:
        return {"status": "missing", "items": [], "source": "fund_portfolio_hold_em"}
    frame = df.copy()
    if "季度" in frame.columns:
        latest_quarter = str(frame["季度"].dropna().iloc[-1]) if not frame["季度"].dropna().empty else None
        if latest_quarter:
            frame = frame[frame["季度"].astype(str) == latest_quarter]
    else:
        latest_quarter = None
    frame["占净值比例"] = frame.get("占净值比例", pd.Series(dtype=float)).map(_to_float)
    frame = frame.dropna(subset=["占净值比例"]).sort_values("占净值比例", ascending=False)
    items = [
        {
            "stock_code": str(row.get("股票代码") or ""),
            "stock_name": str(row.get("股票名称") or ""),
            "nav_ratio_pct": round(float(row.get("占净值比例") or 0), 2),
            "market_value": _to_float(row.get("持仓市值")),
        }
        for _, row in frame.head(10).iterrows()
        if row.get("股票名称")
    ]
    return {
        "status": "ok" if items else "missing",
        "latest_quarter": latest_quarter,
        "items": items,
        "source": "fund_portfolio_hold_em",
    }


def normalize_fund_reports(df: pd.DataFrame) -> Dict[str, Any]:
    if df.empty or "公告标题" not in df.columns:
        return {"status": "missing", "items": [], "source": "fund_announcement_report_em"}
    frame = df.copy()
    if "公告日期" in frame.columns:
        frame["公告日期"] = pd.to_datetime(frame["公告日期"], errors="coerce")
        frame = frame.sort_values("公告日期", ascending=False)
    items = [
        {
            "title": str(row.get("公告标题") or ""),
            "date": row.get("公告日期").date().isoformat() if pd.notna(row.get("公告日期")) else None,
            "report_id": str(row.get("报告ID") or "") or None,
        }
        for _, row in frame.head(5).iterrows()
        if row.get("公告标题")
    ]
    return {
        "status": "ok" if items else "missing",
        "items": items,
        "source": "fund_announcement_report_em",
    }


def normalize_fee_table(df: pd.DataFrame) -> List[Dict[str, Any]]:
    if df.empty:
        return []
    items = []
    for row in df.head(20).to_dict(orient="records"):
        normalized = {}
        for key, value in row.items():
            if value is None:
                continue
            normalized[str(key)] = str(value)
        if normalized:
            items.append(normalized)
    return items


def _fee_rate_from_row(row: Dict[str, Any], *, preferred_labels: Optional[List[str]] = None) -> Optional[float]:
    preferred_labels = preferred_labels or []
    candidates: List[Any] = []
    for key, value in row.items():
        key_text = str(key)
        if any(label in key_text for label in preferred_labels):
            candidates.append(value)
    for key, value in row.items():
        key_text = str(key)
        if "费率" in key_text or "手续费" in key_text:
            candidates.append(value)
    for value in candidates:
        fee = _to_float(value)
        if fee is not None and 0 <= fee <= 100:
            return fee
    return None


def _fee_condition_from_row(row: Dict[str, Any], *, preferred_labels: List[str], fallback: str) -> Optional[str]:
    for label in preferred_labels:
        for key, value in row.items():
            if label in str(key) and str(value or "").strip():
                return str(value).strip()
    for key, value in row.items():
        key_text = str(key)
        if "费率" in key_text or "手续费" in key_text:
            continue
        text = str(value or "").strip()
        if text:
            return text
    return fallback


def _build_subscription_fee_model(
    rows: List[Dict[str, Any]],
    *,
    front_fee: Optional[float],
) -> Dict[str, Any]:
    tiers: List[Dict[str, Any]] = []
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            continue
        rate = _fee_rate_from_row(row)
        if rate is None:
            continue
        tiers.append({
            "index": index + 1,
            "amount_range": _fee_condition_from_row(row, preferred_labels=["购买金额", "申购金额", "适用金额"], fallback=f"第 {index + 1} 档"),
            "rate_pct": round(rate, 4),
            "raw": row,
        })
    tier_rates = [float(item["rate_pct"]) for item in tiers]
    first_tier_rate = tier_rates[0] if tier_rates else None
    selected_rate = front_fee if front_fee is not None else first_tier_rate
    source = None
    if front_fee is not None:
        source = "fund_purchase_em.front_fee"
    elif first_tier_rate is not None:
        source = "fund_fee_em.申购费率.first_tier"
    limitations = []
    if not tiers:
        limitations.append("申购费率分段表不可用，无法展示金额分档")
    return {
        "available": selected_rate is not None,
        "tiers_available": bool(tiers),
        "tiers": tiers,
        "front_fee_pct": round(front_fee, 4) if front_fee is not None else None,
        "first_tier_rate_pct": round(first_tier_rate, 4) if first_tier_rate is not None else None,
        "lowest_rate_pct": round(min(tier_rates), 4) if tier_rates else None,
        "highest_rate_pct": round(max(tier_rates), 4) if tier_rates else None,
        "selected_rate_pct": round(selected_rate, 4) if selected_rate is not None else None,
        "selection_policy": "use_front_fee_when_available_else_first_public_subscription_tier",
        "source": source,
        "limitations": limitations,
    }


def _build_redemption_fee_model(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    tiers: List[Dict[str, Any]] = []
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            continue
        rate = _fee_rate_from_row(row)
        if rate is None:
            continue
        tiers.append({
            "index": index + 1,
            "holding_period": _fee_condition_from_row(row, preferred_labels=["持有期限", "持有时间", "持有期"], fallback=f"第 {index + 1} 档"),
            "rate_pct": round(rate, 4),
            "raw": row,
        })
    tier_rates = [float(item["rate_pct"]) for item in tiers]
    limitations = []
    if not tiers:
        limitations.append("赎回费率持有期分段表不可用，回测无法区分真实持有期")
    return {
        "available": bool(tiers),
        "tiers_available": bool(tiers),
        "tiers": tiers,
        "conservative_rate_pct": round(max(tier_rates), 4) if tier_rates else None,
        "lowest_rate_pct": round(min(tier_rates), 4) if tier_rates else None,
        "selection_policy": "use_highest_public_redemption_rate_as_conservative_backtest_assumption",
        "source": "fund_fee_em.赎回费率" if tiers else None,
        "limitations": limitations,
    }


def _annual_expense_key(label: str) -> Optional[str]:
    text = str(label or "")
    if "管理" in text:
        return "management_fee_pct"
    if "托管" in text:
        return "custody_fee_pct"
    if "销售服务" in text or ("销售" in text and "服务" in text):
        return "sales_service_fee_pct"
    return None


def _build_annual_expense_model(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    expense: Dict[str, Any] = {
        "available": False,
        "items": [],
        "source": None,
    }
    for row in rows:
        if not isinstance(row, dict):
            continue
        row_type_text = " ".join(str(value or "") for value in row.values())
        row_key_text = " ".join(str(key or "") for key in row.keys())
        for key, value in row.items():
            expense_key = _annual_expense_key(str(key))
            if expense_key is None:
                continue
            rate = _to_float(value)
            if rate is not None and 0 <= rate <= 100:
                expense[expense_key] = round(rate, 4)
                expense["items"].append({"type": expense_key, "rate_pct": round(rate, 4), "raw": row})
        expense_key = _annual_expense_key(row_type_text or row_key_text)
        if expense_key is None:
            continue
        rate = _fee_rate_from_row(row, preferred_labels=["费率", "比例"])
        if rate is not None:
            expense[expense_key] = round(rate, 4)
            expense["items"].append({"type": expense_key, "rate_pct": round(rate, 4), "raw": row})
    if expense["items"]:
        expense["available"] = True
        expense["source"] = "fund_fee_em.运作费率"
    return expense


def build_fee_model(
    *,
    front_fee: Optional[float],
    subscription_fee: List[Dict[str, Any]],
    redemption_fee: List[Dict[str, Any]],
    annual_expense_fee: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    annual_expense_fee = annual_expense_fee or []
    subscription = _build_subscription_fee_model(subscription_fee, front_fee=front_fee)
    redemption = _build_redemption_fee_model(redemption_fee)
    annual_expense = _build_annual_expense_model(annual_expense_fee)
    fees_estimated = not (subscription.get("selected_rate_pct") is not None and redemption.get("conservative_rate_pct") is not None)
    limitations = _compact_unique_strings(
        list(subscription.get("limitations") or [])
        + list(redemption.get("limitations") or [])
        + (["管理费/托管费/销售服务费未从公开费率表解析到"] if not annual_expense.get("available") else [])
    )
    if fees_estimated:
        limitations.append("回测费用假设仍不完整，缺失项按 0% 处理")
    status = "ok" if not fees_estimated else ("partial" if subscription.get("available") or redemption.get("available") else "missing")
    return {
        "schema_version": "fund_fee_model_v1",
        "status": status,
        "subscription": subscription,
        "redemption": redemption,
        "annual_expense": annual_expense,
        "fees_estimated": fees_estimated,
        "source": ["fund_purchase_em", "fund_fee_em", "fund_open_fund_daily_em"],
        "limitations": limitations,
        "boundary": "公开费率分段为最近快照；不等同于个人账户、销售渠道优惠或历史逐日真实费率。",
    }


def normalize_purchase_row(df: pd.DataFrame, code: str) -> Dict[str, Any]:
    if df.empty or "基金代码" not in df.columns:
        return {}
    frame = df.copy()
    frame["基金代码"] = frame["基金代码"].astype(str).str.zfill(6)
    rows = frame[frame["基金代码"] == code]
    if rows.empty:
        return {}
    row = rows.iloc[0]
    return {
        "purchase_status": str(row.get("申购状态") or "") or None,
        "redemption_status": str(row.get("赎回状态") or "") or None,
        "next_open_date": str(row.get("下一开放日") or "") or None,
        "min_purchase_amount": _to_float(row.get("购买起点")),
        "daily_limit_amount": _to_float(row.get("日累计限定金额")),
        "front_fee": _to_float(row.get("手续费")),
        "source": "fund_purchase_em",
    }


def build_trading_rules(
    *,
    code: str,
    latest_quote: Optional[FundLatestQuote],
    purchase_row: Dict[str, Any],
    subscription_fee: List[Dict[str, Any]],
    redemption_fee: List[Dict[str, Any]],
    annual_expense_fee: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    limitations = []
    purchase_status = purchase_row.get("purchase_status") or (latest_quote.purchase_status if latest_quote else None)
    redemption_status = purchase_row.get("redemption_status") or (latest_quote.redemption_status if latest_quote else None)
    front_fee = purchase_row.get("front_fee")
    if front_fee is None and latest_quote and latest_quote.fee:
        front_fee = _to_float(latest_quote.fee)
    fee_model = build_fee_model(
        front_fee=front_fee,
        subscription_fee=subscription_fee,
        redemption_fee=redemption_fee,
        annual_expense_fee=annual_expense_fee,
    )
    if not purchase_row:
        limitations.append("申购状态/购买起点表未命中该基金")
    if not subscription_fee:
        limitations.append("申购费率表暂不可用或该基金未披露")
    if not redemption_fee:
        limitations.append("赎回费率表暂不可用")
    status = "ok" if purchase_status or redemption_status or subscription_fee or redemption_fee else "missing"
    if limitations and status == "ok":
        status = "partial"
    return {
        "code": code,
        "status": status,
        "purchase_status": purchase_status,
        "redemption_status": redemption_status,
        "next_open_date": purchase_row.get("next_open_date"),
        "min_purchase_amount": purchase_row.get("min_purchase_amount"),
        "daily_limit_amount": purchase_row.get("daily_limit_amount"),
        "front_fee": front_fee,
        "fee_tables": {
            "subscription": subscription_fee,
            "redemption": redemption_fee,
            "annual_expense": annual_expense_fee or [],
        },
        "fee_model": fee_model,
        "source": ["fund_purchase_em", "fund_fee_em", "fund_open_fund_daily_em"],
        "limitations": _compact_unique_strings(limitations),
    }


def build_market_context(
    *,
    taxonomy: Dict[str, Any],
    metrics: Dict[str, Any],
    peer: Optional[Dict[str, Any]],
    market_snapshot: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Build a truthful market-context layer from currently available public/proxy fields."""
    returns = metrics.get("returns") if isinstance(metrics.get("returns"), dict) else {}
    peer_percentiles = peer.get("percentiles") if isinstance(peer, dict) and isinstance(peer.get("percentiles"), dict) else {}
    trend = str(metrics.get("trend_state") or "unknown")
    r_3m = _to_float(returns.get("3m"))
    r_6m = _to_float(returns.get("6m"))
    peer_1y = _to_float(peer_percentiles.get("1y")) if isinstance(peer_percentiles, dict) else None
    volatility = _to_float(metrics.get("volatility_1y_pct"))
    drawdown = _to_float(metrics.get("max_drawdown_1y_pct"))
    available_proxies: List[str] = []
    market_snapshot = market_snapshot or {}
    index_context = market_snapshot.get("index_context") if isinstance(market_snapshot.get("index_context"), list) else []
    style_rotation = market_snapshot.get("style_rotation") if isinstance(market_snapshot.get("style_rotation"), dict) else {}
    industry_allocation = market_snapshot.get("industry_allocation") if isinstance(market_snapshot.get("industry_allocation"), dict) else {}
    stock_holdings = market_snapshot.get("stock_holdings") if isinstance(market_snapshot.get("stock_holdings"), dict) else {}
    fund_reports = market_snapshot.get("fund_reports") if isinstance(market_snapshot.get("fund_reports"), dict) else {}
    provider_limitations = market_snapshot.get("limitations") if isinstance(market_snapshot.get("limitations"), list) else []

    if trend != "unknown":
        available_proxies.append("基金自身净值趋势")
    if r_3m is not None or r_6m is not None:
        available_proxies.append("阶段收益动量")
    if peer_1y is not None:
        available_proxies.append("同类近 1 年分位")
    if volatility is not None or drawdown is not None:
        available_proxies.append("基金自身风险状态")
    if index_context:
        available_proxies.append("宽基/风格指数趋势")
    if any(item.get("valuation_percentile_5y") is not None for item in index_context if isinstance(item, dict)):
        available_proxies.append("指数 PE/PB 估值分位")
    if industry_allocation.get("items"):
        available_proxies.append("基金持仓行业配置")
    if stock_holdings.get("items"):
        available_proxies.append("基金重仓股")
    if fund_reports.get("items"):
        available_proxies.append("基金定期报告")

    regime_hint = "neutral"
    if drawdown is not None and drawdown <= -20:
        regime_hint = "drawdown_pressure"
    elif trend == "downtrend" or (r_3m is not None and r_3m < -8):
        regime_hint = "risk_off"
    elif trend == "uptrend" and (r_3m is not None and r_3m > 5) and (peer_1y is None or peer_1y >= 60):
        regime_hint = "momentum_tailwind"
    elif volatility is not None and volatility >= 35:
        regime_hint = "high_volatility"

    missing_inputs = list(taxonomy.get("market_context_needs") or [])
    if available_proxies:
        missing_inputs = [
            item
            for item in missing_inputs
            if item not in {"同类基金收益分位", "基金自身净值趋势"}
        ]
    confidence = "low"
    if index_context and style_rotation.get("status") == "ok":
        confidence = "medium"
    elif len(available_proxies) >= 3 and peer_1y is not None:
        confidence = "medium"
    status = "ok" if index_context else ("proxy_only" if available_proxies else "missing")

    return {
        "schema_version": MARKET_CONTEXT_SCHEMA_VERSION,
        "status": status,
        "confidence": confidence,
        "regime_hint": regime_hint,
        "available_proxies": available_proxies,
        "missing_inputs": missing_inputs,
        "source": "akshare_market_context" if index_context else ("fund_nav_and_peer_rank_proxy" if available_proxies else None),
        "reference_indices": index_context,
        "style_rotation": style_rotation,
        "industry_allocation": industry_allocation,
        "stock_holdings": stock_holdings,
        "fund_reports": fund_reports,
        "limitations": provider_limitations,
        "notes": "市场上下文已优先使用公开指数估值和基金持仓行业配置；仍未接入付费研报、实时仓位或非公开投顾观点。",
    }


def build_data_quality_detail(
    *,
    code: str,
    name: Optional[str],
    fund_type: Optional[str],
    metrics: Dict[str, Any],
    peer: Optional[Dict[str, Any]],
    latest_quote: Optional[FundLatestQuote],
    risk_analysis: Optional[Dict[str, Any]],
    market_context: Optional[Dict[str, Any]],
    research_evidence: Optional[Dict[str, Any]],
    trading_rules: Optional[Dict[str, Any]],
    limitations: List[str],
) -> Dict[str, Any]:
    """Build the canonical, versioned fund data-quality contract."""
    returns = metrics.get("returns") if isinstance(metrics.get("returns"), dict) else {}
    peer_percentiles = peer.get("percentiles") if isinstance(peer, dict) and isinstance(peer.get("percentiles"), dict) else {}
    metric_sources = metrics.get("metric_sources") if isinstance(metrics.get("metric_sources"), dict) else {}
    dimensions: List[Dict[str, Any]] = []

    def add_dimension(
        *,
        key: str,
        label: str,
        status: str,
        source: Optional[str],
        as_of: Optional[Any] = None,
        reason: Optional[str] = None,
        notes: Optional[List[str]] = None,
        sample_count: Optional[int] = None,
        field_count: Optional[int] = None,
    ) -> None:
        item: Dict[str, Any] = {
            "key": key,
            "label": label,
            "status": status,
            "source": source,
            "as_of": _iso_date(as_of),
            "date": _iso_date(as_of),
            "reason": reason,
            "notes": notes or [],
        }
        if sample_count is not None:
            item["sample_count"] = int(sample_count)
        if field_count is not None:
            item["field_count"] = int(field_count)
        dimensions.append(item)

    metadata_fields = _compact_strings([code, name, fund_type])
    metadata_status = "ok" if name and fund_type else "partial"
    add_dimension(
        key="metadata",
        label="基金基础信息",
        status=metadata_status,
        source="fund_name_em",
        reason=None if metadata_status == "ok" else "基金名称或类型字段不完整",
        field_count=len(metadata_fields),
    )

    latest_field_count = 0
    latest_status = "missing"
    latest_source = None
    latest_as_of: Optional[Any] = None
    latest_reason = "最新净值日榜未返回可用单位净值"
    latest_notes: List[str] = []
    if latest_quote and latest_quote.unit_nav is not None:
        latest_field_count = len(_compact_strings([
            "unit_nav" if latest_quote.unit_nav is not None else None,
            "accumulated_nav" if latest_quote.accumulated_nav is not None else None,
            "daily_growth_pct" if latest_quote.daily_growth_pct is not None else None,
            "purchase_status" if latest_quote.purchase_status else None,
            "redemption_status" if latest_quote.redemption_status else None,
            "fee" if latest_quote.fee else None,
        ]))
        latest_status = "ok"
        latest_source = latest_quote.source or "fund_open_fund_daily_em"
        latest_as_of = latest_quote.nav_date or metrics.get("latest_date")
        latest_reason = None
        future_days = _future_date_days(latest_as_of)
        age_days = _date_age_days(latest_as_of)
        if future_days is not None:
            latest_status = "partial"
            latest_reason = f"最新净值日期晚于今天 {future_days} 天"
        elif age_days is not None and age_days > 14:
            latest_status = "stale"
            latest_reason = f"最新净值日期距今 {age_days} 天"
    elif metrics.get("latest_nav") is not None:
        latest_field_count = 1
        latest_status = "estimated"
        latest_source = "fund_open_fund_info_em/nav_history"
        latest_as_of = metrics.get("latest_date")
        latest_reason = "最新净值日榜不可用，使用本地历史净值末条近似"
        latest_notes.append("不能等同于当日公开日榜")
    add_dimension(
        key="latest_nav",
        label="最新净值",
        status=latest_status,
        source=latest_source,
        as_of=latest_as_of,
        reason=latest_reason,
        notes=latest_notes,
        field_count=latest_field_count,
    )

    sample_days = int(metrics.get("sample_days") or 0)
    nav_status = "missing"
    nav_reason = "本地暂无历史净值样本"
    if sample_days >= 252:
        nav_status = "ok"
        nav_reason = None
    elif sample_days >= 60:
        nav_status = "partial"
        nav_reason = "历史净值样本不足 252 条，长期风险/回测仍需谨慎"
    elif sample_days > 0:
        nav_status = "partial"
        nav_reason = "历史净值样本不足 60 条，风险指标参考价值有限"
    latest_history_date = metrics.get("latest_date")
    future_days = _future_date_days(latest_history_date)
    age_days = _date_age_days(latest_history_date)
    if nav_status in {"ok", "partial"} and future_days is not None:
        nav_status = "partial"
        nav_reason = f"历史净值末条日期晚于今天 {future_days} 天"
    elif nav_status in {"ok", "partial"} and age_days is not None and age_days > 30:
        nav_status = "stale"
        nav_reason = f"历史净值末条距今 {age_days} 天"
    add_dimension(
        key="nav_history",
        label="历史净值样本",
        status=nav_status,
        source="fund_open_fund_info_em",
        as_of=latest_history_date,
        reason=nav_reason,
        sample_count=sample_days,
        field_count=len(_compact_strings([
            "latest_nav" if metrics.get("latest_nav") is not None else None,
            "returns" if any(value is not None for value in returns.values()) else None,
            "max_drawdown_1y_pct" if metrics.get("max_drawdown_1y_pct") is not None else None,
            "volatility_1y_pct" if metrics.get("volatility_1y_pct") is not None else None,
        ])),
    )

    peer_returns = peer.get("returns") if isinstance(peer, dict) and isinstance(peer.get("returns"), dict) else {}
    peer_field_count = len([value for value in list(peer_returns.values()) + list(peer_percentiles.values()) if value is not None])
    peer_sample_count = int(peer.get("sample_size") or 0) if isinstance(peer, dict) else 0
    peer_as_of = peer.get("date") if isinstance(peer, dict) else None
    if isinstance(peer, dict) and peer_field_count > 0 and peer.get("rank") is not None and peer_sample_count > 0:
        peer_status = "ok"
        peer_reason = None
    elif isinstance(peer, dict) and (peer_field_count > 0 or peer_sample_count > 0):
        peer_status = "partial"
        peer_reason = peer.get("message") or "公开榜单存在，但同类排名/分位字段不完整"
    else:
        peer_status = "missing"
        peer_reason = "公开收益榜单或同类分位不可用"
    peer_future_days = _future_date_days(peer_as_of)
    peer_age_days = _date_age_days(peer_as_of)
    if peer_status in {"ok", "partial"}:
        if peer_future_days is not None:
            peer_status = "partial"
            peer_reason = f"公开榜单日期晚于今天 {peer_future_days} 天"
        elif peer_age_days is None:
            peer_status = "partial"
            peer_reason = "公开榜单日期缺失，无法确认同类分位新鲜度"
        elif peer_age_days > 30:
            peer_status = "stale"
            peer_reason = f"公开榜单日期距今 {peer_age_days} 天"
    add_dimension(
        key="peer_returns_rank",
        label="公开收益榜单/同类分位",
        status=peer_status,
        source="fund_open_fund_rank_em" if isinstance(peer, dict) else None,
        as_of=peer_as_of,
        reason=peer_reason,
        sample_count=peer_sample_count,
        field_count=peer_field_count,
    )

    risk_fields = _compact_strings([
        "max_drawdown_1y_pct" if metrics.get("max_drawdown_1y_pct") is not None else None,
        "volatility_1y_pct" if metrics.get("volatility_1y_pct") is not None else None,
        "sharpe_1y" if metrics.get("sharpe_1y") is not None else None,
        "peer_risk_return_ratio" if metrics.get("peer_risk_return_ratio") is not None else None,
        "peer_anti_volatility" if metrics.get("peer_anti_volatility") is not None else None,
    ])
    published_risk_fields = [
        key for key in ("max_drawdown_1y_pct", "volatility_1y_pct", "sharpe_1y", "peer_risk_return_ratio", "peer_anti_volatility")
        if isinstance(risk_analysis, dict) and risk_analysis.get(key) is not None
    ]
    if len(published_risk_fields) >= 3:
        risk_status = "ok"
        risk_source = str(risk_analysis.get("source") or "fund_individual_analysis_xq")
        risk_reason = None
    elif risk_fields:
        risk_status = "estimated"
        risk_source = metric_sources.get("risk") or "nav_calculation"
        risk_reason = "平台风险接口不可用或字段不足，风险指标使用本地净值估算"
    else:
        risk_status = "missing"
        risk_source = metric_sources.get("risk")
        risk_reason = "风险指标和可估算净值样本均不足"
    add_dimension(
        key="risk_metrics",
        label="风险指标",
        status=risk_status,
        source=risk_source,
        as_of=metrics.get("latest_date"),
        reason=risk_reason,
        field_count=len(risk_fields),
    )

    trading_rules = trading_rules if isinstance(trading_rules, dict) else {}
    fee_tables = trading_rules.get("fee_tables") if isinstance(trading_rules.get("fee_tables"), dict) else {}
    fee_model = trading_rules.get("fee_model") if isinstance(trading_rules.get("fee_model"), dict) else {}
    annual_expense = fee_model.get("annual_expense") if isinstance(fee_model.get("annual_expense"), dict) else {}
    has_subscription_fee = bool(fee_tables.get("subscription"))
    has_redemption_fee = bool(fee_tables.get("redemption"))
    trading_fields = _compact_strings([
        "purchase_status" if trading_rules.get("purchase_status") else None,
        "redemption_status" if trading_rules.get("redemption_status") else None,
        "min_purchase_amount" if trading_rules.get("min_purchase_amount") is not None else None,
        "daily_limit_amount" if trading_rules.get("daily_limit_amount") is not None else None,
        "front_fee" if trading_rules.get("front_fee") is not None else None,
        "subscription_fee" if has_subscription_fee else None,
        "redemption_fee" if has_redemption_fee else None,
        "fee_model" if fee_model else None,
        "annual_expense" if annual_expense.get("available") else None,
    ])
    trading_status = str(trading_rules.get("status") or "missing")
    trading_notes = list(trading_rules.get("limitations") or [])
    if trading_status == "ok" and not (has_subscription_fee and has_redemption_fee):
        trading_status = "partial"
        trading_notes.append("申购/赎回费率表未完整覆盖")
    add_dimension(
        key="trading_rules_fees",
        label="交易规则/费率",
        status=trading_status if trading_status in {"ok", "partial", "missing", "stale", "estimated"} else "partial",
        source="fund_purchase_em/fund_fee_em/fund_open_fund_daily_em" if trading_fields else None,
        reason=None if trading_status == "ok" else "交易规则或费率字段未完整覆盖",
        notes=_compact_unique_strings(trading_notes),
        field_count=len(trading_fields),
    )

    market_context = market_context if isinstance(market_context, dict) else {}
    industry_allocation = market_context.get("industry_allocation") if isinstance(market_context.get("industry_allocation"), dict) else {}
    stock_holdings = market_context.get("stock_holdings") if isinstance(market_context.get("stock_holdings"), dict) else {}
    fund_reports = market_context.get("fund_reports") if isinstance(market_context.get("fund_reports"), dict) else {}
    research_categories = research_evidence.get("categories") if isinstance(research_evidence, dict) and isinstance(research_evidence.get("categories"), dict) else {}
    connected_news_categories = [
        key for key in ("industry_news", "holding_company_news", "macro_market_news")
        if isinstance(research_categories.get(key), dict) and research_categories[key].get("items")
    ]
    evidence_fields = _compact_strings([
        "industry_allocation" if industry_allocation.get("items") else None,
        "stock_holdings" if stock_holdings.get("items") else None,
        "fund_reports" if fund_reports.get("items") else None,
        "news_evidence" if connected_news_categories else None,
    ])
    raw_report_dates = [
        item.get("date")
        for item in (fund_reports.get("items") or [])
        if isinstance(item, dict)
    ]
    report_dates = [
        _iso_date(value)
        for value in raw_report_dates
        if _iso_date(value)
    ]
    evidence_dates = _compact_strings([
        industry_allocation.get("latest_date") if industry_allocation.get("items") else None,
        stock_holdings.get("latest_date") if stock_holdings.get("items") else None,
        stock_holdings.get("as_of") if stock_holdings.get("items") else None,
        *report_dates,
    ])
    evidence_as_of = _latest_iso_date(evidence_dates)
    evidence_ages = [_date_age_days(value) for value in evidence_dates]
    known_evidence_ages = [age for age in evidence_ages if age is not None]
    future_evidence_dates = [value for value in evidence_dates if _future_date_days(value) is not None]
    has_fresh_dated_evidence = any(
        age <= 365 and _future_date_days(value) is None
        for value, age in zip(evidence_dates, evidence_ages)
        if age is not None
    )
    has_stale_dated_evidence = any(age > 365 for age in known_evidence_ages)
    unknown_dated_evidence = _compact_strings([
        "industry_allocation" if industry_allocation.get("items") and not _iso_date(industry_allocation.get("latest_date")) else None,
        "stock_holdings" if stock_holdings.get("items") and not (_iso_date(stock_holdings.get("latest_date")) or _iso_date(stock_holdings.get("as_of"))) else None,
        "fund_reports" if fund_reports.get("items") and not report_dates else None,
    ])
    if len(evidence_fields) >= 4:
        evidence_status = "ok"
        evidence_reason = None
    elif evidence_fields:
        evidence_status = "partial"
        evidence_reason = "持仓/报告/资讯佐证未完整覆盖"
    else:
        evidence_status = "missing"
        evidence_reason = "持仓、行业、报告和资讯佐证均不可用"
    evidence_notes = []
    if evidence_fields and future_evidence_dates and not has_fresh_dated_evidence:
        evidence_status = "partial"
        evidence_reason = "持仓/行业/报告佐证日期晚于今天，无法确认新鲜度"
    elif evidence_status == "ok" and future_evidence_dates:
        evidence_status = "partial"
        evidence_reason = "部分持仓/行业/报告佐证日期晚于今天，无法确认新鲜度"
    elif evidence_fields and has_stale_dated_evidence and not has_fresh_dated_evidence:
        evidence_status = "stale"
        evidence_reason = "最新持仓/行业/报告佐证距今超过 365 天"
    elif evidence_fields and has_stale_dated_evidence:
        evidence_status = "partial"
        evidence_reason = "部分持仓/行业/报告佐证距今超过 365 天"
    elif evidence_status == "ok" and unknown_dated_evidence:
        evidence_status = "partial"
        evidence_reason = "部分持仓/行业/报告佐证缺少日期，无法确认新鲜度"
    elif evidence_fields and unknown_dated_evidence and not has_fresh_dated_evidence:
        evidence_status = "partial"
        evidence_reason = "持仓/行业/报告佐证缺少日期，无法确认新鲜度"
    if unknown_dated_evidence:
        evidence_notes.append(f"日期未知的佐证：{', '.join(unknown_dated_evidence)}")
    if future_evidence_dates:
        evidence_notes.append("日期晚于今天的佐证不可作为新鲜数据")
    if not connected_news_categories:
        evidence_notes.append("本地资讯源未命中或未配置，新闻/宏观佐证不可用")
    add_dimension(
        key="holdings_reports_news",
        label="持仓/行业/报告/资讯佐证",
        status=evidence_status,
        source="fund_portfolio_industry_allocation_em/fund_portfolio_hold_em/fund_announcement_report_em/intelligence_repository",
        as_of=evidence_as_of,
        reason=evidence_reason,
        notes=evidence_notes,
        sample_count=sum(len(item.get("items") or []) for item in (industry_allocation, stock_holdings, fund_reports) if isinstance(item, dict)),
        field_count=len(evidence_fields),
    )

    weights = {
        "metadata": 8.0,
        "latest_nav": 14.0,
        "nav_history": 18.0,
        "peer_returns_rank": 16.0,
        "risk_metrics": 16.0,
        "trading_rules_fees": 12.0,
        "holdings_reports_news": 16.0,
    }
    quality_score = round(sum(weights.get(item["key"], 0.0) * _quality_factor(str(item.get("status"))) for item in dimensions), 1)

    blocking_issues: List[str] = []
    warnings: List[str] = []
    for item in dimensions:
        status = str(item.get("status") or "")
        key = str(item.get("key") or "")
        label = str(item.get("label") or key)
        reason = str(item.get("reason") or "")
        if key in {"latest_nav", "nav_history", "peer_returns_rank", "risk_metrics"} and status == "missing":
            blocking_issues.append(f"{label}缺失：{reason}")
        elif key == "nav_history" and status in {"partial", "stale"} and int(item.get("sample_count") or 0) < 60:
            blocking_issues.append(f"{label}不足：{reason}")
        elif status in {"partial", "stale", "estimated", "missing"}:
            warnings.append(f"{label}{status}：{reason}" if reason else f"{label}{status}")
        for note in item.get("notes") or []:
            warnings.append(str(note))
    warnings.extend(limitations)
    blocking_issues = _compact_unique_strings(blocking_issues)
    warnings = _compact_unique_strings(warnings)

    statuses = {str(item.get("status")) for item in dimensions}
    if blocking_issues and quality_score < 35:
        overall_status = "missing"
    elif blocking_issues:
        overall_status = "partial"
    elif "stale" in statuses:
        overall_status = "stale"
    elif statuses == {"ok"}:
        overall_status = "ok"
    elif statuses <= {"ok", "estimated"}:
        overall_status = "estimated"
    else:
        overall_status = "partial"

    return {
        "schema_version": FUND_DATA_QUALITY_SCHEMA_VERSION,
        "code": code,
        "overall_status": overall_status,
        "quality_score": min(max(quality_score, 0.0), 100.0),
        "dimensions": dimensions,
        "blocking_issues": blocking_issues,
        "warnings": warnings,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
    }


def build_data_coverage(
    *,
    metrics: Dict[str, Any],
    peer: Optional[Dict[str, Any]],
    latest_quote: Optional[FundLatestQuote],
    risk_analysis: Optional[Dict[str, Any]],
    market_context: Optional[Dict[str, Any]],
    research_evidence: Optional[Dict[str, Any]],
    trading_rules: Optional[Dict[str, Any]],
    limitations: List[str],
) -> Dict[str, Any]:
    returns = metrics.get("returns") if isinstance(metrics.get("returns"), dict) else {}
    metric_sources = metrics.get("metric_sources") if isinstance(metrics.get("metric_sources"), dict) else {}
    has_nav_history = bool(metrics.get("sample_days") and metrics.get("sample_days", 0) >= 60)
    dimensions = [
        {
            "key": "metadata",
            "label": "基金基础信息",
            "status": "ok",
            "source": "fund_name_em",
        },
        {
            "key": "latest_quote",
            "label": "最新净值/交易状态",
            "status": "ok" if latest_quote else "partial",
            "source": "fund_open_fund_daily_em" if latest_quote else None,
            "freshness": latest_quote.nav_date.isoformat() if latest_quote and latest_quote.nav_date else metrics.get("latest_date"),
        },
        {
            "key": "returns_rank",
            "label": "多周期收益榜单",
            "status": "ok" if any(value is not None for value in returns.values()) else "missing",
            "source": metric_sources.get("returns") or "fund_open_fund_rank_em",
            "fields": [key for _, key in FUND_RETURN_COLUMNS if returns.get(key) is not None],
        },
        {
            "key": "peer_rank",
            "label": "同类排名/分位",
            "status": "ok" if isinstance(peer, dict) and peer.get("rank") is not None else "partial",
            "source": "fund_open_fund_rank_em" if peer else None,
            "freshness": peer.get("date") if isinstance(peer, dict) else None,
        },
        {
            "key": "nav_history",
            "label": "历史净值序列",
            "status": "ok" if has_nav_history else "partial",
            "source": "fund_open_fund_info_em",
            "sample_days": metrics.get("sample_days", 0),
        },
        {
            "key": "risk_metrics",
            "label": "风险指标",
            "status": "ok" if risk_analysis else ("partial" if metrics.get("max_drawdown_1y_pct") is not None else "missing"),
            "source": metric_sources.get("risk"),
            "fields": _compact_strings([
                "max_drawdown_1y_pct" if metrics.get("max_drawdown_1y_pct") is not None else None,
                "volatility_1y_pct" if metrics.get("volatility_1y_pct") is not None else None,
                "sharpe_1y" if metrics.get("sharpe_1y") is not None else None,
            ]),
        },
        {
            "key": "market_context",
            "label": "市场周期/风格上下文",
            "status": "ok" if market_context and market_context.get("status") == "ok" else ("partial" if market_context and market_context.get("status") == "proxy_only" else "missing"),
            "source": market_context.get("source") if market_context else None,
            "fields": market_context.get("available_proxies") if market_context else [],
        },
        {
            "key": "research_evidence",
            "label": "资讯/权威解读佐证",
            "status": "ok" if research_evidence and research_evidence.get("status") == "connected" else ("partial" if research_evidence and research_evidence.get("status") in {"not_configured", "no_match"} else "missing"),
            "source": research_evidence.get("source") if research_evidence else None,
            "fields": [item.get("title") for item in research_evidence.get("items", [])[:3]] if research_evidence else [],
        },
        {
            "key": "trading_rules",
            "label": "交易规则/费用",
            "status": trading_rules.get("status") if isinstance(trading_rules, dict) else "missing",
            "source": "fund_purchase_em/fund_fee_em",
            "fields": _compact_strings([
                "purchase_status" if trading_rules and trading_rules.get("purchase_status") else None,
                "redemption_status" if trading_rules and trading_rules.get("redemption_status") else None,
                "min_purchase_amount" if trading_rules and trading_rules.get("min_purchase_amount") is not None else None,
                "redemption_fee" if trading_rules and trading_rules.get("fee_tables", {}).get("redemption") else None,
            ]),
        },
    ]
    missing_or_partial = [
        item["label"]
        for item in dimensions
        if item.get("status") in {"partial", "missing"}
    ]
    return {
        "dimensions": dimensions,
        "status": "ok" if not missing_or_partial and not limitations else "partial",
        "missing_or_partial": missing_or_partial,
        "limitations": limitations,
    }


def build_strategy_readiness(
    *,
    taxonomy: Dict[str, Any],
    data_coverage: Dict[str, Any],
    market_context: Dict[str, Any],
    calibration_status: Dict[str, Any],
    metric_profile: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    dimensions = data_coverage.get("dimensions") or []
    status_by_key = {item.get("key"): item.get("status") for item in dimensions if isinstance(item, dict)}
    metric_profile = metric_profile if isinstance(metric_profile, dict) else {}
    missing_specialized_metrics = [
        item
        for item in metric_profile.get("missing_specialized_metrics", [])
        if isinstance(item, dict)
    ]
    metric_limitations = [
        str(item)
        for item in metric_profile.get("limitations", [])
        if item
    ]
    blockers = []
    warnings = []
    if status_by_key.get("returns_rank") not in {"ok"}:
        blockers.append("缺少多周期收益榜单，无法稳定比较同类表现")
    if status_by_key.get("nav_history") not in {"ok"}:
        blockers.append("历史净值样本不足，无法可靠评估回撤和趋势")
    if status_by_key.get("peer_rank") not in {"ok"}:
        blockers.append("缺少同类排名/分位，策略校准样本不足")
    if taxonomy.get("strategy_family") == "money_market":
        blockers.append("货币基金需要七日年化、万份收益和流动性专项指标，当前底座未接入")
    if missing_specialized_metrics and taxonomy.get("strategy_family") != "money_market":
        warnings.append(
            "专项指标缺口："
            + "、".join(str(item.get("label") or item.get("key")) for item in missing_specialized_metrics[:5])
        )
    warnings.extend(metric_limitations)
    if market_context.get("status") == "proxy_only":
        warnings.append("市场上下文目前只有基金自身代理，不能等同于真实市场周期/估值判断")
    if status_by_key.get("trading_rules") not in {"ok", "partial"}:
        warnings.append("交易规则和费率未覆盖，执行建议暂不能估算真实申赎成本")
    if status_by_key.get("research_evidence") not in {"ok", "partial"}:
        warnings.append("资讯/公告/财报佐证不足，LLM 只能做数据解释而不能扩展外部判断")
    if calibration_status.get("status") != "calibrated":
        warnings.append("策略参数尚未完成历史回测校准")

    next_layers = []
    if status_by_key.get("market_context") != "ok":
        next_layers.append("接入市场周期/估值/风格轮动上下文")
    if status_by_key.get("trading_rules") not in {"ok", "partial"}:
        next_layers.append("补齐交易规则和申赎费率")
    if status_by_key.get("research_evidence") != "ok":
        next_layers.append("接入行业新闻/重仓公司财报/权威解读佐证")
    for item in missing_specialized_metrics:
        label = item.get("label") or item.get("key")
        if label:
            next_layers.append(f"补齐{label}")
    next_layers.extend([
        "建立分类型回测校准",
        "LLM 仅做解释与风险审阅",
    ])

    return {
        "profile_schema_version": FUND_PROFILE_SCHEMA_VERSION,
        "signal_model_version": FUND_SIGNAL_MODEL_VERSION,
        "strategy_family": taxonomy.get("strategy_family"),
        "status": "ready_for_rule_signal" if not blockers else "partial",
        "backtest_status": calibration_status.get("status"),
        "blockers": blockers,
        "warnings": warnings,
        "next_layers": next_layers,
        "metric_profile_schema_version": metric_profile.get("schema_version"),
        "missing_specialized_metrics": missing_specialized_metrics,
        "metric_limitations": metric_limitations,
    }


def build_calibration_status(
    *,
    taxonomy: Dict[str, Any],
    metrics: Dict[str, Any],
    data_coverage: Dict[str, Any],
) -> Dict[str, Any]:
    """Describe whether this fund has enough evidence for parameter calibration."""
    sample_days = int(metrics.get("sample_days") or 0)
    required_days = 756 if taxonomy.get("strategy_family") in {"active_equity", "index_beta", "qdii_global"} else 504
    dimensions = data_coverage.get("dimensions") or []
    status_by_key = {item.get("key"): item.get("status") for item in dimensions if isinstance(item, dict)}
    missing_inputs = []
    if sample_days < required_days:
        missing_inputs.append(f"需要至少 {required_days} 条净值样本，目前 {sample_days} 条")
    if status_by_key.get("market_context") != "ok":
        missing_inputs.append("缺少真实市场周期/估值/风格上下文")
    if status_by_key.get("peer_rank") != "ok":
        missing_inputs.append("缺少稳定同类分位样本")
    if status_by_key.get("risk_metrics") == "missing":
        missing_inputs.append("缺少风险指标")

    readiness_score = 0
    if status_by_key.get("trading_rules") == "missing":
        missing_inputs.append("缺少交易规则/费率，回测无法计入申赎成本")

    readiness_score += min(sample_days / required_days, 1.0) * 35
    readiness_score += 15 if status_by_key.get("returns_rank") == "ok" else 0
    readiness_score += 15 if status_by_key.get("peer_rank") == "ok" else 0
    readiness_score += 15 if status_by_key.get("risk_metrics") in {"ok", "partial"} else 0
    readiness_score += 10 if status_by_key.get("market_context") == "ok" else 0
    readiness_score += 5 if status_by_key.get("trading_rules") in {"ok", "partial"} else 0
    readiness_score += 5 if status_by_key.get("research_evidence") in {"ok", "partial"} else 0

    status = "ready_for_research" if not missing_inputs else "not_ready"
    return {
        "status": status,
        "validation_status": "not_validated",
        "sample_days": sample_days,
        "required_sample_days": required_days,
        "readiness_score": round(min(readiness_score, 100), 1),
        "missing_inputs": missing_inputs,
        "research_plan": [
            "按策略族分组做历史窗口回测",
            "校准买入/定投/减仓阈值与最大回撤约束",
            "加入申赎费率、持有期和换手成本假设",
            "用同类分位和市场周期做分层评估",
        ],
    }


def build_fund_profile(
    *,
    code: str,
    name: Optional[str],
    fund_type: Optional[str],
    metrics: Dict[str, Any],
    peer: Optional[Dict[str, Any]],
    latest_quote: Optional[FundLatestQuote],
    risk_analysis: Optional[Dict[str, Any]],
    trading_rules: Optional[Dict[str, Any]] = None,
    market_snapshot: Optional[Dict[str, Any]] = None,
    research_evidence: Optional[Dict[str, Any]] = None,
    limitations: List[str],
) -> Dict[str, Any]:
    taxonomy = infer_fund_taxonomy(name, fund_type)
    strategy_policy = build_strategy_policy(taxonomy)
    market_context = build_market_context(
        taxonomy=taxonomy,
        metrics=metrics,
        peer=peer,
        market_snapshot=market_snapshot,
    )
    data_quality_detail = build_data_quality_detail(
        code=code,
        name=name,
        fund_type=fund_type,
        metrics=metrics,
        peer=peer,
        latest_quote=latest_quote,
        risk_analysis=risk_analysis,
        market_context=market_context,
        research_evidence=research_evidence,
        trading_rules=trading_rules,
        limitations=limitations,
    )
    data_coverage = build_data_coverage(
        metrics=metrics,
        peer=peer,
        latest_quote=latest_quote,
        risk_analysis=risk_analysis,
        market_context=market_context,
        research_evidence=research_evidence,
        trading_rules=trading_rules,
        limitations=limitations,
    )
    data_coverage.update({
        "quality_schema_version": data_quality_detail["schema_version"],
        "overall_status": data_quality_detail["overall_status"],
        "quality_score": data_quality_detail["quality_score"],
        "blocking_issues": data_quality_detail["blocking_issues"],
        "warnings": data_quality_detail["warnings"],
        "quality_dimensions": [
            {
                "key": item.get("key"),
                "label": item.get("label"),
                "status": item.get("status"),
                "source": item.get("source"),
                "as_of": item.get("as_of"),
                "sample_count": item.get("sample_count"),
                "field_count": item.get("field_count"),
            }
            for item in data_quality_detail.get("dimensions", [])
        ],
    })
    calibration_status = build_calibration_status(
        taxonomy=taxonomy,
        metrics=metrics,
        data_coverage=data_coverage,
    )
    metric_profile = build_metric_profile(
        taxonomy=taxonomy,
        metrics=metrics,
        peer=peer,
        latest_quote=latest_quote,
        risk_analysis=risk_analysis,
    )
    strategy_readiness = build_strategy_readiness(
        taxonomy=taxonomy,
        data_coverage=data_coverage,
        market_context=market_context,
        calibration_status=calibration_status,
        metric_profile=metric_profile,
    )
    return {
        "code": code,
        "name": name,
        "fund_type": fund_type,
        "taxonomy": taxonomy,
        "metric_profile": metric_profile,
        "type_specific_metrics": metric_profile,
        "strategy_policy": strategy_policy,
        "market_context": market_context,
        "research_evidence": research_evidence or {
            "status": "not_configured",
            "source": "intelligence_repository",
            "items": [],
            "limitations": ["尚未配置基金/行业/市场解读资讯源"],
        },
        "trading_rules": trading_rules or {
            "status": "missing",
            "limitations": ["交易规则/费用数据未接入"],
        },
        "calibration_status": calibration_status,
        "data_coverage": data_coverage,
        "data_quality": {
            "schema_version": data_quality_detail["schema_version"],
            "overall_status": data_quality_detail["overall_status"],
            "quality_score": data_quality_detail["quality_score"],
            "blocking_issues": data_quality_detail["blocking_issues"],
            "warnings": data_quality_detail["warnings"],
        },
        "data_quality_detail": data_quality_detail,
        "strategy_readiness": strategy_readiness,
    }


def _compact_quality_dimensions(quality_detail: Dict[str, Any]) -> List[Dict[str, Any]]:
    return [
        {
            "key": item.get("key"),
            "label": item.get("label"),
            "status": item.get("status"),
            "source": item.get("source"),
            "as_of": item.get("as_of"),
            "sample_count": item.get("sample_count"),
            "field_count": item.get("field_count"),
        }
        for item in quality_detail.get("dimensions", [])
        if isinstance(item, dict)
    ]


def _build_signal_data_quality_context(
    *,
    quality_summary: Dict[str, Any],
    quality_detail: Dict[str, Any],
) -> Dict[str, Any]:
    quality_dimensions = _compact_quality_dimensions(quality_detail)
    return {
        "schema_version": quality_summary.get("schema_version") or quality_detail.get("schema_version"),
        "overall_status": quality_summary.get("overall_status") or quality_detail.get("overall_status"),
        "quality_score": quality_summary.get("quality_score") if quality_summary.get("quality_score") is not None else quality_detail.get("quality_score"),
        "dimension_statuses": {
            str(item.get("key")): item.get("status")
            for item in quality_dimensions
            if item.get("key")
        },
        "dimensions": quality_dimensions,
        "blocking_issues": quality_summary.get("blocking_issues") if quality_summary.get("blocking_issues") is not None else quality_detail.get("blocking_issues"),
        "warnings": quality_summary.get("warnings") if quality_summary.get("warnings") is not None else quality_detail.get("warnings"),
    }


def _build_signal_metric_profile_context(profile: Dict[str, Any]) -> Dict[str, Any]:
    metric_profile = profile.get("metric_profile") if isinstance(profile.get("metric_profile"), dict) else {}
    primary_metrics = [
        item
        for item in metric_profile.get("primary_metrics", [])
        if isinstance(item, dict)
    ]
    missing_specialized_metrics = [
        item
        for item in metric_profile.get("missing_specialized_metrics", [])
        if isinstance(item, dict)
    ]
    not_applicable_metrics = [
        item
        for item in metric_profile.get("not_applicable_metrics", [])
        if isinstance(item, dict)
    ]
    return {
        "schema_version": metric_profile.get("schema_version"),
        "fund_category": metric_profile.get("fund_category"),
        "strategy_family": metric_profile.get("strategy_family"),
        "asset_class": metric_profile.get("asset_class"),
        "primary_metric_statuses": {
            str(item.get("key")): item.get("status")
            for item in primary_metrics
            if item.get("key")
        },
        "missing_specialized_metrics": missing_specialized_metrics,
        "not_applicable_metrics": not_applicable_metrics,
        "limitations": metric_profile.get("limitations") or [],
    }


def _build_signal_calibration_context(profile: Dict[str, Any]) -> Dict[str, Any]:
    calibration_status = profile.get("calibration_status") if isinstance(profile.get("calibration_status"), dict) else {}
    strategy_readiness = profile.get("strategy_readiness") if isinstance(profile.get("strategy_readiness"), dict) else {}
    return {
        "schema_version": "fund_signal_calibration_context_v1",
        "source": "profile.calibration_status + strategy_readiness",
        "profile_status": calibration_status.get("status"),
        "validation_status": calibration_status.get("validation_status"),
        "strategy_readiness_status": strategy_readiness.get("status"),
        "strategy_readiness_backtest_status": strategy_readiness.get("backtest_status"),
        "readiness_score": calibration_status.get("readiness_score"),
        "sample_days": calibration_status.get("sample_days"),
        "required_sample_days": calibration_status.get("required_sample_days"),
        "missing_inputs": list(calibration_status.get("missing_inputs") or []),
        "applied_to_thresholds": False,
        "threshold_source": "strategy_policy.action_thresholds",
        "endpoint_boundary": "P0-2 校准端点只聚合历史 walk-forward 证据；当前信号不会自动套用校准后的阈值。",
    }


def _build_execution_constraints(
    *,
    trading_rules: Optional[Dict[str, Any]],
    latest_quote: Optional[FundLatestQuote],
) -> Dict[str, Any]:
    rules = trading_rules if isinstance(trading_rules, dict) else {}
    fee_tables = rules.get("fee_tables") if isinstance(rules.get("fee_tables"), dict) else {}
    fee_model = rules.get("fee_model") if isinstance(rules.get("fee_model"), dict) else {}
    subscription_model = fee_model.get("subscription") if isinstance(fee_model.get("subscription"), dict) else {}
    redemption_model = fee_model.get("redemption") if isinstance(fee_model.get("redemption"), dict) else {}
    annual_expense = fee_model.get("annual_expense") if isinstance(fee_model.get("annual_expense"), dict) else {}
    has_subscription_fee = bool(fee_tables.get("subscription"))
    has_redemption_fee = bool(fee_tables.get("redemption"))
    front_fee = rules.get("front_fee")
    if front_fee is None and latest_quote and latest_quote.fee:
        front_fee = _to_float(latest_quote.fee)
    fee_available = front_fee is not None or has_subscription_fee or has_redemption_fee
    fees_estimated = bool(fee_model.get("fees_estimated")) if fee_model else not (front_fee is not None and has_subscription_fee and has_redemption_fee)
    fee_model_summary = {
        "schema_version": "fund_fee_model_summary_v1",
        "fee_model_schema_version": fee_model.get("schema_version"),
        "subscription_tiers_available": bool(subscription_model.get("tiers_available")),
        "redemption_tiers_available": bool(redemption_model.get("tiers_available")),
        "annual_expense_available": bool(annual_expense.get("available")),
        "fees_estimated": fees_estimated,
        "subscription_backtest_rate_pct": subscription_model.get("selected_rate_pct"),
        "redemption_backtest_rate_pct": redemption_model.get("conservative_rate_pct"),
        "subscription_policy": subscription_model.get("selection_policy"),
        "redemption_policy": redemption_model.get("selection_policy"),
        "limitations": list(fee_model.get("limitations") or []),
        "boundary": fee_model.get("boundary") or "公开费率不等同于个人账户或销售渠道实际费率。",
    }
    return {
        "schema_version": "fund_signal_execution_constraints_v1",
        "status": rules.get("status") or "missing",
        "purchase_status": rules.get("purchase_status") or (latest_quote.purchase_status if latest_quote else None),
        "redemption_status": rules.get("redemption_status") or (latest_quote.redemption_status if latest_quote else None),
        "next_open_date": rules.get("next_open_date"),
        "min_purchase_amount": rules.get("min_purchase_amount"),
        "daily_limit_amount": rules.get("daily_limit_amount"),
        "front_fee": front_fee,
        "fee_availability": {
            "front_fee": front_fee is not None,
            "subscription_fee_table": has_subscription_fee,
            "redemption_fee_table": has_redemption_fee,
        },
        "fees_estimated": fees_estimated,
        "fee_model_summary": fee_model_summary,
        "fee_source": rules.get("source"),
        "limitations": list(rules.get("limitations") or []),
        "boundary": "费用和申赎状态来自公开快照，可能不同于具体销售渠道、账户费率或实际持有期。",
        "available": bool(rules) or latest_quote is not None or fee_available,
    }


def _status_contains_block(text: Any) -> bool:
    value = str(text or "")
    return any(word in value for word in ("暂停", "封闭", "不可", "不开放", "停止"))


def _build_decision_checks(
    *,
    action: str,
    signal_score: Any,
    risk_score: Any,
    metrics: Dict[str, Any],
    data_quality: Dict[str, Any],
    calibration: Dict[str, Any],
    execution_constraints: Dict[str, Any],
    thresholds: Dict[str, Any],
    risk_gate: Any,
) -> List[Dict[str, Any]]:
    checks: List[Dict[str, Any]] = []
    quality_score = _to_float(data_quality.get("quality_score")) or 0.0
    blocking_issues = list(data_quality.get("blocking_issues") or [])
    quality_status = str(data_quality.get("overall_status") or "partial")
    if blocking_issues:
        quality_check_status = "block"
        quality_detail = "；".join(blocking_issues[:2])
    elif quality_score < 70 or quality_status != "ok":
        quality_check_status = "warn"
        quality_detail = f"数据质量 {quality_status}，质量分 {quality_score:.1f}"
    else:
        quality_check_status = "pass"
        quality_detail = f"数据质量可用，质量分 {quality_score:.1f}"
    checks.append({
        "key": "data_quality_gate",
        "status": quality_check_status,
        "label": "数据质量门槛",
        "detail": quality_detail,
    })

    calibration_status = str(calibration.get("profile_status") or "not_ready")
    validation_status = str(calibration.get("validation_status") or "not_validated")
    if calibration.get("applied_to_thresholds") is True and validation_status in {"validated", "calibrated"}:
        calibration_check_status = "pass"
    else:
        calibration_check_status = "warn"
    checks.append({
        "key": "backtest_calibration",
        "status": calibration_check_status,
        "label": "回测校准状态",
        "detail": f"校准状态 {calibration_status}/{validation_status}，当前未自动应用到动作阈值",
    })

    purchase_status = execution_constraints.get("purchase_status")
    if _status_contains_block(purchase_status):
        purchase_check_status = "block"
        purchase_detail = f"申购状态为 {purchase_status}"
    elif purchase_status:
        purchase_check_status = "pass"
        purchase_detail = f"申购状态为 {purchase_status}"
    else:
        purchase_check_status = "warn"
        purchase_detail = "申购状态缺失，执行前需在交易平台确认"
    checks.append({
        "key": "purchase_status",
        "status": purchase_check_status,
        "label": "申购状态",
        "detail": purchase_detail,
    })

    redemption_status = execution_constraints.get("redemption_status")
    if action in {"reduce", "sell_watch"} and _status_contains_block(redemption_status):
        redemption_check_status = "block"
        redemption_detail = f"赎回状态为 {redemption_status}"
    elif redemption_status:
        redemption_check_status = "pass"
        redemption_detail = f"赎回状态为 {redemption_status}"
    else:
        redemption_check_status = "warn"
        redemption_detail = "赎回状态缺失，减仓/赎回前需在交易平台确认"
    checks.append({
        "key": "redemption_status",
        "status": redemption_check_status,
        "label": "赎回状态",
        "detail": redemption_detail,
    })

    risk_value = _to_float(risk_score) or 0.0
    risk_gate_value = _to_float(risk_gate) or 70.0
    drawdown = _to_float(metrics.get("max_drawdown_1y_pct"))
    if risk_value >= risk_gate_value:
        risk_check_status = "block" if action in {"buy", "dca"} else "warn"
        risk_detail = f"风险分 {risk_value:.1f} 已达到风险门槛 {risk_gate_value:.1f}"
    else:
        risk_check_status = "pass"
        risk_detail = f"风险分 {risk_value:.1f} 低于风险门槛 {risk_gate_value:.1f}"
    if drawdown is not None:
        risk_detail += f"，近 1 年最大回撤 {drawdown:.2f}%"
    checks.append({
        "key": "risk_gate",
        "status": risk_check_status,
        "label": "风险门槛",
        "detail": risk_detail,
    })

    if execution_constraints.get("fees_estimated"):
        fee_check_status = "warn"
        fee_detail = "费率未完整覆盖，执行成本仍按公开快照/静态假设处理"
    else:
        fee_check_status = "pass"
        fee_detail = "申购/赎回费率表可用，但仍非个人账户实际费率"
    checks.append({
        "key": "fee_coverage",
        "status": fee_check_status,
        "label": "费用覆盖",
        "detail": fee_detail,
    })

    signal_value = _to_float(signal_score) or 0.0
    checks.append({
        "key": "threshold_match",
        "status": "pass",
        "label": "动作阈值匹配",
        "detail": f"信号分 {signal_value:.1f}，阈值 buy/dca/watch/reduce = {thresholds.get('buy')}/{thresholds.get('dca')}/{thresholds.get('watch')}/{thresholds.get('reduce')}",
    })
    return checks


def _build_alternative_actions(
    *,
    selected_action: str,
    signal_score: Any,
    risk_score: Any,
    risk_gate: Any,
    drawdown: Any,
    thresholds: Dict[str, Any],
    drawdown_stop: Any,
    execution_constraints: Dict[str, Any],
) -> List[Dict[str, Any]]:
    signal_value = _to_float(signal_score) or 0.0
    risk_value = _to_float(risk_score) or 0.0
    risk_gate_value = _to_float(risk_gate) or 70.0
    drawdown_value = _to_float(drawdown)
    drawdown_stop_value = _to_float(drawdown_stop)
    purchase_blocked = _status_contains_block(execution_constraints.get("purchase_status"))
    redemption_blocked = _status_contains_block(execution_constraints.get("redemption_status"))
    buy_threshold = _to_float(thresholds.get("buy")) or 72.0
    dca_threshold = _to_float(thresholds.get("dca")) or 58.0
    watch_threshold = _to_float(thresholds.get("watch")) or 45.0
    reduce_threshold = _to_float(thresholds.get("reduce")) or 30.0

    alternatives: List[Dict[str, Any]] = []

    def append(action: str, status: str, reason: str) -> None:
        alternatives.append({
            "action": action,
            "action_label": FUND_ACTION_LABELS.get(action, action),
            "status": status,
            "reason": reason,
        })

    if selected_action == "buy" and not purchase_blocked and risk_value < risk_gate_value:
        append("buy", "selected", "信号分达到买入阈值且未触发申购/风险阻断")
    elif purchase_blocked:
        append("buy", "blocked", "公开申购状态阻断买入")
    elif risk_value >= risk_gate_value:
        append("buy", "blocked", "风险分达到风险门槛，买入被阻断")
    else:
        append("buy", "not_selected", f"信号分 {signal_value:.1f} 低于买入阈值 {buy_threshold:.1f}")

    if selected_action == "dca" and not purchase_blocked and risk_value < risk_gate_value:
        append("dca", "selected", "信号分进入定投区间且未触发买入/风险阻断")
    elif purchase_blocked:
        append("dca", "blocked", "公开申购状态阻断定投")
    elif risk_value >= risk_gate_value:
        append("dca", "blocked", "风险分达到风险门槛，定投被阻断")
    elif signal_value >= buy_threshold:
        append("dca", "not_selected", "信号分已达到更高的买入区间")
    else:
        append("dca", "not_selected", f"信号分 {signal_value:.1f} 未达到定投阈值 {dca_threshold:.1f}")

    if selected_action == "pause_buy":
        append("pause_buy", "selected", "公开申购状态显示暂停，规则选择暂停申购并阻断新增买入/定投")
    elif purchase_blocked:
        append("pause_buy", "not_selected", f"申购状态为 {execution_constraints.get('purchase_status')}，但当前动作由更高优先级规则解释")
    else:
        append("pause_buy", "not_selected", "公开申购状态未显示暂停")

    if selected_action == "watch":
        append("watch", "selected", "规则未触发更积极或更防御的动作")
    elif signal_value >= dca_threshold and risk_value < risk_gate_value:
        append("watch", "not_selected", "信号分高于观察区间，规则选择更积极动作")
    elif signal_value < reduce_threshold or risk_value >= risk_gate_value:
        append("watch", "not_selected", "风险或信号已偏防御，观察不是唯一约束动作")
    else:
        append("watch", "not_selected", f"信号分 {signal_value:.1f} 未落在观察阈值 {watch_threshold:.1f} 附近")

    if selected_action == "reduce":
        append("reduce", "selected", "风险或信号触发减仓/暂停定投规则")
    elif redemption_blocked:
        append("reduce", "blocked", "公开赎回状态阻断减仓执行")
    elif risk_value < risk_gate_value and signal_value >= reduce_threshold:
        append("reduce", "not_selected", "风险分未触发防御门槛，暂不进入减仓")
    elif drawdown_value is not None and drawdown_stop_value is not None and drawdown_value > drawdown_stop_value:
        append("reduce", "not_selected", "回撤尚未跌破止损式减仓阈值")
    else:
        append("reduce", "not_selected", "当前规则未满足减仓组合条件")

    if selected_action == "sell_watch":
        append("sell_watch", "selected", "信号分低于减仓区间，进入赎回观察")
    elif redemption_blocked:
        append("sell_watch", "blocked", "公开赎回状态阻断赎回观察执行")
    else:
        append("sell_watch", "not_selected", f"信号分 {signal_value:.1f} 仍高于赎回观察触发区间")

    return alternatives


def _derive_signal_confidence_level(
    *,
    data_quality: Dict[str, Any],
    calibration: Dict[str, Any],
    decision_checks: List[Dict[str, Any]],
) -> str:
    quality_score = _to_float(data_quality.get("quality_score")) or 0.0
    if data_quality.get("blocking_issues") or any(item.get("status") == "block" for item in decision_checks):
        return "limited"
    if quality_score < 70:
        return "low"
    if calibration.get("profile_status") not in {"ready_for_research", "calibrated"}:
        return "low"
    warning_keys = {
        str(item.get("key"))
        for item in decision_checks
        if item.get("status") == "warn"
    }
    if warning_keys & {"fee_coverage", "risk_gate", "purchase_status", "redemption_status"}:
        return "low"
    if calibration.get("applied_to_thresholds") is not True:
        return "medium"
    return "high" if quality_score >= 85 else "medium"


def build_signal_context_v3(
    *,
    base_context: Dict[str, Any],
    signal: Dict[str, Any],
    metrics: Dict[str, Any],
    profile: Dict[str, Any],
    trading_rules: Optional[Dict[str, Any]],
    latest_quote: Optional[FundLatestQuote],
) -> Dict[str, Any]:
    quality_detail = profile.get("data_quality_detail") if isinstance(profile.get("data_quality_detail"), dict) else {}
    quality_summary = profile.get("data_quality") if isinstance(profile.get("data_quality"), dict) else {}
    data_quality = _build_signal_data_quality_context(
        quality_summary=quality_summary,
        quality_detail=quality_detail,
    )
    metric_profile_context = _build_signal_metric_profile_context(profile)
    calibration = _build_signal_calibration_context(profile)
    execution_constraints = _build_execution_constraints(
        trading_rules=trading_rules,
        latest_quote=latest_quote,
    )
    thresholds = base_context.get("action_thresholds") if isinstance(base_context.get("action_thresholds"), dict) else {}
    risk_gate = base_context.get("risk_gate")
    decision_checks = _build_decision_checks(
        action=str(signal.get("action") or "watch"),
        signal_score=signal.get("signal_score"),
        risk_score=signal.get("risk_score"),
        metrics=metrics,
        data_quality=data_quality,
        calibration=calibration,
        execution_constraints=execution_constraints,
        thresholds=thresholds,
        risk_gate=risk_gate,
    )
    alternative_actions = _build_alternative_actions(
        selected_action=str(signal.get("action") or "watch"),
        signal_score=signal.get("signal_score"),
        risk_score=signal.get("risk_score"),
        risk_gate=risk_gate,
        drawdown=metrics.get("max_drawdown_1y_pct"),
        thresholds=thresholds,
        drawdown_stop=base_context.get("drawdown_stop_pct"),
        execution_constraints=execution_constraints,
    )
    confidence_level = _derive_signal_confidence_level(
        data_quality=data_quality,
        calibration=calibration,
        decision_checks=decision_checks,
    )
    return {
        **base_context,
        "signal_model_version": FUND_SIGNAL_MODEL_VERSION,
        "schema_version": "fund_signal_context_v3",
        "data_quality": data_quality,
        "metric_profile": metric_profile_context,
        "calibration": calibration,
        "backtest_calibration": calibration,
        "execution_constraints": execution_constraints,
        "decision_checks": decision_checks,
        "alternative_actions": alternative_actions,
        "confidence_level": confidence_level,
        "boundaries": [
            "不读取个人账户、持仓成本、可用现金或真实交易记录",
            "不自动下单，动作仅为规则引擎生成的跟踪建议",
            "P0-2 校准结果尚未自动应用到当前动作阈值",
            "基金类型专属指标缺口只作为解释边界，当前不会自动接入外部专项 API",
            "费用、申赎状态和起购金额来自公开快照，可能与具体销售渠道不同",
            "LLM 不自由生成买卖建议，只能解释规则信号和风险边界",
        ],
    }


def _round_money(value: float) -> float:
    return round(float(value), 2)


def _prepare_nav_backtest_frame(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame(columns=["date", "unit_nav", "accumulated_nav", "daily_growth_pct"])
    frame = df.copy()
    frame["date"] = pd.to_datetime(frame["date"], errors="coerce")
    frame["unit_nav"] = pd.to_numeric(frame["unit_nav"], errors="coerce")
    frame = frame.dropna(subset=["date", "unit_nav"])
    frame = frame[frame["unit_nav"] > 0]
    if frame.empty:
        return pd.DataFrame(columns=["date", "unit_nav", "accumulated_nav", "daily_growth_pct"])
    return (
        frame.sort_values("date")
        .drop_duplicates(subset=["date"], keep="last")
        .reset_index(drop=True)
    )


def _extract_fee_pct_from_rows(rows: Any, *, conservative: bool = False) -> Optional[float]:
    if not isinstance(rows, list):
        return None
    values: List[float] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        for key, value in row.items():
            key_text = str(key)
            if "费率" not in key_text and "手续费" not in key_text:
                continue
            fee = _to_float(value)
            if fee is not None and 0 <= fee <= 100:
                values.append(fee)
    if not values:
        return None
    return max(values) if conservative else values[0]


def _resolve_backtest_fee_assumptions(snapshot_payload: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    metrics = snapshot_payload.get("metrics") if isinstance(snapshot_payload, dict) else {}
    if not isinstance(metrics, dict):
        metrics = {}
    profile = metrics.get("profile") if isinstance(metrics.get("profile"), dict) else {}
    trading_rules = metrics.get("trading_rules") if isinstance(metrics.get("trading_rules"), dict) else None
    if trading_rules is None and isinstance(profile, dict):
        trading_rules = profile.get("trading_rules") if isinstance(profile.get("trading_rules"), dict) else {}
    if not isinstance(trading_rules, dict):
        trading_rules = {}

    fee_tables = trading_rules.get("fee_tables") if isinstance(trading_rules.get("fee_tables"), dict) else {}
    fee_model = trading_rules.get("fee_model") if isinstance(trading_rules.get("fee_model"), dict) else {}
    subscription_model = fee_model.get("subscription") if isinstance(fee_model.get("subscription"), dict) else {}
    redemption_model = fee_model.get("redemption") if isinstance(fee_model.get("redemption"), dict) else {}
    subscription_fee_pct = _to_float(subscription_model.get("selected_rate_pct"))
    redemption_fee_pct = _to_float(redemption_model.get("conservative_rate_pct"))
    subscription_source = subscription_model.get("source")
    redemption_source = redemption_model.get("source")
    subscription_policy = subscription_model.get("selection_policy") or "use_front_fee_when_available_else_first_public_subscription_tier"
    redemption_policy = redemption_model.get("selection_policy") or "use_highest_public_redemption_rate_as_conservative_backtest_assumption"
    limitations = list(fee_model.get("limitations") or [])
    if subscription_fee_pct is None:
        subscription_fee_pct = _to_float(trading_rules.get("front_fee"))
        subscription_source = subscription_source or ("latest_analysis.trading_rules.front_fee" if subscription_fee_pct is not None else None)
    if subscription_fee_pct is None:
        subscription_fee_pct = _extract_fee_pct_from_rows(fee_tables.get("subscription"), conservative=False)
        subscription_source = subscription_source or ("latest_analysis.trading_rules.fee_tables.subscription" if subscription_fee_pct is not None else None)
    if redemption_fee_pct is None:
        redemption_fee_pct = _extract_fee_pct_from_rows(fee_tables.get("redemption"), conservative=True)
        redemption_source = redemption_source or ("latest_analysis.trading_rules.fee_tables.redemption" if redemption_fee_pct is not None else None)

    fees_estimated = subscription_fee_pct is None or redemption_fee_pct is None or bool(fee_model.get("fees_estimated"))
    if subscription_fee_pct is None:
        limitations.append("申购费率缺失，回测申购成本按 0% 暂估")
    if redemption_fee_pct is None:
        limitations.append("赎回费率缺失，回测赎回成本按 0% 暂估")
    source = "latest_analysis.trading_rules.fee_model" if fee_model else ("latest_analysis.trading_rules" if trading_rules else "zero_fee_assumption")
    if subscription_fee_pct is None and redemption_fee_pct is None:
        source = "zero_fee_assumption"
    return {
        "subscription_fee_pct": round(subscription_fee_pct or 0.0, 4),
        "redemption_fee_pct": round(redemption_fee_pct or 0.0, 4),
        "source": source,
        "subscription_fee_model": subscription_policy,
        "redemption_fee_model": redemption_policy,
        "subscription_fee_source": subscription_source,
        "redemption_fee_source": redemption_source,
        "fees_estimated": fees_estimated,
        "fee_model_schema_version": fee_model.get("schema_version"),
        "limitations": _compact_unique_strings(limitations),
        "has_fee_table": bool(fee_tables),
    }


def _portfolio_curve_from_events(
    frame: pd.DataFrame,
    *,
    events: List[Dict[str, Any]],
    initial_cash: float,
) -> List[Dict[str, Any]]:
    events_by_idx: Dict[int, List[Dict[str, Any]]] = {}
    for event in events:
        idx = int(event.get("idx") or 0)
        events_by_idx.setdefault(idx, []).append(event)

    cash = float(initial_cash)
    units = 0.0
    curve: List[Dict[str, Any]] = []
    for idx, row in frame.iterrows():
        for event in events_by_idx.get(int(idx), []):
            cash += float(event.get("cash_delta") or 0.0)
            units += float(event.get("unit_delta") or 0.0)
            if abs(cash) < 0.000001:
                cash = 0.0
            if abs(units) < 0.000000001:
                units = 0.0
        price = float(row["unit_nav"])
        value = cash + units * price
        exposure = (units * price / value * 100) if value > 0 else 0.0
        curve.append(
            {
                "date": row["date"].date().isoformat(),
                "value": _round_money(value),
                "cash": _round_money(cash),
                "units": round(units, 6),
                "exposure_pct": round(exposure, 2),
            }
        )
    return curve


def _classify_backtest_outcome(
    *,
    action: str,
    forward_return_pct: Optional[float],
    forward_drawdown_pct: Optional[float],
    neutral_band_pct: float,
) -> Dict[str, Any]:
    if forward_return_pct is None:
        outcome = "unavailable"
    elif action in FUND_BACKTEST_BULLISH_ACTIONS:
        if forward_return_pct > neutral_band_pct:
            outcome = "win"
        elif forward_return_pct < -neutral_band_pct:
            outcome = "loss"
        else:
            outcome = "neutral"
    elif action in FUND_BACKTEST_DEFENSIVE_ACTIONS:
        drawdown_hit = forward_drawdown_pct is not None and forward_drawdown_pct <= -max(5.0, neutral_band_pct * 2)
        if forward_return_pct > neutral_band_pct:
            outcome = "loss"
        elif forward_return_pct < -neutral_band_pct or drawdown_hit:
            outcome = "win"
        else:
            outcome = "neutral"
    else:
        outcome = "neutral"
    return {
        "outcome": outcome,
        "outcome_label": FUND_BACKTEST_OUTCOME_LABELS.get(outcome, outcome),
    }


def _average_by_action(items: List[Dict[str, Any]], field: str) -> Dict[str, float]:
    buckets: Dict[str, List[float]] = {}
    for item in items:
        action = str(item.get("action") or "unknown")
        value = _to_float(item.get(field))
        if value is None:
            continue
        buckets.setdefault(action, []).append(value)
    return {
        action: round(sum(values) / len(values), 2)
        for action, values in buckets.items()
        if values
    }


class FundService:
    """基金池业务服务。"""

    def __init__(
        self,
        repo: Optional[FundRepository] = None,
        provider: Optional[AkshareFundProvider] = None,
        intelligence_repo: Optional[IntelligenceRepository] = None,
    ):
        self.repo = repo or FundRepository()
        self.provider = provider or AkshareFundProvider()
        self.intelligence_repo = intelligence_repo or IntelligenceRepository(self.repo.db)

    def _fetch_market_snapshot(
        self,
        *,
        code: str,
        taxonomy: Dict[str, Any],
        limitations: List[str],
    ) -> Dict[str, Any]:
        reference_symbols = select_reference_indices(taxonomy)
        index_context: List[Dict[str, Any]] = []
        budget_started = time.monotonic()
        for symbol in reference_symbols:
            if time.monotonic() - budget_started > 18:
                limitations.append("市场指数上下文获取超过预算，剩余指数已跳过")
                break
            try:
                pe_df = _call_with_timeout(f"{symbol} PE", lambda symbol=symbol: self.provider.index_pe(symbol), timeout=6)
                pb_df = _call_with_timeout(f"{symbol} PB", lambda symbol=symbol: self.provider.index_pb(symbol), timeout=6)
                index_context.append(build_index_context(symbol, pe_df, pb_df))
            except Exception as exc:  # noqa: BLE001
                logger.warning("基金市场指数上下文获取失败 %s/%s: %s", code, symbol, exc)
                limitations.append(f"{symbol} 指数估值/趋势获取失败")

        industry_allocation: Dict[str, Any] = {
            "status": "missing",
            "items": [],
            "source": "fund_portfolio_industry_allocation_em",
        }
        current_year = date.today().year
        for year in (str(current_year), str(current_year - 1), str(current_year - 2)):
            try:
                candidate = normalize_industry_allocation(
                    _call_with_timeout(
                        f"{code} 行业配置 {year}",
                        lambda year=year: self.provider.fund_industry_allocation(code, year),
                        timeout=6,
                    )
                )
                if candidate.get("status") == "ok":
                    industry_allocation = candidate
                    break
            except Exception as exc:  # noqa: BLE001
                logger.debug("基金行业配置获取失败 %s/%s: %s", code, year, exc)
        if industry_allocation.get("status") != "ok":
            limitations.append("基金持仓行业配置获取失败或暂不可用")

        stock_holdings: Dict[str, Any] = {
            "status": "missing",
            "items": [],
            "source": "fund_portfolio_hold_em",
        }
        for year in (str(current_year), str(current_year - 1), str(current_year - 2)):
            try:
                candidate = normalize_stock_holdings(
                    _call_with_timeout(
                        f"{code} 重仓股 {year}",
                        lambda year=year: self.provider.fund_stock_holdings(code, year),
                        timeout=6,
                    )
                )
                if candidate.get("status") == "ok":
                    stock_holdings = candidate
                    break
            except Exception as exc:  # noqa: BLE001
                logger.debug("基金重仓股获取失败 %s/%s: %s", code, year, exc)
        if stock_holdings.get("status") != "ok":
            limitations.append("基金重仓股获取失败或暂不可用")

        fund_reports: Dict[str, Any] = {
            "status": "missing",
            "items": [],
            "source": "fund_announcement_report_em",
        }
        try:
            fund_reports = normalize_fund_reports(
                _call_with_timeout(f"{code} 定期报告", lambda: self.provider.fund_reports(code), timeout=6)
            )
        except Exception as exc:  # noqa: BLE001
            logger.debug("基金定期报告获取失败 %s: %s", code, exc)
            limitations.append("基金定期报告获取失败或暂不可用")

        return {
            "reference_symbols": reference_symbols,
            "index_context": index_context,
            "style_rotation": build_style_rotation(index_context),
            "industry_allocation": industry_allocation,
            "stock_holdings": stock_holdings,
            "fund_reports": fund_reports,
            "limitations": [
                item for item in limitations
                if "指数估值/趋势获取失败" in item or "行业配置" in item or "重仓股" in item or "定期报告" in item
            ],
        }

    def _fetch_trading_rules(
        self,
        *,
        code: str,
        latest_quote: Optional[FundLatestQuote],
        limitations: List[str],
    ) -> Dict[str, Any]:
        purchase_row: Dict[str, Any] = {}
        subscription_fee: List[Dict[str, Any]] = []
        redemption_fee: List[Dict[str, Any]] = []
        annual_expense_fee: List[Dict[str, Any]] = []
        try:
            purchase_row = normalize_purchase_row(
                _call_with_timeout(f"{code} 申购状态", self.provider.fund_purchase_table, timeout=8),
                code,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("基金申购状态/购买起点获取失败 %s: %s", code, exc)
            limitations.append("基金申购状态/购买起点获取失败")
        try:
            subscription_fee = normalize_fee_table(
                _call_with_timeout(f"{code} 申购费率", lambda: self.provider.fund_fee(code, "申购费率"), timeout=6)
            )
        except Exception as exc:  # noqa: BLE001
            logger.debug("基金申购费率获取失败 %s: %s", code, exc)
        try:
            redemption_fee = normalize_fee_table(
                _call_with_timeout(f"{code} 赎回费率", lambda: self.provider.fund_fee(code, "赎回费率"), timeout=6)
            )
        except Exception as exc:  # noqa: BLE001
            logger.debug("基金赎回费率获取失败 %s: %s", code, exc)
            limitations.append("基金赎回费率获取失败")
        try:
            annual_expense_fee = normalize_fee_table(
                _call_with_timeout(f"{code} 运作费率", lambda: self.provider.fund_fee(code, "运作费率"), timeout=6)
            )
        except Exception as exc:  # noqa: BLE001
            logger.debug("基金运作费率获取失败 %s: %s", code, exc)

        trading_rules = build_trading_rules(
            code=code,
            latest_quote=latest_quote,
            purchase_row=purchase_row,
            subscription_fee=subscription_fee,
            redemption_fee=redemption_fee,
            annual_expense_fee=annual_expense_fee,
        )
        limitations.extend(trading_rules.get("limitations") or [])
        return trading_rules

    def _collect_research_evidence(
        self,
        *,
        code: str,
        name: Optional[str],
        taxonomy: Dict[str, Any],
        market_snapshot: Dict[str, Any],
    ) -> Dict[str, Any]:
        fund_reports = market_snapshot.get("fund_reports") if isinstance(market_snapshot.get("fund_reports"), dict) else {}
        stock_holdings = market_snapshot.get("stock_holdings") if isinstance(market_snapshot.get("stock_holdings"), dict) else {}
        industry_allocation = market_snapshot.get("industry_allocation") if isinstance(market_snapshot.get("industry_allocation"), dict) else {}

        categories: Dict[str, Dict[str, Any]] = {
            "fund_reports": {
                "label": "基金定期报告/公告",
                "status": "connected" if fund_reports.get("items") else "missing",
                "source": fund_reports.get("source") or "fund_announcement_report_em",
                "items": fund_reports.get("items") or [],
                "limitations": [] if fund_reports.get("items") else ["基金定期报告暂未命中"],
            },
            "industry_news": {
                "label": "行业新闻/景气佐证",
                "status": "pending",
                "source": "intelligence_repository",
                "items": [],
                "limitations": [],
            },
            "holding_company_news": {
                "label": "重仓公司资讯/财报线索",
                "status": "pending",
                "source": "intelligence_repository",
                "items": [],
                "limitations": [],
                "holdings": stock_holdings.get("items") or [],
            },
            "macro_market_news": {
                "label": "宏观/市场事件",
                "status": "pending",
                "source": "intelligence_repository",
                "items": [],
                "limitations": [],
            },
        }

        try:
            sources, source_total = self.intelligence_repo.list_sources(enabled=True, page=1, page_size=20)
        except Exception as exc:  # noqa: BLE001
            logger.warning("基金佐证资讯源查询失败 %s: %s", code, exc)
            for key in ("industry_news", "holding_company_news", "macro_market_news"):
                categories[key]["status"] = "unavailable"
                categories[key]["limitations"] = ["本地资讯库查询失败"]
            return {
                "status": "unavailable",
                "source": "intelligence_repository",
                "items": [],
                "categories": categories,
                "enabled_sources": 0,
                "limitations": ["本地资讯库查询失败"],
            }

        if source_total <= 0:
            for key in ("industry_news", "holding_company_news", "macro_market_news"):
                categories[key]["status"] = "not_configured"
                categories[key]["limitations"] = ["尚未启用 RSS/NewsNow 等资讯源"]
            return {
                "status": "connected" if categories["fund_reports"]["items"] else "not_configured",
                "source": "intelligence_repository",
                "items": categories["fund_reports"]["items"],
                "categories": categories,
                "enabled_sources": 0,
                "limitations": ["尚未启用 RSS/NewsNow 等基金或行业解读资讯源"],
            }

        keyword_groups = {
            "industry_news": [
                str(item.get("industry"))
                for item in (industry_allocation.get("items") or [])[:4]
                if isinstance(item, dict) and item.get("industry")
            ] + [str(tag) for tag in taxonomy.get("style_tags") or []],
            "holding_company_news": [
                str(item.get("stock_name"))
                for item in (stock_holdings.get("items") or [])[:5]
                if isinstance(item, dict) and item.get("stock_name")
            ],
            "macro_market_news": list(dict.fromkeys([
                *(str(item) for item in market_snapshot.get("reference_symbols") or []),
                "权益市场",
                "基金",
            ])),
        }

        all_items: List[Dict[str, Any]] = list(categories["fund_reports"]["items"])
        seen_urls: set[str] = set()
        for category_key, keywords in keyword_groups.items():
            category_items: List[Dict[str, Any]] = []
            for keyword in list(dict.fromkeys(keyword for keyword in keywords if keyword and len(keyword) >= 2))[:8]:
                try:
                    rows, _ = self.intelligence_repo.list_items(query=keyword, days=30, page=1, page_size=5)
                except Exception as exc:  # noqa: BLE001
                    logger.debug("基金佐证资讯检索失败 %s/%s: %s", code, keyword, exc)
                    continue
                for row in rows:
                    url = row.url or ""
                    if not url or url in seen_urls:
                        continue
                    seen_urls.add(url)
                    item = {
                        "title": row.title,
                        "summary": row.summary,
                        "url": url,
                        "source_name": row.source_name,
                        "source_type": row.source_type,
                        "published_at": row.published_at.isoformat() if row.published_at else None,
                        "matched_keyword": keyword,
                    }
                    category_items.append(item)
                    all_items.append(item)
                    if len(category_items) >= 4:
                        break
                if len(category_items) >= 4:
                    break
            categories[category_key]["items"] = category_items
            categories[category_key]["status"] = "connected" if category_items else "no_match"
            categories[category_key]["limitations"] = [] if category_items else ["近 30 天未命中该类别资讯"]

        return {
            "status": "connected" if any(category.get("items") for category in categories.values()) else "no_match",
            "source": "intelligence_repository",
            "enabled_sources": int(source_total),
            "items": all_items[:10],
            "categories": categories,
            "limitations": [] if any(category.get("items") for category in categories.values()) else ["已启用资讯源，但近 30 天未命中基金/行业/重仓公司/市场关键词"],
        }

    def list_pool(self) -> Dict[str, Any]:
        items = []
        for item in self.repo.list_pool(active_only=True):
            latest = self.repo.get_latest_analysis_snapshot(item.code)
            payload = item.to_dict()
            payload["latest_analysis"] = latest.to_dict() if latest else None
            items.append(payload)
        ledgers = [ledger.to_dict() for ledger in self.repo.list_ledgers(active_only=True)]
        counts: Dict[int, int] = {}
        for item in items:
            ledger_id = item.get("ledger_id")
            if ledger_id is None:
                continue
            counts[int(ledger_id)] = counts.get(int(ledger_id), 0) + 1
        for ledger in ledgers:
            ledger["fund_count"] = counts.get(int(ledger["id"]), 0)
        return {"items": items, "total": len(items), "ledgers": ledgers}

    def market_rankings(self, *, limit: int = 10, fund_type: str = "全部") -> Dict[str, Any]:
        from src.services.fund_market_ranking_service import FundMarketRankingService

        return FundMarketRankingService(self.provider).build_market_rankings(limit=limit, fund_type=fund_type)

    def recommendations_today(self, *, limit: int = 10, fund_type: str = "全部") -> Dict[str, Any]:
        from src.services.fund_recommendation_service import FundRecommendationService

        return FundRecommendationService(self.provider, repo=self.repo).today(limit=limit, fund_type=fund_type)

    def personal_actions(self) -> Dict[str, Any]:
        from src.services.fund_personal_action_service import FundPersonalActionService

        return FundPersonalActionService(repo=self.repo).build()

    def create_ledger(
        self,
        name: str,
        color: str,
        **profile_fields: Any,
    ) -> Dict[str, Any]:
        name = (name or "").strip()
        if not name:
            raise ValueError("账本名称不能为空")
        if len(name) > 20:
            raise ValueError("账本名称不能超过 20 个字符")
        profile = normalize_fund_ledger_profile(profile_fields)
        ledger = self.repo.create_ledger(
            name=name,
            color=normalize_fund_ledger_color(color),
            **profile,
        )
        payload = ledger.to_dict()
        payload["fund_count"] = 0
        return payload

    def update_ledger_profile(self, ledger_id: int, **updates: Any) -> Dict[str, Any]:
        normalized: Dict[str, Any] = {}
        if "name" in updates:
            name = (updates.get("name") or "").strip()
            if not name:
                raise ValueError("账本名称不能为空")
            if len(name) > 20:
                raise ValueError("账本名称不能超过 20 个字符")
            normalized["name"] = name
        if "color" in updates:
            normalized["color"] = normalize_fund_ledger_color(str(updates.get("color") or ""))
        normalized.update(normalize_fund_ledger_profile(updates))
        if not normalized:
            raise ValueError("没有可更新的账本画像字段")
        ledger = self.repo.update_ledger_profile(int(ledger_id), **normalized)
        payload = ledger.to_dict()
        pool = self.list_pool()
        counts = {
            int(item["id"]): int(item.get("fund_count") or 0)
            for item in pool.get("ledgers", [])
            if item.get("id") is not None
        }
        payload["fund_count"] = counts.get(int(payload["id"]), 0)
        return payload

    def assign_fund_ledger(self, code: str, ledger_id: int) -> Dict[str, Any]:
        code = normalize_fund_code(code)
        item = self.repo.assign_fund_to_ledger(code, int(ledger_id))
        if item is None:
            raise ValueError("基金不在基金池中")
        payload = item.to_dict()
        latest = self.repo.get_latest_analysis_snapshot(code)
        payload["latest_analysis"] = latest.to_dict() if latest else None
        return payload

    def search(self, query: str, limit: int = 20) -> Dict[str, Any]:
        keyword = (query or "").strip()
        if not keyword:
            return {"items": [], "total": 0, "query": keyword}
        results = []
        for metadata in self.provider.search_funds(keyword, limit=limit):
            peer = None
            limitations: List[str] = []
            try:
                peer = self.provider.get_peer_snapshot(metadata.code, metadata.fund_type)
            except Exception as exc:  # noqa: BLE001
                logger.warning("基金搜索同类榜单获取失败 %s: %s", metadata.code, exc)
                limitations.append("同类榜单不可用")
            latest = peer.get("latest") if isinstance(peer, dict) and isinstance(peer.get("latest"), dict) else {}
            peer_returns = peer.get("returns") if isinstance(peer, dict) and isinstance(peer.get("returns"), dict) else {}
            if peer is not None and not peer_returns:
                limitations.append("同类榜单阶段收益暂不可用")
            search_metrics = {
                "latest_nav": latest.get("unit_nav"),
                "latest_date": latest.get("nav_date"),
                "sample_days": 0,
                "returns": peer_returns,
                "metric_sources": {
                    "returns": "fund_open_fund_rank_em" if peer else None,
                    "risk": None,
                },
            }
            profile = build_fund_profile(
                code=metadata.code,
                name=metadata.name,
                fund_type=metadata.fund_type,
                metrics=search_metrics,
                peer=peer,
                latest_quote=None,
                risk_analysis=None,
                limitations=limitations,
            )
            results.append(
                {
                    "code": metadata.code,
                    "name": metadata.name,
                    "fund_type": metadata.fund_type,
                    "latest": {
                        "unit_nav": latest.get("unit_nav"),
                        "accumulated_nav": latest.get("accumulated_nav"),
                        "daily_growth_pct": latest.get("daily_growth_pct"),
                        "nav_date": latest.get("nav_date"),
                        "purchase_status": None,
                        "redemption_status": None,
                        "fee": latest.get("fee"),
                    },
                    "peer": peer,
                    "returns": peer_returns,
                    "rank": peer.get("rank") if isinstance(peer, dict) else None,
                    "sample_size": peer.get("sample_size") if isinstance(peer, dict) else None,
                    "category": peer.get("category") if isinstance(peer, dict) else None,
                    "profile": profile,
                    "limitations": limitations,
                    "data_sources": {
                        "metadata": "fund_name_em",
                        "latest": "fund_open_fund_rank_em" if latest else None,
                        "returns": "fund_open_fund_rank_em" if peer else None,
                    },
                }
            )
        return {"items": results, "total": len(results), "query": keyword}

    def add_to_pool(
        self,
        code: str,
        name: Optional[str] = None,
        notes: Optional[str] = None,
        ledger_id: Optional[int] = None,
    ) -> Dict[str, Any]:
        code = normalize_fund_code(code)
        metadata = FundMetadata(code=code, name=name)
        try:
            metadata = self.provider.get_metadata(code)
        except Exception as exc:  # noqa: BLE001 - 外部数据源失败不应阻断手工入池。
            logger.warning("基金元数据获取失败 %s: %s", code, exc)
        item = self.repo.upsert_pool_item(
            code=code,
            name=name or metadata.name or f"基金{code}",
            fund_type=metadata.fund_type,
            source=metadata.source,
            notes=notes,
            ledger_id=ledger_id,
        )
        return item.to_dict()

    def remove_from_pool(self, code: str) -> Dict[str, Any]:
        code = normalize_fund_code(code)
        removed = self.repo.mark_pool_item_inactive(code)
        return {"code": code, "removed": removed}

    def refresh_fund(self, code: str) -> Dict[str, Any]:
        code = normalize_fund_code(code)
        limitations: List[str] = []
        metadata = FundMetadata(code=code)
        latest_quote: Optional[FundLatestQuote] = None
        nav_records: List[Dict[str, Any]] = []
        peer: Optional[Dict[str, Any]] = None
        risk_analysis: Optional[Dict[str, Any]] = None

        try:
            metadata = _call_with_timeout(f"{code} 基础信息", lambda: self.provider.get_metadata(code), timeout=12)
        except Exception as exc:  # noqa: BLE001
            logger.warning("基金元数据刷新失败 %s: %s", code, exc)
            limitations.append("基金基础信息获取失败，名称和类型可能不完整")

        try:
            latest_quote = _call_with_timeout(f"{code} 最新净值", lambda: self.provider.get_latest_quote(code), timeout=15)
        except Exception as exc:  # noqa: BLE001
            logger.warning("基金最新净值刷新失败 %s: %s", code, exc)
            limitations.append("最新净值日榜获取失败")

        if latest_quote and latest_quote.nav_date and latest_quote.unit_nav is not None:
            latest_record = {
                "date": latest_quote.nav_date,
                "unit_nav": latest_quote.unit_nav,
                "accumulated_nav": latest_quote.accumulated_nav,
                "daily_growth_pct": latest_quote.daily_growth_pct,
            }
            self.repo.save_nav_records(code=code, records=[latest_record], source=latest_quote.source)

        if not (metadata.fund_type and "货币" in metadata.fund_type):
            try:
                nav_records = _call_with_timeout(f"{code} 历史净值", lambda: self.provider.get_nav_records(code), timeout=25)
                self.repo.save_nav_records(code=code, records=nav_records, source=metadata.source)
            except Exception as exc:  # noqa: BLE001
                logger.warning("基金历史净值刷新失败 %s: %s", code, exc)
                limitations.append("历史净值获取失败，收益/回撤/波动指标可能缺失")
        else:
            limitations.append("货币基金暂不拉取慢速历史接口，仅展示基础日榜边界")

        item = self.repo.upsert_pool_item(
            code=code,
            name=(latest_quote.name if latest_quote else None) or metadata.name or f"基金{code}",
            fund_type=metadata.fund_type,
            source=metadata.source,
            last_refreshed_at=datetime.now(),
        )

        try:
            peer = _call_with_timeout(f"{code} 同类榜单", lambda: self.provider.get_peer_snapshot(code, item.fund_type), timeout=20)
        except Exception as exc:  # noqa: BLE001
            logger.warning("基金同类比较获取失败 %s: %s", code, exc)
            limitations.append("同类榜单获取失败，同类分位暂不可用")

        try:
            risk_analysis = _call_with_timeout(f"{code} 风险指标", lambda: self.provider.individual_analysis(code), timeout=12)
        except Exception as exc:  # noqa: BLE001
            logger.warning("基金平台风险指标获取失败 %s: %s", code, exc)
            limitations.append("平台风险指标获取失败，回撤/波动/夏普使用本地净值估算")

        analysis = self._analyze(
            item,
            latest_quote=latest_quote,
            peer=peer,
            risk_analysis=risk_analysis,
            extra_limitations=limitations,
        )
        return self.repo.save_analysis_snapshot(analysis)

    def refresh_pool(self) -> Dict[str, Any]:
        results = []
        for item in self.repo.list_pool(active_only=True):
            try:
                results.append({"code": item.code, "success": True, "analysis": self.refresh_fund(item.code)})
            except Exception as exc:  # noqa: BLE001
                logger.warning("基金池刷新失败 %s: %s", item.code, exc)
                results.append({"code": item.code, "success": False, "error": str(exc)})
        return {
            "items": results,
            "success_count": sum(1 for item in results if item.get("success")),
            "failure_count": sum(1 for item in results if not item.get("success")),
        }

    def latest_analysis(self, code: str) -> Optional[Dict[str, Any]]:
        code = normalize_fund_code(code)
        snapshot = self.repo.get_latest_analysis_snapshot(code)
        return snapshot.to_dict() if snapshot else None

    def nav_history(self, code: str, limit: int = 260) -> Dict[str, Any]:
        code = normalize_fund_code(code)
        rows = self.repo.get_nav_history(code, limit=limit)
        return {"code": code, "items": [row.to_dict() for row in rows], "total": len(rows)}

    def backtest(
        self,
        code: str,
        *,
        lookback_days: int = 252,
        eval_window_days: int = 60,
        rebalance_interval_days: int = 20,
        initial_cash: float = 10000.0,
        dca_amount: float = 1000.0,
        neutral_band_pct: float = 2.0,
    ) -> Dict[str, Any]:
        code = normalize_fund_code(code)
        lookback_days = int(lookback_days)
        eval_window_days = int(eval_window_days)
        rebalance_interval_days = int(rebalance_interval_days)
        initial_cash = float(initial_cash)
        dca_amount = float(dca_amount)
        neutral_band_pct = float(neutral_band_pct)
        if lookback_days < 60:
            raise ValueError("lookback_days 至少需要 60")
        if eval_window_days < 5:
            raise ValueError("eval_window_days 至少需要 5")
        if rebalance_interval_days < 5:
            raise ValueError("rebalance_interval_days 至少需要 5")
        if initial_cash <= 0 or dca_amount <= 0:
            raise ValueError("initial_cash 和 dca_amount 必须大于 0")

        pool_item = self.repo.get_pool_item(code)
        latest_snapshot = self.repo.get_latest_analysis_snapshot(code)
        snapshot_payload = latest_snapshot.to_dict() if latest_snapshot else {}
        name = (pool_item.name if pool_item else None) or snapshot_payload.get("name") or f"基金{code}"
        fund_type = (pool_item.fund_type if pool_item else None) or snapshot_payload.get("fund_type")
        taxonomy = infer_fund_taxonomy(name, fund_type)
        strategy_policy = build_strategy_policy(taxonomy)
        fee_assumptions = _resolve_backtest_fee_assumptions(snapshot_payload)

        frame = _prepare_nav_backtest_frame(self.repo.get_nav_dataframe(code))
        required_samples = lookback_days + eval_window_days + 1
        base_limitations = [
            "回测仅使用本地已缓存公开净值序列，不读取个人账户、持仓成本或交易记录",
            "历史信号只使用信号日前的净值窗口计算，未使用未来净值、未来同类榜单或未来资讯",
            "交易按净值日单位净值估值，未模拟确认日、限购、滑点、税费和分红再投资差异",
        ]
        if fee_assumptions["source"] == "zero_fee_assumption":
            base_limitations.append("未找到公开费率表，回测费用按 0% 暂估")
        elif fee_assumptions.get("fees_estimated"):
            base_limitations.append("公开费率结构不完整，缺失的申购或赎回费用按 0% 暂估")
        else:
            base_limitations.append("申购使用公开 selected/front 费率，赎回使用最高公开持有期费率作为保守静态假设，非历史逐日真实费率")
        base_limitations.extend(fee_assumptions.get("limitations") or [])

        parameters = {
            "lookback_days": lookback_days,
            "eval_window_days": eval_window_days,
            "rebalance_interval_days": rebalance_interval_days,
            "initial_cash": _round_money(initial_cash),
            "dca_amount": _round_money(dca_amount),
            "neutral_band_pct": round(neutral_band_pct, 2),
        }
        methodology = {
            "engine_version": FUND_BACKTEST_ENGINE_VERSION,
            "signal_model_version": FUND_SIGNAL_MODEL_VERSION,
            "signal_core": "calculate_nav_metrics + build_fund_signal",
            "walk_forward": True,
            "no_future_data": True,
            "benchmark": "首个信号日一次性申购并持有至最近净值日",
            "cash_model": "初始现金账户，buy 提升至约 80% 暴露，dca 每次投入定投金额，reduce 降至约 35%，sell_watch 清仓观察",
            "fee_model": "申购使用 fee_model.subscription.selected_rate_pct；赎回使用 fee_model.redemption.conservative_rate_pct；缺失项按 0% 暂估并标记 fees_estimated",
        }
        if len(frame) < required_samples:
            return {
                "code": code,
                "name": name,
                "fund_type": fund_type,
                "status": "insufficient_data",
                "engine_version": FUND_BACKTEST_ENGINE_VERSION,
                "parameters": parameters,
                "summary": {
                    "sample_days": int(len(frame)),
                    "required_sample_days": int(required_samples),
                    "signal_count": 0,
                },
                "signals": [],
                "portfolio_curve": [],
                "fee_assumptions": fee_assumptions,
                "methodology": methodology,
                "limitations": base_limitations + [f"本地净值样本 {len(frame)} 条，少于回测所需 {required_samples} 条"],
            }

        last_anchor_idx = len(frame) - 1 - eval_window_days
        anchor_indices = list(range(lookback_days, last_anchor_idx + 1, rebalance_interval_days))
        if not anchor_indices:
            return {
                "code": code,
                "name": name,
                "fund_type": fund_type,
                "status": "insufficient_data",
                "engine_version": FUND_BACKTEST_ENGINE_VERSION,
                "parameters": parameters,
                "summary": {
                    "sample_days": int(len(frame)),
                    "required_sample_days": int(required_samples),
                    "signal_count": 0,
                },
                "signals": [],
                "portfolio_curve": [],
                "fee_assumptions": fee_assumptions,
                "methodology": methodology,
                "limitations": base_limitations + ["当前参数下没有可评估的滚动信号日"],
            }

        subscription_fee_pct = _to_float(fee_assumptions.get("subscription_fee_pct")) or 0.0
        redemption_fee_pct = _to_float(fee_assumptions.get("redemption_fee_pct")) or 0.0
        cash = float(initial_cash)
        units = 0.0
        trade_events: List[Dict[str, Any]] = []
        signal_items: List[Dict[str, Any]] = []

        for idx in anchor_indices:
            row = frame.iloc[idx]
            price = float(row["unit_nav"])
            signal_date = row["date"].date().isoformat()
            metrics, metric_limitations = calculate_nav_metrics(frame.iloc[: idx + 1])
            signal = build_fund_signal(
                metrics=metrics,
                peer=None,
                latest_quote=None,
                fund_type=fund_type,
                limitations=metric_limitations,
                taxonomy=taxonomy,
                strategy_policy=strategy_policy,
            )
            action = str(signal.get("action") or "watch")
            action_label = str(signal.get("action_label") or FUND_ACTION_LABELS.get(action, action))

            holding_value = units * price
            portfolio_before = cash + holding_value
            trade_type = "hold"
            trade_amount = 0.0
            fee = 0.0
            cash_delta = 0.0
            unit_delta = 0.0
            if action == "buy" and portfolio_before > 0:
                target_holding = portfolio_before * 0.8
                trade_amount = min(cash, max(0.0, target_holding - holding_value))
                if trade_amount > 0.01:
                    fee = trade_amount * subscription_fee_pct / 100
                    net_amount = max(0.0, trade_amount - fee)
                    unit_delta = net_amount / price
                    cash_delta = -trade_amount
                    trade_type = "buy"
            elif action == "dca":
                trade_amount = min(cash, dca_amount)
                if trade_amount > 0.01:
                    fee = trade_amount * subscription_fee_pct / 100
                    net_amount = max(0.0, trade_amount - fee)
                    unit_delta = net_amount / price
                    cash_delta = -trade_amount
                    trade_type = "dca"
            elif action == "reduce" and units > 0 and portfolio_before > 0:
                target_holding = portfolio_before * 0.35
                trade_amount = max(0.0, holding_value - target_holding)
                sell_units = min(units, trade_amount / price) if price > 0 else 0.0
                if sell_units > 0.000001:
                    trade_amount = sell_units * price
                    fee = trade_amount * redemption_fee_pct / 100
                    unit_delta = -sell_units
                    cash_delta = trade_amount - fee
                    trade_type = "sell"
            elif action == "sell_watch" and units > 0:
                sell_units = units
                trade_amount = sell_units * price
                fee = trade_amount * redemption_fee_pct / 100
                unit_delta = -sell_units
                cash_delta = trade_amount - fee
                trade_type = "sell"

            if trade_type != "hold":
                cash += cash_delta
                units += unit_delta
                if abs(cash) < 0.000001:
                    cash = 0.0
                if abs(units) < 0.000000001:
                    units = 0.0
                trade_events.append(
                    {
                        "idx": int(idx),
                        "date": signal_date,
                        "action": action,
                        "trade_type": trade_type,
                        "cash_delta": cash_delta,
                        "unit_delta": unit_delta,
                        "trade_amount": _round_money(trade_amount),
                        "fee": _round_money(fee),
                        "nav": round(price, 4),
                    }
                )

            portfolio_after = cash + units * price
            end_idx = idx + eval_window_days
            end_row = frame.iloc[end_idx]
            end_price = float(end_row["unit_nav"])
            forward_frame = frame.iloc[idx : end_idx + 1]
            fund_forward_return_pct = (end_price / price - 1) * 100 if price > 0 else None
            fund_forward_drawdown_pct = _max_drawdown(forward_frame["unit_nav"].to_numpy(dtype=float))
            strategy_end_value = cash + units * end_price
            strategy_forward_return_pct = (
                (strategy_end_value / portfolio_after - 1) * 100
                if portfolio_after > 0
                else None
            )
            outcome = _classify_backtest_outcome(
                action=action,
                forward_return_pct=fund_forward_return_pct,
                forward_drawdown_pct=fund_forward_drawdown_pct,
                neutral_band_pct=neutral_band_pct,
            )
            exposure_pct = (units * price / portfolio_after * 100) if portfolio_after > 0 else 0.0
            signal_items.append(
                {
                    "signal_date": signal_date,
                    "evaluation_end_date": end_row["date"].date().isoformat(),
                    "action": action,
                    "action_label": action_label,
                    "risk_score": _safe_percent(_to_float(signal.get("risk_score"))),
                    "signal_score": _safe_percent(_to_float(signal.get("signal_score"))),
                    "nav": round(price, 4),
                    "portfolio_value": _round_money(portfolio_after),
                    "cash": _round_money(cash),
                    "units": round(units, 6),
                    "exposure_pct": round(exposure_pct, 2),
                    "trade_type": trade_type,
                    "trade_amount": _round_money(trade_amount),
                    "fee": _round_money(fee),
                    "fund_forward_return_pct": _safe_percent(fund_forward_return_pct),
                    "fund_forward_drawdown_pct": _safe_percent(fund_forward_drawdown_pct),
                    "strategy_forward_return_pct": _safe_percent(strategy_forward_return_pct),
                    **outcome,
                    "reasons": list(signal.get("reasons") or [])[:5],
                }
            )

        portfolio_curve = _portfolio_curve_from_events(frame, events=trade_events, initial_cash=initial_cash)
        final_value = _to_float(portfolio_curve[-1]["value"]) if portfolio_curve else initial_cash
        first_anchor_idx = anchor_indices[0]
        start_nav = float(frame.iloc[first_anchor_idx]["unit_nav"])
        final_nav = float(frame.iloc[-1]["unit_nav"])
        benchmark_fee = initial_cash * subscription_fee_pct / 100
        benchmark_units = max(0.0, initial_cash - benchmark_fee) / start_nav
        benchmark_final_value = benchmark_units * final_nav
        strategy_return_pct = (final_value / initial_cash - 1) * 100 if final_value is not None else None
        buy_hold_return_pct = (benchmark_final_value / initial_cash - 1) * 100
        excess_return_pct = (
            strategy_return_pct - buy_hold_return_pct
            if strategy_return_pct is not None
            else None
        )
        strategy_drawdown_pct = _max_drawdown(np.array([item["value"] for item in portfolio_curve], dtype=float))
        fund_drawdown_pct = _max_drawdown(frame.iloc[first_anchor_idx:]["unit_nav"].to_numpy(dtype=float))
        wins = sum(1 for item in signal_items if item.get("outcome") == "win")
        losses = sum(1 for item in signal_items if item.get("outcome") == "loss")
        neutral = sum(1 for item in signal_items if item.get("outcome") == "neutral")
        evaluated = wins + losses
        action_distribution: Dict[str, int] = {}
        for item in signal_items:
            action_distribution[str(item.get("action") or "unknown")] = action_distribution.get(str(item.get("action") or "unknown"), 0) + 1
        total_fees = sum(float(event.get("fee") or 0.0) for event in trade_events)
        active_curve = portfolio_curve[first_anchor_idx:] if len(portfolio_curve) > first_anchor_idx else portfolio_curve
        avg_exposure = (
            sum(float(item.get("exposure_pct") or 0.0) for item in active_curve) / len(active_curve)
            if active_curve
            else 0.0
        )

        return {
            "code": code,
            "name": name,
            "fund_type": fund_type,
            "status": "completed",
            "engine_version": FUND_BACKTEST_ENGINE_VERSION,
            "parameters": parameters,
            "summary": {
                "sample_days": int(len(frame)),
                "start_date": frame.iloc[first_anchor_idx]["date"].date().isoformat(),
                "end_date": frame.iloc[-1]["date"].date().isoformat(),
                "signal_count": int(len(signal_items)),
                "wins": int(wins),
                "losses": int(losses),
                "neutral": int(neutral),
                "hit_rate_pct": _safe_percent(wins / evaluated * 100) if evaluated else None,
                "strategy_final_value": _round_money(final_value or 0.0),
                "buy_hold_final_value": _round_money(benchmark_final_value),
                "strategy_return_pct": _safe_percent(strategy_return_pct),
                "buy_hold_return_pct": _safe_percent(buy_hold_return_pct),
                "excess_return_pct": _safe_percent(excess_return_pct),
                "max_drawdown_strategy_pct": _safe_percent(strategy_drawdown_pct),
                "max_drawdown_fund_pct": _safe_percent(fund_drawdown_pct),
                "transaction_count": int(len(trade_events)),
                "total_fees": _round_money(total_fees),
                "fee_drag_pct": _safe_percent(total_fees / initial_cash * 100),
                "avg_exposure_pct": round(avg_exposure, 2),
                "action_distribution": action_distribution,
                "avg_forward_return_by_action": _average_by_action(signal_items, "fund_forward_return_pct"),
            },
            "signals": signal_items,
            "portfolio_curve": portfolio_curve[-260:],
            "fee_assumptions": fee_assumptions,
            "methodology": methodology,
            "limitations": base_limitations,
        }

    def calibrate_backtests(
        self,
        *,
        ledger_id: Optional[int] = None,
        fund_type: Optional[str] = None,
        codes: Optional[List[str]] = None,
        lookback_days: int = 252,
        eval_window_days: int = 60,
        rebalance_interval_days: int = 20,
        initial_cash: float = 10000.0,
    ) -> Dict[str, Any]:
        from src.services.fund_backtest_calibration import calibrate_fund_backtests

        normalized_codes = [normalize_fund_code(code) for code in codes] if codes else None
        lookback_days = int(lookback_days)
        eval_window_days = int(eval_window_days)
        rebalance_interval_days = int(rebalance_interval_days)
        initial_cash = float(initial_cash)
        if ledger_id is not None:
            ledger_id = int(ledger_id)
        if lookback_days < 60:
            raise ValueError("lookback_days 至少需要 60")
        if eval_window_days < 5:
            raise ValueError("eval_window_days 至少需要 5")
        if rebalance_interval_days < 5:
            raise ValueError("rebalance_interval_days 至少需要 5")
        if initial_cash <= 0:
            raise ValueError("initial_cash 必须大于 0")

        return calibrate_fund_backtests(
            pool=self.list_pool(),
            backtest_runner=lambda code: self.backtest(
                code,
                lookback_days=lookback_days,
                eval_window_days=eval_window_days,
                rebalance_interval_days=rebalance_interval_days,
                initial_cash=initial_cash,
            ),
            ledger_id=ledger_id,
            fund_type=(fund_type or "").strip() or None,
            codes=normalized_codes,
            lookback_days=lookback_days,
            eval_window_days=eval_window_days,
            rebalance_interval_days=rebalance_interval_days,
            initial_cash=initial_cash,
        )

    def _analyze(
        self,
        item: FundPoolItem,
        *,
        latest_quote: Optional[FundLatestQuote],
        peer: Optional[Dict[str, Any]],
        risk_analysis: Optional[Dict[str, Any]],
        extra_limitations: List[str],
    ) -> Dict[str, Any]:
        df = self.repo.get_nav_dataframe(item.code)
        metrics, metric_limitations = calculate_nav_metrics(df)
        metrics = apply_direct_fund_metrics(metrics, peer=peer, risk_analysis=risk_analysis)
        limitations = list(dict.fromkeys(extra_limitations + metric_limitations))
        taxonomy = infer_fund_taxonomy(item.name, item.fund_type)
        strategy_policy = build_strategy_policy(taxonomy)
        market_snapshot = self._fetch_market_snapshot(
            code=item.code,
            taxonomy=taxonomy,
            limitations=limitations,
        )
        trading_rules = self._fetch_trading_rules(
            code=item.code,
            latest_quote=latest_quote,
            limitations=limitations,
        )
        research_evidence = self._collect_research_evidence(
            code=item.code,
            name=item.name,
            taxonomy=taxonomy,
            market_snapshot=market_snapshot,
        )
        limitations = list(dict.fromkeys(limitations))
        signal = build_fund_signal(
            metrics=metrics,
            peer=peer,
            latest_quote=latest_quote,
            fund_type=item.fund_type,
            limitations=limitations,
            taxonomy=taxonomy,
            strategy_policy=strategy_policy,
        )
        profile = build_fund_profile(
            code=item.code,
            name=item.name,
            fund_type=item.fund_type,
            metrics=metrics,
            peer=peer,
            latest_quote=latest_quote,
            risk_analysis=risk_analysis,
            trading_rules=trading_rules,
            market_snapshot=market_snapshot,
            research_evidence=research_evidence,
            limitations=limitations,
        )
        latest_date = metrics.get("latest_date") or (latest_quote.nav_date.isoformat() if latest_quote and latest_quote.nav_date else None)
        analysis_date = latest_date or date.today().isoformat()
        quality_detail = profile.get("data_quality_detail") if isinstance(profile.get("data_quality_detail"), dict) else {}
        quality_summary = profile.get("data_quality") if isinstance(profile.get("data_quality"), dict) else {}
        overall_quality = str(quality_detail.get("overall_status") or quality_summary.get("overall_status") or "partial")
        data_quality = overall_quality if overall_quality in {"ok", "partial"} else "partial"
        if not metrics.get("latest_nav") and overall_quality == "missing":
            data_quality = "limited"
        signal_context = signal.get("signal_context")
        if isinstance(signal_context, dict):
            signal_context = build_signal_context_v3(
                base_context=signal_context,
                signal=signal,
                metrics=metrics,
                profile=profile,
                trading_rules=trading_rules,
                latest_quote=latest_quote,
            )
        return {
            "code": item.code,
            "name": item.name,
            "fund_type": item.fund_type,
            "analysis_date": analysis_date,
            "action": signal["action"],
            "action_label": signal["action_label"],
            "risk_level": signal["risk_level"],
            "risk_score": signal["risk_score"],
            "signal_score": signal["signal_score"],
            "summary": signal["summary"],
            "metrics": {
                **metrics,
                "purchase_status": latest_quote.purchase_status if latest_quote else None,
                "redemption_status": latest_quote.redemption_status if latest_quote else None,
                "fee": latest_quote.fee if latest_quote else None,
                "profile": profile,
                "data_quality": quality_summary,
                "data_quality_detail": quality_detail,
                "trading_rules": trading_rules,
                "signal_context": signal_context,
            },
            "peer": peer,
            "reasons": signal["reasons"],
            "data_quality": data_quality,
            "limitations": limitations,
        }


def calculate_nav_metrics(df: pd.DataFrame) -> Tuple[Dict[str, Any], List[str]]:
    limitations: List[str] = []
    if df.empty:
        return {
            "latest_nav": None,
            "latest_date": None,
            "sample_days": 0,
        }, ["本地暂无历史净值"]

    frame = df.copy()
    frame["date"] = pd.to_datetime(frame["date"])
    frame["unit_nav"] = pd.to_numeric(frame["unit_nav"], errors="coerce")
    frame = frame.dropna(subset=["date", "unit_nav"]).sort_values("date")
    if frame.empty:
        return {"latest_nav": None, "latest_date": None, "sample_days": 0}, ["历史净值缺少可计算单位净值"]

    latest = frame.iloc[-1]
    latest_date = latest["date"].date()
    latest_nav = float(latest["unit_nav"])
    returns = {
        "1w": _period_return(frame, latest_date, latest_nav, days=7),
        "1m": _period_return(frame, latest_date, latest_nav, days=30),
        "3m": _period_return(frame, latest_date, latest_nav, days=90),
        "6m": _period_return(frame, latest_date, latest_nav, days=180),
        "1y": _period_return(frame, latest_date, latest_nav, days=365),
        "ytd": _ytd_return(frame, latest_date, latest_nav),
    }
    recent_1y = frame[frame["date"] >= pd.Timestamp(latest_date - timedelta(days=365))]
    if len(recent_1y) < 60:
        limitations.append("历史净值不足 60 条，风险指标参考价值有限")
    daily_returns = recent_1y["unit_nav"].pct_change().dropna()
    volatility = None
    if not daily_returns.empty:
        volatility = float(daily_returns.std(ddof=0) * math.sqrt(252) * 100)
    max_drawdown = _max_drawdown(recent_1y["unit_nav"].to_numpy(dtype=float))
    annual_return = returns.get("1y")
    sharpe = None
    if annual_return is not None and volatility and volatility > 0:
        sharpe = annual_return / volatility
    ma20 = _rolling_mean(frame, 20)
    ma60 = _rolling_mean(frame, 60)
    trend_state = "unknown"
    if ma20 is not None and ma60 is not None:
        if latest_nav >= ma20 >= ma60:
            trend_state = "uptrend"
        elif latest_nav < ma20 < ma60:
            trend_state = "downtrend"
        else:
            trend_state = "sideways"
    return {
        "latest_nav": round(latest_nav, 4),
        "latest_date": latest_date.isoformat(),
        "sample_days": int(len(frame)),
        "returns": {key: _safe_percent(value) for key, value in returns.items()},
        "max_drawdown_1y_pct": _safe_percent(max_drawdown),
        "volatility_1y_pct": _safe_percent(volatility),
        "sharpe_1y": round(sharpe, 2) if sharpe is not None else None,
        "ma20": round(ma20, 4) if ma20 is not None else None,
        "ma60": round(ma60, 4) if ma60 is not None else None,
        "trend_state": trend_state,
    }, limitations


def apply_direct_fund_metrics(
    metrics: Dict[str, Any],
    *,
    peer: Optional[Dict[str, Any]],
    risk_analysis: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    """Prefer provider-published metrics and keep NAV-derived values as fallback."""
    merged = dict(metrics)
    sources = {
        "returns": "nav_calculation",
        "risk": "nav_calculation",
    }
    returns = dict(merged.get("returns") or {})
    peer_returns = peer.get("returns") if isinstance(peer, dict) else None
    if isinstance(peer_returns, dict):
        for _, key in FUND_RETURN_COLUMNS:
            value = _to_float(peer_returns.get(key))
            if value is not None:
                returns[key] = round(value, 2)
        sources["returns"] = "fund_open_fund_rank_em"
    merged["returns"] = returns

    if isinstance(risk_analysis, dict):
        for key in ("max_drawdown_1y_pct", "volatility_1y_pct", "sharpe_1y"):
            value = _to_float(risk_analysis.get(key))
            if value is not None:
                merged[key] = round(value, 2)
        if risk_analysis.get("peer_risk_return_ratio") is not None:
            merged["peer_risk_return_ratio"] = risk_analysis.get("peer_risk_return_ratio")
        if risk_analysis.get("peer_anti_volatility") is not None:
            merged["peer_anti_volatility"] = risk_analysis.get("peer_anti_volatility")
        if risk_analysis.get("period"):
            merged["risk_metric_period"] = risk_analysis.get("period")
        sources["risk"] = str(risk_analysis.get("source") or "fund_individual_analysis_xq")
    merged["metric_sources"] = sources
    return merged


def _period_return(frame: pd.DataFrame, latest_date: date, latest_nav: float, *, days: int) -> Optional[float]:
    cutoff = pd.Timestamp(latest_date - timedelta(days=days))
    candidates = frame[frame["date"] >= cutoff]
    if candidates.empty:
        return None
    start_nav = _to_float(candidates.iloc[0]["unit_nav"])
    if not start_nav or start_nav <= 0:
        return None
    return (latest_nav / start_nav - 1) * 100


def _ytd_return(frame: pd.DataFrame, latest_date: date, latest_nav: float) -> Optional[float]:
    start = pd.Timestamp(date(latest_date.year, 1, 1))
    candidates = frame[frame["date"] >= start]
    if candidates.empty:
        return None
    start_nav = _to_float(candidates.iloc[0]["unit_nav"])
    if not start_nav or start_nav <= 0:
        return None
    return (latest_nav / start_nav - 1) * 100


def _rolling_mean(frame: pd.DataFrame, window: int) -> Optional[float]:
    if len(frame) < window:
        return None
    value = frame["unit_nav"].tail(window).mean()
    return _to_float(value)


def _max_drawdown(values: np.ndarray) -> Optional[float]:
    if values.size < 2:
        return None
    cumulative_max = np.maximum.accumulate(values)
    drawdowns = values / cumulative_max - 1
    return float(drawdowns.min() * 100)


def build_fund_signal(
    *,
    metrics: Dict[str, Any],
    peer: Optional[Dict[str, Any]],
    latest_quote: Optional[FundLatestQuote],
    fund_type: Optional[str],
    limitations: List[str],
    taxonomy: Optional[Dict[str, Any]] = None,
    strategy_policy: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    taxonomy = taxonomy or infer_fund_taxonomy(None, fund_type)
    strategy_policy = strategy_policy or build_strategy_policy(taxonomy)
    return_weights = strategy_policy.get("return_weights") if isinstance(strategy_policy.get("return_weights"), dict) else {}
    risk_weights = strategy_policy.get("risk_weights") if isinstance(strategy_policy.get("risk_weights"), dict) else {}
    trend_bonus = strategy_policy.get("trend_bonus") if isinstance(strategy_policy.get("trend_bonus"), dict) else {}
    thresholds = strategy_policy.get("action_thresholds") if isinstance(strategy_policy.get("action_thresholds"), dict) else {}
    risk_baseline = _to_float(strategy_policy.get("risk_baseline")) or 30.0
    volatility_floor = _to_float(strategy_policy.get("volatility_floor_pct")) or 8.0
    drawdown_alert = _to_float(strategy_policy.get("drawdown_alert_pct")) or -20.0
    drawdown_stop = _to_float(strategy_policy.get("drawdown_stop_pct")) or -32.0
    risk_gate = _to_float(strategy_policy.get("risk_gate")) or 70.0
    returns = metrics.get("returns") or {}
    r_3m = returns.get("3m")
    r_6m = returns.get("6m")
    r_1y = returns.get("1y")
    drawdown = metrics.get("max_drawdown_1y_pct")
    volatility = metrics.get("volatility_1y_pct")
    trend = metrics.get("trend_state")
    peer_1y = None
    if peer and isinstance(peer.get("percentiles"), dict):
        peer_1y = peer["percentiles"].get("1y")

    if taxonomy.get("strategy_family") == "money_market":
        reasons = ["货币基金需要七日年化、万份收益、规模和流动性数据，当前仅做观察"]
        return {
            "action": "watch",
            "action_label": "观察",
            "risk_level": "低",
            "risk_score": round(risk_baseline, 1),
            "signal_score": 45.0,
            "summary": "观察：货币基金专用收益和流动性数据尚未接入，当前不生成申购/赎回建议。",
            "reasons": reasons,
            "signal_context": {
                "signal_model_version": FUND_SIGNAL_MODEL_VERSION,
                "strategy_family": taxonomy.get("strategy_family"),
                "policy_version": strategy_policy.get("policy_version"),
                "policy_source": strategy_policy.get("source"),
                "validation_status": strategy_policy.get("validation_status"),
                "risk_gate": risk_gate,
                "action_thresholds": thresholds,
            },
        }

    risk_score = risk_baseline
    if volatility is not None:
        risk_score += min(max(volatility - volatility_floor, 0) * (_to_float(risk_weights.get("volatility")) or 1.4), 28)
    if drawdown is not None:
        risk_score += min(abs(min(drawdown, 0)) * (_to_float(risk_weights.get("drawdown")) or 1.1), 32)
    if r_3m is not None and r_3m < -8:
        risk_score += _to_float(risk_weights.get("recent_loss")) or 10
    risk_score = round(max(0, min(100, risk_score)), 1)

    signal_score = 50.0
    if r_3m is not None:
        signal_score += max(min(r_3m * (_to_float(return_weights.get("3m")) or 0.8), 16), -18)
    if r_6m is not None:
        signal_score += max(min(r_6m * (_to_float(return_weights.get("6m")) or 0.35), 12), -12)
    if r_1y is not None:
        signal_score += max(min(r_1y * (_to_float(return_weights.get("1y")) or 0.18), 12), -12)
    if peer_1y is not None:
        signal_score += (peer_1y - 50) * (_to_float(return_weights.get("peer_1y")) or 0.22)
    if trend == "uptrend":
        signal_score += _to_float(trend_bonus.get("uptrend")) or 8
    elif trend == "downtrend":
        signal_score += _to_float(trend_bonus.get("downtrend")) or -10
    if drawdown is not None and drawdown < drawdown_alert:
        signal_score -= 10
    if risk_score > risk_gate:
        signal_score -= 8
    purchase_status = (latest_quote.purchase_status or "") if latest_quote else ""
    if purchase_status and "暂停" in purchase_status:
        signal_score -= 15
    signal_score = round(max(0, min(100, signal_score)), 1)

    risk_level = "低"
    if risk_score >= 70:
        risk_level = "高"
    elif risk_score >= 48:
        risk_level = "中"

    action = "watch"
    action_label = "观望"
    if purchase_status and "暂停" in purchase_status:
        action = "pause_buy"
        action_label = "暂停申购"
    elif risk_score >= risk_gate:
        if drawdown is not None and drawdown <= drawdown_stop:
            action = "reduce"
            action_label = "暂停定投/减仓"
        else:
            action = "watch"
            action_label = "高风险观察"
    elif signal_score >= (_to_float(thresholds.get("buy")) or 72) and risk_score < risk_gate:
        action = "buy"
        action_label = "分批申购"
    elif signal_score >= (_to_float(thresholds.get("dca")) or 58):
        action = "dca"
        action_label = "定投跟踪"
    elif signal_score >= (_to_float(thresholds.get("watch")) or 45):
        action = "watch"
        action_label = "观望"
    elif signal_score >= (_to_float(thresholds.get("reduce")) or 30):
        action = "reduce"
        action_label = "暂停定投/减仓"
    else:
        action = "sell_watch"
        action_label = "赎回观察"

    reasons = []
    if r_3m is not None:
        reasons.append(f"近 3 月收益 {r_3m:.2f}%")
    if drawdown is not None:
        reasons.append(f"近 1 年最大回撤 {drawdown:.2f}%")
    if volatility is not None:
        reasons.append(f"近 1 年年化波动 {volatility:.2f}%")
    if peer_1y is not None:
        reasons.append(f"同类近 1 年分位约 {peer_1y:.1f}%")
    if trend and trend != "unknown":
        trend_label = {"uptrend": "上行", "sideways": "震荡", "downtrend": "下行"}.get(trend, trend)
        reasons.append(f"净值趋势为{trend_label}")
    if not reasons:
        reasons.append("历史净值样本不足，暂以数据质量为主")
    if strategy_policy.get("label"):
        reasons.append(f"策略参数：{strategy_policy.get('label')}（未回测校准）")
    reasons.append("执行边界：规则信号不读取个人账户，也不会自动交易")

    summary = f"{action_label}：信号分 {signal_score:.1f}，风险 {risk_level}（{risk_score:.1f}）。"
    if limitations:
        summary += " 当前存在数据边界，建议作为跟踪信号而非自动交易指令。"
    else:
        summary += " 当前为分类型初始规则，仍需结合自身期限、仓位约束和回测校准执行。"

    return {
        "action": action,
        "action_label": action_label,
        "risk_level": risk_level,
        "risk_score": risk_score,
        "signal_score": signal_score,
        "summary": summary,
        "reasons": reasons,
        "signal_context": {
            "signal_model_version": FUND_SIGNAL_MODEL_VERSION,
            "strategy_family": taxonomy.get("strategy_family"),
            "policy_version": strategy_policy.get("policy_version"),
            "policy_source": strategy_policy.get("source"),
            "validation_status": strategy_policy.get("validation_status"),
            "risk_gate": risk_gate,
            "drawdown_alert_pct": drawdown_alert,
            "drawdown_stop_pct": drawdown_stop,
            "action_thresholds": thresholds,
        },
    }
