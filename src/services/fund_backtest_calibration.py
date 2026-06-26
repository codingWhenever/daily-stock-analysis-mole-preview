# -*- coding: utf-8 -*-
"""Aggregate fund NAV walk-forward backtests into a calibration center."""

from __future__ import annotations

from typing import Any, Callable, Dict, Iterable, List, Optional


SCHEMA_VERSION = "fund_backtest_calibration_v1"


def calibrate_fund_backtests(
    *,
    pool: Dict[str, Any],
    backtest_runner: Callable[[str], Dict[str, Any]],
    ledger_id: Optional[int] = None,
    fund_type: Optional[str] = None,
    codes: Optional[List[str]] = None,
    lookback_days: int = 252,
    eval_window_days: int = 60,
    rebalance_interval_days: int = 20,
    initial_cash: float = 10000.0,
) -> Dict[str, Any]:
    """Run and aggregate single-fund backtests without mutating strategy params."""

    requested_codes = list(dict.fromkeys(codes or []))
    requested_code_set = set(requested_codes)
    pool_items = [
        item for item in pool.get("items", [])
        if isinstance(item, dict)
    ]
    scoped_items = [
        item for item in pool_items
        if (ledger_id is None or item.get("ledger_id") == ledger_id)
        and (not fund_type or item.get("fund_type") == fund_type)
    ]
    items = [
        item for item in scoped_items
        if not requested_code_set or str(item.get("code") or "") in requested_code_set
    ]
    pool_codes = {str(item.get("code")) for item in pool_items if item.get("code")}
    scoped_codes = {str(item.get("code")) for item in scoped_items if item.get("code")}
    missing_pool_codes = [code for code in requested_codes if code not in pool_codes]
    filtered_out_codes = [
        code for code in requested_codes
        if code in pool_codes and code not in scoped_codes
    ]
    ledger_lookup = {
        int(ledger["id"]): ledger
        for ledger in pool.get("ledgers", [])
        if isinstance(ledger, dict) and ledger.get("id") is not None
    }

    by_fund: List[Dict[str, Any]] = []
    limitations = [
        "第一版只聚合单基金 NAV walk-forward 回测结果，不回写信号参数、不自动调阈值",
        "校准仅使用本地已缓存公开净值和当前静态费用假设，不读取真实账户成本或申赎确认日",
        "暂未接入真实申赎确认日、历史费率变动、持有期赎回费阶梯、分红再投、同类分位历史、市场状态分层或真实账户成本",
    ]
    if missing_pool_codes:
        limitations.append(f"请求代码不在当前基金池中，已跳过：{', '.join(missing_pool_codes)}")
    if filtered_out_codes:
        limitations.append(f"请求代码不在当前筛选范围中，已跳过：{', '.join(filtered_out_codes)}")
    if not items:
        limitations.append("当前筛选范围没有可校准的基金池条目")

    for item in items:
        code = str(item.get("code") or "")
        if not code:
            continue
        try:
            result = backtest_runner(code)
        except Exception as exc:  # noqa: BLE001 - 单只失败不应阻断校准中心。
            by_fund.append(_failed_fund_row(item, str(exc)))
            continue
        by_fund.append(_fund_row(item, result))

    status = _scope_status(by_fund)
    sample_funds = len(by_fund)
    completed_funds = sum(1 for row in by_fund if row.get("status") == "completed")
    sample_signals = sum(int(row.get("signal_count") or 0) for row in by_fund if row.get("status") == "completed")
    calibration_status = _calibration_status(
        sample_funds=sample_funds,
        completed_funds=completed_funds,
        sample_signals=sample_signals,
    )

    scope = {
        "ledger_id": ledger_id,
        "fund_type": fund_type,
        "codes": [str(item.get("code")) for item in items if item.get("code")],
        "requested_codes": requested_codes,
        "lookback_days": int(lookback_days),
        "eval_window_days": int(eval_window_days),
        "rebalance_interval_days": int(rebalance_interval_days),
        "initial_cash": _round_money(initial_cash),
    }

    return {
        "schema_version": SCHEMA_VERSION,
        "status": status,
        "scope": scope,
        "calibration_status": calibration_status,
        "by_fund": by_fund,
        "by_ledger": _aggregate_by_ledger(by_fund, ledger_lookup, initial_cash),
        "by_fund_type": _aggregate_by_fund_type(by_fund, initial_cash),
        "limitations": limitations,
    }


def _fund_row(pool_item: Dict[str, Any], result: Dict[str, Any]) -> Dict[str, Any]:
    summary = result.get("summary") if isinstance(result.get("summary"), dict) else {}
    signals = result.get("signals") if isinstance(result.get("signals"), list) else []
    status = str(result.get("status") or "unknown")
    completed = status == "completed"
    signal_count = int(summary.get("signal_count") or 0) if completed else 0

    row = {
        "code": str(result.get("code") or pool_item.get("code") or ""),
        "name": result.get("name") or pool_item.get("name"),
        "fund_type": result.get("fund_type") or pool_item.get("fund_type"),
        "ledger_id": pool_item.get("ledger_id"),
        "status": status,
        "sample_days": int(summary.get("sample_days") or 0),
        "signal_count": signal_count,
        "action_hit_rate_pct": summary.get("hit_rate_pct") if completed else None,
        "avg_forward_return_pct": _mean_signal_field(signals, "fund_forward_return_pct") if completed else None,
        "avg_forward_drawdown_pct": _mean_signal_field(signals, "fund_forward_drawdown_pct") if completed else None,
        "max_drawdown_strategy_pct": summary.get("max_drawdown_strategy_pct") if completed else None,
        "max_drawdown_fund_pct": summary.get("max_drawdown_fund_pct") if completed else None,
        "total_fees": summary.get("total_fees") if completed else 0.0,
        "fee_drag_pct": summary.get("fee_drag_pct") if completed else None,
        "action_stats": _action_stats(signals if completed else []),
        "limitations": list(result.get("limitations") or []),
    }
    row["calibration_status"] = _calibration_status(
        sample_funds=1,
        completed_funds=1 if completed else 0,
        sample_signals=signal_count,
    )
    return row


def _failed_fund_row(pool_item: Dict[str, Any], error: str) -> Dict[str, Any]:
    row = {
        "code": str(pool_item.get("code") or ""),
        "name": pool_item.get("name"),
        "fund_type": pool_item.get("fund_type"),
        "ledger_id": pool_item.get("ledger_id"),
        "status": "failed",
        "sample_days": 0,
        "signal_count": 0,
        "action_hit_rate_pct": None,
        "avg_forward_return_pct": None,
        "avg_forward_drawdown_pct": None,
        "max_drawdown_strategy_pct": None,
        "max_drawdown_fund_pct": None,
        "total_fees": 0.0,
        "fee_drag_pct": None,
        "action_stats": {},
        "limitations": [f"单基金回测失败：{error}"],
    }
    row["calibration_status"] = _calibration_status(sample_funds=1, completed_funds=0, sample_signals=0)
    return row


def _aggregate_by_ledger(
    rows: List[Dict[str, Any]],
    ledger_lookup: Dict[int, Dict[str, Any]],
    initial_cash: float,
) -> List[Dict[str, Any]]:
    buckets: Dict[Optional[int], List[Dict[str, Any]]] = {}
    for row in rows:
        ledger = row.get("ledger_id")
        buckets.setdefault(int(ledger) if ledger is not None else None, []).append(row)

    result = []
    for key, bucket in sorted(buckets.items(), key=lambda item: (-1 if item[0] is None else item[0])):
        ledger = ledger_lookup.get(key) if key is not None else None
        result.append(_aggregate_rows(
            bucket,
            initial_cash=initial_cash,
            extra={
                "ledger_id": key,
                "ledger_name": ledger.get("name") if ledger else "未分账本",
            },
        ))
    return result


def _aggregate_by_fund_type(rows: List[Dict[str, Any]], initial_cash: float) -> List[Dict[str, Any]]:
    buckets: Dict[str, List[Dict[str, Any]]] = {}
    for row in rows:
        buckets.setdefault(str(row.get("fund_type") or "未知类型"), []).append(row)
    return [
        _aggregate_rows(bucket, initial_cash=initial_cash, extra={"fund_type": fund_type})
        for fund_type, bucket in sorted(buckets.items(), key=lambda item: item[0])
    ]


def _aggregate_rows(rows: List[Dict[str, Any]], *, initial_cash: float, extra: Dict[str, Any]) -> Dict[str, Any]:
    completed_rows = [row for row in rows if row.get("status") == "completed"]
    action_stats = _merge_action_stats(row.get("action_stats") for row in completed_rows)
    sample_signals = sum(int(row.get("signal_count") or 0) for row in completed_rows)
    total_fees = sum(_to_float(row.get("total_fees")) or 0.0 for row in completed_rows)
    completed_funds = len(completed_rows)

    payload = {
        **extra,
        "status": _scope_status(rows),
        "sample_funds": len(rows),
        "completed_funds": completed_funds,
        "sample_signals": sample_signals,
        "codes": [str(row.get("code")) for row in rows if row.get("code")],
        "action_hit_rate_pct": _hit_rate_from_action_stats(action_stats),
        "avg_forward_return_pct": _weighted_action_average(action_stats, "avg_forward_return_pct"),
        "avg_forward_drawdown_pct": _weighted_action_average(action_stats, "avg_forward_drawdown_pct"),
        "max_drawdown_strategy_pct": _min_optional(row.get("max_drawdown_strategy_pct") for row in completed_rows),
        "max_drawdown_fund_pct": _min_optional(row.get("max_drawdown_fund_pct") for row in completed_rows),
        "total_fees": _round_money(total_fees),
        "fee_drag_pct": _safe_percent(total_fees / (initial_cash * completed_funds) * 100) if completed_funds and initial_cash > 0 else None,
        "action_stats": action_stats,
    }
    payload["calibration_status"] = _calibration_status(
        sample_funds=len(rows),
        completed_funds=completed_funds,
        sample_signals=sample_signals,
    )
    return payload


def _scope_status(rows: List[Dict[str, Any]]) -> str:
    if not rows:
        return "insufficient"
    completed = sum(1 for row in rows if row.get("status") == "completed")
    if completed <= 0:
        return "insufficient"
    if completed < len(rows):
        return "partial"
    return "completed"


def _calibration_status(*, sample_funds: int, completed_funds: int, sample_signals: int) -> Dict[str, Any]:
    if completed_funds <= 0 or sample_signals < 8:
        status = "insufficient"
    elif completed_funds >= 8 and sample_signals >= 100:
        status = "strong"
    elif completed_funds >= 3 and sample_signals >= 30:
        status = "usable"
    else:
        status = "experimental"

    reasons = []
    if completed_funds <= 0:
        reasons.append("没有完成状态的单基金回测")
    if sample_signals < 8:
        reasons.append(f"可评估信号少于 8 个，目前 {sample_signals} 个")
    if status == "experimental":
        reasons.append("已有最低观察样本，但完成基金数或信号数仍不足以稳定校准参数")
    elif status == "usable":
        reasons.append("完成基金数不少于 3 且信号数不少于 30，可作为人工校准参考")
    elif status == "strong":
        reasons.append("完成基金数不少于 8 且信号数不少于 100，样本强度较高")

    return {
        "status": status,
        "sample_funds": int(sample_funds),
        "completed_funds": int(completed_funds),
        "sample_signals": int(sample_signals),
        "reasons": reasons,
    }


def _action_stats(signals: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    buckets: Dict[str, Dict[str, Any]] = {}
    for signal in signals:
        action = str(signal.get("action") or "unknown")
        bucket = buckets.setdefault(action, _new_action_bucket())
        _add_signal(bucket, signal)
    return {action: _finalize_action_bucket(bucket) for action, bucket in sorted(buckets.items())}


def _merge_action_stats(stats_items: Iterable[Any]) -> Dict[str, Dict[str, Any]]:
    merged: Dict[str, Dict[str, Any]] = {}
    for stats in stats_items:
        if not isinstance(stats, dict):
            continue
        for action, stat in stats.items():
            if not isinstance(stat, dict):
                continue
            bucket = merged.setdefault(str(action), _new_action_bucket())
            bucket["signal_count"] += int(stat.get("signal_count") or 0)
            bucket["wins"] += int(stat.get("wins") or 0)
            bucket["losses"] += int(stat.get("losses") or 0)
            bucket["neutral"] += int(stat.get("neutral") or 0)
            bucket["unavailable"] += int(stat.get("unavailable") or 0)
            bucket["total_fees"] += _to_float(stat.get("total_fees")) or 0.0
            _extend_weighted(bucket, "forward_returns", stat.get("avg_forward_return_pct"), stat.get("forward_return_count"))
            _extend_weighted(bucket, "forward_drawdowns", stat.get("avg_forward_drawdown_pct"), stat.get("forward_drawdown_count"))
    return {action: _finalize_action_bucket(bucket) for action, bucket in sorted(merged.items())}


def _new_action_bucket() -> Dict[str, Any]:
    return {
        "signal_count": 0,
        "wins": 0,
        "losses": 0,
        "neutral": 0,
        "unavailable": 0,
        "total_fees": 0.0,
        "forward_returns": [],
        "forward_drawdowns": [],
    }


def _add_signal(bucket: Dict[str, Any], signal: Dict[str, Any]) -> None:
    bucket["signal_count"] += 1
    outcome = str(signal.get("outcome") or "unavailable")
    if outcome in {"win", "loss", "neutral", "unavailable"}:
        key = {
            "win": "wins",
            "loss": "losses",
            "neutral": "neutral",
            "unavailable": "unavailable",
        }[outcome]
        bucket[key] += 1
    else:
        bucket["unavailable"] += 1
    bucket["total_fees"] += _to_float(signal.get("fee")) or 0.0
    forward_return = _to_float(signal.get("fund_forward_return_pct"))
    if forward_return is not None:
        bucket["forward_returns"].append(forward_return)
    forward_drawdown = _to_float(signal.get("fund_forward_drawdown_pct"))
    if forward_drawdown is not None:
        bucket["forward_drawdowns"].append(forward_drawdown)


def _extend_weighted(bucket: Dict[str, Any], key: str, average: Any, count: Any) -> None:
    value = _to_float(average)
    weight = int(count or 0)
    if value is None or weight <= 0:
        return
    bucket[key].extend([value] * weight)


def _finalize_action_bucket(bucket: Dict[str, Any]) -> Dict[str, Any]:
    evaluated = int(bucket["wins"]) + int(bucket["losses"])
    return {
        "signal_count": int(bucket["signal_count"]),
        "wins": int(bucket["wins"]),
        "losses": int(bucket["losses"]),
        "neutral": int(bucket["neutral"]),
        "unavailable": int(bucket["unavailable"]),
        "evaluated": evaluated,
        "hit_rate_pct": _safe_percent(bucket["wins"] / evaluated * 100) if evaluated else None,
        "avg_forward_return_pct": _mean(bucket["forward_returns"]),
        "avg_forward_drawdown_pct": _mean(bucket["forward_drawdowns"]),
        "forward_return_count": len(bucket["forward_returns"]),
        "forward_drawdown_count": len(bucket["forward_drawdowns"]),
        "total_fees": _round_money(bucket["total_fees"]),
    }


def _hit_rate_from_action_stats(stats: Dict[str, Dict[str, Any]]) -> Optional[float]:
    wins = sum(int(stat.get("wins") or 0) for stat in stats.values())
    losses = sum(int(stat.get("losses") or 0) for stat in stats.values())
    evaluated = wins + losses
    return _safe_percent(wins / evaluated * 100) if evaluated else None


def _weighted_action_average(stats: Dict[str, Dict[str, Any]], field: str) -> Optional[float]:
    values = []
    count_field = "forward_return_count" if field == "avg_forward_return_pct" else "forward_drawdown_count"
    for stat in stats.values():
        value = _to_float(stat.get(field))
        count = int(stat.get(count_field) or 0)
        if value is not None and count > 0:
            values.extend([value] * count)
    return _mean(values)


def _mean_signal_field(signals: List[Dict[str, Any]], field: str) -> Optional[float]:
    return _mean(_to_float(signal.get(field)) for signal in signals)


def _mean(values: Iterable[Optional[float]]) -> Optional[float]:
    usable = [value for value in values if value is not None]
    if not usable:
        return None
    return _safe_percent(sum(usable) / len(usable))


def _min_optional(values: Iterable[Any]) -> Optional[float]:
    usable = [_to_float(value) for value in values]
    usable = [value for value in usable if value is not None]
    if not usable:
        return None
    return _safe_percent(min(usable))


def _to_float(value: Any) -> Optional[float]:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    if result != result or result in {float("inf"), float("-inf")}:
        return None
    return result


def _safe_percent(value: Optional[float]) -> Optional[float]:
    if value is None:
        return None
    return round(float(value), 2)


def _round_money(value: Any) -> float:
    numeric = _to_float(value)
    return round(numeric or 0.0, 2)
