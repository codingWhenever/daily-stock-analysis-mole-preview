# -*- coding: utf-8 -*-
from __future__ import annotations

from src.config import Config
from src.repositories.fund_repo import FundRepository
from src.services.fund_holding_import_service import (
    FUND_HOLDING_CONFIRM_SCHEMA_VERSION,
    FUND_HOLDING_PREVIEW_SCHEMA_VERSION,
    FundHoldingImportService,
    OCRTextLine,
    _extract_layout_holding_rows,
    _rapidocr_result_to_text,
    parse_fund_holding_text,
)
from src.services.fund_service import FundMetadata, FundService
from src.storage import DatabaseManager


class MinimalFundProvider:
    def get_metadata(self, code: str) -> FundMetadata:
        return FundMetadata(code=code, name=f"基金{code}", fund_type="混合型")

    def search_funds(self, query: str, limit: int = 20) -> list[FundMetadata]:
        if "南方原油" in query:
            return [
                FundMetadata(code="006476", name="南方原油C", fund_type="QDII-商品"),
                FundMetadata(code="501018", name="南方原油A", fund_type="QDII-商品"),
            ][:limit]
        if "广发纳斯达克100ETF联接" in query or "广发纳指100ETF联接" in query:
            return [
                FundMetadata(code="000055", name="广发纳斯达克100ETF联接美元(QDII)A", fund_type="指数型-海外股票"),
                FundMetadata(code="006479", name="广发纳斯达克100ETF联接人民币(QDII)C", fund_type="指数型-海外股票"),
                FundMetadata(code="270042", name="广发纳斯达克100ETF联接人民币(QDII)A", fund_type="指数型-海外股票"),
            ][:limit]
        return []

    def get_nav_records(self, code: str) -> list[dict[str, object]]:
        if code == "501018":
            return [{"date": "2026-06-24", "unit_nav": 1.5018}]
        if code == "270042":
            return [{"date": "2026-06-24", "unit_nav": 8.1772}]
        return []


class FakeRapidOCROutput:
    txts = ("基金名称", "财通成长优选混合C", "021528", "持有金额 12345.67")


def teardown_function():
    DatabaseManager.reset_instance()
    Config.reset_instance()


def _service() -> FundHoldingImportService:
    DatabaseManager.reset_instance()
    db = DatabaseManager(db_url="sqlite:///:memory:")
    repo = FundRepository(db_manager=db)
    fund_service = FundService(repo=repo, provider=MinimalFundProvider())
    return FundHoldingImportService(repo=repo, fund_service=fund_service)


def test_parse_fund_holding_text_extracts_confirmable_fields() -> None:
    text = """
    财通成长优选混合C 021528
    持有金额 12,345.67
    持有份额 2,345.89
    持有收益 +123.45
    收益率 +1.23%
    最新净值 5.4321
    截至 2026-06-26
    """

    rows = parse_fund_holding_text(text, source_platform="alipay")

    assert len(rows) == 1
    row = rows[0]
    assert row["code"] == "021528"
    assert row["name"] == "财通成长优选混合C"
    assert row["market_value"] == 12345.67
    assert row["units"] == 2345.89
    assert row["pnl_amount"] == 123.45
    assert row["pnl_pct"] == 1.23
    assert row["latest_nav"] == 5.4321
    assert row["as_of_date"] == "2026-06-26"
    assert row["confidence"] == "high"


def test_rapidocr_output_object_converts_to_text_lines() -> None:
    text = _rapidocr_result_to_text(FakeRapidOCROutput())

    assert "财通成长优选混合C" in text
    assert "021528" in text
    assert "持有金额 12345.67" in text


def test_layout_holding_rows_resolve_name_only_jd_finance_snapshot() -> None:
    service = _service()
    lines = [
        OCRTextLine("基金名称", 148, 635, 60, 610, 240, 660),
        OCRTextLine("金额/昨日收益", 673, 637, 540, 610, 810, 660),
        OCRTextLine("持仓收益/率", 1030, 636, 900, 610, 1140, 660),
        OCRTextLine("南方原油(QDII-", 244, 812, 70, 780, 420, 840),
        OCRTextLine("8,238.32", 715, 818, 620, 790, 810, 850),
        OCRTextLine("+1,571.32", 1036, 817, 930, 790, 1140, 850),
        OCRTextLine("FOF-LOF)", 194, 875, 70, 850, 320, 900),
        OCRTextLine("-246.85", 733, 885, 650, 860, 820, 910),
        OCRTextLine("+23.57%", 1057, 885, 960, 860, 1140, 910),
        OCRTextLine("商品基金榜No.3>", 281, 949, 70, 920, 490, 980),
        OCRTextLine("广发纳指100ETF联", 280, 1349, 70, 1320, 500, 1380),
        OCRTextLine("20,164.40", 706, 1354, 600, 1320, 820, 1380),
        OCRTextLine("+15,164.40", 1022, 1355, 900, 1320, 1160, 1380),
        OCRTextLine("接(QDII)A", 180, 1411, 70, 1380, 320, 1440),
        OCRTextLine("-83.60", 744, 1422, 650, 1390, 820, 1450),
        OCRTextLine("+303.29%", 1046, 1422, 930, 1390, 1160, 1450),
    ]

    layout_rows = _extract_layout_holding_rows(lines, source_platform="jd_finance")
    rows = service._resolve_layout_candidates(layout_rows, source_platform="jd_finance")

    assert [row["code"] for row in rows] == ["501018", "270042"]
    assert rows[0]["market_value"] == 8238.32
    assert rows[0]["cost_amount"] == 6667.0
    assert rows[0]["latest_nav"] == 1.5018
    assert rows[0]["units"] == 5485.63
    assert rows[0]["pnl_amount"] == 1571.32
    assert rows[0]["pnl_pct"] == 23.57
    assert rows[1]["market_value"] == 20164.40
    assert rows[1]["cost_amount"] == 5000.0
    assert rows[1]["latest_nav"] == 8.1772
    assert rows[1]["units"] == 2465.93
    assert rows[1]["pnl_amount"] == 15164.40
    assert rows[1]["pnl_pct"] == 303.29
    assert all("代码由" in " ".join(row["warnings"]) for row in rows)


def test_preview_import_from_text_does_not_persist_snapshot() -> None:
    service = _service()

    preview = service.preview_import(
        source_platform="jd_finance",
        ocr_text="永赢先锋半导体智选混合发起C 025209\n持有金额: 3000.00\n份额: 1200.00",
    )
    holdings = service.list_holdings()

    assert preview["schema_version"] == FUND_HOLDING_PREVIEW_SCHEMA_VERSION
    assert preview["status"] == "completed"
    assert preview["source_platform"] == "jd_finance"
    assert preview["candidate_count"] == 1
    assert holdings["items"] == []


def test_confirm_import_writes_canonical_snapshot_and_analysis_pool_entry() -> None:
    service = _service()
    preview = service.preview_import(
        source_platform="alipay",
        ocr_text="财通成长优选混合C 021528\n持有金额 12000\n持有份额 2000\n收益率 8.5%",
    )

    result = service.confirm_import(
        source_platform="alipay",
        holdings=preview["candidates"],
    )
    holdings = service.list_holdings()
    pool = service.fund_service.list_pool()

    assert result["schema_version"] == FUND_HOLDING_CONFIRM_SCHEMA_VERSION
    assert result["status"] == "completed"
    assert result["ledger"]["name"] == "支付宝账本"
    assert result["confirmed_count"] == 1
    assert result["items"][0]["confidence"] == "user_confirmed"
    assert result["items"][0]["source_channel"] == "platform_screenshot_user_confirmed"
    assert holdings["total"] == 1
    assert holdings["aggregated_by_code"][0]["code"] == "021528"
    assert holdings["aggregated_by_code"][0]["market_value"] == 12000.0
    assert any(item["code"] == "021528" for item in pool["items"])


def test_same_fund_can_remain_separate_by_platform_but_aggregate_globally() -> None:
    service = _service()
    service.confirm_import(
        source_platform="alipay",
        holdings=[
            {"code": "021528", "name": "财通成长优选混合C", "market_value": 1000.0, "units": 100.0}
        ],
    )
    service.confirm_import(
        source_platform="jd_finance",
        holdings=[
            {"code": "021528", "name": "财通成长优选混合C", "market_value": 2500.0, "units": 200.0}
        ],
    )

    holdings = service.list_holdings()
    aggregate = holdings["aggregated_by_code"][0]

    assert holdings["total"] == 2
    assert aggregate["code"] == "021528"
    assert aggregate["market_value"] == 3500.0
    assert aggregate["units"] == 300.0
    assert len(aggregate["source_breakdown"]) == 2


if __name__ == "__main__":
    for name, func in sorted(globals().items()):
        if name.startswith("test_") and callable(func):
            func()
