# -*- coding: utf-8 -*-
"""公募基金池 API 模型。"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field


class FundPoolAddRequest(BaseModel):
    code: str = Field(..., description="6 位公募基金代码")
    name: Optional[str] = Field(None, description="可选基金名称，未提供时尝试从公开数据源获取")
    notes: Optional[str] = Field(None, description="跟踪备注")
    ledger_id: Optional[int] = Field(None, description="可选账本/分类 ID")


class FundLedgerCreateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=20, description="账本/分类名称")
    color: str = Field("#06B6D4", description="主题色，十六进制色值")
    account_type: Optional[str] = Field(None, max_length=40, description="本地账户类型，如 long_term/cash_management")
    purpose: Optional[str] = Field(None, max_length=80, description="资金用途或账户目标")
    risk_target: Optional[str] = Field(None, max_length=40, description="风险目标，如 conservative/balanced/aggressive")
    investment_horizon: Optional[str] = Field(None, max_length=40, description="投资期限，如 6m/1y/3y+")
    rebalance_frequency: Optional[str] = Field(None, max_length=40, description="调仓频率，如 monthly/quarterly/ad_hoc")
    drawdown_tolerance: Optional[str] = Field(None, max_length=40, description="最大回撤承受，如 lt_5/5_10/10_20/20_30/30_plus")
    liquidity_need: Optional[str] = Field(None, max_length=40, description="资金流动性需求，如 anytime/within_3m/within_1y/long_term")
    investment_experience: Optional[str] = Field(None, max_length=40, description="投资经验，如 beginner/familiar/experienced/professional")
    monthly_budget: Optional[float] = Field(None, ge=0, le=10000000, description="可用于基金加仓/定投的月度预算")
    cash_reserve_months: Optional[float] = Field(None, ge=0, le=120, description="现金安全垫月数")
    preferred_fund_types: Optional[str] = Field(None, max_length=160, description="偏好基金类型，逗号分隔")
    notes: Optional[str] = Field(None, max_length=500, description="账户备注")


class FundLedgerUpdateRequest(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=20, description="账本/分类名称")
    color: Optional[str] = Field(None, description="主题色，十六进制色值")
    account_type: Optional[str] = Field(None, max_length=40, description="本地账户类型，如 long_term/cash_management")
    purpose: Optional[str] = Field(None, max_length=80, description="资金用途或账户目标")
    risk_target: Optional[str] = Field(None, max_length=40, description="风险目标，如 conservative/balanced/aggressive")
    investment_horizon: Optional[str] = Field(None, max_length=40, description="投资期限，如 6m/1y/3y+")
    rebalance_frequency: Optional[str] = Field(None, max_length=40, description="调仓频率，如 monthly/quarterly/ad_hoc")
    drawdown_tolerance: Optional[str] = Field(None, max_length=40, description="最大回撤承受，如 lt_5/5_10/10_20/20_30/30_plus")
    liquidity_need: Optional[str] = Field(None, max_length=40, description="资金流动性需求，如 anytime/within_3m/within_1y/long_term")
    investment_experience: Optional[str] = Field(None, max_length=40, description="投资经验，如 beginner/familiar/experienced/professional")
    monthly_budget: Optional[float] = Field(None, ge=0, le=10000000, description="可用于基金加仓/定投的月度预算")
    cash_reserve_months: Optional[float] = Field(None, ge=0, le=120, description="现金安全垫月数")
    preferred_fund_types: Optional[str] = Field(None, max_length=160, description="偏好基金类型，逗号分隔")
    notes: Optional[str] = Field(None, max_length=500, description="账户备注")


class FundLedgerAssignRequest(BaseModel):
    ledger_id: int = Field(..., description="目标账本/分类 ID")


class FundLedgerResponse(BaseModel):
    id: int
    name: str
    color: str
    sort_order: int = 0
    is_default: bool = False
    account_type: Optional[str] = None
    purpose: Optional[str] = None
    risk_target: Optional[str] = None
    investment_horizon: Optional[str] = None
    rebalance_frequency: Optional[str] = None
    drawdown_tolerance: Optional[str] = None
    liquidity_need: Optional[str] = None
    investment_experience: Optional[str] = None
    monthly_budget: Optional[float] = None
    cash_reserve_months: Optional[float] = None
    preferred_fund_types: Optional[str] = None
    notes: Optional[str] = None
    active: bool = True
    fund_count: int = 0
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


class FundAnalysisSnapshotResponse(BaseModel):
    id: Optional[int] = Field(None, description="快照 ID")
    code: str = Field(..., description="基金代码")
    name: Optional[str] = Field(None, description="基金名称")
    fund_type: Optional[str] = Field(None, description="基金类型")
    analysis_date: str = Field(..., description="分析基准日期")
    action: str = Field(..., description="规则化动作")
    action_label: str = Field(..., description="动作中文标签")
    risk_level: str = Field(..., description="风险等级")
    risk_score: Optional[float] = Field(None, description="风险分，0-100")
    signal_score: Optional[float] = Field(None, description="信号分，0-100")
    summary: Optional[str] = Field(None, description="摘要")
    metrics: Dict[str, Any] = Field(
        default_factory=dict,
        description="收益、回撤、波动等指标；基金数据质量明细见 metrics.profile.data_quality_detail / metrics.data_quality_detail",
    )
    peer: Optional[Dict[str, Any]] = Field(None, description="同类比较")
    reasons: List[str] = Field(default_factory=list, description="信号触发原因")
    data_quality: str = Field(
        "partial",
        description="兼容数据质量摘要 ok/partial/limited；新版维度状态见 metrics.profile.data_quality_detail，支持 ok/partial/stale/missing/estimated",
    )
    limitations: List[str] = Field(default_factory=list, description="数据边界")
    created_at: Optional[str] = Field(None, description="生成时间")


class FundSearchLatest(BaseModel):
    unit_nav: Optional[float] = None
    accumulated_nav: Optional[float] = None
    daily_growth_pct: Optional[float] = None
    nav_date: Optional[str] = None
    purchase_status: Optional[str] = None
    redemption_status: Optional[str] = None
    fee: Optional[str] = None


class FundSearchItem(BaseModel):
    code: str
    name: Optional[str] = None
    fund_type: Optional[str] = None
    latest: FundSearchLatest = Field(default_factory=FundSearchLatest)
    returns: Dict[str, Any] = Field(default_factory=dict)
    peer: Optional[Dict[str, Any]] = None
    rank: Optional[int] = None
    sample_size: Optional[int] = None
    category: Optional[str] = None
    profile: Dict[str, Any] = Field(
        default_factory=dict,
        description="基金画像；包含 data_coverage 兼容摘要和 versioned data_quality/data_quality_detail",
    )
    limitations: List[str] = Field(default_factory=list)
    data_sources: Dict[str, Any] = Field(default_factory=dict)


class FundSearchResponse(BaseModel):
    items: List[FundSearchItem] = Field(default_factory=list)
    total: int = 0
    query: str = ""


class FundMarketRankingItem(BaseModel):
    rank: int
    code: str
    name: Optional[str] = None
    fund_type: Optional[str] = None
    industry: Optional[str] = None
    market: Optional[str] = None
    score: Optional[float] = None
    status: str = Field(..., description="ok/proxy_only/partial/stale/missing/not_supported/failed")
    proxy_type: Optional[str] = Field(None, description="公开代理指标类型，不等同真实买卖流水")
    recommendation_role: Optional[str] = None
    metrics: Dict[str, Any] = Field(default_factory=dict)
    evidence_metrics: Dict[str, Any] = Field(
        default_factory=dict,
        description="公开证据指标；真实买卖金额/笔数字段不可得时必须为 null 并标 not_supported",
    )
    source: str
    source_url: Optional[str] = None
    freshness: Dict[str, Any] = Field(default_factory=dict)
    limitations: List[str] = Field(default_factory=list)


class FundMarketRankingGroup(BaseModel):
    rank_type: str = Field(
        ...,
        description="etf_net_inflow/etf_net_outflow/etf_turnover_heat/open_fund_return_rank/platform_public_buy_rank 等市场级榜单类型",
    )
    title: str
    description: Optional[str] = None
    status: str = Field(..., description="ok/proxy_only/partial/stale/missing/not_supported/failed")
    source: str
    source_url: Optional[str] = None
    freshness: Dict[str, Any] = Field(default_factory=dict)
    items: List[FundMarketRankingItem] = Field(default_factory=list)
    limitations: List[str] = Field(default_factory=list)


class FundMarketRankingsResponse(BaseModel):
    schema_version: str = Field("market_fund_ranking_v1", description="市场级基金榜单响应版本")
    status: str = Field(..., description="completed/partial/failed")
    as_of_date: Optional[str] = None
    fetched_at: str
    scope: Dict[str, Any] = Field(default_factory=dict)
    personalization: Dict[str, Any] = Field(
        default_factory=dict,
        description="市场榜单是否使用用户画像/持仓；P0 必须是 market_only 且不生成个人动作",
    )
    groups: List[FundMarketRankingGroup] = Field(default_factory=list)
    recommendation_candidates: List[Dict[str, Any]] = Field(
        default_factory=list,
        description="仅基于公开市场榜单的候选池，不是个性化买入建议",
    )
    limitations: List[str] = Field(default_factory=list)


class FundPoolItemResponse(BaseModel):
    id: Optional[int] = None
    code: str
    name: Optional[str] = None
    fund_type: Optional[str] = None
    ledger_id: Optional[int] = None
    source: Optional[str] = None
    active: bool = True
    notes: Optional[str] = None
    last_refreshed_at: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    latest_analysis: Optional[FundAnalysisSnapshotResponse] = None


class FundPoolResponse(BaseModel):
    items: List[FundPoolItemResponse] = Field(default_factory=list)
    ledgers: List[FundLedgerResponse] = Field(default_factory=list)
    total: int = 0


class FundRemoveResponse(BaseModel):
    code: str
    removed: bool


class FundPoolRefreshItem(BaseModel):
    code: str
    success: bool
    analysis: Optional[FundAnalysisSnapshotResponse] = None
    error: Optional[str] = None


class FundPoolRefreshResponse(BaseModel):
    items: List[FundPoolRefreshItem]
    success_count: int
    failure_count: int


class FundNavPoint(BaseModel):
    code: str
    date: str
    unit_nav: Optional[float] = None
    accumulated_nav: Optional[float] = None
    daily_growth_pct: Optional[float] = None
    source: Optional[str] = None


class FundNavHistoryResponse(BaseModel):
    code: str
    items: List[FundNavPoint] = Field(default_factory=list)
    total: int = 0

    model_config = ConfigDict(json_schema_extra={
        "example": {
            "code": "110022",
            "items": [
                {"code": "110022", "date": "2026-06-24", "unit_nav": 4.2, "daily_growth_pct": 0.3}
            ],
            "total": 1,
        }
    })


class FundBacktestResponse(BaseModel):
    code: str
    name: Optional[str] = None
    fund_type: Optional[str] = None
    status: str = Field(..., description="completed/insufficient_data")
    engine_version: str
    parameters: Dict[str, Any] = Field(default_factory=dict)
    summary: Dict[str, Any] = Field(default_factory=dict)
    signals: List[Dict[str, Any]] = Field(default_factory=list)
    portfolio_curve: List[Dict[str, Any]] = Field(default_factory=list)
    fee_assumptions: Dict[str, Any] = Field(default_factory=dict)
    methodology: Dict[str, Any] = Field(default_factory=dict)
    limitations: List[str] = Field(default_factory=list)


class FundBacktestCalibrationResponse(BaseModel):
    schema_version: str = Field("fund_backtest_calibration_v1", description="校准中心响应版本")
    status: str = Field(..., description="completed/partial/insufficient")
    scope: Dict[str, Any] = Field(default_factory=dict, description="筛选范围与回测参数")
    calibration_status: Dict[str, Any] = Field(default_factory=dict, description="全局校准样本强度")
    by_fund: List[Dict[str, Any]] = Field(default_factory=list, description="逐基金校准结果")
    by_ledger: List[Dict[str, Any]] = Field(default_factory=list, description="按账本聚合结果")
    by_fund_type: List[Dict[str, Any]] = Field(default_factory=list, description="按基金类型聚合结果")
    limitations: List[str] = Field(default_factory=list, description="校准边界与暂未覆盖项")


class FundHoldingCandidate(BaseModel):
    code: str = Field(..., description="6 位基金代码")
    name: Optional[str] = Field(None, description="基金名称，可能需要用户确认")
    units: Optional[float] = Field(None, description="持有份额")
    available_units: Optional[float] = Field(None, description="可用/可赎回份额")
    market_value: Optional[float] = Field(None, description="当前持仓市值/持有金额")
    cost_amount: Optional[float] = Field(None, description="截图展示的成本金额；缺失不估算")
    pnl_amount: Optional[float] = Field(None, description="截图展示的持有收益/盈亏金额；缺失不估算")
    pnl_pct: Optional[float] = Field(None, description="截图展示的收益率百分比；缺失不估算")
    latest_nav: Optional[float] = Field(None, description="截图展示的最新/单位净值；缺失不估算")
    as_of_date: Optional[str] = Field(None, description="截图展示的数据日期，YYYY-MM-DD")
    confidence: str = Field("medium", description="OCR 解析置信度 high/medium/low 或 user_confirmed")
    field_confidence: Dict[str, str] = Field(default_factory=dict, description="字段级置信度，如 code/name/market_value/units/cost_amount/pnl_amount/pnl_pct/latest_nav")
    source_platform: str = Field("other", description="来源平台 alipay/jd_finance/xueqiu/fund_e_account/other")
    source_channel: str = Field("ocr_preview", description="ocr_preview/platform_screenshot_user_confirmed")
    raw_index: Optional[int] = Field(None, description="预览候选行序号；确认后不保留原始 OCR")
    warnings: List[str] = Field(default_factory=list)


class FundHoldingImportPreviewResponse(BaseModel):
    schema_version: str = Field("fund_holding_import_preview_v1")
    status: str = Field(..., description="completed/partial/blocked")
    source_platform: str
    source_platform_label: str
    candidate_count: int = 0
    candidates: List[FundHoldingCandidate] = Field(default_factory=list)
    limitations: List[str] = Field(default_factory=list)


class FundHoldingConfirmRequest(BaseModel):
    source_platform: str = Field(..., description="来源平台 alipay/jd_finance/xueqiu/fund_e_account/other")
    ledger_id: Optional[int] = Field(None, description="可选目标基金账本；不传则按平台自动创建/选择账本")
    replace: bool = Field(True, description="是否用本次确认结果覆盖该平台账本下旧快照")
    holdings: List[FundHoldingCandidate] = Field(default_factory=list, description="用户确认或编辑后的持仓行")


class FundHoldingSnapshotResponse(BaseModel):
    id: Optional[int] = None
    ledger_id: int
    source_platform: str
    source_channel: str
    code: str
    name: Optional[str] = None
    units: Optional[float] = None
    available_units: Optional[float] = None
    market_value: Optional[float] = None
    cost_amount: Optional[float] = None
    pnl_amount: Optional[float] = None
    pnl_pct: Optional[float] = None
    latest_nav: Optional[float] = None
    as_of_date: Optional[str] = None
    confidence: str = "user_confirmed"
    imported_at: Optional[str] = None
    updated_at: Optional[str] = None


class FundHoldingConfirmResponse(BaseModel):
    schema_version: str = Field("fund_holding_confirm_v1")
    status: str
    source_platform: str
    source_platform_label: str
    ledger: FundLedgerResponse
    confirmed_count: int = 0
    skipped: List[Dict[str, str]] = Field(default_factory=list)
    change_summary: Dict[str, Any] = Field(default_factory=dict, description="本次确认相对该平台账本当前快照的新增、更新、移除摘要")
    items: List[FundHoldingSnapshotResponse] = Field(default_factory=list)
    limitations: List[str] = Field(default_factory=list)


class FundHoldingListResponse(BaseModel):
    schema_version: str = Field("fund_holding_snapshot_v1")
    status: str
    items: List[FundHoldingSnapshotResponse] = Field(default_factory=list)
    aggregated_by_code: List[Dict[str, Any]] = Field(default_factory=list)
    portfolio_summary: Dict[str, Any] = Field(default_factory=dict, description="组合级市值、集中度、平台/账本分布和字段覆盖率摘要")
    total: int = 0
    ledger_id: Optional[int] = None
    limitations: List[str] = Field(default_factory=list)


class FundRecommendationCandidate(BaseModel):
    code: str
    name: Optional[str] = None
    fund_type: Optional[str] = None
    score: Optional[float] = None
    market_action: str = Field(..., description="research_only/market_watchlist/add_to_pool；不是个人买卖动作")
    personal_action: Optional[str] = Field(None, description="P0 必须为空；个人动作需用户画像+持仓")
    personalized: bool = False
    source_rank_types: List[str] = Field(default_factory=list)
    market_evidence: List[Dict[str, Any]] = Field(default_factory=list)
    data_quality_summary: str = "unknown"
    latest_analysis: Optional[FundAnalysisSnapshotResponse] = None
    backtest_readiness: Dict[str, Any] = Field(default_factory=dict)
    risk_flags: List[str] = Field(default_factory=list)
    invalid_if: List[str] = Field(default_factory=list)
    limitations: List[str] = Field(default_factory=list)


class FundRecommendationTodayResponse(BaseModel):
    schema_version: str = Field("fund_recommendation_today_v1")
    status: str
    fetched_at: str
    scope: Dict[str, Any] = Field(default_factory=dict)
    personalization: Dict[str, Any] = Field(default_factory=dict)
    candidates: List[FundRecommendationCandidate] = Field(default_factory=list)
    market_rankings: Dict[str, Any] = Field(default_factory=dict)
    limitations: List[str] = Field(default_factory=list)


class FundPersonalActionItem(BaseModel):
    code: str
    name: Optional[str] = None
    ledger_id: Optional[int] = None
    ledger_name: Optional[str] = None
    source_platform: Optional[str] = None
    market_value: Optional[float] = None
    pnl_amount: Optional[float] = None
    pnl_pct: Optional[float] = None
    analysis_action: Optional[str] = None
    personal_action: str = Field(..., description="increase/dca/hold/reduce/sell_watch/refresh_analysis/complete_profile")
    action_label: str
    confidence: str = Field(..., description="low/medium/high")
    profile: Dict[str, Any] = Field(default_factory=dict)
    position_context: Dict[str, Any] = Field(default_factory=dict)
    calibration_context: Dict[str, Any] = Field(default_factory=dict)
    market_context: Dict[str, Any] = Field(default_factory=dict)
    score_breakdown: Dict[str, Any] = Field(default_factory=dict)
    suggested_trade: Dict[str, Any] = Field(default_factory=dict)
    decision_trace: List[str] = Field(default_factory=list)
    evidence: Dict[str, Any] = Field(default_factory=dict)
    blockers: List[str] = Field(default_factory=list)
    blocker_labels: List[str] = Field(default_factory=list)
    invalid_if: List[str] = Field(default_factory=list)
    limitations: List[str] = Field(default_factory=list)


class FundPersonalActionsResponse(BaseModel):
    schema_version: str = Field("fund_personal_actions_v2")
    status: str = Field(..., description="actionable/partial/blocked")
    fetched_at: str
    summary: Dict[str, Any] = Field(default_factory=dict)
    prerequisites: Dict[str, Any] = Field(default_factory=dict)
    actions: List[FundPersonalActionItem] = Field(default_factory=list)
    blockers: List[str] = Field(default_factory=list)
    blocker_labels: List[str] = Field(default_factory=list)
    limitations: List[str] = Field(default_factory=list)
