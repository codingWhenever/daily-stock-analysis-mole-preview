# -*- coding: utf-8 -*-
from __future__ import annotations

from types import SimpleNamespace

import pandas as pd

from api.v1.endpoints import funds as funds_endpoint
from src.services.fund_market_ranking_service import (
    MARKET_FUND_RANKING_SCHEMA_VERSION,
    FundMarketRankingService,
)


class FakeMarketRankingProvider:
    def etf_spot(self) -> pd.DataFrame:
        return pd.DataFrame(
            {
                "代码": ["159516", "515050", "588000"],
                "名称": ["半导体设备ETF国泰", "通信ETF华夏", "科创50ETF"],
                "最新价": [1.766, 1.436, 1.12],
                "涨跌幅": [3.76, -2.1, 0.8],
                "成交量": [32480751, 20400000, 8000000],
                "成交额": [5652155000, 2200000000, 900000000],
                "换手率": [15.63, 10.2, 3.2],
                "主力净流入-净额": [5500960, -32000000, 1200000],
                "主力净流入-净占比": [0.10, -1.45, 0.13],
                "超大单净流入-净额": [228172976, -14000000, 500000],
                "大单净流入-净额": [-222672016, -18000000, 700000],
                "中单净流入-净额": [-13627152, 4500000, 0],
                "小单净流入-净额": [8126176, 1000000, -120000],
                "外盘": [15017814, 9300000, 4000000],
                "内盘": [17462937, 11100000, 3900000],
                "最新份额": [20775180000, 6000000000, 3000000000],
                "流通市值": [36688967937, 8600000000, 3360000000],
                "总市值": [36688967937, 8600000000, 3360000000],
                "数据日期": ["2026-06-26", "2026-06-26", "2026-06-26"],
                "更新时间": [
                    "2026-06-26 14:40:57+08:00",
                    "2026-06-26 14:41:01+08:00",
                    "2026-06-26 14:41:02+08:00",
                ],
            }
        )

    def open_fund_rank(self, symbol: str) -> pd.DataFrame:
        return pd.DataFrame(
            {
                "序号": [1, 2, 3],
                "基金代码": ["001480", "021528", "110022"],
                "基金简称": ["财通成长优选混合A", "财通成长优选混合C", "易方达消费行业股票"],
                "日期": ["2026-06-25", "2026-06-25", "2026-06-25"],
                "单位净值": [10.326, 5.923, 2.4],
                "累计净值": [10.326, 5.923, 2.4],
                "日增长率": [5.27, 5.26, 0.6],
                "近1周": [2.5, 2.49, 1.0],
                "近1月": [43.92, 43.87, 4.0],
                "近3月": [133.41, 133.19, 11.0],
                "近6月": [151.24, 150.76, 18.0],
                "近1年": [508.84, 506.24, 26.0],
                "今年来": [159.71, 159.21, 8.0],
                "手续费": ["0.15%", "0.00%", "0.15%"],
            }
        )

    def open_fund_daily(self) -> pd.DataFrame:
        return pd.DataFrame(
            {
                "基金代码": ["001480", "021528", "110022"],
                "申购状态": ["开放申购", "开放申购", "暂停申购"],
                "赎回状态": ["开放赎回", "开放赎回", "开放赎回"],
                "手续费": ["0.15%", "0.00%", "0.15%"],
            }
        )

    def platform_sales_rank(self, *, sort_column: str = "SALESRANK_D", page_size: int = 30) -> pd.DataFrame:
        return pd.DataFrame(
            {
                "FCODE": ["000057", "000028"],
                "SHORTNAME": ["中银消费主题混合A", "华富安鑫债券A"],
                "FUNDTYPE": ["002", "003"],
                "FSRQ": ["2026-06-26", "2026-06-26"],
                "DWJZ": ["1.4935", "1.0182"],
                "RZDF": ["-1.92", "0.02"],
                "SYL_Y": ["0.51", "0.28"],
                "SYL_3Y": ["-2.64", "1.02"],
                "SYL_6Y": ["-9.21", "2.81"],
                "SYL_1N": ["-11.94", "4.08"],
                "SALEVOLUME": ["49", "31"],
                "PV_Y": ["694", "410"],
                "DTCOUNT_Y": ["41", "9"],
                "BUY": [True, True],
                "ORGSALESRANK": ["--", "--"],
                "ISABNORMAL": ["0", "0"],
            }
        )


class EmptyMarketRankingProvider(FakeMarketRankingProvider):
    def etf_spot(self) -> pd.DataFrame:
        return pd.DataFrame()

    def open_fund_rank(self, symbol: str) -> pd.DataFrame:
        return pd.DataFrame()

    def open_fund_daily(self) -> pd.DataFrame:
        return pd.DataFrame()

    def platform_sales_rank(self, *, sort_column: str = "SALESRANK_D", page_size: int = 30) -> pd.DataFrame:
        return pd.DataFrame()


class FailingMarketRankingProvider(FakeMarketRankingProvider):
    def etf_spot(self) -> pd.DataFrame:
        raise RuntimeError("etf source down")

    def open_fund_rank(self, symbol: str) -> pd.DataFrame:
        raise RuntimeError("open fund source down")

    def platform_sales_rank(self, *, sort_column: str = "SALESRANK_D", page_size: int = 30) -> pd.DataFrame:
        raise RuntimeError("platform sales source down")


def test_market_rankings_build_public_proxy_groups_without_personalization() -> None:
    service = FundMarketRankingService(FakeMarketRankingProvider())

    result = service.build_market_rankings(limit=2, fund_type="全部")

    assert result["schema_version"] == MARKET_FUND_RANKING_SCHEMA_VERSION
    assert result["status"] == "completed"
    assert result["personalization"]["status"] == "market_only"
    assert result["personalization"]["user_profile_used"] is False
    assert result["personalization"]["holdings_used"] is False
    groups = {group["rank_type"]: group for group in result["groups"]}
    assert {
        "etf_net_inflow",
        "etf_net_outflow",
        "etf_turnover_heat",
        "open_fund_return_rank",
        "platform_public_buy_rank",
        "industry_heat_top10",
        "industry_product_top10",
        "public_buy_proxy_rank",
        "public_sell_proxy_rank",
    } <= set(groups)

    inflow = groups["etf_net_inflow"]["items"][0]
    assert inflow["code"] == "159516"
    assert inflow["status"] == "proxy_only"
    assert inflow["evidence_metrics"]["actual_buy_amount"] is None
    assert inflow["evidence_metrics"]["actual_buy_count"] is None
    assert inflow["evidence_metrics"]["availability"] == "not_supported"
    assert inflow["metrics"]["main_net_inflow_amount"] == 5500960.0

    outflow = groups["etf_net_outflow"]["items"][0]
    assert outflow["code"] == "515050"
    assert outflow["metrics"]["proxy_net_outflow_amount"] == 32000000.0
    assert outflow["recommendation_role"] == "market_sell_risk_evidence"

    open_fund = groups["open_fund_return_rank"]["items"][0]
    assert open_fund["code"] == "001480"
    assert open_fund["metrics"]["purchase_status"] == "开放申购"
    assert open_fund["evidence_metrics"]["actual_subscription_amount"] is None
    assert open_fund["evidence_metrics"]["proxy_return_3m_pct"] == 133.41

    platform_buy = groups["platform_public_buy_rank"]["items"][0]
    assert platform_buy["code"] == "000057"
    assert platform_buy["source"] == "eastmoney.fundmobapi.FundMNRank"
    assert platform_buy["evidence_metrics"]["availability"] == "platform_public_rank_only"
    assert platform_buy["evidence_metrics"]["platform_public_purchase_count_proxy"] == 49.0
    assert platform_buy["metrics"]["platform_page_view_yesterday"] == 694.0

    industry = groups["industry_heat_top10"]["items"][0]
    assert industry["name"] == "半导体"
    assert industry["metrics"]["product_count"] >= 1
    assert industry["evidence_metrics"]["actual_buy_amount"] is None
    assert industry["recommendation_role"] == "market_industry_evidence"

    industry_product = groups["industry_product_top10"]["items"][0]
    assert industry_product["industry"] == "半导体"
    assert industry_product["recommendation_role"] == "market_industry_product_evidence"

    buy_proxy = groups["public_buy_proxy_rank"]["items"][0]
    assert buy_proxy["code"] == "000057"
    assert buy_proxy["proxy_type"] == "public_buy_proxy_from_platform_sales_rank"
    assert buy_proxy["evidence_metrics"]["availability"] == "platform_public_rank_only"

    assert result["recommendation_candidates"]
    assert result["recommendation_candidates"][0]["personalized"] is False
    assert "industry_product_top10" in result["recommendation_candidates"][0]["evidence_rank_types"]


def test_market_rankings_empty_sources_fail_without_fabricating_items() -> None:
    service = FundMarketRankingService(EmptyMarketRankingProvider())

    result = service.build_market_rankings(limit=5, fund_type="全部")

    assert result["status"] == "failed"
    assert result["recommendation_candidates"] == []
    assert all(group["items"] == [] for group in result["groups"])
    assert all(group["status"] == "missing" for group in result["groups"])
    assert any("不读取用户画像" in item for item in result["limitations"])


def test_market_rankings_endpoint_uses_response_schema() -> None:
    service = FundMarketRankingService(FakeMarketRankingProvider())
    original_service = funds_endpoint._service
    funds_endpoint._service = lambda: SimpleNamespace(
        market_rankings=lambda **kwargs: service.build_market_rankings(**kwargs)
    )
    try:
        response = funds_endpoint.get_market_fund_rankings(limit=2, fund_type="全部")
    finally:
        funds_endpoint._service = original_service

    assert response.schema_version == MARKET_FUND_RANKING_SCHEMA_VERSION
    assert response.personalization["status"] == "market_only"
    assert response.groups[0].items[0].evidence_metrics["availability"] == "not_supported"


def test_market_rankings_provider_failures_return_failed_groups() -> None:
    service = FundMarketRankingService(FailingMarketRankingProvider())

    result = service.build_market_rankings(limit=2, fund_type="全部")

    assert result["status"] == "failed"
    assert {group["status"] for group in result["groups"]} == {"failed"}
    assert any("etf source down" in item for group in result["groups"] for item in group["limitations"])
    assert any("open fund source down" in item for group in result["groups"] for item in group["limitations"])
    assert any("platform sales source down" in item for group in result["groups"] for item in group["limitations"])
