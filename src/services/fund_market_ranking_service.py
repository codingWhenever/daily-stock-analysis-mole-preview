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
EASTMONEY_MOBILE_FUND_RANK_URL = "https://fundmobapi.eastmoney.com/FundMNewApi/FundMNRank"

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

PLATFORM_PUBLIC_BUY_RANK_UNSUPPORTED = {
    **TRUE_BUY_SELL_UNSUPPORTED,
    "availability": "platform_public_rank_only",
    "reason": "天天基金公开热销排行披露销售热度/购买人数类字段，但不披露用户级真实买入流水、申购金额或卖出/赎回数据",
}

INDUSTRY_THEME_KEYWORDS: Tuple[Tuple[str, Tuple[str, ...]], ...] = (
    ("半导体", ("半导体", "芯片", "集成电路", "科创芯片")),
    ("通信", ("通信", "5G", "通讯", "光模块")),
    ("人工智能", ("人工智能", "AI", "云计算", "机器人", "算力", "数据")),
    ("新能源", ("新能源", "光伏", "电池", "储能", "锂电", "风电")),
    ("医药", ("医药", "医疗", "生物", "创新药", "中药")),
    ("消费", ("消费", "食品饮料", "白酒", "家电")),
    ("金融", ("金融", "银行", "证券", "保险", "非银")),
    ("军工", ("军工", "国防", "航天", "航空")),
    ("汽车", ("汽车", "智能车", "新能源车", "车联网")),
    ("红利", ("红利", "股息", "高股息")),
    ("海外科技", ("纳斯达克", "标普", "恒生科技", "中概", "海外互联网", "QDII")),
    ("宽基指数", ("沪深300", "中证500", "中证1000", "科创50", "创业板", "上证50", "A500")),
)


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


def _infer_industry_theme(name: Any, fund_type: Any = None) -> str:
    text = f"{name or ''} {fund_type or ''}".upper()
    for industry, keywords in INDUSTRY_THEME_KEYWORDS:
        if any(keyword.upper() in text for keyword in keywords):
            return industry
    if "ETF" in text or "指数" in text:
        return "宽基/指数"
    return "其他"


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

        try:
            platform_rank_loader = getattr(self.provider, "platform_sales_rank")
            platform_sales_df = _call_with_timeout(
                "天天基金公开热销排行",
                lambda: platform_rank_loader(sort_column="SALESRANK_D", page_size=limit),
                timeout=12,
            )
            groups.append(self._build_platform_public_buy_group(platform_sales_df, fetched_at, limit=limit))
        except AttributeError:
            groups.append(self._failed_group(
                rank_type="platform_public_buy_rank",
                title="平台公开热销榜",
                source="eastmoney.fundmobapi.FundMNRank",
                source_url=EASTMONEY_MOBILE_FUND_RANK_URL,
                fetched_at=fetched_at,
                reason="当前 provider 未实现 platform_sales_rank",
            ))
        except Exception as exc:  # noqa: BLE001
            logger.warning("天天基金公开热销榜获取失败: %s", exc)
            groups.append(self._failed_group(
                rank_type="platform_public_buy_rank",
                title="平台公开热销榜",
                source="eastmoney.fundmobapi.FundMNRank",
                source_url=EASTMONEY_MOBILE_FUND_RANK_URL,
                fetched_at=fetched_at,
                reason=str(exc),
            ))

        if any(group.get("items") for group in groups):
            groups.extend(self._build_industry_ranking_groups(groups, fetched_at=fetched_at, limit=limit))
            groups.extend(self._build_public_buy_sell_proxy_groups(groups, limit=limit))

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
                "industry": _infer_industry_theme(_first_value(raw, "名称", "基金简称"), "ETF"),
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
                "industry": _infer_industry_theme(_first_value(raw, "名称", "基金简称"), "ETF"),
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
                "industry": _infer_industry_theme(_first_value(raw, "基金简称", "名称"), _first_value(raw, "类型", "基金类型")),
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
                "industry": _infer_industry_theme(_first_value(raw, "基金简称", "名称"), _first_value(raw, "类型", "基金类型")),
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

    def _build_platform_public_buy_group(self, df: pd.DataFrame, fetched_at: datetime, *, limit: int) -> Dict[str, Any]:
        rows = self._normalize_platform_sales_rows(df, fetched_at)
        rows.sort(
            key=lambda row: (
                row["metrics"].get("platform_sale_volume") is not None,
                row["metrics"].get("platform_sale_volume") or 0.0,
                row["metrics"].get("platform_page_view_yesterday") or 0.0,
            ),
            reverse=True,
        )
        selected = rows[:limit]
        total = len(selected)
        for index, row in enumerate(selected, start=1):
            row["rank"] = index
            row["score"] = _score_from_rank(index, total)
            row["recommendation_role"] = "market_buy_evidence"
        return {
            "rank_type": "platform_public_buy_rank",
            "title": "平台公开热销榜",
            "description": "按天天基金公开移动端热销排行和销售热度字段排序，是平台公开买入热度证据，不读取用户个人数据。",
            "status": _status_for_rows(selected, proxy_only=True),
            "source": "eastmoney.fundmobapi.FundMNRank",
            "source_url": EASTMONEY_MOBILE_FUND_RANK_URL,
            "freshness": self._platform_sales_group_freshness(df, fetched_at),
            "items": selected,
            "limitations": [
                "该榜单来自公开平台热销排行，只能说明平台公开购买热度，不披露用户级真实买入流水。",
                "公开接口没有对应真实卖出/赎回榜，卖出压力仍需使用资金流出等代理指标。",
            ],
        }

    def _normalize_platform_sales_rows(self, df: pd.DataFrame, fetched_at: datetime) -> List[Dict[str, Any]]:
        if df is None or df.empty:
            return []
        records: List[Dict[str, Any]] = []
        for raw in df.to_dict(orient="records"):
            code = str(_first_value(raw, "FCODE", "基金代码", "代码") or "").zfill(6)
            if not code or code == "000000":
                continue
            name = _first_value(raw, "SHORTNAME", "基金简称", "名称")
            fund_type = _first_value(raw, "FUNDTYPE", "BFUNDTYPE", "类型")
            data_date = _first_value(raw, "FSRQ", "日期", "净值日期")
            sale_volume = _to_float(_first_value(raw, "SALEVOLUME", "SALECOUNT", "购买人数", "销量"))
            page_view = _to_float(_first_value(raw, "PV_Y", "浏览量", "昨日浏览"))
            discussion_count = _to_float(_first_value(raw, "DTCOUNT_Y", "讨论数", "昨日讨论"))
            metrics = {
                "industry": _infer_industry_theme(name, fund_type),
                "unit_nav": _to_float(_first_value(raw, "DWJZ", "单位净值")),
                "daily_growth_pct": _to_float(_first_value(raw, "RZDF", "日增长率")),
                "return_1w_pct": _to_float(_first_value(raw, "SYL_Z")),
                "return_1m_pct": _to_float(_first_value(raw, "SYL_Y")),
                "return_3m_pct": _to_float(_first_value(raw, "SYL_3Y")),
                "return_6m_pct": _to_float(_first_value(raw, "SYL_6Y")),
                "return_1y_pct": _to_float(_first_value(raw, "SYL_1N")),
                "platform_sale_volume": sale_volume,
                "platform_page_view_yesterday": page_view,
                "platform_discussion_count_yesterday": discussion_count,
                "platform_buy_enabled": bool(_first_value(raw, "BUY")),
                "platform_org_sales_rank": str(_first_value(raw, "ORGSALESRANK") or "") or None,
                "platform_is_abnormal": str(_first_value(raw, "ISABNORMAL") or "") or None,
            }
            records.append({
                "rank": 0,
                "code": code,
                "name": str(name or "") or None,
                "fund_type": str(fund_type or "") or None,
                "industry": _infer_industry_theme(name, fund_type),
                "market": "open_fund",
                "score": None,
                "status": "proxy_only",
                "proxy_type": "tiantian_public_sales_rank",
                "recommendation_role": None,
                "metrics": metrics,
                "evidence_metrics": {
                    **PLATFORM_PUBLIC_BUY_RANK_UNSUPPORTED,
                    "platform_public_purchase_count_proxy": sale_volume,
                    "platform_public_page_view_yesterday": page_view,
                    "platform_public_discussion_count_yesterday": discussion_count,
                    "proxy_fields": ["SALESRANK_D", "SALEVOLUME", "PV_Y", "DTCOUNT_Y"],
                },
                "source": "eastmoney.fundmobapi.FundMNRank",
                "source_url": EASTMONEY_MOBILE_FUND_RANK_URL,
                "freshness": _freshness(data_date, fetched_at, "天天基金移动端公开热销榜；通常随平台榜单刷新"),
                "limitations": ["平台公开热销字段不能还原真实申购金额、买入笔数或个人订单。"],
            })
        return records

    def _platform_sales_group_freshness(self, df: pd.DataFrame, fetched_at: datetime) -> Dict[str, Any]:
        data_date = None
        if df is not None and not df.empty:
            first = df.iloc[0].to_dict()
            data_date = _first_value(first, "FSRQ", "日期", "净值日期")
        return _freshness(data_date, fetched_at, "天天基金移动端公开热销榜；通常随平台榜单刷新")

    def _build_public_buy_sell_proxy_groups(self, groups: List[Dict[str, Any]], *, limit: int) -> List[Dict[str, Any]]:
        by_type = {group.get("rank_type"): group for group in groups}
        result: List[Dict[str, Any]] = []
        specs = [
            ("platform_public_buy_rank", "public_buy_proxy_rank", "公开买入热度榜", "按天天基金公开热销排行代理市场买入热度；真实买入金额/笔数不可公开核验。"),
            ("etf_net_outflow", "public_sell_proxy_rank", "公开卖出压力榜", "按 ETF 主力净流出代理市场卖出压力；真实卖出金额/笔数不可公开核验。"),
        ]
        for source_type, rank_type, title, description in specs:
            source_group = by_type.get(source_type)
            effective_source_type = source_type
            if source_type == "platform_public_buy_rank" and (not source_group or not source_group.get("items")):
                source_group = by_type.get("etf_net_inflow")
                effective_source_type = "etf_net_inflow"
                description = "天天基金公开热销榜不可用时，回退按 ETF 主力净流入代理市场买入强度；真实买入金额/笔数不可公开核验。"
            if not source_group or not source_group.get("items"):
                continue
            items = []
            for index, item in enumerate(source_group.get("items", [])[:limit], start=1):
                copied = {**item}
                copied["rank"] = index
                copied["recommendation_role"] = "market_buy_evidence" if rank_type == "public_buy_proxy_rank" else "market_sell_risk_evidence"
                if effective_source_type == "platform_public_buy_rank":
                    copied["recommendation_role"] = "market_buy_evidence"
                    copied["proxy_type"] = "public_buy_proxy_from_platform_sales_rank"
                else:
                    copied["proxy_type"] = "public_buy_sell_proxy_from_etf_flow"
                copied["limitations"] = [
                    "该榜单是公开平台热销或交易资金流代理口径，不披露用户级真实买入/卖出笔数。",
                    *list(item.get("limitations") or []),
                ]
                items.append(copied)
            result.append({
                "rank_type": rank_type,
                "title": title,
                "description": description,
                "status": "proxy_only",
                "source": source_group.get("source") or "akshare.fund_etf_spot_em",
                "source_url": source_group.get("source_url") or EASTMONEY_ETF_QUOTE_URL,
                "freshness": source_group.get("freshness") or {},
                "items": items,
                "limitations": [
                    "公开源没有用户级真实申购/赎回或买卖笔数，actual_* 字段保持 null。",
                ],
            })
        return result

    def _build_industry_ranking_groups(
        self,
        groups: List[Dict[str, Any]],
        *,
        fetched_at: datetime,
        limit: int,
    ) -> List[Dict[str, Any]]:
        source_items: List[Tuple[str, Dict[str, Any]]] = []
        source_rank_types = {"etf_net_inflow", "etf_net_outflow", "etf_turnover_heat", "open_fund_return_rank", "platform_public_buy_rank"}
        for group in groups:
            rank_type = str(group.get("rank_type") or "")
            if rank_type not in source_rank_types:
                continue
            for item in group.get("items") or []:
                source_items.append((rank_type, item))
        if not source_items:
            return []

        industry_stats: Dict[str, Dict[str, Any]] = {}
        product_best: Dict[str, Dict[str, Any]] = {}
        for rank_type, item in source_items:
            metrics = item.get("metrics") if isinstance(item.get("metrics"), dict) else {}
            industry = str(item.get("industry") or metrics.get("industry") or _infer_industry_theme(item.get("name"), item.get("fund_type")))
            stats = industry_stats.setdefault(
                industry,
                {
                    "industry": industry,
                    "item_count": 0,
                    "product_codes": set(),
                    "score": 0.0,
                    "proxy_net_inflow_amount": 0.0,
                    "proxy_net_outflow_amount": 0.0,
                    "proxy_turnover_amount": 0.0,
                    "change_values": [],
                    "return_3m_values": [],
                    "top_products": [],
                    "rank_types": set(),
                },
            )
            stats["item_count"] += 1
            stats["rank_types"].add(rank_type)
            if item.get("code"):
                stats["product_codes"].add(str(item.get("code")))
            flow = _to_float(metrics.get("main_net_inflow_amount") or metrics.get("proxy_net_inflow_amount"))
            turnover = _to_float(metrics.get("amount") or metrics.get("proxy_turnover_amount"))
            change_pct = _to_float(metrics.get("change_pct") or metrics.get("daily_growth_pct"))
            return_3m = _to_float(metrics.get("return_3m_pct"))
            item_score = float(item.get("score") or 45.0)
            if flow is not None:
                if flow >= 0:
                    stats["proxy_net_inflow_amount"] += flow
                    item_score += min(flow / 10000000.0, 20.0)
                else:
                    stats["proxy_net_outflow_amount"] += abs(flow)
                    item_score -= min(abs(flow) / 10000000.0, 14.0)
            if turnover is not None and turnover > 0:
                stats["proxy_turnover_amount"] += turnover
                item_score += min(turnover / 1000000000.0, 18.0)
            if change_pct is not None:
                stats["change_values"].append(change_pct)
                item_score += max(min(change_pct, 8.0), -8.0)
            if return_3m is not None:
                stats["return_3m_values"].append(return_3m)
                item_score += min(max(return_3m, 0.0) / 5.0, 20.0)
            product = {
                **item,
                "industry": industry,
                "industry_source_rank_type": rank_type,
                "industry_product_score": round(item_score, 2),
            }
            stats["top_products"].append(product)
            code = str(item.get("code") or "")
            if code:
                previous = product_best.get(code)
                if previous is None or product["industry_product_score"] > previous.get("industry_product_score", 0):
                    product_best[code] = product

        industry_rows: List[Dict[str, Any]] = []
        for industry, stats in industry_stats.items():
            product_count = len(stats["product_codes"])
            avg_change = self._average(stats["change_values"])
            avg_return_3m = self._average(stats["return_3m_values"])
            score = stats["score"] + product_count * 2.0
            if avg_return_3m is not None:
                score += min(max(avg_return_3m, 0.0) / 3.0, 25.0)
            top_products = sorted(
                stats["top_products"],
                key=lambda row: row.get("industry_product_score") or 0.0,
                reverse=True,
            )[:10]
            industry_rows.append({
                "rank": 0,
                "code": f"industry:{industry}",
                "name": industry,
                "fund_type": "行业主题",
                "industry": industry,
                "market": "market_theme",
                "score": round(score, 2),
                "status": "proxy_only",
                "proxy_type": "industry_aggregate_from_public_rankings",
                "recommendation_role": "market_industry_evidence",
                "metrics": {
                    "industry": industry,
                    "item_count": stats["item_count"],
                    "product_count": product_count,
                    "proxy_net_inflow_amount": round(stats["proxy_net_inflow_amount"], 2),
                    "proxy_net_outflow_amount": round(stats["proxy_net_outflow_amount"], 2),
                    "proxy_turnover_amount": round(stats["proxy_turnover_amount"], 2),
                    "avg_change_pct": avg_change,
                    "avg_return_3m_pct": avg_return_3m,
                    "source_rank_types": sorted(stats["rank_types"]),
                    "top_products": [
                        {
                            "code": row.get("code"),
                            "name": row.get("name"),
                            "score": row.get("industry_product_score"),
                            "source_rank_type": row.get("industry_source_rank_type"),
                        }
                        for row in top_products
                    ],
                },
                "evidence_metrics": {
                    **TRUE_BUY_SELL_UNSUPPORTED,
                    "proxy_fields": ["proxy_net_inflow_amount", "proxy_turnover_amount", "avg_return_3m_pct", "product_count"],
                },
                "source": "derived_from_public_market_rankings",
                "source_url": AKSHARE_FUND_PUBLIC_DOC_URL,
                "freshness": _freshness(None, fetched_at, "随原始公开榜单刷新"),
                "limitations": ["行业归因来自基金名称/类型关键词和当前公开榜单条目，不代表全市场行业持仓穿透。"],
            })

        industry_rows.sort(key=lambda row: row.get("score") or 0.0, reverse=True)
        for index, row in enumerate(industry_rows[:limit], start=1):
            row["rank"] = index
            row["score"] = _score_from_rank(index, min(len(industry_rows), limit))

        industry_rank_by_name = {row["industry"]: row["rank"] for row in industry_rows[:limit]}
        industry_score_by_name = {row["industry"]: row["score"] for row in industry_rows[:limit]}
        product_rows = []
        for item in product_best.values():
            industry = str(item.get("industry") or "其他")
            industry_rank = industry_rank_by_name.get(industry)
            if industry_rank is None:
                continue
            copied = {**item}
            copied_metrics = dict(copied.get("metrics") or {})
            copied_metrics.update({
                "industry": industry,
                "industry_rank": industry_rank,
                "industry_score": industry_score_by_name.get(industry),
            })
            copied["metrics"] = copied_metrics
            copied["score"] = round(float(copied.get("industry_product_score") or copied.get("score") or 0.0) + float(industry_score_by_name.get(industry) or 0.0) * 0.25, 2)
            copied["rank"] = 0
            copied["recommendation_role"] = "market_industry_product_evidence"
            copied["proxy_type"] = "industry_product_from_public_rankings"
            copied["limitations"] = [
                "行业内产品 Top10 来自公开榜单候选的行业归因，不代表全市场完整排名。",
                *list(copied.get("limitations") or []),
            ]
            product_rows.append(copied)
        product_rows.sort(key=lambda row: row.get("score") or 0.0, reverse=True)
        selected_products = product_rows[:limit]
        for index, row in enumerate(selected_products, start=1):
            row["rank"] = index
            row["score"] = _score_from_rank(index, len(selected_products))

        return [
            {
                "rank_type": "industry_heat_top10",
                "title": "行业热度 Top10",
                "description": "按当前公开榜单候选聚合行业资金流、成交热度和收益表现，形成市场级行业观察。",
                "status": "proxy_only",
                "source": "derived_from_public_market_rankings",
                "source_url": AKSHARE_FUND_PUBLIC_DOC_URL,
                "freshness": _freshness(None, fetched_at, "随原始公开榜单刷新"),
                "items": industry_rows[:limit],
                "limitations": ["行业榜是公开榜单条目的关键词归因汇总，不读取个人持仓，也不代表全市场行业申赎。"],
            },
            {
                "rank_type": "industry_product_top10",
                "title": "行业内产品 Top10",
                "description": "在高热行业中筛选公开证据更强的基金/ETF，作为荐基候选的前置实证。",
                "status": _status_for_rows(selected_products, proxy_only=True),
                "source": "derived_from_public_market_rankings",
                "source_url": AKSHARE_FUND_PUBLIC_DOC_URL,
                "freshness": _freshness(None, fetched_at, "随原始公开榜单刷新"),
                "items": selected_products,
                "limitations": ["行业内产品 Top10 仍是市场级候选，不等同个人买入建议。"],
            },
        ]

    @staticmethod
    def _average(values: List[float]) -> Optional[float]:
        values = [float(value) for value in values if value is not None]
        if not values:
            return None
        return round(sum(values) / len(values), 2)

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
        preferred_rank_types = {
            "industry_product_top10",
            "platform_public_buy_rank",
            "public_buy_proxy_rank",
            "etf_net_inflow",
            "open_fund_return_rank",
            "etf_turnover_heat",
        }
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
