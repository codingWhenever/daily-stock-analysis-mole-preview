# -*- coding: utf-8 -*-
from __future__ import annotations

import pandas as pd

from src.config import Config
from src.repositories.fund_repo import FundRepository
from src.services.fund_recommendation_service import (
    FUND_RECOMMENDATION_TODAY_SCHEMA_VERSION,
    FundRecommendationService,
)
from src.storage import DatabaseManager


class RecommendationProvider:
    def etf_spot(self) -> pd.DataFrame:
        return pd.DataFrame(
            {
                "代码": ["159516", "515050"],
                "名称": ["半导体设备ETF国泰", "通信ETF华夏"],
                "涨跌幅": [3.76, -2.1],
                "成交额": [5652155000, 2200000000],
                "主力净流入-净额": [5500960, -32000000],
                "数据日期": ["2026-06-26", "2026-06-26"],
            }
        )

    def open_fund_rank(self, symbol: str) -> pd.DataFrame:
        return pd.DataFrame(
            {
                "序号": [1, 2],
                "基金代码": ["021528", "110022"],
                "基金简称": ["财通成长优选混合C", "易方达消费行业股票"],
                "日期": ["2026-06-25", "2026-06-25"],
                "日增长率": [5.26, 0.6],
                "近3月": [133.19, 11.0],
                "近6月": [150.76, 18.0],
                "近1年": [506.24, 26.0],
                "手续费": ["0.00%", "0.15%"],
            }
        )

    def open_fund_daily(self) -> pd.DataFrame:
        return pd.DataFrame(
            {
                "基金代码": ["021528", "110022"],
                "申购状态": ["开放申购", "暂停申购"],
                "赎回状态": ["开放赎回", "开放赎回"],
                "手续费": ["0.00%", "0.15%"],
            }
        )

    def platform_sales_rank(self, *, sort_column: str = "SALESRANK_D", page_size: int = 30) -> pd.DataFrame:
        return pd.DataFrame(
            {
                "FCODE": ["000057", "021528"],
                "SHORTNAME": ["中银消费主题混合A", "财通成长优选混合C"],
                "FUNDTYPE": ["002", "002"],
                "FSRQ": ["2026-06-26", "2026-06-26"],
                "DWJZ": ["1.4935", "5.923"],
                "RZDF": ["-1.92", "5.26"],
                "SYL_3Y": ["-2.64", "133.19"],
                "SYL_6Y": ["-9.21", "150.76"],
                "SALEVOLUME": ["49", "17"],
                "PV_Y": ["694", "220"],
                "DTCOUNT_Y": ["41", "12"],
                "BUY": [True, True],
            }
        )


def teardown_function():
    DatabaseManager.reset_instance()
    Config.reset_instance()


def test_today_recommendations_are_market_only_and_not_personal_actions() -> None:
    DatabaseManager.reset_instance()
    db = DatabaseManager(db_url="sqlite:///:memory:")
    repo = FundRepository(db_manager=db)
    service = FundRecommendationService(RecommendationProvider(), repo=repo)

    result = service.today(limit=4, fund_type="全部")

    assert result["schema_version"] == FUND_RECOMMENDATION_TODAY_SCHEMA_VERSION
    assert result["personalization"]["status"] == "market_only"
    assert result["personalization"]["holdings_used"] is False
    assert result["personalization"]["personal_actions_supported"] is False
    assert result["candidates"]
    candidate = result["candidates"][0]
    assert candidate["market_action"] in {"add_to_pool", "market_watchlist", "research_only"}
    assert candidate["personal_action"] is None
    assert candidate["personalized"] is False
    assert candidate["market_evidence"]
    assert any(rank_type in candidate["source_rank_types"] for rank_type in {"platform_public_buy_rank", "industry_product_top10", "public_buy_proxy_rank"})
    assert candidate["backtest_readiness"]["status"] in {"ready_for_research", "insufficient_nav_history"}
    assert "buy" not in result["personalization"]["allowed_actions"]


def test_pool_candidate_is_watchlist_and_keeps_backtest_boundary() -> None:
    DatabaseManager.reset_instance()
    db = DatabaseManager(db_url="sqlite:///:memory:")
    repo = FundRepository(db_manager=db)
    repo.upsert_pool_item(code="021528", name="财通成长优选混合C", fund_type="混合型")
    service = FundRecommendationService(RecommendationProvider(), repo=repo)

    result = service.today(limit=4, fund_type="全部")
    by_code = {item["code"]: item for item in result["candidates"]}

    assert by_code["021528"]["market_action"] == "market_watchlist"
    assert by_code["021528"]["data_quality_summary"] == "not_analyzed"
    assert "backtest_sample_insufficient" in by_code["021528"]["risk_flags"]
    assert any("NAV 样本不足" in item for item in by_code["021528"]["invalid_if"])


if __name__ == "__main__":
    for name, func in sorted(globals().items()):
        if name.startswith("test_") and callable(func):
            func()
