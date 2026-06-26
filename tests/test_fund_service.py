# -*- coding: utf-8 -*-
from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path
import sqlite3
import tempfile

import pandas as pd
from sqlalchemy.exc import OperationalError

from src.config import Config
import src.storage as storage_module
from src.repositories.fund_repo import FundRepository
from src.services.fund_service import (
    FundLatestQuote,
    FundMetadata,
    FundService,
    build_data_quality_detail,
    calculate_nav_metrics,
    normalize_fund_code,
)
from src.services.fund_backtest_calibration import calibrate_fund_backtests
from src.storage import DatabaseManager


class FakeFundProvider:
    def _index_frame(self, start: float, pe: bool = True) -> pd.DataFrame:
        base = date.today() - timedelta(days=1319)
        rows = []
        for i in range(1320):
            rows.append(
                {
                    "日期": base + timedelta(days=i),
                    "指数": start + i * 1.2,
                    "滚动市盈率": 10 + i * 0.004 if pe else None,
                    "市净率": 1.2 + i * 0.0005 if not pe else None,
                }
            )
        return pd.DataFrame(rows)

    def get_metadata(self, code: str) -> FundMetadata:
        return FundMetadata(code=code, name="易方达消费行业股票", fund_type="股票型")

    def get_latest_quote(self, code: str) -> FundLatestQuote:
        latest_date = date.today() - timedelta(days=2)
        return FundLatestQuote(
            code=code,
            name="易方达消费行业股票",
            unit_nav=2.4,
            accumulated_nav=2.4,
            daily_growth_pct=0.6,
            purchase_status="开放申购",
            redemption_status="开放赎回",
            fee="0.15%",
            nav_date=latest_date,
        )

    def get_nav_records(self, code: str):
        start = date.today() - timedelta(days=365)
        records = []
        for i in range(366):
            current = start + timedelta(days=i)
            records.append(
                {
                    "date": current.isoformat(),
                    "unit_nav": 1.8 + i * 0.0015,
                    "accumulated_nav": 1.8 + i * 0.0015,
                    "daily_growth_pct": 0.08,
                }
            )
        records[-1]["unit_nav"] = 2.4
        records[-1]["accumulated_nav"] = 2.4
        return records

    def get_peer_snapshot(self, code: str, fund_type: str | None):
        return {
            "category": "股票型",
            "sample_size": 100,
            "rank": 18,
            "percentiles": {"1w": 68.0, "1m": 70.0, "3m": 74.0, "6m": 68.0, "1y": 82.0},
            "returns": {"1w": 1.0, "1m": 4.0, "3m": 11.0, "6m": 18.0, "1y": 26.0},
            "date": (date.today() - timedelta(days=2)).isoformat(),
            "data_quality": "ok",
        }

    def individual_analysis(self, code: str):
        return {
            "period": "近1年",
            "peer_risk_return_ratio": 72.0,
            "peer_anti_volatility": 61.0,
            "volatility_1y_pct": 18.5,
            "sharpe_1y": 1.8,
            "max_drawdown_1y_pct": -16.2,
            "source": "fund_individual_analysis_xq",
        }

    def index_pe(self, symbol: str) -> pd.DataFrame:
        return self._index_frame(3600, pe=True)

    def index_pb(self, symbol: str) -> pd.DataFrame:
        return self._index_frame(3600, pe=False)

    def fund_industry_allocation(self, code: str, year: str) -> pd.DataFrame:
        latest_date = (date.today() - timedelta(days=90)).isoformat()
        return pd.DataFrame(
            {
                "行业类别": ["食品饮料", "家用电器", "医药生物"],
                "占净值比例": [32.5, 18.2, 9.6],
                "截止时间": [latest_date, latest_date, latest_date],
            }
        )

    def fund_stock_holdings(self, code: str, year: str) -> pd.DataFrame:
        return pd.DataFrame(
            {
                "股票代码": ["600519", "000858", "000333"],
                "股票名称": ["贵州茅台", "五粮液", "美的集团"],
                "占净值比例": [8.9, 7.1, 5.2],
                "持仓市值": [89000000, 71000000, 52000000],
                "季度": ["2026年1季度股票投资明细", "2026年1季度股票投资明细", "2026年1季度股票投资明细"],
            }
        )

    def fund_reports(self, code: str) -> pd.DataFrame:
        report_date = (date.today() - timedelta(days=60)).isoformat()
        return pd.DataFrame(
            {
                "基金代码": [code],
                "公告标题": ["易方达消费行业股票型证券投资基金近期季度报告"],
                "公告日期": [report_date],
                "报告ID": ["REPORT-110022-Q1"],
            }
        )

    def fund_purchase_table(self) -> pd.DataFrame:
        return pd.DataFrame(
            {
                "基金代码": ["110022"],
                "申购状态": ["开放申购"],
                "赎回状态": ["开放赎回"],
                "购买起点": ["10"],
                "日累计限定金额": ["100000"],
                "手续费": ["0.15%"],
            }
        )

    def fund_fee(self, code: str, indicator: str) -> pd.DataFrame:
        if indicator == "赎回费率":
            return pd.DataFrame(
                {
                    "持有期限": ["小于7天", "大于等于7天，小于30天", "大于等于30天"],
                    "费率": ["1.50%", "0.50%", "0.00%"],
                }
            )
        if indicator == "申购费率":
            return pd.DataFrame(
                {
                    "购买金额": ["小于100万", "大于等于100万"],
                    "费率": ["0.15%", "0.10%"],
                }
            )
        return pd.DataFrame()


class MissingRiskFeeProvider(FakeFundProvider):
    def individual_analysis(self, code: str):
        return None

    def fund_fee(self, code: str, indicator: str) -> pd.DataFrame:
        return pd.DataFrame()


class MoneyMarketProvider(FakeFundProvider):
    def get_metadata(self, code: str) -> FundMetadata:
        return FundMetadata(code=code, name="天弘余额宝货币", fund_type="货币型")

    def get_latest_quote(self, code: str) -> FundLatestQuote:
        latest_date = date.today() - timedelta(days=1)
        return FundLatestQuote(
            code=code,
            name="天弘余额宝货币",
            unit_nav=1.0,
            accumulated_nav=1.0,
            daily_growth_pct=None,
            purchase_status="开放申购",
            redemption_status="开放赎回",
            fee="0.00%",
            nav_date=latest_date,
        )

    def get_peer_snapshot(self, code: str, fund_type: str | None):
        return None

    def individual_analysis(self, code: str):
        return None

    def fund_purchase_table(self) -> pd.DataFrame:
        return pd.DataFrame()

    def fund_fee(self, code: str, indicator: str) -> pd.DataFrame:
        return pd.DataFrame()


class IndexFundProvider(FakeFundProvider):
    def get_metadata(self, code: str) -> FundMetadata:
        return FundMetadata(code=code, name="华夏沪深300ETF联接A", fund_type="指数型")

    def get_latest_quote(self, code: str) -> FundLatestQuote:
        quote = super().get_latest_quote(code)
        quote.name = "华夏沪深300ETF联接A"
        return quote

    def get_peer_snapshot(self, code: str, fund_type: str | None):
        snapshot = super().get_peer_snapshot(code, fund_type)
        snapshot["category"] = "指数型"
        return snapshot


class QdiiCompositeProvider(IndexFundProvider):
    def get_metadata(self, code: str) -> FundMetadata:
        return FundMetadata(code=code, name="纳斯达克100ETF联接(QDII)", fund_type="指数型")

    def get_latest_quote(self, code: str) -> FundLatestQuote:
        quote = super().get_latest_quote(code)
        quote.name = "纳斯达克100ETF联接(QDII)"
        return quote


class FofCompositeProvider(FakeFundProvider):
    def get_metadata(self, code: str) -> FundMetadata:
        return FundMetadata(code=code, name="稳健债券型FOF", fund_type="债券型")

    def get_latest_quote(self, code: str) -> FundLatestQuote:
        quote = super().get_latest_quote(code)
        quote.name = "稳健债券型FOF"
        return quote

    def get_peer_snapshot(self, code: str, fund_type: str | None):
        snapshot = super().get_peer_snapshot(code, fund_type)
        snapshot["category"] = "债券型"
        return snapshot


class NoFeeProvider(MissingRiskFeeProvider):
    def get_latest_quote(self, code: str) -> FundLatestQuote:
        quote = super().get_latest_quote(code)
        quote.fee = None
        return quote

    def fund_purchase_table(self) -> pd.DataFrame:
        table = super().fund_purchase_table()
        table.loc[table["基金代码"] == "110022", "手续费"] = ""
        return table


class AnnualExpenseProvider(FakeFundProvider):
    def fund_fee(self, code: str, indicator: str) -> pd.DataFrame:
        if indicator == "运作费率":
            return pd.DataFrame(
                {
                    "费用类型": ["管理费", "托管费", "销售服务费"],
                    "费率": ["1.50%", "0.25%", "0.00%"],
                }
            )
        return super().fund_fee(code, indicator)


class PausedPurchaseProvider(FakeFundProvider):
    def get_latest_quote(self, code: str) -> FundLatestQuote:
        quote = super().get_latest_quote(code)
        quote.purchase_status = "暂停申购"
        return quote

    def fund_purchase_table(self) -> pd.DataFrame:
        table = super().fund_purchase_table()
        table.loc[table["基金代码"] == "110022", "申购状态"] = "暂停申购"
        return table


class StaleQualityProvider(FakeFundProvider):
    def get_peer_snapshot(self, code: str, fund_type: str | None):
        snapshot = super().get_peer_snapshot(code, fund_type)
        snapshot["date"] = "2024-01-15"
        return snapshot

    def fund_industry_allocation(self, code: str, year: str) -> pd.DataFrame:
        return pd.DataFrame(
            {
                "行业类别": ["食品饮料", "家用电器"],
                "占净值比例": [32.5, 18.2],
                "截止时间": ["2024-03-31", "2024-03-31"],
            }
        )

    def fund_reports(self, code: str) -> pd.DataFrame:
        return pd.DataFrame(
            {
                "基金代码": [code],
                "公告标题": ["易方达消费行业股票型证券投资基金2024年第1季度报告"],
                "公告日期": ["2024-04-22"],
                "报告ID": ["REPORT-110022-OLD-Q1"],
            }
        )


def teardown_function():
    DatabaseManager.reset_instance()
    Config.reset_instance()


def _seed_calibration_fund(
    repo: FundRepository,
    *,
    code: str,
    name: str,
    fund_type: str,
    ledger_id: int | None = None,
    days: int = 190,
    base_nav: float = 1.0,
    daily_step: float = 0.002,
) -> None:
    repo.upsert_pool_item(
        code=code,
        name=name,
        fund_type=fund_type,
        source="test",
        ledger_id=ledger_id,
    )
    start = date.today() - timedelta(days=days)
    repo.save_nav_records(
        code=code,
        source="test",
        records=[
            {
                "date": (start + timedelta(days=i)).isoformat(),
                "unit_nav": round(max(0.1, base_nav + i * daily_step + (i % 9) * 0.0002), 4),
                "accumulated_nav": round(max(0.1, base_nav + i * daily_step + (i % 9) * 0.0002), 4),
                "daily_growth_pct": round(daily_step * 100, 4),
            }
            for i in range(days)
        ],
    )


def test_normalize_fund_code_requires_six_digits() -> None:
    assert normalize_fund_code("110022") == "110022"
    try:
        normalize_fund_code("AAPL")
    except ValueError as exc:
        assert "6 位" in str(exc)
    else:
        raise AssertionError("expected ValueError")


def test_calculate_nav_metrics_returns_risk_and_return_fields() -> None:
    start = date(2025, 1, 1)
    df = pd.DataFrame(
        {
            "date": [(start + timedelta(days=i)).isoformat() for i in range(260)],
            "unit_nav": [1 + i * 0.002 for i in range(260)],
            "accumulated_nav": [1 + i * 0.002 for i in range(260)],
            "daily_growth_pct": [0.2 for _ in range(260)],
        }
    )

    metrics, limitations = calculate_nav_metrics(df)

    assert limitations == []
    assert metrics["sample_days"] == 260
    assert metrics["latest_nav"] > 1
    assert metrics["returns"]["3m"] is not None
    assert metrics["max_drawdown_1y_pct"] <= 0
    assert metrics["trend_state"] in {"uptrend", "sideways", "downtrend"}


def test_refresh_fund_saves_pool_nav_and_analysis_snapshot() -> None:
    DatabaseManager.reset_instance()
    db = DatabaseManager(db_url="sqlite:///:memory:")
    repo = FundRepository(db_manager=db)
    service = FundService(repo=repo, provider=FakeFundProvider())

    snapshot = service.refresh_fund("110022")
    pool = service.list_pool()
    nav_history = service.nav_history("110022", limit=5)

    assert snapshot["code"] == "110022"
    assert snapshot["action"] in {"buy", "dca", "watch", "reduce", "sell_watch", "pause_buy"}
    assert snapshot["metrics"]["latest_nav"] == 2.4
    assert snapshot["metrics"]["returns"]["3m"] == 11.0
    assert snapshot["metrics"]["max_drawdown_1y_pct"] == -16.2
    assert snapshot["metrics"]["metric_sources"]["returns"] == "fund_open_fund_rank_em"
    assert snapshot["metrics"]["metric_sources"]["risk"] == "fund_individual_analysis_xq"
    assert snapshot["metrics"]["profile"]["taxonomy"]["asset_class"] == "active_equity"
    metric_profile = snapshot["metrics"]["profile"]["metric_profile"]
    assert snapshot["metrics"]["profile"]["type_specific_metrics"] == metric_profile
    assert metric_profile["schema_version"] == "fund_metric_profile_v1"
    assert metric_profile["strategy_family"] == "active_equity"
    active_metric_statuses = {
        item["key"]: item["status"]
        for item in metric_profile["primary_metrics"]
    }
    assert active_metric_statuses["three_month_return_pct"] == "ok"
    assert active_metric_statuses["max_drawdown_1y_pct"] == "ok"
    assert active_metric_statuses["volatility_1y_pct"] == "ok"
    assert active_metric_statuses["peer_one_year_percentile"] == "ok"
    assert snapshot["metrics"]["signal_context"]["metric_profile"]["strategy_family"] == "active_equity"
    assert snapshot["metrics"]["profile"]["strategy_readiness"]["signal_model_version"] == "fund_signal_rule_v3_contextual"
    assert snapshot["metrics"]["profile"]["strategy_policy"]["validation_status"] == "heuristic_unvalidated"
    assert snapshot["metrics"]["profile"]["market_context"]["status"] == "ok"
    assert snapshot["metrics"]["profile"]["market_context"]["reference_indices"]
    assert snapshot["metrics"]["profile"]["market_context"]["industry_allocation"]["items"][0]["industry"] == "食品饮料"
    assert snapshot["metrics"]["profile"]["market_context"]["stock_holdings"]["items"][0]["stock_name"] == "贵州茅台"
    assert snapshot["metrics"]["profile"]["research_evidence"]["categories"]["fund_reports"]["items"]
    assert snapshot["metrics"]["profile"]["trading_rules"]["min_purchase_amount"] == 10.0
    assert snapshot["metrics"]["trading_rules"]["fee_tables"]["redemption"][0]["费率"] == "1.50%"
    fee_model = snapshot["metrics"]["trading_rules"]["fee_model"]
    assert fee_model["schema_version"] == "fund_fee_model_v1"
    assert fee_model["subscription"]["tiers"][0]["amount_range"] == "小于100万"
    assert fee_model["subscription"]["first_tier_rate_pct"] == 0.15
    assert fee_model["subscription"]["lowest_rate_pct"] == 0.1
    assert fee_model["subscription"]["highest_rate_pct"] == 0.15
    assert fee_model["subscription"]["selected_rate_pct"] == 0.15
    assert fee_model["subscription"]["selection_policy"] == "use_front_fee_when_available_else_first_public_subscription_tier"
    assert fee_model["redemption"]["tiers"][0]["holding_period"] == "小于7天"
    assert fee_model["redemption"]["conservative_rate_pct"] == 1.5
    assert fee_model["redemption"]["lowest_rate_pct"] == 0.0
    assert fee_model["redemption"]["selection_policy"] == "use_highest_public_redemption_rate_as_conservative_backtest_assumption"
    assert fee_model["annual_expense"]["available"] is False
    assert "management_fee_pct" not in fee_model["annual_expense"]
    assert snapshot["metrics"]["profile"]["calibration_status"]["validation_status"] == "not_validated"
    assert snapshot["metrics"]["signal_context"]["signal_model_version"] == "fund_signal_rule_v3_contextual"
    assert snapshot["metrics"]["signal_context"]["schema_version"] == "fund_signal_context_v3"
    assert snapshot["metrics"]["signal_context"]["validation_status"] == "heuristic_unvalidated"
    assert snapshot["metrics"]["profile"]["data_coverage"]["dimensions"]
    assert snapshot["metrics"]["profile"]["data_quality"]["schema_version"] == "fund_data_quality_v1"
    assert snapshot["metrics"]["profile"]["data_quality"]["overall_status"] in {"ok", "partial"}
    assert snapshot["metrics"]["profile"]["data_quality"]["quality_score"] >= 70
    assert snapshot["metrics"]["profile"]["data_quality_detail"]["schema_version"] == "fund_data_quality_v1"
    quality_dimensions = {
        item["key"]: item
        for item in snapshot["metrics"]["profile"]["data_quality_detail"]["dimensions"]
    }
    assert {
        "metadata",
        "latest_nav",
        "nav_history",
        "peer_returns_rank",
        "risk_metrics",
        "trading_rules_fees",
        "holdings_reports_news",
    }.issubset(quality_dimensions)
    assert quality_dimensions["metadata"]["status"] == "ok"
    assert quality_dimensions["latest_nav"]["status"] == "ok"
    assert quality_dimensions["nav_history"]["sample_count"] == 366
    assert quality_dimensions["peer_returns_rank"]["sample_count"] == 100
    assert quality_dimensions["risk_metrics"]["status"] == "ok"
    assert quality_dimensions["trading_rules_fees"]["status"] == "ok"
    assert quality_dimensions["holdings_reports_news"]["status"] in {"ok", "partial"}
    assert snapshot["metrics"]["data_quality_detail"]["overall_status"] == snapshot["metrics"]["profile"]["data_quality"]["overall_status"]
    signal_context = snapshot["metrics"]["signal_context"]
    assert signal_context["data_quality"]["quality_score"] == snapshot["metrics"]["profile"]["data_quality"]["quality_score"]
    assert signal_context["data_quality"]["dimension_statuses"]["risk_metrics"] == "ok"
    assert signal_context["data_quality"]["dimensions"][0]["key"] == "metadata"
    assert signal_context["calibration"]["applied_to_thresholds"] is False
    assert signal_context["backtest_calibration"]["applied_to_thresholds"] is False
    assert signal_context["execution_constraints"]["purchase_status"] == "开放申购"
    assert signal_context["execution_constraints"]["redemption_status"] == "开放赎回"
    assert signal_context["execution_constraints"]["min_purchase_amount"] == 10.0
    assert signal_context["execution_constraints"]["fee_availability"]["front_fee"] is True
    assert signal_context["execution_constraints"]["fee_model_summary"]["subscription_tiers_available"] is True
    assert signal_context["execution_constraints"]["fee_model_summary"]["redemption_tiers_available"] is True
    assert signal_context["execution_constraints"]["fee_model_summary"]["fees_estimated"] is False
    assert signal_context["execution_constraints"]["fee_model_summary"]["subscription_backtest_rate_pct"] == 0.15
    assert signal_context["execution_constraints"]["fee_model_summary"]["redemption_backtest_rate_pct"] == 1.5
    assert signal_context["decision_checks"]
    assert {item["key"] for item in signal_context["decision_checks"]} >= {
        "data_quality_gate",
        "backtest_calibration",
        "purchase_status",
        "fee_coverage",
    }
    assert signal_context["alternative_actions"]
    assert {"buy", "dca", "watch", "reduce", "sell_watch"} <= {
        item["action"] for item in signal_context["alternative_actions"]
    }
    assert signal_context["confidence_level"] in {"low", "medium", "high", "limited"}
    assert any("不自动下单" in item for item in signal_context["boundaries"])
    assert snapshot["metrics"]["profile"]["data_coverage"]["quality_schema_version"] == "fund_data_quality_v1"
    assert snapshot["peer"]["category"] == "股票型"
    assert pool["total"] == 1
    assert pool["items"][0]["latest_analysis"]["code"] == "110022"
    assert nav_history["total"] == 5


def test_money_market_metric_profile_marks_specialized_metrics_missing_and_keeps_watch() -> None:
    DatabaseManager.reset_instance()
    db = DatabaseManager(db_url="sqlite:///:memory:")
    repo = FundRepository(db_manager=db)
    service = FundService(repo=repo, provider=MoneyMarketProvider())

    snapshot = service.refresh_fund("000001")
    metric_profile = snapshot["metrics"]["profile"]["metric_profile"]
    primary_statuses = {
        item["key"]: item["status"]
        for item in metric_profile["primary_metrics"]
    }
    missing_keys = {
        item["key"]
        for item in metric_profile["missing_specialized_metrics"]
    }
    signal_metric_profile = snapshot["metrics"]["signal_context"]["metric_profile"]

    assert snapshot["action"] == "watch"
    assert metric_profile["strategy_family"] == "money_market"
    assert primary_statuses["seven_day_annualized_yield"] == "missing"
    assert primary_statuses["income_per_10k"] == "missing"
    assert primary_statuses["fund_size_liquidity"] == "missing"
    assert {"seven_day_annualized_yield", "income_per_10k", "fund_size_liquidity"} <= missing_keys
    assert metric_profile["not_applicable_metrics"]
    assert any("只作为解释边界" in item for item in snapshot["metrics"]["signal_context"]["boundaries"])
    assert signal_metric_profile["missing_specialized_metrics"]
    assert snapshot["metrics"]["profile"]["strategy_readiness"]["missing_specialized_metrics"]


def test_index_metric_profile_keeps_tracking_error_and_index_valuation_as_gaps() -> None:
    DatabaseManager.reset_instance()
    db = DatabaseManager(db_url="sqlite:///:memory:")
    repo = FundRepository(db_manager=db)
    service = FundService(repo=repo, provider=IndexFundProvider())

    snapshot = service.refresh_fund("000300")
    metric_profile = snapshot["metrics"]["profile"]["metric_profile"]
    primary_statuses = {
        item["key"]: item["status"]
        for item in metric_profile["primary_metrics"]
    }
    missing_keys = {
        item["key"]
        for item in metric_profile["missing_specialized_metrics"]
    }

    assert metric_profile["strategy_family"] == "index_beta"
    assert metric_profile["asset_class"] == "equity_beta"
    assert primary_statuses["tracking_error"] == "missing"
    assert primary_statuses["tracked_index_name"] == "missing"
    assert primary_statuses["index_valuation_percentile"] == "missing"
    assert {"tracking_error", "tracked_index_name", "index_valuation_percentile"} <= missing_keys
    assert "three_month_return_pct" not in primary_statuses
    assert snapshot["metrics"]["signal_context"]["metric_profile"]["strategy_family"] == "index_beta"


def test_qdii_composite_name_takes_priority_and_marks_subscription_quota_gap() -> None:
    DatabaseManager.reset_instance()
    db = DatabaseManager(db_url="sqlite:///:memory:")
    repo = FundRepository(db_manager=db)
    service = FundService(repo=repo, provider=QdiiCompositeProvider())

    snapshot = service.refresh_fund("000100")
    metric_profile = snapshot["metrics"]["profile"]["metric_profile"]
    missing_by_key = {
        item["key"]: item["label"]
        for item in metric_profile["missing_specialized_metrics"]
    }

    assert metric_profile["strategy_family"] == "qdii_global"
    assert metric_profile["asset_class"] == "global_asset"
    assert missing_by_key["qdii_subscription_quota"] == "申赎额度/额度限制"
    assert snapshot["metrics"]["signal_context"]["metric_profile"]["strategy_family"] == "qdii_global"


def test_fof_composite_name_takes_priority_and_marks_asset_allocation_gap() -> None:
    DatabaseManager.reset_instance()
    db = DatabaseManager(db_url="sqlite:///:memory:")
    repo = FundRepository(db_manager=db)
    service = FundService(repo=repo, provider=FofCompositeProvider())

    snapshot = service.refresh_fund("000200")
    metric_profile = snapshot["metrics"]["profile"]["metric_profile"]
    missing_by_key = {
        item["key"]: item["label"]
        for item in metric_profile["missing_specialized_metrics"]
    }

    assert metric_profile["strategy_family"] == "fof_allocation"
    assert metric_profile["asset_class"] == "multi_asset"
    assert missing_by_key["asset_allocation_exposure"] == "资产配置比例/大类资产暴露"
    assert snapshot["metrics"]["signal_context"]["metric_profile"]["strategy_family"] == "fof_allocation"


def test_refresh_fund_marks_missing_risk_and_fee_quality_warnings() -> None:
    DatabaseManager.reset_instance()
    db = DatabaseManager(db_url="sqlite:///:memory:")
    repo = FundRepository(db_manager=db)
    service = FundService(repo=repo, provider=MissingRiskFeeProvider())

    snapshot = service.refresh_fund("110022")
    detail = snapshot["metrics"]["profile"]["data_quality_detail"]
    dimensions = {item["key"]: item for item in detail["dimensions"]}
    warnings = "\n".join(detail["warnings"])

    assert dimensions["risk_metrics"]["status"] == "estimated"
    assert dimensions["risk_metrics"]["source"] == "nav_calculation"
    assert "平台风险接口不可用" in dimensions["risk_metrics"]["reason"]
    assert dimensions["trading_rules_fees"]["status"] == "partial"
    assert "申购费率表暂不可用" in warnings
    assert "赎回费率表暂不可用" in warnings
    assert detail["overall_status"] == "partial"
    assert snapshot["data_quality"] == "partial"
    signal_context = snapshot["metrics"]["signal_context"]
    assert signal_context["data_quality"]["overall_status"] == "partial"
    assert signal_context["data_quality"]["dimension_statuses"]["risk_metrics"] == "estimated"
    assert signal_context["execution_constraints"]["fees_estimated"] is True
    assert signal_context["execution_constraints"]["fee_availability"]["subscription_fee_table"] is False
    assert signal_context["execution_constraints"]["fee_availability"]["redemption_fee_table"] is False
    assert signal_context["execution_constraints"]["fee_model_summary"]["subscription_tiers_available"] is False
    assert signal_context["execution_constraints"]["fee_model_summary"]["redemption_tiers_available"] is False
    assert signal_context["execution_constraints"]["fee_model_summary"]["fees_estimated"] is True
    assert any(
        item["key"] == "fee_coverage" and item["status"] == "warn"
        for item in signal_context["decision_checks"]
    )
    assert signal_context["confidence_level"] in {"low", "limited"}


def test_refresh_fund_adds_annual_expense_only_when_provider_discloses_it() -> None:
    DatabaseManager.reset_instance()
    db = DatabaseManager(db_url="sqlite:///:memory:")
    repo = FundRepository(db_manager=db)
    service = FundService(repo=repo, provider=AnnualExpenseProvider())

    snapshot = service.refresh_fund("110022")
    annual_expense = snapshot["metrics"]["trading_rules"]["fee_model"]["annual_expense"]
    summary = snapshot["metrics"]["signal_context"]["execution_constraints"]["fee_model_summary"]

    assert annual_expense["available"] is True
    assert annual_expense["management_fee_pct"] == 1.5
    assert annual_expense["custody_fee_pct"] == 0.25
    assert annual_expense["sales_service_fee_pct"] == 0.0
    assert summary["annual_expense_available"] is True


def test_fund_backtest_keeps_zero_fee_assumption_warning_when_fees_missing() -> None:
    DatabaseManager.reset_instance()
    db = DatabaseManager(db_url="sqlite:///:memory:")
    repo = FundRepository(db_manager=db)
    service = FundService(repo=repo, provider=NoFeeProvider())

    service.refresh_fund("110022")
    result = service.backtest(
        "110022",
        lookback_days=120,
        eval_window_days=40,
        rebalance_interval_days=20,
        initial_cash=10000,
        dca_amount=1000,
    )

    assert result["status"] == "completed"
    assert result["fee_assumptions"]["source"] == "zero_fee_assumption"
    assert result["fee_assumptions"]["subscription_fee_pct"] == 0.0
    assert result["fee_assumptions"]["redemption_fee_pct"] == 0.0
    assert result["fee_assumptions"]["fees_estimated"] is True
    assert "申购费率缺失" in "\n".join(result["fee_assumptions"]["limitations"])
    assert "赎回费率缺失" in "\n".join(result["fee_assumptions"]["limitations"])
    assert any("回测费用按 0% 暂估" in item for item in result["limitations"])


def test_refresh_fund_explains_paused_purchase_signal_alternatives() -> None:
    DatabaseManager.reset_instance()
    db = DatabaseManager(db_url="sqlite:///:memory:")
    repo = FundRepository(db_manager=db)
    service = FundService(repo=repo, provider=PausedPurchaseProvider())

    snapshot = service.refresh_fund("110022")
    signal_context = snapshot["metrics"]["signal_context"]
    alternatives = {
        item["action"]: item
        for item in signal_context["alternative_actions"]
    }

    assert snapshot["action"] == "pause_buy"
    assert signal_context["execution_constraints"]["purchase_status"] == "暂停申购"
    assert alternatives["pause_buy"]["status"] == "selected"
    assert alternatives["buy"]["status"] == "blocked"
    assert alternatives["dca"]["status"] == "blocked"
    assert signal_context["confidence_level"] == "limited"


def test_refresh_fund_marks_stale_peer_and_evidence_dates() -> None:
    DatabaseManager.reset_instance()
    db = DatabaseManager(db_url="sqlite:///:memory:")
    repo = FundRepository(db_manager=db)
    service = FundService(repo=repo, provider=StaleQualityProvider())

    snapshot = service.refresh_fund("110022")
    detail = snapshot["metrics"]["profile"]["data_quality_detail"]
    dimensions = {item["key"]: item for item in detail["dimensions"]}
    warnings = "\n".join(detail["warnings"])

    assert dimensions["peer_returns_rank"]["status"] == "stale"
    assert "公开榜单日期距今" in dimensions["peer_returns_rank"]["reason"]
    assert dimensions["holdings_reports_news"]["status"] == "stale"
    assert "超过 365 天" in dimensions["holdings_reports_news"]["reason"]
    assert "公开收益榜单/同类分位stale" in warnings
    assert "持仓/行业/报告/资讯佐证stale" in warnings
    assert snapshot["metrics"]["signal_context"]["data_quality"]["dimension_statuses"]["peer_returns_rank"] == "stale"
    assert snapshot["metrics"]["signal_context"]["data_quality"]["dimension_statuses"]["holdings_reports_news"] == "stale"


def test_data_quality_rejects_unknown_report_date_as_ok_evidence() -> None:
    latest_date = (date.today() - timedelta(days=2)).isoformat()
    evidence_date = (date.today() - timedelta(days=90)).isoformat()
    metrics = {
        "latest_nav": 2.4,
        "latest_date": latest_date,
        "sample_days": 366,
        "returns": {"3m": 11.0, "6m": 18.0, "1y": 26.0},
        "max_drawdown_1y_pct": -16.2,
        "volatility_1y_pct": 18.5,
        "sharpe_1y": 1.8,
        "metric_sources": {"returns": "fund_open_fund_rank_em", "risk": "fund_individual_analysis_xq"},
    }
    peer = {
        "sample_size": 100,
        "rank": 18,
        "percentiles": {"1y": 82.0},
        "date": latest_date,
    }
    market_context = {
        "industry_allocation": {
            "status": "ok",
            "latest_date": evidence_date,
            "items": [{"industry": "食品饮料", "nav_ratio_pct": 32.5}],
        },
        "stock_holdings": {
            "status": "ok",
            "latest_date": evidence_date,
            "items": [{"stock_name": "贵州茅台", "nav_ratio_pct": 8.9}],
        },
        "fund_reports": {
            "status": "ok",
            "items": [{"title": "季度报告", "date": "not-a-date", "report_id": "BAD-DATE"}],
        },
    }
    research_evidence = {
        "status": "connected",
        "categories": {
            "industry_news": {"items": [{"title": "行业新闻"}]},
            "holding_company_news": {"items": [{"title": "公司新闻"}]},
            "macro_market_news": {"items": [{"title": "市场新闻"}]},
        },
    }

    detail = build_data_quality_detail(
        code="110022",
        name="易方达消费行业股票",
        fund_type="股票型",
        metrics=metrics,
        peer=peer,
        latest_quote=FundLatestQuote(code="110022", unit_nav=2.4, nav_date=date.today() - timedelta(days=2)),
        risk_analysis={"max_drawdown_1y_pct": -16.2, "volatility_1y_pct": 18.5, "sharpe_1y": 1.8},
        market_context=market_context,
        research_evidence=research_evidence,
        trading_rules={"status": "ok", "purchase_status": "开放申购", "redemption_status": "开放赎回", "fee_tables": {"subscription": [{"费率": "0.15%"}], "redemption": [{"费率": "1.50%"}]}},
        limitations=[],
    )
    dimension = {item["key"]: item for item in detail["dimensions"]}["holdings_reports_news"]
    warnings = "\n".join(detail["warnings"])

    assert dimension["status"] != "ok"
    assert "fund_reports" in "\n".join(dimension["notes"])
    assert "日期未知的佐证：fund_reports" in warnings


def test_data_quality_future_dates_are_downgraded() -> None:
    future = date.today() + timedelta(days=5)
    future_iso = future.isoformat()
    metrics = {
        "latest_nav": 2.4,
        "latest_date": future_iso,
        "sample_days": 366,
        "returns": {"3m": 11.0},
        "max_drawdown_1y_pct": -16.2,
        "volatility_1y_pct": 18.5,
        "sharpe_1y": 1.8,
        "metric_sources": {"returns": "fund_open_fund_rank_em", "risk": "fund_individual_analysis_xq"},
    }
    detail = build_data_quality_detail(
        code="110022",
        name="易方达消费行业股票",
        fund_type="股票型",
        metrics=metrics,
        peer={
            "sample_size": 100,
            "rank": 18,
            "returns": {"3m": 11.0},
            "percentiles": {"1y": 82.0},
            "date": future_iso,
        },
        latest_quote=FundLatestQuote(code="110022", unit_nav=2.4, nav_date=future),
        risk_analysis={"max_drawdown_1y_pct": -16.2, "volatility_1y_pct": 18.5, "sharpe_1y": 1.8},
        market_context={
            "industry_allocation": {"latest_date": future_iso, "items": [{"industry": "食品饮料"}]},
            "stock_holdings": {"latest_date": future_iso, "items": [{"stock_name": "贵州茅台"}]},
            "fund_reports": {"items": [{"title": "未来报告", "date": future_iso}]},
        },
        research_evidence={},
        trading_rules={"status": "ok", "purchase_status": "开放申购", "redemption_status": "开放赎回", "fee_tables": {"subscription": [{"费率": "0.15%"}], "redemption": [{"费率": "1.50%"}]}},
        limitations=[],
    )
    dimensions = {item["key"]: item for item in detail["dimensions"]}
    warnings = "\n".join(detail["warnings"])

    assert dimensions["latest_nav"]["status"] == "partial"
    assert dimensions["nav_history"]["status"] == "partial"
    assert dimensions["peer_returns_rank"]["status"] == "partial"
    assert dimensions["holdings_reports_news"]["status"] == "partial"
    assert "晚于今天" in warnings


def test_peer_quality_ignores_nav_only_returns() -> None:
    latest_date = (date.today() - timedelta(days=2)).isoformat()
    detail = build_data_quality_detail(
        code="110022",
        name="易方达消费行业股票",
        fund_type="股票型",
        metrics={
            "latest_nav": 2.4,
            "latest_date": latest_date,
            "sample_days": 366,
            "returns": {"3m": 11.0, "6m": 18.0},
            "max_drawdown_1y_pct": -16.2,
            "volatility_1y_pct": 18.5,
            "sharpe_1y": 1.8,
            "metric_sources": {"returns": "nav_calculation", "risk": "nav_calculation"},
        },
        peer={"sample_size": 100, "rank": 18, "date": latest_date},
        latest_quote=FundLatestQuote(code="110022", unit_nav=2.4, nav_date=date.today() - timedelta(days=2)),
        risk_analysis=None,
        market_context={},
        research_evidence={},
        trading_rules={},
        limitations=[],
    )
    peer_dimension = {item["key"]: item for item in detail["dimensions"]}["peer_returns_rank"]

    assert peer_dimension["field_count"] == 0
    assert peer_dimension["status"] != "ok"


def test_fund_pool_supports_ledgers_and_manual_assignment() -> None:
    DatabaseManager.reset_instance()
    db = DatabaseManager(db_url="sqlite:///:memory:")
    repo = FundRepository(db_manager=db)
    service = FundService(repo=repo, provider=FakeFundProvider())

    service.add_to_pool("110022")
    pool = service.list_pool()
    default_ledger = pool["ledgers"][0]
    ledger = service.create_ledger("长期账户", "#22C55E")
    moved = service.assign_fund_ledger("110022", ledger["id"])
    pool_after = service.list_pool()

    assert default_ledger["is_default"] is True
    assert default_ledger["name"] == "全部基金"
    assert ledger["name"] == "长期账户"
    assert ledger["color"] == "#22C55E"
    assert moved["ledger_id"] == ledger["id"]
    assert any(item["ledger_id"] == ledger["id"] for item in pool_after["items"])
    assert any(item["fund_count"] == 1 for item in pool_after["ledgers"] if item["id"] == ledger["id"])


def test_fund_ledger_supports_local_account_profile_create_update_and_list() -> None:
    DatabaseManager.reset_instance()
    db = DatabaseManager(db_url="sqlite:///:memory:")
    repo = FundRepository(db_manager=db)
    service = FundService(repo=repo, provider=FakeFundProvider())

    service.add_to_pool("110022")
    ledger = service.create_ledger(
        "教育账户",
        "#22C55E",
        account_type="education",
        purpose="孩子教育金",
        risk_target="balanced",
        investment_horizon="3y+",
        rebalance_frequency="quarterly",
        notes="只记录本地目标，不接个人平台账户",
    )
    moved = service.assign_fund_ledger("110022", ledger["id"])
    updated = service.update_ledger_profile(
        ledger["id"],
        risk_target="aggressive",
        investment_horizon="5y+",
        rebalance_frequency="ad_hoc",
        notes=None,
    )
    pool_after = service.list_pool()
    listed = next(item for item in pool_after["ledgers"] if item["id"] == ledger["id"])

    assert ledger["account_type"] == "education"
    assert ledger["purpose"] == "孩子教育金"
    assert ledger["risk_target"] == "balanced"
    assert ledger["investment_horizon"] == "3y+"
    assert ledger["rebalance_frequency"] == "quarterly"
    assert moved["ledger_id"] == ledger["id"]
    assert updated["risk_target"] == "aggressive"
    assert updated["investment_horizon"] == "5y+"
    assert updated["rebalance_frequency"] == "ad_hoc"
    assert updated["notes"] is None
    assert listed["account_type"] == "education"
    assert listed["purpose"] == "孩子教育金"
    assert listed["risk_target"] == "aggressive"
    assert listed["fund_count"] == 1


def test_default_fund_ledger_can_hold_profile_without_required_fields() -> None:
    DatabaseManager.reset_instance()
    db = DatabaseManager(db_url="sqlite:///:memory:")
    repo = FundRepository(db_manager=db)
    service = FundService(repo=repo, provider=FakeFundProvider())

    default_ledger = service.list_pool()["ledgers"][0]
    updated = service.update_ledger_profile(
        default_ledger["id"],
        purpose="默认观察池",
        risk_target="conservative",
    )
    pool_after = service.list_pool()
    listed = next(item for item in pool_after["ledgers"] if item["id"] == default_ledger["id"])

    assert updated["is_default"] is True
    assert updated["purpose"] == "默认观察池"
    assert listed["risk_target"] == "conservative"
    assert listed["investment_horizon"] is None


def test_fund_ledger_profile_columns_migrate_existing_sqlite() -> None:
    DatabaseManager.reset_instance()
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "legacy.sqlite"
        connection = sqlite3.connect(db_path)
        try:
            connection.execute(
                """
                CREATE TABLE fund_ledgers (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name VARCHAR(80) NOT NULL UNIQUE,
                    color VARCHAR(16) NOT NULL,
                    sort_order INTEGER NOT NULL,
                    is_default BOOLEAN NOT NULL,
                    active BOOLEAN NOT NULL,
                    created_at DATETIME,
                    updated_at DATETIME
                )
                """
            )
            connection.execute(
                """
                INSERT INTO fund_ledgers (
                    name, color, sort_order, is_default, active, created_at, updated_at
                ) VALUES ('全部基金', '#06B6D4', 0, 1, 1, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                """
            )
            connection.commit()
        finally:
            connection.close()

        db = DatabaseManager(db_url=f"sqlite:///{db_path}")
        repo = FundRepository(db_manager=db)
        service = FundService(repo=repo, provider=FakeFundProvider())
        pool = service.list_pool()
        default_ledger = pool["ledgers"][0]
        updated = service.update_ledger_profile(default_ledger["id"], account_type="long_term")

        assert default_ledger["account_type"] is None
        assert default_ledger["purpose"] is None
        assert updated["account_type"] == "long_term"


def test_create_ledger_rejects_duplicate_name_without_overwriting_profile() -> None:
    DatabaseManager.reset_instance()
    db = DatabaseManager(db_url="sqlite:///:memory:")
    repo = FundRepository(db_manager=db)
    service = FundService(repo=repo, provider=FakeFundProvider())

    created = service.create_ledger(
        "教育账户",
        "#22C55E",
        account_type="education",
        purpose="孩子教育金",
        risk_target="balanced",
        notes="原始画像",
    )

    try:
        service.create_ledger(
            "教育账户",
            "#EF4444",
            account_type="retirement",
            purpose="退休账户",
            risk_target="aggressive",
            notes="不应覆盖",
        )
        assert False, "expected duplicate ledger name to raise"
    except ValueError as exc:
        assert str(exc) == "账本名称已存在"

    listed = next(item for item in service.list_pool()["ledgers"] if item["id"] == created["id"])
    assert listed["color"] == "#22C55E"
    assert listed["account_type"] == "education"
    assert listed["purpose"] == "孩子教育金"
    assert listed["risk_target"] == "balanced"
    assert listed["notes"] == "原始画像"


def test_create_ledger_rejects_duplicate_inactive_name() -> None:
    DatabaseManager.reset_instance()
    db = DatabaseManager(db_url="sqlite:///:memory:")
    repo = FundRepository(db_manager=db)
    service = FundService(repo=repo, provider=FakeFundProvider())

    created = service.create_ledger("备用账户", "#22C55E", purpose="旧账本")

    def _deactivate(session):
        ledger = session.get(storage_module.FundLedger, created["id"])
        assert ledger is not None
        ledger.active = False
        return ledger.id

    db._run_write_transaction("deactivate_test_ledger", _deactivate)

    try:
        service.create_ledger("备用账户", "#EF4444", purpose="新账本")
        assert False, "expected duplicate inactive ledger name to raise"
    except ValueError as exc:
        assert str(exc) == "账本名称已存在"


def test_update_ledger_rejects_duplicate_inactive_name() -> None:
    DatabaseManager.reset_instance()
    db = DatabaseManager(db_url="sqlite:///:memory:")
    repo = FundRepository(db_manager=db)
    service = FundService(repo=repo, provider=FakeFundProvider())

    active = service.create_ledger("稳健账户", "#22C55E", purpose="保留原名")
    inactive = service.create_ledger("备用账户", "#0EA5E9", purpose="旧账本")

    def _deactivate(session):
        ledger = session.get(storage_module.FundLedger, inactive["id"])
        assert ledger is not None
        ledger.active = False
        return ledger.id

    db._run_write_transaction("deactivate_duplicate_name_test_ledger", _deactivate)

    try:
        service.update_ledger_profile(active["id"], name="备用账户")
        assert False, "expected duplicate inactive ledger name to raise"
    except ValueError as exc:
        assert str(exc) == "账本名称已存在"

    listed = next(item for item in service.list_pool()["ledgers"] if item["id"] == active["id"])
    assert listed["name"] == "稳健账户"
    assert listed["purpose"] == "保留原名"


def test_fund_pool_item_ledger_column_migrates_existing_sqlite() -> None:
    DatabaseManager.reset_instance()
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "legacy-pool.sqlite"
        connection = sqlite3.connect(db_path)
        try:
            connection.execute(
                """
                CREATE TABLE fund_pool_items (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    code VARCHAR(12) NOT NULL UNIQUE,
                    name VARCHAR(100),
                    fund_type VARCHAR(50),
                    source VARCHAR(50),
                    active BOOLEAN NOT NULL,
                    notes TEXT,
                    last_refreshed_at DATETIME,
                    created_at DATETIME,
                    updated_at DATETIME
                )
                """
            )
            connection.execute(
                """
                INSERT INTO fund_pool_items (
                    code, name, fund_type, source, active, created_at, updated_at
                ) VALUES ('110022', '易方达消费行业股票', '股票型', 'legacy', 1, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                """
            )
            connection.commit()
        finally:
            connection.close()

        db = DatabaseManager(db_url=f"sqlite:///{db_path}")
        repo = FundRepository(db_manager=db)
        service = FundService(repo=repo, provider=FakeFundProvider())
        pool = service.list_pool()

        item = next(row for row in pool["items"] if row["code"] == "110022")
        default_ledger = next(row for row in pool["ledgers"] if row["is_default"])
        assert item["ledger_id"] == default_ledger["id"]
        assert default_ledger["name"] == "全部基金"


def test_fund_pool_ledger_column_migration_fail_fast_on_inspect_error() -> None:
    manager = object.__new__(DatabaseManager)
    manager._is_sqlite_engine = True
    manager._engine = object()

    original_inspect = storage_module.inspect
    try:
        def _broken_inspect(_engine):
            raise RuntimeError("inspect failed")

        storage_module.inspect = _broken_inspect
        try:
            manager._ensure_fund_pool_item_ledger_columns()
            assert False, "expected inspect failure to raise"
        except RuntimeError as exc:
            assert "账本列检查失败" in str(exc)
    finally:
        storage_module.inspect = original_inspect


def test_fund_ledger_profile_column_migration_fail_fast_on_alter_error() -> None:
    class FakeConnection:
        def exec_driver_sql(self, _sql):
            raise OperationalError("ALTER TABLE", None, sqlite3.OperationalError("disk I/O error"))

    class FakeBeginContext:
        def __enter__(self):
            return FakeConnection()

        def __exit__(self, exc_type, exc, tb):
            return False

    class FakeEngine:
        def begin(self):
            return FakeBeginContext()

    class FakeInspector:
        def get_columns(self, _table_name):
            return [{"name": "id"}, {"name": "name"}]

    manager = object.__new__(DatabaseManager)
    manager._is_sqlite_engine = True
    manager._engine = FakeEngine()
    manager._sqlite_write_retry_max = 0
    manager._sqlite_write_retry_base_delay = 0

    original_inspect = storage_module.inspect
    try:
        storage_module.inspect = lambda _engine: FakeInspector()
        try:
            manager._ensure_fund_ledger_profile_columns()
            assert False, "expected ALTER TABLE failure to raise"
        except RuntimeError as exc:
            assert "补列失败" in str(exc)
            assert "account_type" in str(exc)
    finally:
        storage_module.inspect = original_inspect


def test_fund_backtest_runs_walk_forward_with_fee_assumptions() -> None:
    DatabaseManager.reset_instance()
    db = DatabaseManager(db_url="sqlite:///:memory:")
    repo = FundRepository(db_manager=db)
    service = FundService(repo=repo, provider=FakeFundProvider())

    service.refresh_fund("110022")
    result = service.backtest(
        "110022",
        lookback_days=120,
        eval_window_days=40,
        rebalance_interval_days=20,
        initial_cash=10000,
        dca_amount=1000,
    )

    assert result["status"] == "completed"
    assert result["engine_version"] == "fund_nav_walk_forward_v1"
    assert result["methodology"]["no_future_data"] is True
    assert result["summary"]["signal_count"] > 0
    assert result["summary"]["strategy_return_pct"] is not None
    assert result["summary"]["buy_hold_return_pct"] is not None
    assert result["summary"]["transaction_count"] >= 0
    assert result["signals"][0]["signal_date"] > (date.today() - timedelta(days=365)).isoformat()
    assert result["signals"][0]["evaluation_end_date"] > result["signals"][0]["signal_date"]
    assert result["fee_assumptions"]["subscription_fee_pct"] == 0.15
    assert result["fee_assumptions"]["redemption_fee_pct"] == 1.5
    assert result["fee_assumptions"]["source"] == "latest_analysis.trading_rules.fee_model"
    assert result["fee_assumptions"]["fees_estimated"] is False
    assert result["fee_assumptions"]["subscription_fee_source"] == "fund_purchase_em.front_fee"
    assert result["fee_assumptions"]["redemption_fee_source"] == "fund_fee_em.赎回费率"
    assert result["fee_assumptions"]["subscription_fee_model"] == "use_front_fee_when_available_else_first_public_subscription_tier"
    assert result["fee_assumptions"]["redemption_fee_model"] == "use_highest_public_redemption_rate_as_conservative_backtest_assumption"
    assert "未来净值" in "".join(result["limitations"])


def test_fund_backtest_reports_insufficient_nav_samples() -> None:
    DatabaseManager.reset_instance()
    db = DatabaseManager(db_url="sqlite:///:memory:")
    repo = FundRepository(db_manager=db)
    service = FundService(repo=repo, provider=FakeFundProvider())
    start = date.today() - timedelta(days=100)
    repo.upsert_pool_item(code="110023", name="短样本基金", fund_type="混合型", source="test")
    repo.save_nav_records(
        code="110023",
        source="test",
        records=[
            {
                "date": (start + timedelta(days=i)).isoformat(),
                "unit_nav": 1 + i * 0.001,
                "accumulated_nav": 1 + i * 0.001,
                "daily_growth_pct": 0.1,
            }
            for i in range(80)
        ],
    )

    result = service.backtest("110023", lookback_days=60, eval_window_days=30, rebalance_interval_days=10)

    assert result["status"] == "insufficient_data"
    assert result["summary"]["sample_days"] == 80
    assert result["summary"]["required_sample_days"] == 91
    assert result["signals"] == []


def test_fund_backtest_calibration_aggregates_multiple_funds_and_actions() -> None:
    DatabaseManager.reset_instance()
    db = DatabaseManager(db_url="sqlite:///:memory:")
    repo = FundRepository(db_manager=db)
    service = FundService(repo=repo, provider=FakeFundProvider())

    ledger = service.create_ledger("长期账户", "#22C55E")
    _seed_calibration_fund(repo, code="110022", name="权益一号", fund_type="股票型")
    _seed_calibration_fund(repo, code="110023", name="权益二号", fund_type="股票型", ledger_id=ledger["id"], base_nav=1.2)
    _seed_calibration_fund(repo, code="110024", name="稳健一号", fund_type="债券型", ledger_id=ledger["id"], base_nav=0.9, daily_step=0.0015)

    result = service.calibrate_backtests(
        lookback_days=60,
        eval_window_days=20,
        rebalance_interval_days=10,
        initial_cash=10000,
    )

    assert result["schema_version"] == "fund_backtest_calibration_v1"
    assert result["status"] == "completed"
    assert result["calibration_status"]["status"] == "usable"
    assert result["calibration_status"]["completed_funds"] == 3
    assert result["calibration_status"]["sample_signals"] >= 30
    assert {item["code"] for item in result["by_fund"]} == {"110022", "110023", "110024"}
    assert {item["fund_type"] for item in result["by_fund_type"]} == {"股票型", "债券型"}
    default_ledger_id = next(item["ledger_id"] for item in result["by_fund"] if item["code"] == "110022")
    assert {item["ledger_id"] for item in result["by_ledger"]} == {default_ledger_id, ledger["id"]}

    total_fund_signals = sum(item["signal_count"] for item in result["by_fund"])
    total_action_signals = sum(
        stat["signal_count"]
        for group in result["by_fund_type"]
        for stat in group["action_stats"].values()
    )
    assert total_action_signals == total_fund_signals
    assert any(stat["wins"] > 0 for item in result["by_fund"] for stat in item["action_stats"].values())


def test_fund_backtest_calibration_filters_by_ledger_and_fund_type() -> None:
    DatabaseManager.reset_instance()
    db = DatabaseManager(db_url="sqlite:///:memory:")
    repo = FundRepository(db_manager=db)
    service = FundService(repo=repo, provider=FakeFundProvider())

    ledger = service.create_ledger("长期账户", "#22C55E")
    _seed_calibration_fund(repo, code="110022", name="权益一号", fund_type="股票型")
    _seed_calibration_fund(repo, code="110023", name="权益二号", fund_type="股票型", ledger_id=ledger["id"])
    _seed_calibration_fund(repo, code="110024", name="稳健一号", fund_type="债券型", ledger_id=ledger["id"])

    ledger_result = service.calibrate_backtests(
        ledger_id=ledger["id"],
        lookback_days=60,
        eval_window_days=20,
        rebalance_interval_days=10,
    )
    type_result = service.calibrate_backtests(
        fund_type="债券型",
        lookback_days=60,
        eval_window_days=20,
        rebalance_interval_days=10,
    )
    code_result = service.calibrate_backtests(
        codes=["110024"],
        lookback_days=60,
        eval_window_days=20,
        rebalance_interval_days=10,
    )

    assert {item["code"] for item in ledger_result["by_fund"]} == {"110023", "110024"}
    assert all(item["ledger_id"] == ledger["id"] for item in ledger_result["by_fund"])
    assert {item["code"] for item in type_result["by_fund"]} == {"110024"}
    assert type_result["by_fund_type"][0]["fund_type"] == "债券型"
    assert code_result["scope"]["requested_codes"] == ["110024"]
    assert {item["code"] for item in code_result["by_fund"]} == {"110024"}


def test_fund_backtest_calibration_labels_codes_filtered_out_of_scope() -> None:
    pool = {
        "items": [
            {"code": "110022", "name": "权益一号", "fund_type": "股票型", "ledger_id": 1},
            {"code": "110023", "name": "权益二号", "fund_type": "股票型", "ledger_id": 2},
            {"code": "110024", "name": "稳健一号", "fund_type": "债券型", "ledger_id": 1},
        ],
        "ledgers": [{"id": 1, "name": "长期账户"}],
    }

    result = calibrate_fund_backtests(
        pool=pool,
        backtest_runner=lambda code: {
            "code": code,
            "status": "completed",
            "summary": {"sample_days": 120, "signal_count": 8, "hit_rate_pct": 50.0},
            "signals": [],
            "limitations": [],
        },
        ledger_id=1,
        fund_type="股票型",
        codes=["110022", "110023", "999999"],
    )
    limitations = "\n".join(result["limitations"])

    assert result["scope"]["codes"] == ["110022"]
    assert "请求代码不在当前筛选范围中，已跳过：110023" in limitations
    assert "请求代码不在当前基金池中，已跳过：999999" in limitations
    assert "请求代码不在当前基金池中，已跳过：110023" not in limitations


def test_fund_backtest_calibration_failed_fund_does_not_pollute_aggregates() -> None:
    pool = {
        "items": [
            {"code": "110022", "name": "成功基金", "fund_type": "股票型", "ledger_id": 1},
            {"code": "110023", "name": "失败基金", "fund_type": "股票型", "ledger_id": 1},
        ],
        "ledgers": [{"id": 1, "name": "长期账户"}],
    }

    def backtest_runner(code: str):
        if code == "110023":
            raise RuntimeError("boom")
        return {
            "code": code,
            "status": "completed",
            "summary": {
                "sample_days": 120,
                "signal_count": 2,
                "hit_rate_pct": 100.0,
                "total_fees": 12.0,
                "fee_drag_pct": 0.12,
            },
            "signals": [
                {
                    "action": "buy",
                    "outcome": "win",
                    "fund_forward_return_pct": 2.0,
                    "fund_forward_drawdown_pct": -1.0,
                    "fee": 5.0,
                },
                {
                    "action": "buy",
                    "outcome": "win",
                    "fund_forward_return_pct": 4.0,
                    "fund_forward_drawdown_pct": -2.0,
                    "fee": 7.0,
                },
            ],
            "limitations": [],
        }

    result = calibrate_fund_backtests(
        pool=pool,
        backtest_runner=backtest_runner,
        initial_cash=10000,
    )
    group = result["by_fund_type"][0]
    failed = next(item for item in result["by_fund"] if item["code"] == "110023")

    assert result["status"] == "partial"
    assert failed["status"] == "failed"
    assert failed["signal_count"] == 0
    assert group["sample_funds"] == 2
    assert group["completed_funds"] == 1
    assert group["sample_signals"] == 2
    assert group["action_hit_rate_pct"] == 100.0
    assert group["avg_forward_return_pct"] == 3.0
    assert group["total_fees"] == 12.0
    assert group["fee_drag_pct"] == 0.12


def test_fund_backtest_calibration_ignores_insufficient_data_in_hit_rate() -> None:
    DatabaseManager.reset_instance()
    db = DatabaseManager(db_url="sqlite:///:memory:")
    repo = FundRepository(db_manager=db)
    service = FundService(repo=repo, provider=FakeFundProvider())

    _seed_calibration_fund(repo, code="110022", name="长样本基金", fund_type="股票型", days=190)
    _seed_calibration_fund(repo, code="110023", name="短样本基金", fund_type="股票型", days=80)

    result = service.calibrate_backtests(
        lookback_days=60,
        eval_window_days=30,
        rebalance_interval_days=10,
    )

    completed = next(item for item in result["by_fund"] if item["code"] == "110022")
    insufficient = next(item for item in result["by_fund"] if item["code"] == "110023")
    group = result["by_fund_type"][0]

    assert result["status"] == "partial"
    assert insufficient["status"] == "insufficient_data"
    assert insufficient["signal_count"] == 0
    assert insufficient["action_hit_rate_pct"] is None
    assert group["completed_funds"] == 1
    assert group["sample_signals"] == completed["signal_count"]
    assert group["action_hit_rate_pct"] == completed["action_hit_rate_pct"]
