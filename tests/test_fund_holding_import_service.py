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
        if "安信灵活配置混合" in query:
            return [FundMetadata(code="750001", name="安信灵活配置混合A", fund_type="混合型")][:limit]
        if "易方达安盈回报混合" in query:
            return [FundMetadata(code="001603", name="易方达安盈回报混合A", fund_type="混合型")][:limit]
        if "交银中证海外中国互联网指数" in query:
            return [FundMetadata(code="164906", name="交银中证海外中国互联网指数(LOF)A", fund_type="QDII")][:limit]
        if "德邦半导体产业混合发起式" in query or "德邦半导体产业" in query:
            return [
                FundMetadata(code="014319", name="德邦半导体产业混合发起式A", fund_type="混合型"),
                FundMetadata(code="014320", name="德邦半导体产业混合发起式C", fund_type="混合型"),
            ][:limit]
        if "德邦鑫星价值灵活配置混合" in query:
            return [
                FundMetadata(code="001412", name="德邦鑫星价值灵活配置混合A", fund_type="混合型"),
                FundMetadata(code="002112", name="德邦鑫星价值灵活配置混合C", fund_type="混合型"),
            ][:limit]
        if "金信稳健策略混合" in query or "金信稳健策略" in query:
            return [
                FundMetadata(code="007872", name="金信稳健策略混合A", fund_type="混合型"),
                FundMetadata(code="020436", name="金信稳健策略混合C", fund_type="混合型"),
            ][:limit]
        if "华夏创业板成长ETF联接" in query:
            return [
                FundMetadata(code="007474", name="华夏创业板成长ETF联接A", fund_type="指数型"),
                FundMetadata(code="007475", name="华夏创业板成长ETF联接C", fund_type="指数型"),
            ][:limit]
        if "易方达中证海外互联网50ETF联接" in query:
            return [
                FundMetadata(code="006328", name="易方达中证海外互联网50ETF联接(QDII)C", fund_type="QDII"),
                FundMetadata(code="006327", name="易方达中证海外互联网50ETF联接(QDII)A", fund_type="QDII"),
                FundMetadata(code="006329", name="易方达中证海外互联网50ETF联接(QDII)(美元现汇)A", fund_type="QDII"),
            ][:limit]
        if "国富大中华精选混合" in query:
            return [
                FundMetadata(code="000934", name="国富大中华精选混合", fund_type="QDII"),
                FundMetadata(code="006370", name="国富大中华精选混合美元", fund_type="QDII"),
            ][:limit]
        if "万家新利灵活配置混合" in query:
            return [FundMetadata(code="519191", name="万家新利灵活配置混合", fund_type="混合型")][:limit]
        if "中欧价值智选混合" in query:
            return [
                FundMetadata(code="004235", name="中欧价值智选混合C", fund_type="混合型"),
                FundMetadata(code="166019", name="中欧价值智选混合A", fund_type="混合型"),
            ][:limit]
        if "兴全沪深300" in query:
            return [
                FundMetadata(code="022962", name="兴全沪深300指数增强(LOF)Y", fund_type="指数型"),
                FundMetadata(code="163407", name="兴全沪深300指数(LOF)A", fund_type="指数型"),
                FundMetadata(code="007230", name="兴全沪深300指数(LOF)C", fund_type="指数型"),
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
    assert row["field_confidence"]["code"] == "high"
    assert row["field_confidence"]["market_value"] == "high"
    assert row["field_confidence"]["units"] == "high"


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
    assert rows[0]["field_confidence"]["code"] == "medium"
    assert rows[0]["field_confidence"]["market_value"] == "high"
    assert rows[0]["field_confidence"]["cost_amount"] == "medium"
    assert rows[0]["field_confidence"]["latest_nav"] == "medium"
    assert rows[0]["field_confidence"]["units"] == "low"
    assert rows[1]["market_value"] == 20164.40
    assert rows[1]["cost_amount"] == 5000.0
    assert rows[1]["latest_nav"] == 8.1772
    assert rows[1]["units"] == 2465.93
    assert rows[1]["pnl_amount"] == 15164.40
    assert rows[1]["pnl_pct"] == 303.29
    assert all("代码由" in " ".join(row["warnings"]) for row in rows)


def test_layout_holding_rows_resolve_alipay_snapshot_headers() -> None:
    service = _service()
    lines = [
        OCRTextLine("名称", 108, 644, 70, 620, 150, 670),
        OCRTextLine("金额/昨日收益", 690, 645, 540, 620, 820, 670),
        OCRTextLine("持有收益/率", 1037, 645, 900, 620, 1160, 670),
        OCRTextLine("36,881.55", 708, 740, 620, 710, 820, 770),
        OCRTextLine("德邦半导体产业混合C", 289, 741, 70, 710, 500, 770),
        OCRTextLine("+26,165.63", 1027, 741, 900, 710, 1160, 770),
        OCRTextLine("+244.18%", 1050, 802, 930, 770, 1160, 830),
        OCRTextLine("+1,263.23", 720, 802, 620, 770, 820, 830),
        OCRTextLine("投资锦囊 德邦半导体产业混合发起式最新投资策略...", 619, 913, 70, 880, 1160, 940),
        OCRTextLine("12,676.81", 708, 1135, 620, 1100, 820, 1160),
        OCRTextLine("+6,390.40", 1038, 1135, 900, 1100, 1160, 1160),
        OCRTextLine("德邦鑫星价值灵活配置", 296, 1137, 70, 1100, 520, 1165),
        OCRTextLine("混合C", 131, 1192, 70, 1165, 200, 1220),
        OCRTextLine("+371.40", 736, 1197, 640, 1165, 830, 1225),
        OCRTextLine("+101.65%", 1051, 1197, 930, 1165, 1160, 1225),
        OCRTextLine("金信基金财富号>", 267, 1501, 70, 1470, 460, 1530),
        OCRTextLine("68,107.44", 709, 1648, 620, 1615, 820, 1675),
        OCRTextLine("+43,295.75", 1025, 1647, 900, 1615, 1160, 1675),
        OCRTextLine("金信稳健策略灵活配置", 297, 1649, 70, 1615, 520, 1675),
        OCRTextLine("混合A", 131, 1704, 70, 1675, 200, 1735),
        OCRTextLine("+174.50%", 1051, 1710, 930, 1680, 1160, 1740),
        OCRTextLine("+2,176.01", 719, 1711, 620, 1680, 830, 1740),
        OCRTextLine("华夏基金财富号>", 266, 2055, 70, 2020, 460, 2090),
        OCRTextLine("88,639.80", 709, 2202, 620, 2170, 820, 2230),
        OCRTextLine("+47,415.55", 1027, 2201, 900, 2170, 1160, 2230),
        OCRTextLine("华夏创业板成长ETF联", 288, 2202, 70, 2170, 520, 2230),
        OCRTextLine("接A", 110, 2257, 70, 2230, 160, 2290),
        OCRTextLine("+115.02%", 1051, 2263, 930, 2230, 1160, 2295),
        OCRTextLine("+3,294.24", 721, 2265, 620, 2230, 830, 2295),
        OCRTextLine("金选指数基金", 205, 2313, 70, 2285, 330, 2340),
        OCRTextLine("定投", 391, 2313, 350, 2285, 430, 2340),
    ]

    layout_rows = _extract_layout_holding_rows(lines, source_platform="alipay")
    rows = service._resolve_layout_candidates(layout_rows, source_platform="alipay")

    assert [row["code"] for row in rows] == ["014320", "002112", "007872", "007474"]
    assert rows[0]["market_value"] == 36881.55
    assert rows[0]["pnl_amount"] == 26165.63
    assert rows[0]["pnl_pct"] == 244.18
    assert rows[0]["field_confidence"]["code"] == "medium"
    assert rows[0]["field_confidence"]["market_value"] == "high"
    assert rows[3]["name"] == "华夏创业板成长ETF联接A"
    assert "金选" not in rows[3]["name"]


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
    assert holdings["portfolio_summary"]["status"] == "empty"


def test_xueqiu_name_only_snapshot_resolves_rows_from_list_layout() -> None:
    service = _service()
    text = """
    原日积月累
    安信灵活配置混合A
    更多数据>
    5,790.33
    -69.92
    -470.27
    持有金额(元)
    日收益(06-25)
    累计收益(元)
    易方达安盈回报混合
    更多数据>
    5,735.07
    +172.91
    +4,024.63
    持有金额(元)
    日收益(06-25)
    累计收益(元)
    """

    preview = service.preview_import(source_platform="xueqiu", ocr_text=text)
    rows = preview["candidates"]

    assert preview["status"] == "completed"
    assert [row["code"] for row in rows] == ["750001", "001603"]
    assert rows[0]["name"] == "安信灵活配置混合A"
    assert rows[0]["market_value"] == 5790.33
    assert rows[0]["pnl_amount"] == -470.27
    assert rows[0]["as_of_date"] == "2026-06-25"
    assert rows[1]["market_value"] == 5735.07
    assert rows[1]["pnl_amount"] == 4024.63
    assert all("雪球列表未展示份额" in " ".join(row["warnings"]) for row in rows)


def test_xueqiu_name_aliases_resolve_common_public_catalog_differences() -> None:
    service = _service()
    text = """
    原日积月累
    易方达中证海外中国互联网50ETF联接（QDII）A(人民币)
    更多数据>
    1,567.47
    +12.00
    +45.00
    持有金额(元)
    日收益(06-25)
    累计收益(元)
    国富大中华精选混合(QDII)人民币
    更多数据>
    9,829.93
    -11.00
    +21.00
    持有金额(元)
    日收益(06-25)
    累计收益(元)
    万家新利混合
    更多数据>
    9,386.85
    +8.00
    +18.00
    持有金额(元)
    日收益(06-25)
    累计收益(元)
    中欧价值智选回报A
    更多数据>
    6,491.14
    +7.00
    +17.00
    持有金额(元)
    日收益(06-25)
    累计收益(元)
    兴全沪深300指数增强（LOF）A
    更多数据>
    539.00
    +1.00
    +2.00
    持有金额(元)
    日收益(06-25)
    累计收益(元)
    """

    preview = service.preview_import(source_platform="xueqiu", ocr_text=text)
    rows = preview["candidates"]

    assert [row["code"] for row in rows] == ["006327", "000934", "519191", "166019", "163407"]
    assert rows[0]["name"] == "易方达中证海外互联网50ETF联接(QDII)A"
    assert rows[1]["name"] == "国富大中华精选混合"
    assert rows[4]["name"] == "兴全沪深300指数(LOF)A"


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


def test_confirm_import_reports_replace_change_summary() -> None:
    service = _service()
    service.confirm_import(
        source_platform="alipay",
        holdings=[
            {
                "code": "021528",
                "name": "财通成长优选混合C",
                "market_value": 1000.0,
                "units": 100.0,
                "cost_amount": 900.0,
                "pnl_amount": 100.0,
                "pnl_pct": 11.11,
                "latest_nav": 10.0,
                "as_of_date": "2026-06-24",
            },
            {
                "code": "110022",
                "name": "易方达消费行业股票",
                "market_value": 2000.0,
                "units": 200.0,
                "cost_amount": 1800.0,
                "pnl_amount": 200.0,
                "pnl_pct": 11.11,
                "latest_nav": 10.0,
                "as_of_date": "2026-06-24",
            },
        ],
    )

    result = service.confirm_import(
        source_platform="alipay",
        holdings=[
            {
                "code": "021528",
                "name": "财通成长优选混合C",
                "market_value": 1300.0,
                "units": 100.0,
                "cost_amount": 900.0,
                "pnl_amount": 400.0,
                "pnl_pct": 44.44,
                "latest_nav": 13.0,
                "as_of_date": "2026-06-25",
            }
        ],
    )
    summary = result["change_summary"]
    holdings = service.list_holdings()

    assert summary["mode"] == "replace"
    assert summary["new_count"] == 0
    assert summary["updated_count"] == 1
    assert summary["removed_count"] == 1
    assert summary["removed_codes"] == ["110022"]
    assert summary["updated"][0]["code"] == "021528"
    assert "market_value" in summary["updated"][0]["fields"]
    assert "pnl_amount" in summary["updated"][0]["fields"]
    assert holdings["total"] == 1
    assert holdings["items"][0]["code"] == "021528"
    assert holdings["items"][0]["market_value"] == 1300.0


def test_same_fund_can_remain_separate_by_platform_but_aggregate_globally() -> None:
    service = _service()
    service.confirm_import(
        source_platform="alipay",
        holdings=[
            {
                "code": "021528",
                "name": "财通成长优选混合C",
                "market_value": 1000.0,
                "units": 100.0,
                "cost_amount": 900.0,
                "pnl_amount": 100.0,
                "latest_nav": 10.0,
                "as_of_date": "2026-06-24",
            }
        ],
    )
    service.confirm_import(
        source_platform="jd_finance",
        holdings=[
            {
                "code": "021528",
                "name": "财通成长优选混合C",
                "market_value": 2500.0,
                "units": 200.0,
                "cost_amount": 2300.0,
                "pnl_amount": 200.0,
                "latest_nav": 12.5,
                "as_of_date": "2026-06-25",
            }
        ],
    )

    holdings = service.list_holdings()
    aggregate = holdings["aggregated_by_code"][0]

    assert holdings["total"] == 2
    assert aggregate["code"] == "021528"
    assert aggregate["market_value"] == 3500.0
    assert aggregate["units"] == 300.0
    assert aggregate["cost_amount"] == 3200.0
    assert aggregate["pnl_amount"] == 300.0
    assert aggregate["pnl_pct"] == 9.38
    assert aggregate["cost_unit_price"] == 10.6667
    assert aggregate["latest_nav"] == 12.5
    assert aggregate["as_of_date"] == "2026-06-25"
    assert len(aggregate["source_breakdown"]) == 2


def test_list_holdings_returns_portfolio_concentration_summary() -> None:
    service = _service()
    service.confirm_import(
        source_platform="alipay",
        holdings=[
            {
                "code": "021528",
                "name": "财通成长优选混合C",
                "market_value": 30000.0,
                "units": 3000.0,
                "cost_amount": 24000.0,
                "pnl_amount": 6000.0,
            },
            {
                "code": "110022",
                "name": "易方达消费行业股票",
                "market_value": 5000.0,
                "units": 500.0,
                "cost_amount": 5200.0,
                "pnl_amount": -200.0,
            },
        ],
    )
    service.confirm_import(
        source_platform="jd_finance",
        holdings=[
            {
                "code": "501018",
                "name": "南方原油A",
                "market_value": 5000.0,
                "cost_amount": 4800.0,
                "pnl_amount": 200.0,
            }
        ],
    )

    holdings = service.list_holdings()
    summary = holdings["portfolio_summary"]
    concentration = summary["concentration"]

    assert summary["status"] == "completed"
    assert summary["holding_count"] == 3
    assert summary["product_count"] == 3
    assert summary["platform_count"] == 2
    assert summary["total_market_value"] == 40000.0
    assert summary["total_cost_amount"] == 34000.0
    assert summary["total_pnl_amount"] == 6000.0
    assert summary["pnl_pct"] == 17.65
    assert summary["amount_privacy_sensitive"] is True
    assert concentration["status"] == "high"
    assert concentration["top_weight_pct"] == 75.0
    assert concentration["top3_weight_pct"] == 100.0
    assert concentration["top_positions"][0]["code"] == "021528"
    assert concentration["top_positions"][0]["weight_pct"] == 75.0
    assert "single_position_extreme" in summary["risk_flags"]
    assert "top3_concentration_extreme" in summary["risk_flags"]
    assert summary["by_platform"][0]["key"] == "alipay"
    assert summary["by_platform"][0]["weight_pct"] == 87.5
    assert summary["data_quality"]["market_value_coverage_pct"] == 100.0
    assert summary["data_quality"]["units_coverage_pct"] == 66.67


if __name__ == "__main__":
    for name, func in sorted(globals().items()):
        if name.startswith("test_") and callable(func):
            func()
