# -*- coding: utf-8 -*-
"""公募基金池接口。"""

from __future__ import annotations

import logging
from typing import List, Optional

from fastapi import APIRouter, File, Form, HTTPException, Query, UploadFile

from api.v1.schemas.common import ErrorResponse
from api.v1.schemas.funds import (
    FundBacktestCalibrationResponse,
    FundAnalysisSnapshotResponse,
    FundBacktestResponse,
    FundHoldingConfirmRequest,
    FundHoldingConfirmResponse,
    FundHoldingImportPreviewResponse,
    FundHoldingListResponse,
    FundLedgerAssignRequest,
    FundLedgerCreateRequest,
    FundLedgerResponse,
    FundLedgerUpdateRequest,
    FundMarketRankingsResponse,
    FundNavHistoryResponse,
    FundPersonalActionsResponse,
    FundPoolAddRequest,
    FundPoolRefreshResponse,
    FundPoolResponse,
    FundPoolItemResponse,
    FundRecommendationTodayResponse,
    FundRemoveResponse,
    FundSearchResponse,
)
from src.services.fund_holding_import_service import (
    HOLDING_MAX_IMAGE_BYTES,
    HOLDING_MAX_IMAGE_COUNT,
    HOLDING_MAX_TOTAL_IMAGE_BYTES,
    HoldingImageInput,
    FundHoldingImportService,
)
from src.services.fund_service import FundService, normalize_fund_code

logger = logging.getLogger(__name__)

router = APIRouter()


def _service() -> FundService:
    return FundService()


def _holding_service() -> FundHoldingImportService:
    return FundHoldingImportService()


def _bad_request(message: str) -> HTTPException:
    return HTTPException(status_code=400, detail={"error": "invalid_fund_code", "message": message})


@router.get(
    "/search",
    response_model=FundSearchResponse,
    responses={
        400: {"description": "参数错误", "model": ErrorResponse},
        500: {"description": "服务器错误", "model": ErrorResponse},
    },
    summary="搜索公募基金",
    description="按基金代码、名称或拼音搜索公募基金，并返回公开最新净值、申购赎回、近期收益和同类排名。",
)
def search_funds(
    q: str = Query(..., min_length=1, max_length=64, description="基金代码、名称或拼音"),
    limit: int = Query(20, ge=1, le=50, description="最多返回条数"),
) -> FundSearchResponse:
    try:
        return FundSearchResponse(**_service().search(q, limit=limit))
    except ValueError as exc:
        raise _bad_request(str(exc))
    except Exception as exc:  # noqa: BLE001
        logger.error("搜索基金失败: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail={"error": "internal_error", "message": "搜索基金失败"})


@router.get(
    "/pool",
    response_model=FundPoolResponse,
    responses={500: {"description": "服务器错误", "model": ErrorResponse}},
    summary="获取基金池",
    description="返回当前跟踪的公募基金池及最近一次规则化分析快照。",
)
def list_fund_pool() -> FundPoolResponse:
    try:
        return FundPoolResponse(**_service().list_pool())
    except Exception as exc:  # noqa: BLE001
        logger.error("获取基金池失败: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail={"error": "internal_error", "message": "获取基金池失败"})


@router.post(
    "/ledgers",
    response_model=FundLedgerResponse,
    responses={
        400: {"description": "参数错误", "model": ErrorResponse},
        500: {"description": "服务器错误", "model": ErrorResponse},
    },
    summary="创建基金账本",
    description="创建一个用于基金池分类的账本/账户，可设置主题色。",
)
def create_fund_ledger(request: FundLedgerCreateRequest) -> FundLedgerResponse:
    try:
        return FundLedgerResponse(**_service().create_ledger(
            request.name,
            request.color,
            account_type=request.account_type,
            purpose=request.purpose,
            risk_target=request.risk_target,
            investment_horizon=request.investment_horizon,
            rebalance_frequency=request.rebalance_frequency,
            drawdown_tolerance=request.drawdown_tolerance,
            liquidity_need=request.liquidity_need,
            investment_experience=request.investment_experience,
            monthly_budget=request.monthly_budget,
            cash_reserve_months=request.cash_reserve_months,
            preferred_fund_types=request.preferred_fund_types,
            notes=request.notes,
        ))
    except ValueError as exc:
        raise _bad_request(str(exc))
    except Exception as exc:  # noqa: BLE001
        logger.error("创建基金账本失败: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail={"error": "internal_error", "message": "创建基金账本失败"})


@router.patch(
    "/ledgers/{ledger_id}",
    response_model=FundLedgerResponse,
    responses={
        400: {"description": "参数错误", "model": ErrorResponse},
        500: {"description": "服务器错误", "model": ErrorResponse},
    },
    summary="更新基金账本画像",
    description="更新本地账本/账户画像字段，可选更新名称和主题色；不处理删除、排序或个人平台账号接入。",
)
def update_fund_ledger(ledger_id: int, request: FundLedgerUpdateRequest) -> FundLedgerResponse:
    try:
        return FundLedgerResponse(**_service().update_ledger_profile(
            ledger_id,
            **request.model_dump(exclude_unset=True),
        ))
    except ValueError as exc:
        raise _bad_request(str(exc))
    except Exception as exc:  # noqa: BLE001
        logger.error("更新基金账本画像失败 %s: %s", ledger_id, exc, exc_info=True)
        raise HTTPException(status_code=500, detail={"error": "internal_error", "message": "更新基金账本画像失败"})


@router.post(
    "/pool",
    response_model=FundPoolItemResponse,
    responses={
        400: {"description": "参数错误", "model": ErrorResponse},
        500: {"description": "服务器错误", "model": ErrorResponse},
    },
    summary="加入基金池",
    description="将 6 位公募基金代码加入基金池。不会读取个人账户或持仓。",
)
def add_fund_to_pool(request: FundPoolAddRequest) -> FundPoolItemResponse:
    try:
        normalize_fund_code(request.code)
        return FundPoolItemResponse(**_service().add_to_pool(
            request.code,
            name=request.name,
            notes=request.notes,
            ledger_id=request.ledger_id,
        ))
    except ValueError as exc:
        raise _bad_request(str(exc))
    except Exception as exc:  # noqa: BLE001
        logger.error("加入基金池失败: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail={"error": "internal_error", "message": "加入基金池失败"})


@router.delete(
    "/pool/{code}",
    response_model=FundRemoveResponse,
    responses={
        400: {"description": "参数错误", "model": ErrorResponse},
        500: {"description": "服务器错误", "model": ErrorResponse},
    },
    summary="移出基金池",
    description="将基金池条目标记为不再跟踪，历史净值和快照保留。",
)
def remove_fund_from_pool(code: str) -> FundRemoveResponse:
    try:
        return FundRemoveResponse(**_service().remove_from_pool(code))
    except ValueError as exc:
        raise _bad_request(str(exc))
    except Exception as exc:  # noqa: BLE001
        logger.error("移出基金池失败: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail={"error": "internal_error", "message": "移出基金池失败"})


@router.patch(
    "/pool/{code}/ledger",
    response_model=FundPoolItemResponse,
    responses={
        400: {"description": "参数错误", "model": ErrorResponse},
        500: {"description": "服务器错误", "model": ErrorResponse},
    },
    summary="调整基金账本归属",
    description="将基金池中的某只基金手动归属到指定账本/分类。",
)
def assign_fund_ledger(code: str, request: FundLedgerAssignRequest) -> FundPoolItemResponse:
    try:
        return FundPoolItemResponse(**_service().assign_fund_ledger(code, request.ledger_id))
    except ValueError as exc:
        raise _bad_request(str(exc))
    except Exception as exc:  # noqa: BLE001
        logger.error("调整基金账本失败 %s: %s", code, exc, exc_info=True)
        raise HTTPException(status_code=500, detail={"error": "internal_error", "message": "调整基金账本失败"})


@router.post(
    "/pool/refresh",
    response_model=FundPoolRefreshResponse,
    responses={500: {"description": "服务器错误", "model": ErrorResponse}},
    summary="刷新基金池",
    description="逐只刷新基金净值、指标、同类比较并生成最新动作信号。",
)
def refresh_fund_pool() -> FundPoolRefreshResponse:
    try:
        return FundPoolRefreshResponse(**_service().refresh_pool())
    except Exception as exc:  # noqa: BLE001
        logger.error("刷新基金池失败: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail={"error": "internal_error", "message": "刷新基金池失败"})


@router.get(
    "/calibration/backtests",
    response_model=FundBacktestCalibrationResponse,
    responses={
        400: {"description": "参数错误", "model": ErrorResponse},
        500: {"description": "服务器错误", "model": ErrorResponse},
    },
    summary="基金回测校准中心",
    description="按基金、账本和基金类型聚合本地 NAV walk-forward 回测结果。第一版只做聚合与状态，不回写信号参数。",
)
def calibrate_fund_backtests(
    ledger_id: int | None = Query(None, ge=1, description="可选账本/分类 ID"),
    fund_type: str | None = Query(None, min_length=1, max_length=50, description="可选基金类型精确筛选"),
    codes: str | None = Query(None, description="逗号分隔的 6 位基金代码，仅在当前基金池内筛选"),
    lookback_days: int = Query(252, ge=60, le=1500, description="每次生成信号使用的历史净值样本数"),
    eval_window_days: int = Query(60, ge=5, le=365, description="每个信号向后评估的净值样本窗口"),
    rebalance_interval_days: int = Query(20, ge=5, le=120, description="滚动信号间隔"),
    initial_cash: float = Query(10000, gt=0, le=10000000, description="回测初始现金"),
) -> FundBacktestCalibrationResponse:
    try:
        code_list = [item.strip() for item in codes.split(",") if item.strip()] if codes else None
        return FundBacktestCalibrationResponse(
            **_service().calibrate_backtests(
                ledger_id=ledger_id,
                fund_type=fund_type,
                codes=code_list,
                lookback_days=lookback_days,
                eval_window_days=eval_window_days,
                rebalance_interval_days=rebalance_interval_days,
                initial_cash=initial_cash,
            )
        )
    except ValueError as exc:
        raise _bad_request(str(exc))
    except Exception as exc:  # noqa: BLE001
        logger.error("基金回测校准失败: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail={"error": "internal_error", "message": "基金回测校准失败"})


@router.get(
    "/market-rankings",
    response_model=FundMarketRankingsResponse,
    responses={
        400: {"description": "参数错误", "model": ErrorResponse},
        500: {"description": "服务器错误", "model": ErrorResponse},
    },
    summary="市场级基金公开榜单",
    description="汇总 ETF 资金流/成交热度和开放式基金公开收益排行。该接口不读取用户画像、持仓、账本或成本价，不生成个人买卖动作。",
)
def get_market_fund_rankings(
    limit: int = Query(10, ge=1, le=30, description="每个榜单最多返回条数"),
    fund_type: str = Query("全部", min_length=1, max_length=50, description="开放式基金排行类型，如 全部/股票型/混合型/债券型/指数型/QDII/FOF"),
) -> FundMarketRankingsResponse:
    try:
        return FundMarketRankingsResponse(**_service().market_rankings(limit=limit, fund_type=fund_type))
    except ValueError as exc:
        raise _bad_request(str(exc))
    except Exception as exc:  # noqa: BLE001
        logger.error("获取市场级基金榜单失败: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail={"error": "internal_error", "message": "获取市场级基金榜单失败"})


@router.post(
    "/holding-imports/preview",
    response_model=FundHoldingImportPreviewResponse,
    responses={
        400: {"description": "参数错误", "model": ErrorResponse},
        500: {"description": "服务器错误", "model": ErrorResponse},
    },
    summary="预览基金持仓截图导入",
    description="上传支付宝/京东金融/雪球/基金E账户等平台截图，或提交 OCR 文本，返回待用户确认的持仓候选；不会写入持仓表，不保存原始 OCR。",
)
def preview_fund_holding_import(
    source_platform: str = Form(..., description="来源平台 alipay/jd_finance/xueqiu/fund_e_account/other"),
    ocr_text: Optional[str] = Form(None, description="可选 OCR 文本；无本地 OCR 依赖时可用于调试/粘贴导入"),
    files: Optional[List[UploadFile]] = File(None, description="持仓截图，可上传多张，支持 JPEG/PNG/WebP"),
) -> FundHoldingImportPreviewResponse:
    try:
        images: List[HoldingImageInput] = []
        upload_files = files or []
        if len(upload_files) > HOLDING_MAX_IMAGE_COUNT:
            raise ValueError(f"一次最多上传 {HOLDING_MAX_IMAGE_COUNT} 张截图")
        total = 0
        for file in upload_files:
            content_type = (file.content_type or "").split(";")[0].strip().lower()
            data = file.file.read(HOLDING_MAX_IMAGE_BYTES)
            if file.file.read(1):
                raise ValueError(f"单张图片超过 {HOLDING_MAX_IMAGE_BYTES // (1024 * 1024)}MB 限制")
            total += len(data)
            if total > HOLDING_MAX_TOTAL_IMAGE_BYTES:
                raise ValueError(f"图片总大小超过 {HOLDING_MAX_TOTAL_IMAGE_BYTES // (1024 * 1024)}MB 限制")
            images.append(HoldingImageInput(content=data, mime_type=content_type, filename=file.filename or "upload"))
        return FundHoldingImportPreviewResponse(
            **_holding_service().preview_import(
                source_platform=source_platform,
                images=images,
                ocr_text=ocr_text,
            )
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail={"error": "invalid_holding_import", "message": str(exc)})
    except Exception as exc:  # noqa: BLE001
        logger.error("基金持仓导入预览失败: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail={"error": "internal_error", "message": "基金持仓导入预览失败"})


@router.post(
    "/holding-imports/confirm",
    response_model=FundHoldingConfirmResponse,
    responses={
        400: {"description": "参数错误", "model": ErrorResponse},
        500: {"description": "服务器错误", "model": ErrorResponse},
    },
    summary="确认基金持仓导入",
    description="仅写入用户确认或编辑后的持仓当前快照；成本、收益、份额等缺失字段保持为空，不伪造成交易流水。",
)
def confirm_fund_holding_import(request: FundHoldingConfirmRequest) -> FundHoldingConfirmResponse:
    try:
        if not request.holdings:
            raise ValueError("没有可确认的持仓行")
        return FundHoldingConfirmResponse(
            **_holding_service().confirm_import(
                source_platform=request.source_platform,
                ledger_id=request.ledger_id,
                replace=request.replace,
                holdings=[item.model_dump() for item in request.holdings],
            )
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail={"error": "invalid_holding_import", "message": str(exc)})
    except Exception as exc:  # noqa: BLE001
        logger.error("基金持仓导入确认失败: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail={"error": "internal_error", "message": "基金持仓导入确认失败"})


@router.get(
    "/holdings",
    response_model=FundHoldingListResponse,
    responses={500: {"description": "服务器错误", "model": ErrorResponse}},
    summary="查询基金持仓快照",
    description="返回用户确认后的基金持仓当前态；全部视图按基金代码聚合，各账本/平台下仍保留独立明细。",
)
def list_fund_holdings(
    ledger_id: Optional[int] = Query(None, ge=1, description="可选账本 ID"),
) -> FundHoldingListResponse:
    try:
        return FundHoldingListResponse(**_holding_service().list_holdings(ledger_id=ledger_id))
    except Exception as exc:  # noqa: BLE001
        logger.error("查询基金持仓快照失败: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail={"error": "internal_error", "message": "查询基金持仓快照失败"})


@router.get(
    "/recommendations/today",
    response_model=FundRecommendationTodayResponse,
    responses={
        400: {"description": "参数错误", "model": ErrorResponse},
        500: {"description": "服务器错误", "model": ErrorResponse},
    },
    summary="市场级荐基证据卡",
    description="基于公开市场榜单候选，叠加本地分析/回测准备度，输出研究关注证据；不读取用户画像或个人持仓，不生成个人买卖动作。",
)
def get_today_fund_recommendations(
    limit: int = Query(10, ge=1, le=30, description="最多返回候选数量"),
    fund_type: str = Query("全部", min_length=1, max_length=50, description="开放式基金排行类型"),
) -> FundRecommendationTodayResponse:
    try:
        return FundRecommendationTodayResponse(**_service().recommendations_today(limit=limit, fund_type=fund_type))
    except ValueError as exc:
        raise _bad_request(str(exc))
    except Exception as exc:  # noqa: BLE001
        logger.error("获取市场级荐基证据失败: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail={"error": "internal_error", "message": "获取市场级荐基证据失败"})


@router.get(
    "/personal-actions",
    response_model=FundPersonalActionsResponse,
    responses={
        400: {"description": "参数错误", "model": ErrorResponse},
        500: {"description": "服务器错误", "model": ErrorResponse},
    },
    summary="个人持仓动作建议",
    description="基于已确认基金持仓、账本画像和单品分析生成个人动作建议或阻塞项；不会使用未确认 OCR 候选或伪造交易流水。",
)
def get_fund_personal_actions() -> FundPersonalActionsResponse:
    try:
        return FundPersonalActionsResponse(**_service().personal_actions())
    except ValueError as exc:
        raise _bad_request(str(exc))
    except Exception as exc:  # noqa: BLE001
        logger.error("获取基金个人动作建议失败: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail={"error": "internal_error", "message": "获取基金个人动作建议失败"})


@router.post(
    "/{code}/refresh",
    response_model=FundAnalysisSnapshotResponse,
    responses={
        400: {"description": "参数错误", "model": ErrorResponse},
        500: {"description": "服务器错误", "model": ErrorResponse},
    },
    summary="刷新单只基金",
    description="刷新单只公募基金净值、风险收益指标、同类比较并生成动作信号。",
)
def refresh_fund(code: str) -> FundAnalysisSnapshotResponse:
    try:
        normalize_fund_code(code)
        return FundAnalysisSnapshotResponse(**_service().refresh_fund(code))
    except ValueError as exc:
        raise _bad_request(str(exc))
    except Exception as exc:  # noqa: BLE001
        logger.error("刷新基金失败 %s: %s", code, exc, exc_info=True)
        raise HTTPException(status_code=500, detail={"error": "internal_error", "message": "刷新基金失败"})


@router.get(
    "/{code}/backtest",
    response_model=FundBacktestResponse,
    responses={
        400: {"description": "参数错误", "model": ErrorResponse},
        500: {"description": "服务器错误", "model": ErrorResponse},
    },
    summary="基金策略回测",
    description="基于本地缓存公开净值做滚动历史回测，只用每个信号日前的数据生成信号，并与一次性买入持有比较。",
)
def backtest_fund(
    code: str,
    lookback_days: int = Query(252, ge=60, le=1500, description="每次生成信号使用的历史净值样本数"),
    eval_window_days: int = Query(60, ge=5, le=365, description="每个信号向后评估的净值样本窗口"),
    rebalance_interval_days: int = Query(20, ge=5, le=120, description="滚动信号间隔"),
    initial_cash: float = Query(10000, gt=0, le=10000000, description="回测初始现金"),
    dca_amount: float = Query(1000, gt=0, le=1000000, description="定投动作单次投入金额"),
    neutral_band_pct: float = Query(2, ge=0, le=20, description="命中/失误之间的中性收益阈值"),
) -> FundBacktestResponse:
    try:
        return FundBacktestResponse(
            **_service().backtest(
                code,
                lookback_days=lookback_days,
                eval_window_days=eval_window_days,
                rebalance_interval_days=rebalance_interval_days,
                initial_cash=initial_cash,
                dca_amount=dca_amount,
                neutral_band_pct=neutral_band_pct,
            )
        )
    except ValueError as exc:
        raise _bad_request(str(exc))
    except Exception as exc:  # noqa: BLE001
        logger.error("基金回测失败 %s: %s", code, exc, exc_info=True)
        raise HTTPException(status_code=500, detail={"error": "internal_error", "message": "基金回测失败"})


@router.get(
    "/{code}/analysis",
    response_model=FundAnalysisSnapshotResponse,
    responses={
        400: {"description": "参数错误", "model": ErrorResponse},
        404: {"description": "暂无分析", "model": ErrorResponse},
        500: {"description": "服务器错误", "model": ErrorResponse},
    },
    summary="查询最新基金分析",
    description="查询最近一次基金指标与动作信号快照。",
)
def get_latest_fund_analysis(code: str) -> FundAnalysisSnapshotResponse:
    try:
        snapshot = _service().latest_analysis(code)
        if snapshot is None:
            raise HTTPException(status_code=404, detail={"error": "not_found", "message": "暂无基金分析快照"})
        return FundAnalysisSnapshotResponse(**snapshot)
    except HTTPException:
        raise
    except ValueError as exc:
        raise _bad_request(str(exc))
    except Exception as exc:  # noqa: BLE001
        logger.error("查询基金分析失败 %s: %s", code, exc, exc_info=True)
        raise HTTPException(status_code=500, detail={"error": "internal_error", "message": "查询基金分析失败"})


@router.get(
    "/{code}/nav",
    response_model=FundNavHistoryResponse,
    responses={
        400: {"description": "参数错误", "model": ErrorResponse},
        500: {"description": "服务器错误", "model": ErrorResponse},
    },
    summary="查询基金净值历史",
    description="返回本地已缓存的基金净值历史，刷新接口会更新缓存。",
)
def get_fund_nav_history(
    code: str,
    limit: int = Query(260, ge=1, le=5000, description="返回最近 N 条净值记录"),
) -> FundNavHistoryResponse:
    try:
        return FundNavHistoryResponse(**_service().nav_history(code, limit=limit))
    except ValueError as exc:
        raise _bad_request(str(exc))
    except Exception as exc:  # noqa: BLE001
        logger.error("查询基金净值失败 %s: %s", code, exc, exc_info=True)
        raise HTTPException(status_code=500, detail={"error": "internal_error", "message": "查询基金净值失败"})
