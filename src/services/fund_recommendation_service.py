# -*- coding: utf-8 -*-
"""市场级基金荐基证据卡。"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

from src.repositories.fund_repo import FundRepository
from src.services.fund_market_ranking_service import FundMarketRankingService


FUND_RECOMMENDATION_TODAY_SCHEMA_VERSION = "fund_recommendation_today_v1"


class FundRecommendationService:
    """Build market-only fund recommendation evidence from public data."""

    def __init__(
        self,
        provider: Any,
        repo: Optional[FundRepository] = None,
        market_service: Optional[FundMarketRankingService] = None,
    ):
        self.provider = provider
        self.repo = repo or FundRepository()
        self.market_service = market_service or FundMarketRankingService(provider)

    def today(self, *, limit: int = 10, fund_type: str = "全部") -> Dict[str, Any]:
        rankings = self.market_service.build_market_rankings(limit=limit, fund_type=fund_type)
        pool_codes = {item.code for item in self.repo.list_pool(active_only=True)}
        candidates = []
        for candidate in rankings.get("recommendation_candidates", [])[:limit]:
            code = str(candidate.get("code") or "")
            if not code:
                continue
            evidence = self._collect_market_evidence(rankings, code)
            latest = self.repo.get_latest_analysis_snapshot(code)
            nav_count = len(self.repo.get_nav_history(code, limit=1500))
            action = "market_watchlist" if code in pool_codes else "add_to_pool"
            data_quality_summary = latest.data_quality if latest is not None else (
                "not_analyzed" if code in pool_codes else "not_in_pool"
            )
            risk_flags = self._risk_flags(evidence=evidence, latest=latest, nav_count=nav_count)
            candidates.append(
                {
                    "code": code,
                    "name": candidate.get("name"),
                    "fund_type": candidate.get("fund_type"),
                    "score": candidate.get("score"),
                    "market_action": action,
                    "personal_action": None,
                    "personalized": False,
                    "source_rank_types": list(candidate.get("evidence_rank_types") or []),
                    "market_evidence": evidence,
                    "data_quality_summary": data_quality_summary,
                    "latest_analysis": latest.to_dict() if latest is not None else None,
                    "backtest_readiness": {
                        "status": "ready_for_research" if nav_count >= 120 else "insufficient_nav_history",
                        "nav_sample_count": nav_count,
                        "minimum_recommended_sample": 120,
                    },
                    "risk_flags": risk_flags,
                    "invalid_if": self._invalid_if(risk_flags),
                    "limitations": list(candidate.get("limitations") or []),
                }
            )
        return {
            "schema_version": FUND_RECOMMENDATION_TODAY_SCHEMA_VERSION,
            "status": rankings.get("status") or "partial",
            "fetched_at": datetime.now().isoformat(),
            "scope": {
                "fund_type": fund_type,
                "limit": limit,
                "source": "market_rankings",
            },
            "personalization": {
                "status": "market_only",
                "user_profile_used": False,
                "holdings_used": False,
                "personal_actions_supported": False,
                "allowed_actions": ["research_only", "market_watchlist", "add_to_pool"],
            },
            "candidates": candidates,
            "market_rankings": {
                "schema_version": rankings.get("schema_version"),
                "status": rankings.get("status"),
                "as_of_date": rankings.get("as_of_date"),
            },
            "limitations": [
                "该接口只生成公开市场级荐基证据，不读取用户画像或个人持仓",
                "候选动作不是个人买入/卖出建议；个人动作需叠加用户画像、持仓和仓位约束",
                *list(rankings.get("limitations") or []),
            ],
        }

    def _collect_market_evidence(self, rankings: Dict[str, Any], code: str) -> List[Dict[str, Any]]:
        evidence: List[Dict[str, Any]] = []
        for group in rankings.get("groups") or []:
            for item in group.get("items") or []:
                if str(item.get("code")) != code:
                    continue
                evidence.append(
                    {
                        "rank_type": group.get("rank_type"),
                        "rank_title": group.get("title"),
                        "rank": item.get("rank"),
                        "status": item.get("status"),
                        "recommendation_role": item.get("recommendation_role"),
                        "proxy_type": item.get("proxy_type"),
                        "metrics": item.get("metrics") or {},
                        "evidence_metrics": item.get("evidence_metrics") or {},
                        "freshness": item.get("freshness") or {},
                    }
                )
        return evidence

    def _risk_flags(self, *, evidence: List[Dict[str, Any]], latest: Any, nav_count: int) -> List[str]:
        flags: List[str] = []
        if not evidence:
            flags.append("market_evidence_missing")
        if any(item.get("status") == "proxy_only" for item in evidence):
            flags.append("uses_proxy_market_flow")
        if latest is None:
            flags.append("not_analyzed_in_pool")
        elif getattr(latest, "data_quality", None) != "ok":
            flags.append("analysis_data_quality_not_ok")
        if nav_count < 120:
            flags.append("backtest_sample_insufficient")
        return flags

    def _invalid_if(self, risk_flags: List[str]) -> List[str]:
        invalid = [
            "公开榜单数据日期明显滞后或源站返回异常",
            "基金暂停申购/赎回或交易费率约束显著抬高",
        ]
        if "backtest_sample_insufficient" in risk_flags:
            invalid.append("本地 NAV 样本不足，无法形成可靠回测校准")
        if "not_analyzed_in_pool" in risk_flags:
            invalid.append("尚未加入基金池并生成单品画像")
        return invalid
