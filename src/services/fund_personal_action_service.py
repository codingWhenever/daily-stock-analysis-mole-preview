# -*- coding: utf-8 -*-
"""个性化基金持仓动作建议底座。"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

from src.repositories.fund_repo import FundRepository


FUND_PERSONAL_ACTIONS_SCHEMA_VERSION = "fund_personal_actions_v1"

ACTION_LABELS = {
    "increase": "加仓",
    "dca": "定投",
    "hold": "持有观察",
    "reduce": "减仓",
    "sell_watch": "卖出观察",
    "refresh_analysis": "先刷新分析",
    "complete_profile": "先补画像",
}

ACTION_FROM_ANALYSIS = {
    "buy": "increase",
    "dca": "dca",
    "watch": "hold",
    "pause_buy": "hold",
    "reduce": "reduce",
    "sell_watch": "sell_watch",
}

BLOCKER_LABELS = {
    "missing_holdings": "尚未确认持仓快照",
    "missing_ledger_profile": "账本画像缺少风险目标或投资期限",
    "missing_analysis": "该基金尚未生成单品分析",
    "analysis_data_quality_not_ok": "单品分析数据质量未达 ok",
    "missing_market_value": "持仓市值缺失，无法做仓位约束",
}


class FundPersonalActionService:
    """Combine confirmed holdings, ledger profile and fund analysis into actions."""

    def __init__(self, repo: Optional[FundRepository] = None):
        self.repo = repo or FundRepository()

    def build(self) -> Dict[str, Any]:
        holdings = self.repo.list_holding_snapshots()
        ledgers = {int(item.id): item.to_dict() for item in self.repo.list_ledgers(active_only=True)}
        actions: List[Dict[str, Any]] = []
        all_blockers: List[str] = []

        if not holdings:
            all_blockers.append("missing_holdings")

        for holding in holdings:
            row = holding.to_dict()
            ledger = ledgers.get(int(row.get("ledger_id") or 0), {})
            latest = self.repo.get_latest_analysis_snapshot(str(row.get("code") or ""))
            blockers = self._blockers(row=row, ledger=ledger, latest=latest)
            all_blockers.extend(blockers)
            action = self._decide_action(latest=latest, blockers=blockers)
            latest_payload = latest.to_dict() if latest is not None else None
            actions.append(
                {
                    "code": row.get("code"),
                    "name": row.get("name"),
                    "ledger_id": row.get("ledger_id"),
                    "ledger_name": ledger.get("name"),
                    "source_platform": row.get("source_platform"),
                    "market_value": row.get("market_value"),
                    "pnl_amount": row.get("pnl_amount"),
                    "pnl_pct": row.get("pnl_pct"),
                    "analysis_action": latest_payload.get("action") if latest_payload else None,
                    "personal_action": action,
                    "action_label": ACTION_LABELS.get(action, action),
                    "confidence": self._confidence(blockers=blockers, latest=latest_payload),
                    "profile": self._profile_payload(ledger),
                    "evidence": self._evidence(row=row, latest=latest_payload),
                    "blockers": blockers,
                    "blocker_labels": [BLOCKER_LABELS.get(item, item) for item in blockers],
                    "invalid_if": self._invalid_if(blockers),
                    "limitations": [
                        "动作由确认持仓、账本画像和本地单品分析规则合成，不读取未确认交易流水",
                    ],
                }
            )

        unique_blockers = sorted(set(all_blockers))
        actionable_count = sum(
            1
            for item in actions
            if item["personal_action"] not in {"refresh_analysis", "complete_profile"}
        )
        analyzed_count = sum(1 for item in actions if item.get("analysis_action"))
        profile_ready_ledgers = sum(
            1
            for ledger in ledgers.values()
            if ledger.get("risk_target") and ledger.get("investment_horizon")
        )
        status = "blocked" if not holdings else ("partial" if unique_blockers else "actionable")
        return {
            "schema_version": FUND_PERSONAL_ACTIONS_SCHEMA_VERSION,
            "status": status,
            "fetched_at": datetime.now().isoformat(),
            "summary": {
                "holding_count": len(holdings),
                "actionable_count": actionable_count,
                "analyzed_holding_count": analyzed_count,
                "profile_ready_ledger_count": profile_ready_ledgers,
                "blocker_count": len(unique_blockers),
            },
            "prerequisites": {
                "holdings_used": bool(holdings),
                "ledger_profile_used": any(self._profile_payload(ledger) for ledger in ledgers.values()),
                "analysis_used": analyzed_count > 0,
                "required_for_personal_actions": ["confirmed_holdings", "ledger_profile", "latest_fund_analysis"],
            },
            "actions": actions,
            "blockers": unique_blockers,
            "blocker_labels": [BLOCKER_LABELS.get(item, item) for item in unique_blockers],
            "limitations": [
                "该接口只面向已确认持仓；没有持仓时不生成个人加减仓动作",
                "当前为规则化动作 v1，尚未叠加用户全局问卷、现金流、税费和完整交易流水",
            ],
        }

    def _blockers(self, *, row: Dict[str, Any], ledger: Dict[str, Any], latest: Any) -> List[str]:
        blockers: List[str] = []
        if not (ledger.get("risk_target") and ledger.get("investment_horizon")):
            blockers.append("missing_ledger_profile")
        if latest is None:
            blockers.append("missing_analysis")
        elif getattr(latest, "data_quality", None) != "ok":
            blockers.append("analysis_data_quality_not_ok")
        if row.get("market_value") is None:
            blockers.append("missing_market_value")
        return blockers

    def _decide_action(self, *, latest: Any, blockers: List[str]) -> str:
        if "missing_analysis" in blockers:
            return "refresh_analysis"
        if "missing_ledger_profile" in blockers:
            return "complete_profile"
        if latest is None:
            return "refresh_analysis"
        return ACTION_FROM_ANALYSIS.get(getattr(latest, "action", None), "hold")

    def _confidence(self, *, blockers: List[str], latest: Optional[Dict[str, Any]]) -> str:
        hard_blockers = [item for item in blockers if item != "missing_market_value"]
        if hard_blockers:
            return "low"
        if latest and latest.get("data_quality") == "ok":
            return "high"
        return "medium"

    def _profile_payload(self, ledger: Dict[str, Any]) -> Dict[str, Any]:
        return {
            key: ledger.get(key)
            for key in ("account_type", "purpose", "risk_target", "investment_horizon", "rebalance_frequency")
            if ledger.get(key)
        }

    def _evidence(self, *, row: Dict[str, Any], latest: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        return {
            "holding": {
                "market_value": row.get("market_value"),
                "pnl_amount": row.get("pnl_amount"),
                "pnl_pct": row.get("pnl_pct"),
                "as_of_date": row.get("as_of_date"),
                "source_platform": row.get("source_platform"),
            },
            "analysis": {
                "action": latest.get("action") if latest else None,
                "action_label": latest.get("action_label") if latest else None,
                "risk_level": latest.get("risk_level") if latest else None,
                "risk_score": latest.get("risk_score") if latest else None,
                "signal_score": latest.get("signal_score") if latest else None,
                "summary": latest.get("summary") if latest else None,
                "reasons": list(latest.get("reasons") or [])[:3] if latest else [],
                "data_quality": latest.get("data_quality") if latest else None,
            },
        }

    def _invalid_if(self, blockers: List[str]) -> List[str]:
        invalid = [
            "持仓截图日期明显滞后或用户未确认最新持仓",
            "基金暂停申购/赎回、费率或限购规则发生变化",
        ]
        if "analysis_data_quality_not_ok" in blockers:
            invalid.append("单品分析的数据质量仍非 ok")
        if "missing_market_value" in blockers:
            invalid.append("无法判断当前仓位大小")
        return invalid
