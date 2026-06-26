# -*- coding: utf-8 -*-
from __future__ import annotations

from datetime import date

from src.repositories.fund_repo import FundRepository
from src.services.fund_holding_import_service import FundHoldingImportService
from src.services.fund_personal_action_service import (
    FUND_PERSONAL_ACTIONS_SCHEMA_VERSION,
    FundPersonalActionService,
)
from src.storage import DatabaseManager


def teardown_function():
    DatabaseManager.reset_instance()


def test_personal_actions_block_when_no_confirmed_holdings() -> None:
    DatabaseManager.reset_instance()
    db = DatabaseManager(db_url="sqlite:///:memory:")
    repo = FundRepository(db_manager=db)
    service = FundPersonalActionService(repo=repo)

    result = service.build()

    assert result["schema_version"] == FUND_PERSONAL_ACTIONS_SCHEMA_VERSION
    assert result["status"] == "blocked"
    assert result["summary"]["holding_count"] == 0
    assert "missing_holdings" in result["blockers"]
    assert result["actions"] == []


def test_personal_actions_show_blockers_without_profile_or_analysis() -> None:
    DatabaseManager.reset_instance()
    db = DatabaseManager(db_url="sqlite:///:memory:")
    repo = FundRepository(db_manager=db)
    importer = FundHoldingImportService(repo=repo)
    importer.confirm_import(
        source_platform="alipay",
        holdings=[{"code": "021528", "name": "财通成长优选混合C", "market_value": 12000.0}],
    )
    service = FundPersonalActionService(repo=repo)

    result = service.build()
    action = result["actions"][0]

    assert result["status"] == "partial"
    assert action["personal_action"] == "refresh_analysis"
    assert "missing_ledger_profile" in action["blockers"]
    assert "missing_analysis" in action["blockers"]
    assert action["confidence"] == "low"


def test_personal_actions_become_actionable_with_profile_and_analysis() -> None:
    DatabaseManager.reset_instance()
    db = DatabaseManager(db_url="sqlite:///:memory:")
    repo = FundRepository(db_manager=db)
    importer = FundHoldingImportService(repo=repo)
    confirmed = importer.confirm_import(
        source_platform="alipay",
        holdings=[
            {
                "code": "021528",
                "name": "财通成长优选混合C",
                "market_value": 12000.0,
                "pnl_pct": 8.5,
            }
        ],
    )
    repo.update_ledger_profile(
        confirmed["ledger"]["id"],
        risk_target="growth",
        investment_horizon="3y_plus",
        rebalance_frequency="monthly",
    )
    repo.save_analysis_snapshot(
        {
            "code": "021528",
            "name": "财通成长优选混合C",
            "fund_type": "混合型",
            "analysis_date": date.today().isoformat(),
            "action": "buy",
            "action_label": "申购",
            "risk_level": "中",
            "risk_score": 46.0,
            "signal_score": 82.0,
            "summary": "公开数据趋势偏强，允许进入加仓研究。",
            "metrics": {
                "profile": {
                    "strategy_family": "active_equity",
                    "calibration_status": {
                        "status": "ready_for_research",
                        "readiness_score": 76.0,
                        "sample_days": 260,
                        "required_sample_days": 120,
                    },
                    "strategy_readiness": {
                        "status": "ready_for_rule_signal",
                        "backtest_status": "ready_for_research",
                    },
                    "market_context": {
                        "status": "proxy_only",
                        "regime": "momentum_tailwind",
                        "available_proxies": ["fund_nav_momentum"],
                    },
                },
                "signal_context": {
                    "backtest_calibration": {
                        "applied_to_thresholds": False,
                    }
                },
            },
            "reasons": ["近 3 月收益领先", "风险分位可接受"],
            "data_quality": "ok",
            "limitations": [],
        }
    )
    service = FundPersonalActionService(repo=repo)

    result = service.build()
    action = result["actions"][0]

    assert result["status"] == "actionable"
    assert result["summary"]["actionable_count"] == 1
    assert result["summary"]["model_version"] == "fund_personal_action_model_v2"
    assert action["personal_action"] == "increase"
    assert action["action_label"] == "加仓"
    assert action["confidence"] == "high"
    assert action["profile"]["risk_target"] == "growth"
    assert action["evidence"]["analysis"]["signal_score"] == 82.0
    assert action["position_context"]["market_value"] == 12000.0
    assert action["position_context"]["ledger_weight_pct"] == 100.0
    assert action["position_context"]["weight_scope"] == "confirmed_fund_holdings_only"
    assert action["score_breakdown"]["total_score"] >= 70
    assert action["score_breakdown"]["status"] in {"usable", "strong"}
    assert action["calibration_context"]["readiness_score"] == 76.0
    assert action["market_context"]["status"] == "proxy_only"
    assert action["suggested_trade"]["status"] == "ready"
    assert action["suggested_trade"]["amount_max"] is not None
    assert action["suggested_trade"]["requires_cash_confirmation"] is True
    assert action["decision_trace"]


def test_personal_actions_size_reduce_from_confirmed_position() -> None:
    DatabaseManager.reset_instance()
    db = DatabaseManager(db_url="sqlite:///:memory:")
    repo = FundRepository(db_manager=db)
    importer = FundHoldingImportService(repo=repo)
    confirmed = importer.confirm_import(
        source_platform="jd_finance",
        holdings=[
            {
                "code": "501018",
                "name": "南方原油A",
                "market_value": 20000.0,
                "pnl_pct": 23.5,
            },
            {
                "code": "270042",
                "name": "广发纳指100ETF联接A",
                "market_value": 10000.0,
                "pnl_pct": 10.0,
            },
        ],
    )
    repo.update_ledger_profile(
        confirmed["ledger"]["id"],
        risk_target="balanced",
        investment_horizon="1y",
        rebalance_frequency="monthly",
    )
    repo.save_analysis_snapshot(
        {
            "code": "501018",
            "name": "南方原油A",
            "fund_type": "QDII",
            "analysis_date": date.today().isoformat(),
            "action": "reduce",
            "action_label": "减仓",
            "risk_level": "中高",
            "risk_score": 68.0,
            "signal_score": 58.0,
            "summary": "波动抬升，建议降低暴露。",
            "metrics": {"profile": {"market_context": {"status": "proxy_only", "regime": "risk_off"}}},
            "reasons": ["波动放大"],
            "data_quality": "ok",
            "limitations": [],
        }
    )
    service = FundPersonalActionService(repo=repo)

    result = service.build()
    action = next(item for item in result["actions"] if item["code"] == "501018")

    assert action["personal_action"] == "reduce"
    assert action["position_context"]["ledger_weight_pct"] == 66.67
    assert action["suggested_trade"]["status"] == "ready"
    assert action["suggested_trade"]["amount_min"] is not None
    assert action["suggested_trade"]["amount_max"] <= 10000.0
    assert action["suggested_trade"]["requires_cash_confirmation"] is False


if __name__ == "__main__":
    for name, func in sorted(globals().items()):
        if name.startswith("test_") and callable(func):
            func()
