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
            "metrics": {"profile": {"strategy_family": "active_equity"}},
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
    assert action["personal_action"] == "increase"
    assert action["action_label"] == "加仓"
    assert action["confidence"] == "high"
    assert action["profile"]["risk_target"] == "growth"
    assert action["evidence"]["analysis"]["signal_score"] == 82.0


if __name__ == "__main__":
    for name, func in sorted(globals().items()):
        if name.startswith("test_") and callable(func):
            func()
