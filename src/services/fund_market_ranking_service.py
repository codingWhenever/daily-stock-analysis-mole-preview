# -*- coding: utf-8 -*-
"""Market-level public fund ranking aggregation."""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd

from src.services.fund_service import FUND_RETURN_COLUMNS, _call_with_timeout, _iso_date, _to_float

logger = logging.getLogger(__name__)


MARKET_FUND_RANKING_SCHEMA_VERSION = "market_fund_ranking_v1"
AKSHARE_FUND_PUBLIC_DOC_URL = "https://akshare.akfamily.xyz/data/fund/fund_public.html"
EASTMONEY_ETF_QUOTE_URL = "https://quote.eastmoney.com/center/gridlist.html#fund_etf"
EASTMONEY_OPEN_FUND_RANK_URL = "https://fund.eastmoney.com/data/fundranking.html"

TRUE_BUY_SELL_UNSUPPORTED = {
    "actual_buy_amount": None,
    "actual_sell_amount": None,
    "actual_buy_count": None,
    "actual_sell_count": None,
    "actual_subscription_amount": None,
    "actual_redemption_amount": None,
    "availability": "not_supported",
    "reason": "公开行情/排行不披露基金级真实买入金额、卖出金额、买入笔数或卖出笔数",
}


def _first_value(row: Dict[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in row and row.get(key) not in (None, ""):
            return row.get(key)
    return None


def _infer_exchange(code: str) -> str:
    text = str(code or "")
    if text.startswith(("50", "51", "52", "56", "58", "588", "589")):
        return "sse"
    if text.startswith(("15", "16", "18", "159")):
        return "szse"
    return "eastmoney"


def _parse_timestamp(value: Any) -> Optional[datetime]:
    if value is None:
        return None
    try:
        parsed = pd.to_datetime(value, errors="coerce")
    except (TypeError, ValueError):
        return None
    if pd.isna(parsed):
        return None
    try:
        return parsed.to_pydatetime()
    except AttributeError:
        return None


def _freshness(data_date: Any, fetched_at: datetime, update_window: str, timestamp: Any = None) -> Dict[str, Any]:
    source_time = _parse_timestamp(timestamp)
    age_minutes = None
    if source_time is not None:
        if source_time.tzinfo is not None and fetched_at.tzinfo is None:
            source_time = source_time.replace(tzinfo=None)
        age_minutes = round(max((fetched_at - source_time).total_seconds() / 60.0, 0.0), 1)
    return {
        "data_date": _iso_date(data_date) or _iso_date(timestamp),
        "fetched_at": fetched_at.isoformat(timespec="seconds"),
        "age_minutes": age_minutes,
        "update_window": update_window,
    }


def _score_from_rank(rank: int, total: int) -> float:
    if total <= 1:
        return 100.0
    return round(max(0.0, 100.0 - ((rank - 1) / max(total - 1, 1)) * 100.0), 2)


def _status_for_rows(rows: List[Dict[str, Any]], proxy_only: bool = False) -> str:
    if not rows:
        return "missing"
    return "proxy_only" if proxy_only else "ok"


class FundMarketRankingService:
    """Build public market-level rankings without using personal holdings."""

    def __init__(self, provider: Any):
        self.provider = provider

    def build_market_rankings(self, *, limit: int = 10, fund_type: str = "全部") -> Dict[str, Any]:
        limit = max(1, min(int(limit or 10), 30))
        fetched_at = datetime.now()
        groups: List[Dict[str, Any]] = []
        limitations: List[str] = [
            "市场级榜单只使用公开行情、资金流和基金排行，不读取用户画像、账本、持仓或成本价。",
            "公开数据无法证明基金级真实买入笔数、卖出笔数、申购金额或赎回金额；相关字段保持 null。",
        ]

        etf_df: Optional[pd.DataFrame] = None
        try:
            etf_df = _call_with_timeout("ETF 实时资金流", self.provider.etf_spot, timeout=35)
        except Exception as exc:  # noqa: BLE001
            logger.warning("ETF 市场榜单获取失败: %s", exc)
            groups.extend(self._failed_etf_groups(fetched_at, str(exc)))

        if etf_df is not None:
            groups.append(self._build_etf_flow_group(etf_df, fetched_at, limit=limit, direction="inflow"))
            groups.append(self._build_etf_flow_group(etf_df, fetched_at, limit=limit, direction="outflow"))
            groups.append(self._build_etf_turnover_group(etf_df, fetched_at, limit=limit))

        try:
            open_rank_df = _call_with_timeout(
                f"开放式基金收益排行 {fund_type}",
                lambda: self.provider.open_fund_rank(fund_type or "全部"),
                timeout=12,
            )
            daily_df = self._safe_open_fund_daily()
            groups.append(self._build_open_fund_return_group(open_rank_df, daily_df, fetched_at, limit=limit, fund_type=fund_type))
        except Exception as exc:  # noqa: BLE001
            logger.warning("开放式基金市场榜单获取失败: %s", exc)
            groups.append(self._failed_group(
                rank_type="open_fund_return_rank",
                title="开放式基金收益实证榜",
                source="akshare.fund_open_fund_rank_em",
                source_url=EASTMONEY_OPEN_FUND_RANK_URL,
                fetched_at=fetched_at,
                reason=str(exc),
            ))

        response_status = "completed" if any(group.get("items") for group in groups) else "failed"
        if any(group.get("status") in {"failed", "missing"} for group in groups) and response_status == "completed":
            response_status = "partial"
        as_of_date = self._latest_group_date(groups)
        return {
            "schema_version": MARKET_FUND_RANKING_SCHEMA_VERSION,
            "status": response_status,
            "as_of_date": as_of_date,
            "fetched_at": fetched_at.isoformat(timespec="seconds"),
            "scope": {
                "level": "market",
                "fund_type": fund_type or "全部",
                "limit": limit,
                "ranking_types": [group["rank_type"] for group in groups],
            },
            "personalization": {
                "status": "market_only",
                "user_profile_used": False,
                "holdings_used": False,
                "personal_actions_supported": False,
                "requires_profile_for_personal_action": True,
                "requires_confirmed_holdings_for_personal_action": True,
            },
            "groups": groups,
            "recommendation_candidates": self._build_market_seed_candidates(groups, limit=limit),
            "limitations": limitations,
        }

    def _safe_open_fund_daily(self) -> Optional[pd.DataFrame]:
        try:
            return _call_with_timeout("开放式基金日榜", self.provider.open_fund_daily, timeout=10)
        except Exception as exc:  # noqa: BLE001
            logger.debug("开放式基金交易状态获取失败: %s", exc)
            return None

    def _failed_etf_groups(self, fetched_at: datetime, reason: str) -> List[Dict[str, Any]]:
        return [
            self._failed_group("etf_net_inflow", "ETF 资金流入榜", "akshare.fund_etf_spot_em", EASTMONEY_ETF_QUOTE_URL, fetched_at, reason),
            self._failed_group("etf_net_outflow", "ETF 资金流出榜", "akshare.fund_etf_spot_em", EASTMONEY_ETF_QUOTE_URL, fetched_at, reason),
            self._failed_group("etf_turnover_heat", "ETF 成交热度榜", "akshare.fund_etf_spot_em", EASTMONEY_ETF_QUOTE_URL, fetched_at, reason),
        ]

    def _failed_group(
        self,
        rank_type: str,
        title: str,
        source: str,
        source_url: str,
        fetched_at: datetime,
        reason: str,
    ) -> Dict[str, Any]:
        return {
            "rank_type": rank_type,
            "title": title,
            "description": "公开数据源暂不可用，未生成该榜单。",
            "status": "failed",
            "source": source,
            "source_url": source_url,
            "freshness": _freshness(None, fetched_at, "unknown"),
            "items": [],
            "limitations": [reason or "公开数据源返回失败"],
        }

    def _build_etf_flow_group(self, df: pd.DataFrame, fetched_at: datetime, *, limit: int, direction: str) -> Dict[str, Any]:
        positive = direction == "inflow"
        rows = self._normalize_etf_rows(df, fetched_at)
        rows = [
            row for row in rows
            if row["metrics"].get("main_net_inflow_amount") is not None
            and (row["metrics"]["main_net_inflow_amount"] > 0 if positive else row["metrics"]["main_net_inflow_amount"] < 0)
        ]
        rows.sort(key=lambda row: row["metrics"]["main_net_inflow_amount"] or 0.0, reverse=positive)
        selected = rows[:limit]
        total = len(selected)
        for index, row in enumerate(selected, start=1):
            row["rank"] = index
            row["score"] = _score_from_rank(index, total)
            row["recommendation_role"] = "market_buy_evidence" if positive else "market_sell_risk_evidence"
            if not positive:
                row["metrics"]["proxy_net_outflow_amount"] = abs(row["metrics"].get("main_net_inflow_amount") or 0.0)
        return {
            "rank_type": "etf_net_inflow" if positive else "etf_net_outflow",
            "title": "ETF 资金流入榜" if positive else "ETF 资金流出榜",
            "description": "按东方财富 ETF 主力净流入口径排序，属于二级市场资金流代理，不等同申购/赎回。",
            "status": _status_for_rows(selected, proxy_only=True),
            "source": "akshare.fund_etf_spot_em",
            "source_url": EASTMONEY_ETF_QUOTE_URL,
            "freshness": self._etf_group_freshness(df, fetched_at),
            "items": selected,
            "limitations": [
                "主力净流入为交易资金流口径，不代表基金公司确认申购金额。",
                "未披露真实买入/卖出笔数，不能作为个人交易动作依据。",
            ],
        }

    def _build_etf_turnover_group(self, df: pd.DataFrame, fetched_at: datetime, *, limit: int) -> Dict[str, Any]:
        rows = [
            row for row in self._normalize_etf_rows(df, fetched_at)
            if row["metrics"].get("amount") is not None and row["metrics"].get("amount") > 0
        ]
        rows.sort(key=lambda row: row["metrics"].get("amount") or 0.0, reverse=True)
        selected = rows[:limit]
        total = len(selected)
        for index, row in enumerate(selected, start=1):
            row["rank"] = index
            row["score"] = _score_from_rank(index, total)
            row["recommendation_role"] = "market_liquidity_evidence"
        return {
            "rank_type": "etf_turnover_heat",
            "title": "ETF 成交热度榜",
            "description": "按 ETF 成交额排序，用于识别市场关注度和流动性，不代表买入推荐。",
            "status": _status_for_rows(selected),
            "source": "akshare.fund_etf_spot_em",
            "source_url": EASTMONEY_ETF_QUOTE_URL,
            "freshness": self._etf_group_freshness(df, fetched_at),
            "items": selected,
            "limitations": [
                "成交额只描述二级市场交易热度，不能区分主动买入、主动卖出或净申赎。",
            ],
        }

    def _normalize_etf_rows(self, df: pd.DataFrame, fetched_at: datetime) -> List[Dict[str, Any]]:
        if df is None or df.empty:
            return []
        records: List[Dict[str, Any]] = []
        for raw in df.to_dict(orient="records"):
            code = str(_first_value(raw, "代码", "基金代码") or "").zfill(6)
            if not code or code == "000000":
                continue
            data_date = _first_value(raw, "数据日期", "日期")
            update_time = _first_value(raw, "更新时间", "更新日期")
            main_net = _to_float(_first_value(raw, "主力净流入-净额", "主力净流入"))
            amount = _to_float(_first_value(raw, "成交额", "成交金额"))
            metrics = {
                "latest_price": _to_float(_first_value(raw, "最新价", "最新")),
                "change_pct": _to_float(_first_value(raw, "涨跌幅", "涨跌幅%")),
                "amount": amount,
                "volume": _to_float(_first_value(raw, "成交量")),
                "turnover_rate": _to_float(_first_value(raw, "换手率")),
                "main_net_inflow_amount": main_net,
                "main_net_inflow_pct": _to_float(_first_value(raw, "主力净流入-净占比")),
                "super_large_order_net_inflow_amount": _to_float(_first_value(raw, "超大单净流入-净额")),
                "large_order_net_inflow_amount": _to_float(_first_value(raw, "大单净流入-净额")),
                "middle_order_net_inflow_amount": _to_float(_first_value(raw, "中单净流入-净额")),
                "small_order_net_inflow_amount": _to_float(_first_value(raw, "小单净流入-净额")),
                "outer_volume": _to_float(_first_value(raw, "外盘")),
                "inner_volume": _to_float(_first_value(raw, "内盘")),
                "latest_share": _to_float(_first_value(raw, "最新份额")),
                "flow_market_value": _to_float(_first_value(raw, "流通市值")),
                "total_market_value": _to_float(_first_value(raw, "总市值")),
                "proxy_net_inflow_amount": main_net,
                "proxy_turnover_amount": amount,
            }
            records.append({
                "rank": 0,
                "code": code,
                "name": str(_first_value(raw, "名称", "基金简称") or "") or None,
                "fund_type": "ETF",
                "market": _infer_exchange(code),
                "score": None,
                "status": "proxy_only",
                "proxy_type": "eastmoney_etf_trade_flow",
                "recommendation_role": None,
                "metrics": metrics,
                "evidence_metrics": {
                    **TRUE_BUY_SELL_UNSUPPORTED,
                    "proxy_net_inflow_amount": main_net,
                    "proxy_turnover_amount": amount,
                    "proxy_fields": ["main_net_inflow_amount", "amount", "volume", "turnover_rate"],
                },
                "source": "akshare.fund_etf_spot_em",
                "source_url": EASTMONEY_ETF_QUOTE_URL,
                "freshness": _freshness(data_date, fetched_at, "交易时段 10-15 分钟；收盘后冻结日快照", update_time),
                "limitations": ["ETF 资金流和成交热度是公开交易代理指标，不等同真实申购/赎回。"],
            })
        return records

    def _etf_group_freshness(self, df: pd.DataFrame, fetched_at: datetime) -> Dict[str, Any]:
        data_date = None
        update_time = None
        if df is not None and not df.empty:
            first = df.iloc[0].to_dict()
            data_date = _first_value(first, "数据日期", "日期")
            update_time = _first_value(first, "更新时间", "更新日期")
        return _freshness(data_date, fetched_at, "交易时段 10-15 分钟；收盘后冻结日快照", update_time)

    def _build_open_fund_return_group(
        self,
        rank_df: pd.DataFrame,
        daily_df: Optional[pd.DataFrame],
        fetched_at: datetime,
        *,
        limit: int,
        fund_type: str,
    ) -> Dict[str, Any]:
        rows = self._normalize_open_fund_rows(rank_df, daily_df, fetched_at)
        rows.sort(key=lambda row: row["metrics"].get("composite_return_score") or -9999.0, reverse=True)
        selected = rows[:limit]
        total = len(selected)
        for index, row in enumerate(selected, start=1):
            row["rank"] = index
            row["score"] = _score_from_rank(index, total)
            row["recommendation_role"] = "market_return_evidence"
        return {
            "rank_type": "open_fund_return_rank",
            "title": "开放式基金收益实证榜",
            "description": "按公开同类收益排行和申赎状态筛选，作为荐基候选的前期公开实证。",
            "status": _status_for_rows(selected),
            "source": "akshare.fund_open_fund_rank_em",
            "source_url": EASTMONEY_OPEN_FUND_RANK_URL,
            "freshness": self._open_fund_group_freshness(rank_df, fetched_at),
            "items": selected,
            "limitations": [
                f"当前 fund_type={fund_type or '全部'}，仅代表公开收益排行，不代表平台买入热度。",
                "开放式基金公开排行不披露买入金额、卖出金额、申购金额或赎回金额。",
            ],
        }

    def _normalize_open_fund_rows(
        self,
        rank_df: pd.DataFrame,
        daily_df: Optional[pd.DataFrame],
        fetched_at: datetime,
    ) -> List[Dict[str, Any]]:
        if rank_df is None or rank_df.empty:
            return []
        daily_status = self._daily_status_by_code(daily_df)
        records: List[Dict[str, Any]] = []
        for raw in rank_df.to_dict(orient="records"):
            code = str(_first_value(raw, "基金代码", "代码") or "").zfill(6)
            if not code or code == "000000":
                continue
            returns = {
                key: _to_float(raw.get(column))
                for column, key in FUND_RETURN_COLUMNS
                if column in raw
            }
            composite = self._return_score(returns)
            status = daily_status.get(code, {})
            data_date = _first_value(raw, "日期", "净值日期")
            metrics = {
                "unit_nav": _to_float(_first_value(raw, "单位净值")),
                "accumulated_nav": _to_float(_first_value(raw, "累计净值")),
                "daily_growth_pct": _to_float(_first_value(raw, "日增长率")),
                "return_1w_pct": returns.get("1w"),
                "return_1m_pct": returns.get("1m"),
                "return_3m_pct": returns.get("3m"),
                "return_6m_pct": returns.get("6m"),
                "return_1y_pct": returns.get("1y"),
                "return_ytd_pct": returns.get("ytd"),
                "composite_return_score": composite,
                "purchase_status": status.get("purchase_status"),
                "redemption_status": status.get("redemption_status"),
                "fee": str(_first_value(raw, "手续费") or status.get("fee") or "") or None,
            }
            records.append({
                "rank": 0,
                "code": code,
                "name": str(_first_value(raw, "基金简称", "名称") or "") or None,
                "fund_type": str(_first_value(raw, "类型", "基金类型") or "") or None,
                "market": "open_fund",
                "score": None,
                "status": "ok",
                "proxy_type": "open_fund_return_rank",
                "recommendation_role": None,
                "metrics": metrics,
                "evidence_metrics": {
                    **TRUE_BUY_SELL_UNSUPPORTED,
                    "proxy_return_1m_pct": returns.get("1m"),
                    "proxy_return_3m_pct": returns.get("3m"),
                    "proxy_return_6m_pct": returns.get("6m"),
                    "proxy_fields": ["return_1m_pct", "return_3m_pct", "return_6m_pct", "purchase_status"],
                },
                "source": "akshare.fund_open_fund_rank_em",
                "source_url": EASTMONEY_OPEN_FUND_RANK_URL,
                "freshness": _freshness(data_date, fetched_at, "开放式基金日榜通常每日 16:00-23:00 后刷新"),
                "limitations": ["收益排名是历史公开表现，不等同未来收益或个人买入建议。"],
            })
        return records

    def _daily_status_by_code(self, daily_df: Optional[pd.DataFrame]) -> Dict[str, Dict[str, Any]]:
        if daily_df is None or daily_df.empty or "基金代码" not in daily_df.columns:
            return {}
        result: Dict[str, Dict[str, Any]] = {}
        for raw in daily_df.to_dict(orient="records"):
            code = str(_first_value(raw, "基金代码") or "").zfill(6)
            if not code or code == "000000":
                continue
            result[code] = {
                "purchase_status": str(_first_value(raw, "申购状态") or "") or None,
                "redemption_status": str(_first_value(raw, "赎回状态") or "") or None,
                "fee": str(_first_value(raw, "手续费") or "") or None,
            }
        return result

    def _return_score(self, returns: Dict[str, Optional[float]]) -> Optional[float]:
        weights: List[Tuple[str, float]] = [("1m", 0.2), ("3m", 0.45), ("6m", 0.25), ("1y", 0.1)]
        score = 0.0
        used = 0.0
        for key, weight in weights:
            value = returns.get(key)
            if value is None:
                continue
            score += value * weight
            used += weight
        if used <= 0:
            return None
        return round(score / used, 4)

    def _open_fund_group_freshness(self, df: pd.DataFrame, fetched_at: datetime) -> Dict[str, Any]:
        data_date = None
        if df is not None and not df.empty:
            first = df.iloc[0].to_dict()
            data_date = _first_value(first, "日期", "净值日期")
        return _freshness(data_date, fetched_at, "开放式基金日榜通常每日 16:00-23:00 后刷新")

    def _latest_group_date(self, groups: List[Dict[str, Any]]) -> Optional[str]:
        dates = [
            group.get("freshness", {}).get("data_date")
            for group in groups
            if isinstance(group.get("freshness"), dict)
        ]
        dates = [item for item in dates if item]
        return max(dates) if dates else None

    def _build_market_seed_candidates(self, groups: List[Dict[str, Any]], *, limit: int) -> List[Dict[str, Any]]:
        candidates: Dict[str, Dict[str, Any]] = {}
        preferred_rank_types = {"etf_net_inflow", "open_fund_return_rank", "etf_turnover_heat"}
        for group in groups:
            rank_type = group.get("rank_type")
            if rank_type not in preferred_rank_types:
                continue
            for item in group.get("items") or []:
                code = item.get("code")
                if not code:
                    continue
                current = candidates.get(code)
                score = float(item.get("score") or 0.0)
                if current is None:
                    current = {
                        "code": code,
                        "name": item.get("name"),
                        "fund_type": item.get("fund_type"),
                        "market": item.get("market"),
                        "score": 0.0,
                        "evidence_rank_types": [],
                        "action_hint": "加关注",
                        "personalized": False,
                        "limitations": ["仅为公开市场级候选，未结合用户画像、持仓、仓位或成本价。"],
                    }
                    candidates[code] = current
                current["score"] = round(float(current["score"]) + score, 2)
                current["evidence_rank_types"].append(rank_type)
        ranked = sorted(candidates.values(), key=lambda item: item.get("score") or 0.0, reverse=True)
        return ranked[:limit]
