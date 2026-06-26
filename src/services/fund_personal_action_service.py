# -*- coding: utf-8 -*-
"""个性化基金持仓动作建议底座。"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

from src.repositories.fund_repo import FundRepository


FUND_PERSONAL_ACTIONS_SCHEMA_VERSION = "fund_personal_actions_v2"
FUND_PERSONAL_ACTION_MODEL_VERSION = "fund_personal_action_model_v2"

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

TARGET_WEIGHT_BY_RISK = {
    "conservative": 8.0,
    "balanced": 12.0,
    "growth": 18.0,
    "aggressive": 24.0,
}

ACCOUNT_WEIGHT_ADJUSTMENT = {
    "cash_management": -5.0,
    "watchlist": -8.0,
    "long_term": 2.0,
    "sector_theme": 1.0,
    "education_pension": 0.0,
}

HORIZON_WEIGHT_ADJUSTMENT = {
    "3m": -5.0,
    "6m": -3.0,
    "1y": -1.0,
    "3y_plus": 2.0,
    "5y_plus": 4.0,
}

REBALANCE_DCA_MULTIPLIER = {
    "weekly": 0.55,
    "monthly": 1.0,
    "quarterly": 1.6,
    "ad_hoc": 1.2,
}


def _to_float(value: Any) -> Optional[float]:
    if value is None:
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed == parsed else None


def _round_money(value: Optional[float]) -> Optional[float]:
    if value is None:
        return None
    return round(float(value), 2)


def _round_pct(value: Optional[float]) -> Optional[float]:
    if value is None:
        return None
    return round(float(value), 2)


def _round_trade_amount(value: Optional[float]) -> Optional[float]:
    if value is None or value <= 0:
        return None
    step = 10.0 if value < 1000 else 100.0
    return round(round(float(value) / step) * step, 2)


def _read_dict(value: Any) -> Dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _clamp(value: float, low: float, high: float) -> float:
    return min(max(value, low), high)


class FundPersonalActionService:
    """Combine confirmed holdings, ledger profile and fund analysis into actions."""

    def __init__(self, repo: Optional[FundRepository] = None):
        self.repo = repo or FundRepository()

    def build(self) -> Dict[str, Any]:
        holdings = self.repo.list_holding_snapshots()
        holding_rows = [item.to_dict() for item in holdings]
        ledgers = {int(item.id): item.to_dict() for item in self.repo.list_ledgers(active_only=True)}
        portfolio_totals = self._portfolio_totals(holding_rows)
        actions: List[Dict[str, Any]] = []
        all_blockers: List[str] = []

        if not holding_rows:
            all_blockers.append("missing_holdings")

        for row in holding_rows:
            ledger = ledgers.get(int(row.get("ledger_id") or 0), {})
            latest = self.repo.get_latest_analysis_snapshot(str(row.get("code") or ""))
            blockers = self._blockers(row=row, ledger=ledger, latest=latest)
            all_blockers.extend(blockers)
            latest_payload = latest.to_dict() if latest is not None else None
            profile = self._profile_payload(ledger)
            position_context = self._position_context(row=row, totals=portfolio_totals)
            calibration_context = self._calibration_context(row=row, latest=latest_payload)
            market_context = self._market_context(latest=latest_payload)
            base_action = self._decide_action(latest=latest, blockers=blockers)
            score_breakdown = self._score_breakdown(
                row=row,
                profile=profile,
                latest=latest_payload,
                blockers=blockers,
                position_context=position_context,
                calibration_context=calibration_context,
                market_context=market_context,
            )
            action = self._adjust_action(
                base_action=base_action,
                row=row,
                profile=profile,
                position_context=position_context,
                score_breakdown=score_breakdown,
                blockers=blockers,
            )
            suggested_trade = self._suggested_trade(
                action=action,
                row=row,
                profile=profile,
                blockers=blockers,
                position_context=position_context,
                score_breakdown=score_breakdown,
            )
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
                    "confidence": self._confidence(blockers=blockers, latest=latest_payload, score_breakdown=score_breakdown),
                    "profile": profile,
                    "position_context": position_context,
                    "calibration_context": calibration_context,
                    "market_context": market_context,
                    "score_breakdown": score_breakdown,
                    "suggested_trade": suggested_trade,
                    "decision_trace": self._decision_trace(
                        base_action=base_action,
                        action=action,
                        blockers=blockers,
                        suggested_trade=suggested_trade,
                        score_breakdown=score_breakdown,
                    ),
                    "evidence": self._evidence(
                        row=row,
                        latest=latest_payload,
                        position_context=position_context,
                        calibration_context=calibration_context,
                        market_context=market_context,
                        score_breakdown=score_breakdown,
                        suggested_trade=suggested_trade,
                    ),
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
            if item.get("suggested_trade", {}).get("status") == "ready"
        )
        analyzed_count = sum(1 for item in actions if item.get("analysis_action"))
        sized_count = sum(1 for item in actions if item.get("suggested_trade", {}).get("amount_max") is not None)
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
                "model_version": FUND_PERSONAL_ACTION_MODEL_VERSION,
                "holding_count": len(holding_rows),
                "actionable_count": actionable_count,
                "analyzed_holding_count": analyzed_count,
                "profile_ready_ledger_count": profile_ready_ledgers,
                "sized_action_count": sized_count,
                "blocker_count": len(unique_blockers),
                "total_market_value": portfolio_totals["total_market_value"],
            },
            "prerequisites": {
                "holdings_used": bool(holding_rows),
                "ledger_profile_used": any(self._profile_payload(ledger) for ledger in ledgers.values()),
                "analysis_used": analyzed_count > 0,
                "position_sizing_used": sized_count > 0,
                "calibration_context_used": any(item.get("calibration_context", {}).get("status") not in {None, "missing"} for item in actions),
                "market_context_used": any(item.get("market_context", {}).get("status") not in {None, "missing"} for item in actions),
                "required_for_personal_actions": ["confirmed_holdings", "ledger_profile", "latest_fund_analysis", "market_value_for_sizing"],
            },
            "actions": actions,
            "blockers": unique_blockers,
            "blocker_labels": [BLOCKER_LABELS.get(item, item) for item in unique_blockers],
            "limitations": [
                "该接口只面向已确认持仓；没有持仓时不生成个人加减仓动作",
                "当前为个人动作 v2：金额区间基于已确认持仓市值、账本画像、单品分析和本地回测/市场上下文，不读取现金余额或完整交易流水",
                "买入/定投金额区间仍需用户确认可用现金；公开市场资金流只作为代理证据，不等同真实申购赎回",
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

    def _confidence(self, *, blockers: List[str], latest: Optional[Dict[str, Any]], score_breakdown: Dict[str, Any]) -> str:
        hard_blockers = [item for item in blockers if item != "missing_market_value"]
        if hard_blockers:
            return "low"
        score = _to_float(score_breakdown.get("total_score")) or 0.0
        if latest and latest.get("data_quality") == "ok" and score >= 75:
            return "high"
        return "medium"

    def _profile_payload(self, ledger: Dict[str, Any]) -> Dict[str, Any]:
        return {
            key: ledger.get(key)
            for key in ("account_type", "purpose", "risk_target", "investment_horizon", "rebalance_frequency")
            if ledger.get(key)
        }

    def _evidence(
        self,
        *,
        row: Dict[str, Any],
        latest: Optional[Dict[str, Any]],
        position_context: Dict[str, Any],
        calibration_context: Dict[str, Any],
        market_context: Dict[str, Any],
        score_breakdown: Dict[str, Any],
        suggested_trade: Dict[str, Any],
    ) -> Dict[str, Any]:
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
            "position_context": position_context,
            "calibration_context": calibration_context,
            "market_context": market_context,
            "score_breakdown": score_breakdown,
            "suggested_trade": suggested_trade,
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

    def _portfolio_totals(self, rows: List[Dict[str, Any]]) -> Dict[str, Any]:
        total = 0.0
        by_ledger: Dict[int, float] = {}
        counts_by_ledger: Dict[int, int] = {}
        for row in rows:
            market_value = _to_float(row.get("market_value"))
            if market_value is None:
                continue
            total += market_value
            ledger_id = int(row.get("ledger_id") or 0)
            by_ledger[ledger_id] = by_ledger.get(ledger_id, 0.0) + market_value
            counts_by_ledger[ledger_id] = counts_by_ledger.get(ledger_id, 0) + 1
        return {
            "total_market_value": _round_money(total),
            "ledger_market_values": {key: _round_money(value) for key, value in by_ledger.items()},
            "ledger_holding_counts": counts_by_ledger,
        }

    def _position_context(self, *, row: Dict[str, Any], totals: Dict[str, Any]) -> Dict[str, Any]:
        market_value = _to_float(row.get("market_value"))
        ledger_id = int(row.get("ledger_id") or 0)
        total_value = _to_float(totals.get("total_market_value"))
        ledger_values = totals.get("ledger_market_values") if isinstance(totals.get("ledger_market_values"), dict) else {}
        ledger_counts = totals.get("ledger_holding_counts") if isinstance(totals.get("ledger_holding_counts"), dict) else {}
        ledger_total = _to_float(ledger_values.get(ledger_id))
        ledger_holding_count = int(ledger_counts.get(ledger_id) or 0)
        portfolio_weight = (market_value / total_value * 100) if market_value is not None and total_value else None
        ledger_weight = (market_value / ledger_total * 100) if market_value is not None and ledger_total else None
        concentration = "unknown"
        weight_basis = ledger_weight if ledger_weight is not None else portfolio_weight
        if weight_basis is not None:
            if weight_basis >= 35:
                concentration = "heavy"
            elif weight_basis >= 15:
                concentration = "core"
            elif weight_basis >= 5:
                concentration = "satellite"
            else:
                concentration = "small"
        return {
            "market_value": _round_money(market_value),
            "cost_amount": _round_money(_to_float(row.get("cost_amount"))),
            "pnl_amount": _round_money(_to_float(row.get("pnl_amount"))),
            "pnl_pct": _round_pct(_to_float(row.get("pnl_pct"))),
            "portfolio_total_market_value": _round_money(total_value),
            "ledger_total_market_value": _round_money(ledger_total),
            "ledger_holding_count": ledger_holding_count,
            "portfolio_weight_pct": _round_pct(portfolio_weight),
            "ledger_weight_pct": _round_pct(ledger_weight),
            "concentration_level": concentration,
            "weight_scope": "confirmed_fund_holdings_only",
        }

    def _target_weight_pct(self, profile: Dict[str, Any]) -> float:
        risk_target = str(profile.get("risk_target") or "balanced")
        account_type = str(profile.get("account_type") or "")
        horizon = str(profile.get("investment_horizon") or "")
        target = TARGET_WEIGHT_BY_RISK.get(risk_target, TARGET_WEIGHT_BY_RISK["balanced"])
        target += ACCOUNT_WEIGHT_ADJUSTMENT.get(account_type, 0.0)
        target += HORIZON_WEIGHT_ADJUSTMENT.get(horizon, 0.0)
        return round(_clamp(target, 2.0, 30.0), 2)

    def _metrics_profile(self, latest: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        metrics = _read_dict(latest.get("metrics") if latest else {})
        return _read_dict(metrics.get("profile"))

    def _calibration_context(self, *, row: Dict[str, Any], latest: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        profile = self._metrics_profile(latest)
        calibration = _read_dict(profile.get("calibration_status"))
        readiness = _read_dict(profile.get("strategy_readiness"))
        metrics = _read_dict(latest.get("metrics") if latest else {})
        signal_context = _read_dict(metrics.get("signal_context"))
        backtest_calibration = _read_dict(signal_context.get("backtest_calibration"))
        nav_sample_count = len(self.repo.get_nav_history(str(row.get("code") or ""), limit=1500))
        status = str(calibration.get("status") or readiness.get("backtest_status") or ("ready_for_research" if nav_sample_count >= 120 else "missing"))
        return {
            "status": status,
            "readiness_score": _round_pct(_to_float(calibration.get("readiness_score"))),
            "sample_days": int(calibration.get("sample_days") or nav_sample_count or 0),
            "required_sample_days": int(calibration.get("required_sample_days") or 120),
            "backtest_status": readiness.get("backtest_status"),
            "strategy_readiness_status": readiness.get("status"),
            "applied_to_thresholds": bool(backtest_calibration.get("applied_to_thresholds")),
            "source": "latest_analysis_profile",
            "limitations": [
                "回测校准上下文来自最新单品分析或本地 NAV 样本数；当前不在个人动作接口同步运行完整回测",
            ],
        }

    def _market_context(self, *, latest: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        profile = self._metrics_profile(latest)
        market_context = _read_dict(profile.get("market_context"))
        metrics = _read_dict(latest.get("metrics") if latest else {})
        signal_context = _read_dict(metrics.get("signal_context"))
        signal_market_context = _read_dict(signal_context.get("market_context"))
        context = {**market_context, **{key: value for key, value in signal_market_context.items() if value not in (None, "", [])}}
        status = str(context.get("status") or "missing")
        regime = context.get("regime") or context.get("market_regime")
        return {
            "status": status,
            "regime": regime,
            "score": _round_pct(_to_float(context.get("score") or context.get("market_score"))),
            "source": context.get("source") or ("latest_analysis_profile" if context else None),
            "available_proxies": list(context.get("available_proxies") or []),
            "missing_inputs": list(context.get("missing_inputs") or []),
            "limitations": [
                "个人动作 v2 只消费已沉淀的市场上下文；公开榜单资金流接入后仍按 proxy 标记，不等同真实申购赎回"
            ] if status == "missing" else list(context.get("limitations") or []),
        }

    def _score_breakdown(
        self,
        *,
        row: Dict[str, Any],
        profile: Dict[str, Any],
        latest: Optional[Dict[str, Any]],
        blockers: List[str],
        position_context: Dict[str, Any],
        calibration_context: Dict[str, Any],
        market_context: Dict[str, Any],
    ) -> Dict[str, Any]:
        dimensions = [
            self._position_score(position_context),
            self._profile_score(profile),
            self._analysis_score(latest, blockers),
            self._market_score(market_context),
            self._calibration_score(calibration_context),
        ]
        weights = {"position": 0.25, "profile": 0.20, "analysis": 0.30, "market": 0.15, "calibration": 0.10}
        total = sum((item["score"] or 0.0) * weights.get(item["key"], 0.0) for item in dimensions)
        status = "strong" if total >= 78 else "usable" if total >= 62 else "weak" if total >= 40 else "blocked"
        return {
            "model_version": FUND_PERSONAL_ACTION_MODEL_VERSION,
            "total_score": round(total, 1),
            "status": status,
            "dimensions": dimensions,
            "weights": weights,
        }

    def _position_score(self, position_context: Dict[str, Any]) -> Dict[str, Any]:
        if position_context.get("market_value") is None:
            return {"key": "position", "label": "仓位约束", "score": 0.0, "status": "missing", "reason": "缺少持仓市值"}
        concentration = position_context.get("concentration_level")
        score = {"small": 78.0, "satellite": 82.0, "core": 76.0, "heavy": 58.0}.get(str(concentration), 55.0)
        return {"key": "position", "label": "仓位约束", "score": score, "status": "ok", "reason": f"当前仓位为 {concentration}"}

    def _profile_score(self, profile: Dict[str, Any]) -> Dict[str, Any]:
        required = ["risk_target", "investment_horizon", "rebalance_frequency"]
        present = [key for key in required if profile.get(key)]
        score = len(present) / len(required) * 100
        status = "ok" if len(present) == len(required) else "partial" if present else "missing"
        return {"key": "profile", "label": "用户画像", "score": round(score, 1), "status": status, "reason": f"已填写 {len(present)}/{len(required)} 项核心画像"}

    def _analysis_score(self, latest: Optional[Dict[str, Any]], blockers: List[str]) -> Dict[str, Any]:
        if latest is None:
            return {"key": "analysis", "label": "单品分析", "score": 0.0, "status": "missing", "reason": "缺少单品分析"}
        signal_score = _to_float(latest.get("signal_score"))
        score = signal_score if signal_score is not None else 65.0
        if latest.get("data_quality") != "ok":
            score = min(score, 45.0)
        status = "ok" if latest.get("data_quality") == "ok" else "partial"
        if "analysis_data_quality_not_ok" in blockers:
            status = "partial"
        return {"key": "analysis", "label": "单品分析", "score": round(score, 1), "status": status, "reason": f"数据质量 {latest.get('data_quality') or 'unknown'}"}

    def _market_score(self, market_context: Dict[str, Any]) -> Dict[str, Any]:
        status = str(market_context.get("status") or "missing")
        score = 35.0
        if status == "ok":
            score = 78.0
        elif status == "proxy_only":
            score = 62.0
        elif status == "partial":
            score = 52.0
        regime = str(market_context.get("regime") or "")
        if regime in {"momentum_tailwind", "risk_on"}:
            score += 8
        elif regime in {"risk_off", "drawdown_pressure", "high_volatility"}:
            score -= 10
        return {"key": "market", "label": "市场上下文", "score": round(_clamp(score, 0, 100), 1), "status": status, "reason": regime or "暂无市场代理上下文"}

    def _calibration_score(self, calibration_context: Dict[str, Any]) -> Dict[str, Any]:
        readiness_score = _to_float(calibration_context.get("readiness_score"))
        if readiness_score is not None:
            score = readiness_score
        else:
            sample_days = _to_float(calibration_context.get("sample_days")) or 0.0
            required = _to_float(calibration_context.get("required_sample_days")) or 120.0
            score = min(sample_days / required * 70.0, 70.0)
        status = str(calibration_context.get("status") or "missing")
        return {"key": "calibration", "label": "回测校准", "score": round(_clamp(score, 0, 100), 1), "status": status, "reason": f"NAV 样本 {calibration_context.get('sample_days') or 0}"}

    def _adjust_action(
        self,
        *,
        base_action: str,
        row: Dict[str, Any],
        profile: Dict[str, Any],
        position_context: Dict[str, Any],
        score_breakdown: Dict[str, Any],
        blockers: List[str],
    ) -> str:
        if base_action in {"refresh_analysis", "complete_profile"}:
            return base_action
        if "analysis_data_quality_not_ok" in blockers:
            return "hold"
        target_weight = self._target_weight_pct(profile)
        ledger_weight = _to_float(position_context.get("ledger_weight_pct"))
        ledger_holding_count = int(position_context.get("ledger_holding_count") or 0)
        total_score = _to_float(score_breakdown.get("total_score")) or 0.0
        if ledger_holding_count > 1 and ledger_weight is not None and base_action in {"increase", "dca"} and ledger_weight > target_weight + 2:
            return "hold"
        if ledger_holding_count > 1 and ledger_weight is not None and base_action == "hold" and ledger_weight > target_weight + 8 and total_score < 68:
            return "reduce"
        return base_action

    def _suggested_trade(
        self,
        *,
        action: str,
        row: Dict[str, Any],
        profile: Dict[str, Any],
        blockers: List[str],
        position_context: Dict[str, Any],
        score_breakdown: Dict[str, Any],
    ) -> Dict[str, Any]:
        current_value = _to_float(row.get("market_value"))
        ledger_total = _to_float(position_context.get("ledger_total_market_value"))
        current_weight = _to_float(position_context.get("ledger_weight_pct"))
        ledger_holding_count = int(position_context.get("ledger_holding_count") or 0)
        target_weight = self._target_weight_pct(profile)
        total_score = _to_float(score_breakdown.get("total_score")) or 0.0
        base = {
            "status": "blocked",
            "action": action,
            "amount_min": None,
            "amount_max": None,
            "target_weight_pct": target_weight,
            "current_weight_pct": _round_pct(current_weight),
            "target_market_value": None,
            "percent_of_holding_min": None,
            "percent_of_holding_max": None,
            "requires_cash_confirmation": action in {"increase", "dca"},
            "privacy_sensitive": True,
            "sizing_basis": "confirmed_holding_snapshot",
            "reason": None,
        }
        if action in {"refresh_analysis", "complete_profile"}:
            base["reason"] = "缺少生成个人动作所需的分析或画像"
            return base
        if "missing_market_value" in blockers or current_value is None or current_value <= 0:
            base["reason"] = "缺少持仓市值，不能给出金额区间"
            return base
        if "analysis_data_quality_not_ok" in blockers:
            base["status"] = "watch_only"
            base["reason"] = "单品分析数据质量未达 ok，暂不输出金额区间"
            return base

        target_value = ledger_total * target_weight / 100 if ledger_total and ledger_holding_count > 1 else None
        base["target_market_value"] = _round_money(target_value)
        score_multiplier = _clamp(0.65 + (total_score - 55.0) / 100.0, 0.45, 1.25)
        risk_multiplier = {
            "conservative": 0.65,
            "balanced": 0.9,
            "growth": 1.1,
            "aggressive": 1.25,
        }.get(str(profile.get("risk_target") or "balanced"), 0.9)

        if action in {"increase", "dca"}:
            if target_value is not None and current_value >= target_value:
                base["status"] = "watch_only"
                base["reason"] = "当前仓位已达到或超过画像目标仓位，暂不建议继续加仓"
                return base
            gap = max((target_value or current_value * 0.35) - current_value, 0.0) if target_value is not None else current_value * 0.35
            if gap <= 0:
                base["status"] = "watch_only"
                base["reason"] = "目标仓位空间不足"
                return base
            dca_multiplier = REBALANCE_DCA_MULTIPLIER.get(str(profile.get("rebalance_frequency") or "monthly"), 1.0)
            if action == "dca":
                amount_min = gap * 0.06 * dca_multiplier * risk_multiplier * score_multiplier
                amount_max = gap * 0.18 * dca_multiplier * risk_multiplier * score_multiplier
            else:
                amount_min = gap * 0.20 * risk_multiplier * score_multiplier
                amount_max = gap * 0.45 * risk_multiplier * score_multiplier
            base.update(self._amount_payload(amount_min, amount_max, current_value))
            base["status"] = "ready"
            base["reason"] = "根据目标仓位缺口给出分批买入区间，仍需确认可用现金"
            return base

        if action == "reduce":
            target_gap = max(current_value - (target_value or current_value * 0.75), 0.0)
            amount_min = max(current_value * 0.10, target_gap * 0.45)
            amount_max = max(current_value * 0.22, target_gap)
            base.update(self._amount_payload(amount_min, min(amount_max, current_value * 0.5), current_value))
            base["status"] = "ready"
            base["requires_cash_confirmation"] = False
            base["reason"] = "按当前持仓市值和目标仓位给出减仓区间"
            return base

        if action == "sell_watch":
            base.update(self._amount_payload(current_value * 0.50, current_value, current_value))
            base["status"] = "ready"
            base["requires_cash_confirmation"] = False
            base["reason"] = "卖出观察动作对应 50%-100% 持仓处理区间，执行前需复核赎回状态和费用"
            return base

        base["status"] = "watch_only"
        base["reason"] = "当前动作为持有观察，不给出买卖金额"
        return base

    def _amount_payload(self, amount_min: float, amount_max: float, current_value: float) -> Dict[str, Any]:
        rounded_min = _round_trade_amount(amount_min)
        rounded_max = _round_trade_amount(max(amount_max, amount_min))
        if rounded_min is not None and rounded_max is not None and rounded_max < rounded_min:
            rounded_max = rounded_min
        return {
            "amount_min": rounded_min,
            "amount_max": rounded_max,
            "percent_of_holding_min": _round_pct(rounded_min / current_value * 100) if rounded_min is not None and current_value else None,
            "percent_of_holding_max": _round_pct(rounded_max / current_value * 100) if rounded_max is not None and current_value else None,
        }

    def _decision_trace(
        self,
        *,
        base_action: str,
        action: str,
        blockers: List[str],
        suggested_trade: Dict[str, Any],
        score_breakdown: Dict[str, Any],
    ) -> List[str]:
        trace = [
            f"单品分析动作映射为 {ACTION_LABELS.get(base_action, base_action)}",
            f"综合评分 {score_breakdown.get('total_score')}，状态 {score_breakdown.get('status')}",
        ]
        if action != base_action:
            trace.append(f"根据仓位/质量约束将动作调整为 {ACTION_LABELS.get(action, action)}")
        if blockers:
            trace.append("阻塞项：" + "、".join(BLOCKER_LABELS.get(item, item) for item in blockers[:3]))
        if suggested_trade.get("status") == "ready":
            trace.append("已生成金额区间，执行前仍需确认现金余额、申赎状态和费用")
        elif suggested_trade.get("reason"):
            trace.append(str(suggested_trade["reason"]))
        return trace
