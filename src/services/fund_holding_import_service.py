# -*- coding: utf-8 -*-
"""基金持仓截图导入与确认服务。"""

from __future__ import annotations

import logging
import re
import tempfile
from dataclasses import dataclass
from datetime import date, datetime
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from src.repositories.fund_repo import DEFAULT_FUND_LEDGER_COLOR, FundRepository
from src.services.fund_service import FundService, normalize_fund_code

logger = logging.getLogger(__name__)


FUND_HOLDING_PREVIEW_SCHEMA_VERSION = "fund_holding_import_preview_v1"
FUND_HOLDING_CONFIRM_SCHEMA_VERSION = "fund_holding_confirm_v1"
FUND_HOLDING_SNAPSHOT_SCHEMA_VERSION = "fund_holding_snapshot_v1"

HOLDING_ALLOWED_MIME = frozenset({"image/jpeg", "image/png", "image/webp"})
HOLDING_MAX_IMAGE_BYTES = 8 * 1024 * 1024
HOLDING_MAX_IMAGE_COUNT = 6
HOLDING_MAX_TOTAL_IMAGE_BYTES = 30 * 1024 * 1024

PLATFORM_LABELS = {
    "alipay": "支付宝",
    "jd_finance": "京东金融",
    "xueqiu": "雪球",
    "fund_e_account": "基金E账户",
    "other": "其他平台",
}

PLATFORM_LEDGER_NAMES = {
    "alipay": "支付宝账本",
    "jd_finance": "京东金融账本",
    "xueqiu": "雪球账本",
    "fund_e_account": "基金E账户账本",
    "other": "基金持仓账本",
}

_IMAGE_SIGNATURES = {
    "image/jpeg": (b"\xff\xd8\xff",),
    "image/png": (b"\x89PNG\r\n\x1a\n",),
    "image/webp": (b"RIFF",),
}


class OCREngineUnavailable(RuntimeError):
    """Raised when optional local OCR dependencies are not installed."""


@dataclass
class HoldingImageInput:
    content: bytes
    mime_type: str
    filename: str = "upload"


@dataclass
class OCRTextLine:
    text: str
    x_center: float
    y_center: float
    x_min: float
    y_min: float
    x_max: float
    y_max: float
    score: Optional[float] = None


def normalize_source_platform(value: str | None) -> str:
    raw = (value or "other").strip().lower().replace("-", "_")
    aliases = {
        "jd": "jd_finance",
        "jingdong": "jd_finance",
        "danjuan": "xueqiu",
        "fund_eaccount": "fund_e_account",
        "fund_e": "fund_e_account",
    }
    return aliases.get(raw, raw if raw in PLATFORM_LABELS else "other")


def _verify_image(content: bytes, mime_type: str) -> None:
    if not content:
        raise ValueError("图片内容为空")
    if len(content) > HOLDING_MAX_IMAGE_BYTES:
        raise ValueError(f"单张图片超过 {HOLDING_MAX_IMAGE_BYTES // (1024 * 1024)}MB 限制")
    mime = (mime_type or "").split(";")[0].strip().lower()
    if mime not in HOLDING_ALLOWED_MIME:
        raise ValueError(f"不支持的图片类型: {mime}。允许: {sorted(HOLDING_ALLOWED_MIME)}")
    if len(content) < 12:
        raise ValueError("图片文件过小或损坏")
    if mime == "image/webp":
        if content[:4] != b"RIFF" or content[8:12] != b"WEBP":
            raise ValueError("文件内容与声明的类型 image/webp 不匹配")
        return
    if not any(content.startswith(signature) for signature in _IMAGE_SIGNATURES[mime]):
        raise ValueError(f"文件内容与声明的类型 {mime} 不匹配")


def _image_suffix(mime_type: str) -> str:
    if mime_type == "image/png":
        return ".png"
    if mime_type == "image/webp":
        return ".webp"
    return ".jpg"


def _rapidocr_result_to_text(result: Any) -> str:
    if result is None:
        return ""
    if hasattr(result, "txts"):
        txts = getattr(result, "txts")
        if isinstance(txts, (list, tuple)):
            return "\n".join(str(item) for item in txts if item)
    if isinstance(result, tuple) and result:
        return _rapidocr_result_to_text(result[0])
    if isinstance(result, list):
        lines: List[str] = []
        for item in result:
            if isinstance(item, str):
                lines.append(item)
            elif isinstance(item, (list, tuple)) and len(item) >= 2:
                text = item[1]
                if isinstance(text, str):
                    lines.append(text)
        return "\n".join(lines)
    return str(result)


def _rapidocr_result_to_text_and_lines(result: Any) -> Tuple[str, List[OCRTextLine]]:
    text = _rapidocr_result_to_text(result)
    boxes = getattr(result, "boxes", None)
    txts = getattr(result, "txts", None)
    scores = getattr(result, "scores", None)
    if boxes is None or txts is None:
        return text, []

    lines: List[OCRTextLine] = []
    try:
        for index, raw_text in enumerate(txts):
            line_text = str(raw_text or "").strip()
            if not line_text:
                continue
            box = boxes[index]
            points = list(box)
            xs = [float(point[0]) for point in points]
            ys = [float(point[1]) for point in points]
            score = None
            if isinstance(scores, (list, tuple)) and index < len(scores):
                try:
                    score = float(scores[index])
                except (TypeError, ValueError):
                    score = None
            lines.append(
                OCRTextLine(
                    text=line_text,
                    x_center=sum(xs) / len(xs),
                    y_center=sum(ys) / len(ys),
                    x_min=min(xs),
                    y_min=min(ys),
                    x_max=max(xs),
                    y_max=max(ys),
                    score=score,
                )
            )
    except Exception as exc:  # noqa: BLE001
        logger.debug("RapidOCR 坐标结果解析失败: %s", exc)
        return text, []
    return text, sorted(lines, key=lambda item: (item.y_center, item.x_center))


@lru_cache(maxsize=1)
def _get_rapidocr_engine() -> Any:
    try:
        from rapidocr import RapidOCR  # type: ignore
    except Exception as exc:  # noqa: BLE001
        raise OCREngineUnavailable("未安装 RapidOCR，本地 OCR 暂不可用") from exc
    return RapidOCR()


def extract_holding_ocr_payload_from_images(
    images: Sequence[HoldingImageInput],
    *,
    source_platform: str = "other",
) -> Tuple[str, List[str], List[Dict[str, Any]]]:
    if not images:
        return "", [], []
    if len(images) > HOLDING_MAX_IMAGE_COUNT:
        raise ValueError(f"一次最多上传 {HOLDING_MAX_IMAGE_COUNT} 张截图")
    total_size = sum(len(item.content) for item in images)
    if total_size > HOLDING_MAX_TOTAL_IMAGE_BYTES:
        raise ValueError(f"图片总大小超过 {HOLDING_MAX_TOTAL_IMAGE_BYTES // (1024 * 1024)}MB 限制")
    for item in images:
        _verify_image(item.content, item.mime_type)

    engine = _get_rapidocr_engine()
    texts: List[str] = []
    limitations: List[str] = []
    layout_rows: List[Dict[str, Any]] = []
    for index, item in enumerate(images, start=1):
        suffix = _image_suffix(item.mime_type)
        try:
            with tempfile.NamedTemporaryFile(suffix=suffix, delete=True) as handle:
                handle.write(item.content)
                handle.flush()
                result = engine(handle.name)
            text, lines = _rapidocr_result_to_text_and_lines(result)
            if text.strip():
                texts.append(text)
                layout_rows.extend(_extract_layout_holding_rows(lines, source_platform=source_platform))
            else:
                limitations.append(f"第 {index} 张截图未识别出文字")
        except Exception as exc:  # noqa: BLE001
            logger.warning("基金持仓 OCR 失败: file=%s error=%s", item.filename, exc)
            limitations.append(f"第 {index} 张截图 OCR 失败")
    return "\n".join(texts), limitations, layout_rows


def extract_holding_text_from_images(images: Sequence[HoldingImageInput]) -> Tuple[str, List[str]]:
    text, limitations, _ = extract_holding_ocr_payload_from_images(images)
    return text, limitations


def _clean_name(value: str) -> Optional[str]:
    text = re.sub(r"\d{6}", " ", value)
    text = re.sub(r"[+\-]?\d+(?:,\d{3})*(?:\.\d+)?%?", " ", text)
    text = re.sub(r"(基金代码|产品代码|代码|名称|基金名称|持有|持仓|市值|金额|收益|净值|份额|成本|可用)", " ", text)
    text = re.sub(r"[\s:：|｜,，;；/]+", " ", text).strip()
    matches = re.findall(r"[\u4e00-\u9fa5A-Za-z0-9（）()\-]{2,40}", text)
    if not matches:
        return None
    name = max(matches, key=len).strip()
    return name[:60] if name else None


def _parse_number_token(token: str | None) -> Optional[float]:
    if not token:
        return None
    text = token.strip().replace(",", "").replace("，", "")
    multiplier = 1.0
    if text.endswith("%"):
        text = text[:-1]
    if text.endswith("万"):
        multiplier = 10000.0
        text = text[:-1]
    elif text.endswith("亿"):
        multiplier = 100000000.0
        text = text[:-1]
    try:
        return float(text) * multiplier
    except ValueError:
        return None


def _find_labeled_number(text: str, labels: Iterable[str], *, percent: bool = False) -> Optional[float]:
    number = r"([+\-]?\d+(?:,\d{3})*(?:\.\d+)?(?:万|亿|%)?)"
    for label in labels:
        pattern = rf"{label}\s*[:：]?\s*{number}"
        match = re.search(pattern, text)
        if match:
            value = _parse_number_token(match.group(1))
            if value is not None:
                return value
    if percent:
        match = re.search(r"([+\-]?\d+(?:\.\d+)?)\s*%", text)
        if match:
            return _parse_number_token(match.group(1))
    return None


def _parse_as_of_date(text: str) -> Optional[str]:
    patterns = [
        r"(\d{4})[-/.年](\d{1,2})[-/.月](\d{1,2})",
        r"截至\s*(\d{1,2})[-/.月](\d{1,2})",
        r"\((\d{1,2})[-/.月](\d{1,2})\)",
    ]
    for pattern in patterns:
        match = re.search(pattern, text)
        if not match:
            continue
        groups = match.groups()
        try:
            if len(groups) == 3:
                parsed = date(int(groups[0]), int(groups[1]), int(groups[2]))
            else:
                today = date.today()
                parsed = date(today.year, int(groups[0]), int(groups[1]))
            return parsed.isoformat()
        except ValueError:
            continue
    return None


def _infer_cost_from_holding_pnl(
    market_value: Optional[float],
    pnl_amount: Optional[float],
    pnl_pct: Optional[float],
) -> Optional[float]:
    if market_value is None or pnl_amount is None or pnl_pct is None:
        return None
    cost = market_value - pnl_amount
    if cost <= 0:
        return None
    computed_pct = pnl_amount / cost * 100
    if abs(computed_pct - pnl_pct) > 0.15:
        return None
    return round(cost, 2)


def _iso_date_text(value: Any) -> Optional[str]:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    text = str(value).strip()
    return text or None


_HOLDING_LIST_NOISE_KEYWORDS = (
    "基金名称",
    "金额",
    "昨日收益",
    "持仓收益",
    "排序",
    "全部(",
    "股票型",
    "债券型",
    "混合型",
    "商品基金榜",
    "发现基金",
    "聚焦",
    "年内收益",
    "证监会",
    "资金监管",
    "资金安全险",
    "本页面",
    "基金销售服务",
    "过往业绩",
    "京东金融",
    "简单",
    "快捷",
    "安全",
)


def _is_plain_ocr_number(text: str) -> bool:
    value = (text or "").strip().replace("，", ",")
    return bool(re.fullmatch(r"[+\-]?\d+(?:,\d{3})*(?:\.\d+)?%?", value))


def _is_noise_holding_name_line(text: str) -> bool:
    value = (text or "").strip()
    if not value:
        return True
    if _is_plain_ocr_number(value):
        return True
    return any(keyword in value for keyword in _HOLDING_LIST_NOISE_KEYWORDS)


def _extract_layout_holding_rows(lines: Sequence[OCRTextLine], *, source_platform: str) -> List[Dict[str, Any]]:
    if not lines:
        return []
    name_header = next((line for line in lines if "基金名称" in line.text), None)
    amount_header = next((line for line in lines if "金额" in line.text and "收益" in line.text), None)
    profit_header = next((line for line in lines if "持仓收益" in line.text), None)
    if not name_header or not amount_header or not profit_header:
        return []

    header_y = max(name_header.y_center, amount_header.y_center, profit_header.y_center)
    name_col_right = (name_header.x_center + amount_header.x_center) / 2
    amount_col_left = name_col_right
    amount_col_right = (amount_header.x_center + profit_header.x_center) / 2
    profit_col_left = amount_col_right

    amount_anchors = [
        line
        for line in lines
        if line.y_center > header_y + 45
        and amount_col_left <= line.x_center <= amount_col_right
        and _is_plain_ocr_number(line.text)
        and not line.text.strip().startswith(("+", "-"))
        and "%" not in line.text
    ]
    amount_anchors.sort(key=lambda item: item.y_center)
    if not amount_anchors:
        return []

    rows: List[Dict[str, Any]] = []
    for index, anchor in enumerate(amount_anchors):
        previous_y = amount_anchors[index - 1].y_center if index > 0 else header_y
        next_y = amount_anchors[index + 1].y_center if index + 1 < len(amount_anchors) else anchor.y_center + 420
        row_top = (previous_y + anchor.y_center) / 2 if index > 0 else header_y
        row_bottom = (anchor.y_center + next_y) / 2
        row_lines = [line for line in lines if row_top < line.y_center < row_bottom]

        name_parts = [
            line.text.strip()
            for line in sorted(row_lines, key=lambda item: (item.y_center, item.x_center))
            if line.x_center < name_col_right and not _is_noise_holding_name_line(line.text)
        ]
        name = "".join(name_parts).strip()
        if not name:
            continue

        amount_lines = [
            line
            for line in sorted(row_lines, key=lambda item: item.y_center)
            if amount_col_left <= line.x_center <= amount_col_right and _is_plain_ocr_number(line.text)
        ]
        profit_lines = [
            line
            for line in sorted(row_lines, key=lambda item: item.y_center)
            if line.x_center >= profit_col_left and _is_plain_ocr_number(line.text)
        ]
        market_value = _parse_number_token(anchor.text)
        yesterday_pnl = next(
            (
                _parse_number_token(line.text)
                for line in amount_lines
                if line.y_center > anchor.y_center and line.text.strip().startswith(("+", "-"))
            ),
            None,
        )
        pnl_amount = next(
            (
                _parse_number_token(line.text)
                for line in profit_lines
                if "%" not in line.text and line.text.strip().startswith(("+", "-"))
            ),
            None,
        )
        pnl_pct = next((_parse_number_token(line.text) for line in profit_lines if "%" in line.text), None)
        cost_amount = _infer_cost_from_holding_pnl(market_value, pnl_amount, pnl_pct)
        warnings = ["截图未展示基金代码，代码由基金名称反查，请确认"]
        if yesterday_pnl is not None:
            warnings.append("已识别昨日收益但当前持仓快照暂不入库该字段")
        if cost_amount is not None:
            warnings.append("成本由截图市值与持仓收益反推，请确认")
        rows.append(
            {
                "code": "",
                "name": name[:80],
                "units": None,
                "available_units": None,
                "market_value": market_value,
                "cost_amount": cost_amount,
                "pnl_amount": pnl_amount,
                "pnl_pct": pnl_pct,
                "latest_nav": None,
                "as_of_date": None,
                "confidence": "low",
                "source_platform": source_platform,
                "source_channel": "ocr_preview",
                "raw_index": len(rows),
                "warnings": warnings,
            }
        )
    return rows


_XUEQIU_TEXT_STOP_KEYWORDS = (
    "原日积月累",
    "持有金额",
    "日收益",
    "累计收益",
    "升级投顾",
    "卖出",
    "监管要求",
    "服务已关停",
    "组合提醒",
    "有疑问请咨询客服",
)


def _clean_xueqiu_name_line(value: str) -> str:
    text = (value or "").strip()
    text = re.sub(r"更多数据.*$", "", text)
    text = re.sub(r"[>＞]+$", "", text).strip()
    return text


def _is_xueqiu_stop_line(value: str) -> bool:
    text = (value or "").strip()
    if not text:
        return True
    if _is_plain_ocr_number(text):
        return True
    if re.fullmatch(r"\d{1,2}:\d{2}.*", text):
        return True
    if re.fullmatch(r"\d{2,3}", text):
        return True
    if re.fullmatch(r"\[.*\]", text):
        return True
    return any(keyword in text for keyword in _XUEQIU_TEXT_STOP_KEYWORDS)


def _extract_xueqiu_text_holding_rows(text: str, *, source_platform: str) -> List[Dict[str, Any]]:
    lines = [line.strip() for line in (text or "").splitlines() if line.strip()]
    if not lines or not any("持有金额" in line for line in lines):
        return []
    rows: List[Dict[str, Any]] = []
    seen_names: set[str] = set()
    for index, line in enumerate(lines):
        if "持有金额" not in line:
            continue
        if index < 3:
            continue
        market_value = _parse_number_token(lines[index - 3])
        yesterday_pnl = _parse_number_token(lines[index - 2])
        pnl_amount = _parse_number_token(lines[index - 1])
        if market_value is None:
            continue

        name_parts: List[str] = []
        cursor = index - 4
        while cursor >= 0:
            raw_name_line = lines[cursor]
            cleaned = _clean_xueqiu_name_line(raw_name_line)
            if _is_xueqiu_stop_line(raw_name_line) and not cleaned:
                break
            if _is_xueqiu_stop_line(raw_name_line) and "更多数据" not in raw_name_line:
                break
            if cleaned and not _is_xueqiu_stop_line(cleaned):
                name_parts.insert(0, cleaned)
            cursor -= 1
            if len("".join(name_parts)) >= 80:
                break
        name = "".join(name_parts).strip()
        if len(name) < 2 or name in seen_names:
            continue
        seen_names.add(name)
        as_of_date = _parse_as_of_date("\n".join(lines[index : index + 3]))
        warnings = [
            "雪球列表未展示基金代码，代码由基金名称反查，请确认",
            "雪球列表未展示份额、成本和收益率，缺失字段请在候选中手动补充或后续编辑",
        ]
        if yesterday_pnl is not None:
            warnings.append("已识别日收益但当前持仓快照暂不入库该字段")
        rows.append(
            {
                "code": "",
                "name": name[:80],
                "units": None,
                "available_units": None,
                "market_value": market_value,
                "cost_amount": None,
                "pnl_amount": pnl_amount,
                "pnl_pct": None,
                "latest_nav": None,
                "as_of_date": as_of_date,
                "confidence": "low",
                "source_platform": source_platform,
                "source_channel": "ocr_preview",
                "raw_index": len(rows),
                "warnings": warnings,
            }
        )
    return rows


def parse_fund_holding_text(text: str, *, source_platform: str = "other") -> List[Dict[str, Any]]:
    lines = [line.strip() for line in (text or "").splitlines() if line.strip()]
    if not lines:
        return []
    candidates: List[Dict[str, Any]] = []
    seen: set[str] = set()
    for index, line in enumerate(lines):
        for match in re.finditer(r"(?<!\d)(\d{6})(?!\d)", line):
            raw_code = match.group(1)
            try:
                code = normalize_fund_code(raw_code)
            except ValueError:
                continue
            block_lines = [line]
            for next_line in lines[index + 1 : index + 8]:
                if re.search(r"(?<!\d)(\d{6})(?!\d)", next_line):
                    break
                block_lines.append(next_line)
            block = "\n".join(block_lines)
            prefix = line[: match.start()]
            suffix = line[match.end() :]
            name = _clean_name(prefix) or _clean_name(suffix)
            if not name and index > 0 and not re.search(r"(?<!\d)(\d{6})(?!\d)", lines[index - 1]):
                name = _clean_name(lines[index - 1])
            market_value = _find_labeled_number(block, ["持有金额", "持仓金额", "参考市值", "市值", "总金额", "金额"])
            units = _find_labeled_number(block, ["持有份额", "持仓份额", "可用份额", "份额", "持有数量", "持仓数量"])
            available_units = _find_labeled_number(block, ["可用份额", "可卖份额", "可赎回份额"])
            cost_amount = _find_labeled_number(block, ["持仓成本", "持有成本", "成本金额", "成本"])
            pnl_pct = _find_labeled_number(block, ["持有收益率", "收益率", "盈亏比例"], percent=True)
            pnl_amount = _find_labeled_number(block, ["持有收益", "持仓收益", "累计收益", "收益", "盈亏"])
            latest_nav = _find_labeled_number(block, ["最新净值", "单位净值", "净值"])
            as_of_date = _parse_as_of_date(block) or _parse_as_of_date(text)
            confidence = "high" if name and (market_value is not None or units is not None) else "medium" if name else "low"
            dedup_key = f"{source_platform}:{code}:{index}"
            if dedup_key in seen:
                continue
            seen.add(dedup_key)
            candidates.append(
                {
                    "code": code,
                    "name": name,
                    "units": units,
                    "available_units": available_units,
                    "market_value": market_value,
                    "cost_amount": cost_amount,
                    "pnl_amount": pnl_amount,
                    "pnl_pct": pnl_pct,
                    "latest_nav": latest_nav,
                    "as_of_date": as_of_date,
                    "confidence": confidence,
                    "source_platform": source_platform,
                    "source_channel": "ocr_preview",
                    "raw_index": len(candidates),
                    "warnings": [] if name else ["未识别到基金名称，请确认后再导入"],
                }
            )
            if len(candidates) >= 100:
                return candidates
    return candidates


def _compact_fund_name(value: str) -> str:
    text = (value or "").strip()
    text = text.replace("（", "(").replace("）", ")")
    text = re.sub(r"\s+", "", text)
    return text


def _remove_parenthetical(value: str) -> str:
    return re.sub(r"\([^)]*\)", "", value)


def _share_class_hint(value: str) -> Optional[str]:
    compact = _compact_fund_name(value)
    match = re.search(r"(?:\)|）)?([A-Z])$", compact, re.IGNORECASE)
    if not match:
        return None
    share = match.group(1).upper()
    return share if share in {"A", "B", "C", "D", "E", "F", "I"} else None


def _fund_name_search_queries(name: str) -> List[str]:
    compact = _compact_fund_name(name)
    variants = [compact]
    variants.append(_remove_parenthetical(compact))
    variants.append(compact.replace("纳指", "纳斯达克"))
    variants.append(_remove_parenthetical(compact.replace("纳指", "纳斯达克")))
    expanded: List[str] = []
    for value in variants:
        if not value:
            continue
        expanded.append(value)
        if len(value) > 1 and value[-1].upper() in {"A", "B", "C", "D", "E", "F", "I"}:
            expanded.append(value[:-1])
    return list(dict.fromkeys(item for item in expanded if len(item) >= 2))


def _score_resolved_fund_name(ocr_name: str, metadata: Any) -> float:
    candidate_name = _compact_fund_name(str(getattr(metadata, "name", "") or ""))
    if not candidate_name:
        return -100.0
    normalized_candidate = candidate_name.replace("纳斯达克", "纳指")
    normalized_ocr = _compact_fund_name(ocr_name).replace("纳斯达克", "纳指")
    normalized_root = _remove_parenthetical(normalized_ocr)
    share_hint = _share_class_hint(ocr_name)
    score = 0.0
    if normalized_ocr and normalized_ocr in normalized_candidate:
        score += 40
    if normalized_root and normalized_root in normalized_candidate:
        score += 28
    for token in re.findall(r"[\u4e00-\u9fa5A-Za-z0-9]+", normalized_root):
        if len(token) >= 2 and token in normalized_candidate:
            score += min(len(token), 10)
    if share_hint:
        if candidate_name.upper().endswith(share_hint):
            score += 30
        elif re.search(r"[A-Z]$", candidate_name.upper()):
            score -= 12
    else:
        upper_name = candidate_name.upper()
        if upper_name.endswith("A"):
            score += 10
        elif upper_name.endswith(("C", "F")):
            score -= 8
    if "美元" in candidate_name and "美元" not in ocr_name:
        score -= 20
    if "人民币" in candidate_name and "美元" not in ocr_name:
        score += 8
    return score


class FundHoldingImportService:
    """Preview and commit user-confirmed fund holdings from screenshots/OCR text."""

    def __init__(
        self,
        repo: Optional[FundRepository] = None,
        fund_service: Optional[FundService] = None,
    ):
        self.repo = repo or FundRepository()
        self.fund_service = fund_service or FundService(repo=self.repo)
        self._latest_nav_cache: Dict[str, Tuple[Optional[float], Optional[str]]] = {}

    def _latest_unit_nav_for_code(self, code: str) -> Tuple[Optional[float], Optional[str]]:
        if code in self._latest_nav_cache:
            return self._latest_nav_cache[code]
        provider = getattr(self.fund_service, "provider", None)
        unit_nav: Optional[float] = None
        nav_date: Optional[str] = None
        get_latest_quote = getattr(provider, "get_latest_quote", None)
        if callable(get_latest_quote):
            try:
                quote = get_latest_quote(code)
                raw_nav = getattr(quote, "unit_nav", None) if quote is not None else None
                if raw_nav is not None and float(raw_nav) > 0:
                    unit_nav = float(raw_nav)
                    nav_date = _iso_date_text(getattr(quote, "nav_date", None))
            except Exception as exc:  # noqa: BLE001
                logger.warning("基金最新净值反查失败: code=%s error=%s", code, exc)
        if unit_nav is None:
            get_nav_records = getattr(provider, "get_nav_records", None)
            if callable(get_nav_records):
                try:
                    records = get_nav_records(code)
                    for record in reversed(records or []):
                        raw_nav = record.get("unit_nav") if isinstance(record, dict) else None
                        try:
                            parsed_nav = float(raw_nav)
                        except (TypeError, ValueError):
                            continue
                        if parsed_nav <= 0:
                            continue
                        unit_nav = parsed_nav
                        nav_date = _iso_date_text(record.get("date") if isinstance(record, dict) else None)
                        break
                except Exception as exc:  # noqa: BLE001
                    logger.warning("基金历史净值反查失败: code=%s error=%s", code, exc)
        self._latest_nav_cache[code] = (unit_nav, nav_date)
        return self._latest_nav_cache[code]

    def _complete_candidate_from_public_nav(self, candidate: Dict[str, Any]) -> None:
        code = str(candidate.get("code") or "")
        market_value = candidate.get("market_value")
        if not re.fullmatch(r"\d{6}", code) or market_value is None:
            return
        try:
            market_value_float = float(market_value)
        except (TypeError, ValueError):
            return
        if market_value_float <= 0:
            return
        unit_nav, nav_date = self._latest_unit_nav_for_code(code)
        if unit_nav is None or unit_nav <= 0:
            return
        if candidate.get("latest_nav") is None:
            candidate["latest_nav"] = round(unit_nav, 4)
        if candidate.get("units") is None:
            candidate["units"] = round(market_value_float / unit_nav, 2)
            warnings = list(candidate.get("warnings") or [])
            if nav_date:
                warnings.append(f"份额由市值 ÷ 公开单位净值 {unit_nav:g}（{nav_date}）反推，请确认")
            else:
                warnings.append(f"份额由市值 ÷ 公开单位净值 {unit_nav:g} 反推，请确认")
            candidate["warnings"] = list(dict.fromkeys(item for item in warnings if item))

    def _resolve_fund_by_name(self, name: str) -> Tuple[Optional[Any], List[str]]:
        candidates: Dict[str, Any] = {}
        warnings: List[str] = []
        provider = getattr(self.fund_service, "provider", None)
        search = getattr(provider, "search_funds", None)
        if not callable(search):
            return None, ["基金名称反查服务不可用，请手动确认代码"]
        for query in _fund_name_search_queries(name):
            try:
                for item in search(query, limit=10):
                    code = str(getattr(item, "code", "") or "").zfill(6)
                    if re.fullmatch(r"\d{6}", code):
                        candidates[code] = item
            except Exception as exc:  # noqa: BLE001
                logger.warning("基金名称反查失败: query=%s error=%s", query, exc)
                warnings.append("基金名称反查部分失败，请确认代码")
        if not candidates:
            return None, warnings + ["截图未展示基金代码，且名称反查未命中，请手动补充代码"]
        ranked = sorted(
            candidates.values(),
            key=lambda item: (_score_resolved_fund_name(name, item), str(getattr(item, "code", "") or "")),
            reverse=True,
        )
        return ranked[0], warnings

    def _resolve_layout_candidates(self, rows: Sequence[Dict[str, Any]], *, source_platform: str) -> List[Dict[str, Any]]:
        resolved: List[Dict[str, Any]] = []
        for row in rows:
            candidate = dict(row)
            candidate["source_platform"] = source_platform
            name = str(candidate.get("name") or "").strip()
            metadata, warnings = self._resolve_fund_by_name(name)
            candidate_warnings = list(candidate.get("warnings") or [])
            candidate_warnings.extend(warnings)
            if metadata is not None:
                candidate["code"] = str(getattr(metadata, "code", "") or "").zfill(6)
                candidate["name"] = str(getattr(metadata, "name", "") or name) or name
                candidate["confidence"] = "medium"
                candidate_warnings.append("基金代码由公开基金名录按截图名称反查，请确认后再覆盖入账")
            else:
                candidate["code"] = ""
                candidate["confidence"] = "low"
            candidate["warnings"] = list(dict.fromkeys(item for item in candidate_warnings if item))
            self._complete_candidate_from_public_nav(candidate)
            candidate["raw_index"] = len(resolved)
            resolved.append(candidate)
        return resolved

    def preview_import(
        self,
        *,
        source_platform: str,
        images: Optional[Sequence[HoldingImageInput]] = None,
        ocr_text: Optional[str] = None,
    ) -> Dict[str, Any]:
        platform = normalize_source_platform(source_platform)
        text_parts: List[str] = []
        limitations: List[str] = []
        layout_rows: List[Dict[str, Any]] = []
        if ocr_text and ocr_text.strip():
            text_parts.append(ocr_text.strip())
        if images:
            try:
                image_text, image_limitations, image_layout_rows = extract_holding_ocr_payload_from_images(
                    images,
                    source_platform=platform,
                )
                if image_text.strip():
                    text_parts.append(image_text.strip())
                limitations.extend(image_limitations)
                layout_rows.extend(image_layout_rows)
            except OCREngineUnavailable as exc:
                limitations.append(str(exc))
            except ValueError:
                raise
            except Exception as exc:  # noqa: BLE001
                logger.warning("基金持仓截图预览失败: %s", exc)
                limitations.append("截图 OCR 失败，请改用手动文本或稍后重试")
        full_text = "\n".join(text_parts)
        if platform == "xueqiu" and full_text.strip():
            layout_rows.extend(_extract_xueqiu_text_holding_rows(full_text, source_platform=platform))
        candidates = parse_fund_holding_text(full_text, source_platform=platform)
        for item in candidates:
            self._complete_candidate_from_public_nav(item)
        if layout_rows:
            seen_codes = {str(item.get("code") or "") for item in candidates if item.get("code")}
            seen_names = {str(item.get("name") or "") for item in candidates if item.get("name")}
            for item in self._resolve_layout_candidates(layout_rows, source_platform=platform):
                code = str(item.get("code") or "")
                name = str(item.get("name") or "")
                if code and code in seen_codes:
                    continue
                if name and name in seen_names:
                    continue
                item["raw_index"] = len(candidates)
                candidates.append(item)
                if code:
                    seen_codes.add(code)
                if name:
                    seen_names.add(name)
        status = "completed" if candidates else "blocked" if images and not full_text.strip() else "partial"
        if not candidates:
            limitations.append("未解析到 6 位基金代码或可确认持仓行")
        return {
            "schema_version": FUND_HOLDING_PREVIEW_SCHEMA_VERSION,
            "status": status,
            "source_platform": platform,
            "source_platform_label": PLATFORM_LABELS[platform],
            "candidate_count": len(candidates),
            "candidates": candidates,
            "limitations": limitations,
        }

    def ensure_platform_ledger(self, source_platform: str) -> Dict[str, Any]:
        platform = normalize_source_platform(source_platform)
        name = PLATFORM_LEDGER_NAMES[platform]
        existing = self.repo.get_ledger_by_name(name)
        if existing is not None:
            payload = existing.to_dict()
            payload["fund_count"] = 0
            return payload
        return self.fund_service.create_ledger(
            name,
            DEFAULT_FUND_LEDGER_COLOR,
            account_type="platform_snapshot",
            purpose=f"{PLATFORM_LABELS[platform]} 当前持仓快照",
            notes="由基金持仓导入助手创建；仅保存用户确认后的当前持仓，不代表交易流水。",
        )

    def confirm_import(
        self,
        *,
        source_platform: str,
        holdings: Sequence[Dict[str, Any]],
        ledger_id: Optional[int] = None,
        replace: bool = True,
    ) -> Dict[str, Any]:
        platform = normalize_source_platform(source_platform)
        if ledger_id:
            ledger = self.repo.get_ledger(int(ledger_id))
            if ledger is None:
                raise ValueError("账本不存在或已停用")
            ledger_payload = ledger.to_dict()
        else:
            ledger_payload = self.ensure_platform_ledger(platform)
        target_ledger_id = int(ledger_payload["id"])
        normalized: List[Dict[str, Any]] = []
        skipped: List[Dict[str, str]] = []
        for row in holdings:
            try:
                code = normalize_fund_code(str(row.get("code") or ""))
            except ValueError:
                skipped.append({"code": str(row.get("code") or ""), "reason": "invalid_fund_code"})
                continue
            name = str(row.get("name") or "").strip() or None
            normalized.append(
                {
                    "code": code,
                    "name": name,
                    "units": row.get("units"),
                    "available_units": row.get("available_units"),
                    "market_value": row.get("market_value"),
                    "cost_amount": row.get("cost_amount"),
                    "pnl_amount": row.get("pnl_amount"),
                    "pnl_pct": row.get("pnl_pct"),
                    "latest_nav": row.get("latest_nav"),
                    "as_of_date": row.get("as_of_date"),
                    "confidence": "user_confirmed",
                    "source_channel": "platform_screenshot_user_confirmed",
                }
            )
            self.fund_service.add_to_pool(
                code,
                name=name,
                notes=f"{PLATFORM_LABELS[platform]} 持仓导入确认",
            )
        snapshots = self.repo.save_holding_snapshots(
            ledger_id=target_ledger_id,
            source_platform=platform,
            rows=normalized,
            replace=replace,
        )
        return {
            "schema_version": FUND_HOLDING_CONFIRM_SCHEMA_VERSION,
            "status": "completed",
            "source_platform": platform,
            "source_platform_label": PLATFORM_LABELS[platform],
            "ledger": ledger_payload,
            "confirmed_count": len(normalized),
            "skipped": skipped,
            "items": [item.to_dict() for item in snapshots],
            "limitations": [
                "该导入只代表用户确认后的当前持仓快照，不代表真实交易流水",
                "无法由截图字段或公开净值可靠推导的缺失字段保持为空",
            ],
        }

    def list_holdings(self, *, ledger_id: Optional[int] = None) -> Dict[str, Any]:
        rows = [item.to_dict() for item in self.repo.list_holding_snapshots(ledger_id=ledger_id)]
        aggregate: Dict[str, Dict[str, Any]] = {}
        for row in rows:
            code = row["code"]
            bucket = aggregate.setdefault(
                code,
                {
                    "code": code,
                    "name": row.get("name"),
                    "market_value": 0.0,
                    "units": 0.0,
                    "cost_amount": 0.0,
                    "pnl_amount": 0.0,
                    "source_breakdown": [],
                },
            )
            for field in ("market_value", "units", "cost_amount", "pnl_amount"):
                if row.get(field) is not None:
                    bucket[field] += float(row[field])
            bucket["source_breakdown"].append(
                {
                    "ledger_id": row.get("ledger_id"),
                    "source_platform": row.get("source_platform"),
                    "market_value": row.get("market_value"),
                    "units": row.get("units"),
                }
            )
        return {
            "schema_version": FUND_HOLDING_SNAPSHOT_SCHEMA_VERSION,
            "status": "completed",
            "items": rows,
            "aggregated_by_code": list(aggregate.values()),
            "total": len(rows),
            "ledger_id": ledger_id,
            "limitations": [
                "全部视图按基金代码聚合展示；各账本/平台下仍保留独立持仓行",
            ],
        }
