# -*- coding: utf-8 -*-
"""公募基金池与净值数据访问层。"""

from __future__ import annotations

import json
from datetime import date, datetime
from typing import Any, Dict, Iterable, List, Optional

import pandas as pd
from sqlalchemy import and_, delete, desc, select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from src.storage import (
    DatabaseManager,
    FundAnalysisSnapshot,
    FundHoldingSnapshot,
    FundLedger,
    FundNavDaily,
    FundPoolItem,
)

DEFAULT_FUND_LEDGER_COLOR = "#06B6D4"
FUND_LEDGER_PROFILE_LIMITS = {
    "account_type": 40,
    "purpose": 80,
    "risk_target": 40,
    "investment_horizon": 40,
    "rebalance_frequency": 40,
    "drawdown_tolerance": 40,
    "liquidity_need": 40,
    "investment_experience": 40,
    "preferred_fund_types": 160,
    "notes": 500,
}
FUND_LEDGER_NUMERIC_PROFILE_FIELDS = {
    "monthly_budget": (0.0, 10000000.0),
    "cash_reserve_months": (0.0, 120.0),
}
FUND_LEDGER_PROFILE_FIELDS = tuple(FUND_LEDGER_PROFILE_LIMITS.keys()) + tuple(FUND_LEDGER_NUMERIC_PROFILE_FIELDS.keys())


def _normalize_optional_text(value: Optional[str], *, field: str, max_length: int) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    if len(text) > max_length:
        raise ValueError(f"{field} 不能超过 {max_length} 个字符")
    return text


def _normalize_optional_float(value: Any, *, field: str, min_value: float, max_value: float) -> Optional[float]:
    if value is None:
        return None
    if isinstance(value, str) and not value.strip():
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field} 应为数字") from exc
    if parsed != parsed:
        return None
    if parsed < min_value or parsed > max_value:
        raise ValueError(f"{field} 应在 {min_value:g}-{max_value:g} 之间")
    return round(parsed, 2)


class FundRepository:
    """封装基金池、净值和分析快照的数据库操作。"""

    def __init__(self, db_manager: Optional[DatabaseManager] = None):
        self.db = db_manager or DatabaseManager.get_instance()

    def _ensure_default_ledger(self) -> FundLedger:
        with self.db.get_session() as session:
            existing = session.execute(
                select(FundLedger)
                .where(FundLedger.is_default.is_(True), FundLedger.active.is_(True))
                .order_by(FundLedger.sort_order.asc(), FundLedger.id.asc())
                .limit(1)
            ).scalar_one_or_none()
            if existing is not None:
                return existing

        def _write(session):
            existing = session.execute(
                select(FundLedger)
                .where(FundLedger.is_default.is_(True), FundLedger.active.is_(True))
                .order_by(FundLedger.sort_order.asc(), FundLedger.id.asc())
                .limit(1)
            ).scalar_one_or_none()
            if existing is not None:
                return existing.id
            by_name = session.execute(
                select(FundLedger).where(FundLedger.name == "全部基金").limit(1)
            ).scalar_one_or_none()
            if by_name is not None:
                by_name.is_default = True
                by_name.active = True
                by_name.updated_at = datetime.now()
                return by_name.id
            item = FundLedger(
                name="全部基金",
                color=DEFAULT_FUND_LEDGER_COLOR,
                sort_order=0,
                is_default=True,
                active=True,
                created_at=datetime.now(),
                updated_at=datetime.now(),
            )
            session.add(item)
            session.flush()
            return item.id

        ledger_id = int(self.db._run_write_transaction("ensure_default_fund_ledger", _write))
        with self.db.get_session() as session:
            ledger = session.execute(select(FundLedger).where(FundLedger.id == ledger_id)).scalar_one()
            return ledger

    def list_ledgers(self, active_only: bool = True) -> List[FundLedger]:
        self._ensure_default_ledger()
        with self.db.get_session() as session:
            statement = select(FundLedger).order_by(FundLedger.sort_order.asc(), FundLedger.created_at.asc())
            if active_only:
                statement = statement.where(FundLedger.active.is_(True))
            return list(session.execute(statement).scalars().all())

    def get_ledger(self, ledger_id: int, *, active_only: bool = True) -> Optional[FundLedger]:
        with self.db.get_session() as session:
            statement = select(FundLedger).where(FundLedger.id == int(ledger_id)).limit(1)
            if active_only:
                statement = statement.where(FundLedger.active.is_(True))
            return session.execute(statement).scalar_one_or_none()

    def get_ledger_by_name(self, name: str, *, active_only: bool = True) -> Optional[FundLedger]:
        normalized = (name or "").strip()
        if not normalized:
            return None
        with self.db.get_session() as session:
            statement = select(FundLedger).where(FundLedger.name == normalized).limit(1)
            if active_only:
                statement = statement.where(FundLedger.active.is_(True))
            return session.execute(statement).scalar_one_or_none()

    def create_ledger(
        self,
        *,
        name: str,
        color: str = DEFAULT_FUND_LEDGER_COLOR,
        account_type: Optional[str] = None,
        purpose: Optional[str] = None,
        risk_target: Optional[str] = None,
        investment_horizon: Optional[str] = None,
        rebalance_frequency: Optional[str] = None,
        drawdown_tolerance: Optional[str] = None,
        liquidity_need: Optional[str] = None,
        investment_experience: Optional[str] = None,
        monthly_budget: Optional[float] = None,
        cash_reserve_months: Optional[float] = None,
        preferred_fund_types: Optional[str] = None,
        notes: Optional[str] = None,
    ) -> FundLedger:
        name = (name or "").strip()
        if not name:
            raise ValueError("账本名称不能为空")
        if len(name) > 20:
            raise ValueError("账本名称不能超过 20 个字符")
        color = (color or DEFAULT_FUND_LEDGER_COLOR).strip()
        if not color.startswith("#") or len(color) not in {4, 7}:
            color = DEFAULT_FUND_LEDGER_COLOR
        profile = self._normalize_profile_updates(
            {
                "account_type": account_type,
                "purpose": purpose,
                "risk_target": risk_target,
                "investment_horizon": investment_horizon,
                "rebalance_frequency": rebalance_frequency,
                "drawdown_tolerance": drawdown_tolerance,
                "liquidity_need": liquidity_need,
                "investment_experience": investment_experience,
                "monthly_budget": monthly_budget,
                "cash_reserve_months": cash_reserve_months,
                "preferred_fund_types": preferred_fund_types,
                "notes": notes,
            }
        )
        self._ensure_default_ledger()
        with self.db.get_session() as session:
            max_order = max((ledger.sort_order or 0 for ledger in session.execute(select(FundLedger)).scalars().all()), default=0)

        def _write(session):
            existing = session.execute(
                select(FundLedger).where(FundLedger.name == name).limit(1)
            ).scalar_one_or_none()
            if existing is not None:
                raise ValueError("账本名称已存在")
            item = FundLedger(
                name=name,
                color=color,
                sort_order=max_order + 10,
                is_default=False,
                active=True,
                **profile,
                created_at=datetime.now(),
                updated_at=datetime.now(),
            )
            session.add(item)
            session.flush()
            return item.id

        ledger_id = int(self.db._run_write_transaction(f"create_fund_ledger[{name}]", _write))
        with self.db.get_session() as session:
            return session.execute(select(FundLedger).where(FundLedger.id == ledger_id)).scalar_one()

    def update_ledger_profile(self, ledger_id: int, **updates: Any) -> FundLedger:
        ledger_id = int(ledger_id)
        normalized: Dict[str, Any] = {}
        if "name" in updates:
            name = (updates.get("name") or "").strip()
            if not name:
                raise ValueError("账本名称不能为空")
            if len(name) > 20:
                raise ValueError("账本名称不能超过 20 个字符")
            normalized["name"] = name
        if "color" in updates:
            color = (updates.get("color") or DEFAULT_FUND_LEDGER_COLOR).strip()
            if not color.startswith("#") or len(color) not in {4, 7}:
                color = DEFAULT_FUND_LEDGER_COLOR
            normalized["color"] = color
        profile_updates = {
            field: updates[field]
            for field in FUND_LEDGER_PROFILE_FIELDS
            if field in updates
        }
        normalized.update(self._normalize_profile_updates(profile_updates))
        if not normalized:
            raise ValueError("没有可更新的账本画像字段")

        def _write(session):
            ledger = session.execute(
                select(FundLedger).where(FundLedger.id == ledger_id, FundLedger.active.is_(True)).limit(1)
            ).scalar_one_or_none()
            if ledger is None:
                raise ValueError("账本不存在或已停用")
            if "name" in normalized:
                existing = session.execute(
                    select(FundLedger)
                    .where(FundLedger.name == normalized["name"], FundLedger.id != ledger_id)
                    .limit(1)
                ).scalar_one_or_none()
                if existing is not None:
                    raise ValueError("账本名称已存在")
            for field, value in normalized.items():
                setattr(ledger, field, value)
            ledger.updated_at = datetime.now()
            session.flush()
            return ledger.id

        updated_id = int(self.db._run_write_transaction(f"update_fund_ledger[{ledger_id}]", _write))
        with self.db.get_session() as session:
            return session.execute(select(FundLedger).where(FundLedger.id == updated_id)).scalar_one()

    def _normalize_profile_updates(self, updates: Dict[str, Any]) -> Dict[str, Any]:
        normalized: Dict[str, Any] = {}
        for field, value in updates.items():
            if field in FUND_LEDGER_PROFILE_LIMITS:
                normalized[field] = _normalize_optional_text(
                    value,
                    field=field,
                    max_length=FUND_LEDGER_PROFILE_LIMITS[field],
                )
            elif field in FUND_LEDGER_NUMERIC_PROFILE_FIELDS:
                min_value, max_value = FUND_LEDGER_NUMERIC_PROFILE_FIELDS[field]
                normalized[field] = _normalize_optional_float(
                    value,
                    field=field,
                    min_value=min_value,
                    max_value=max_value,
                )
        return normalized

    def list_pool(self, active_only: bool = True) -> List[FundPoolItem]:
        default_ledger = self._ensure_default_ledger()
        with self.db.get_session() as session:
            statement = select(FundPoolItem).order_by(FundPoolItem.created_at.desc())
            if active_only:
                statement = statement.where(FundPoolItem.active.is_(True))
            items = list(session.execute(statement).scalars().all())
        missing = [item.code for item in items if item.ledger_id is None]
        if missing:
            self.assign_codes_to_ledger(missing, default_ledger.id)
            with self.db.get_session() as session:
                statement = select(FundPoolItem).order_by(FundPoolItem.created_at.desc())
                if active_only:
                    statement = statement.where(FundPoolItem.active.is_(True))
                items = list(session.execute(statement).scalars().all())
        return items

    def get_pool_item(self, code: str) -> Optional[FundPoolItem]:
        with self.db.get_session() as session:
            return session.execute(
                select(FundPoolItem).where(FundPoolItem.code == code).limit(1)
            ).scalar_one_or_none()

    def upsert_pool_item(
        self,
        *,
        code: str,
        name: Optional[str] = None,
        fund_type: Optional[str] = None,
        source: str = "akshare",
        notes: Optional[str] = None,
        ledger_id: Optional[int] = None,
        last_refreshed_at: Optional[datetime] = None,
    ) -> FundPoolItem:
        now = datetime.now()
        requested_ledger_id = ledger_id
        create_ledger_id = ledger_id if ledger_id is not None else self._ensure_default_ledger().id

        def _write(session):
            item = session.execute(
                select(FundPoolItem).where(FundPoolItem.code == code).limit(1)
            ).scalar_one_or_none()
            if item is None:
                item = FundPoolItem(
                    code=code,
                    name=name,
                    fund_type=fund_type,
                    ledger_id=create_ledger_id,
                    source=source,
                    notes=notes,
                    active=True,
                    last_refreshed_at=last_refreshed_at,
                    created_at=now,
                    updated_at=now,
                )
                session.add(item)
            else:
                if name:
                    item.name = name
                if fund_type:
                    item.fund_type = fund_type
                if notes is not None:
                    item.notes = notes
                if requested_ledger_id is not None:
                    item.ledger_id = requested_ledger_id
                item.source = source or item.source
                item.active = True
                item.updated_at = now
                if last_refreshed_at is not None:
                    item.last_refreshed_at = last_refreshed_at
            session.flush()
            session.refresh(item)
            return item.to_dict()

        self.db._run_write_transaction(f"upsert_fund_pool[{code}]", _write)
        saved = self.get_pool_item(code)
        if saved is None:
            raise RuntimeError(f"基金池条目写入后未找到: {code}")
        return saved

    def mark_pool_item_inactive(self, code: str) -> bool:
        def _write(session):
            item = session.execute(
                select(FundPoolItem).where(FundPoolItem.code == code).limit(1)
            ).scalar_one_or_none()
            if item is None:
                return False
            item.active = False
            item.updated_at = datetime.now()
            return True

        return bool(self.db._run_write_transaction(f"delete_fund_pool[{code}]", _write))

    def assign_codes_to_ledger(self, codes: List[str], ledger_id: int) -> int:
        if not codes:
            return 0

        def _write(session):
            ledger = session.execute(
                select(FundLedger).where(FundLedger.id == ledger_id, FundLedger.active.is_(True)).limit(1)
            ).scalar_one_or_none()
            if ledger is None:
                raise ValueError("账本不存在或已停用")
            count = 0
            for code in codes:
                item = session.execute(
                    select(FundPoolItem).where(FundPoolItem.code == code).limit(1)
                ).scalar_one_or_none()
                if item is None:
                    continue
                item.ledger_id = ledger_id
                item.updated_at = datetime.now()
                count += 1
            return count

        return int(self.db._run_write_transaction(f"assign_fund_ledger[{ledger_id}]", _write))

    def assign_fund_to_ledger(self, code: str, ledger_id: int) -> Optional[FundPoolItem]:
        self.assign_codes_to_ledger([code], ledger_id)
        return self.get_pool_item(code)

    def save_holding_snapshots(
        self,
        *,
        ledger_id: int,
        source_platform: str,
        rows: Iterable[Dict[str, Any]],
        replace: bool = True,
    ) -> List[FundHoldingSnapshot]:
        ledger_id = int(ledger_id)
        platform = (source_platform or "").strip()
        if not platform:
            raise ValueError("持仓来源平台不能为空")
        now = datetime.now()
        normalized_rows: Dict[str, Dict[str, Any]] = {}
        for row in rows:
            code = str(row.get("code") or "").strip()
            if not code:
                continue
            normalized_rows[code] = {
                "ledger_id": ledger_id,
                "source_platform": platform,
                "source_channel": row.get("source_channel") or "ocr_confirmed",
                "code": code,
                "name": row.get("name"),
                "units": self.db._normalize_sql_value(row.get("units")),
                "available_units": self.db._normalize_sql_value(row.get("available_units")),
                "market_value": self.db._normalize_sql_value(row.get("market_value")),
                "cost_amount": self.db._normalize_sql_value(row.get("cost_amount")),
                "pnl_amount": self.db._normalize_sql_value(row.get("pnl_amount")),
                "pnl_pct": self.db._normalize_sql_value(row.get("pnl_pct")),
                "latest_nav": self.db._normalize_sql_value(row.get("latest_nav")),
                "as_of_date": self.db._normalize_daily_date(row.get("as_of_date")),
                "confidence": row.get("confidence") or "medium",
                "imported_at": now,
                "updated_at": now,
            }
        if not normalized_rows and not replace:
            return []

        codes = sorted(normalized_rows)

        def _write(session):
            ledger = session.execute(
                select(FundLedger).where(FundLedger.id == ledger_id, FundLedger.active.is_(True)).limit(1)
            ).scalar_one_or_none()
            if ledger is None:
                raise ValueError("账本不存在或已停用")
            if replace:
                statement = delete(FundHoldingSnapshot).where(
                    FundHoldingSnapshot.ledger_id == ledger_id,
                    FundHoldingSnapshot.source_platform == platform,
                )
                if codes:
                    statement = statement.where(~FundHoldingSnapshot.code.in_(codes))
                session.execute(statement)
            for code, values in normalized_rows.items():
                existing = session.execute(
                    select(FundHoldingSnapshot)
                    .where(
                        FundHoldingSnapshot.ledger_id == ledger_id,
                        FundHoldingSnapshot.source_platform == platform,
                        FundHoldingSnapshot.code == code,
                    )
                    .limit(1)
                ).scalar_one_or_none()
                if existing is None:
                    session.add(FundHoldingSnapshot(**values))
                else:
                    for field, value in values.items():
                        if field == "imported_at":
                            continue
                        setattr(existing, field, value)
                    existing.updated_at = now
            session.flush()
            return True

        self.db._run_write_transaction(f"save_fund_holdings[{ledger_id}:{platform}]", _write)
        return self.list_holding_snapshots(ledger_id=ledger_id, source_platform=platform)

    def list_holding_snapshots(
        self,
        *,
        ledger_id: Optional[int] = None,
        source_platform: Optional[str] = None,
    ) -> List[FundHoldingSnapshot]:
        with self.db.get_session() as session:
            statement = select(FundHoldingSnapshot).order_by(
                FundHoldingSnapshot.source_platform.asc(),
                FundHoldingSnapshot.code.asc(),
                FundHoldingSnapshot.updated_at.desc(),
            )
            if ledger_id is not None:
                statement = statement.where(FundHoldingSnapshot.ledger_id == int(ledger_id))
            if source_platform:
                statement = statement.where(FundHoldingSnapshot.source_platform == source_platform)
            return list(session.execute(statement).scalars().all())

    def save_nav_records(
        self,
        *,
        code: str,
        records: Iterable[Dict[str, Any]],
        source: str = "akshare",
    ) -> int:
        now = datetime.now()
        normalized: Dict[date, Dict[str, Any]] = {}
        for record in records:
            row_date = self.db._normalize_daily_date(record.get("date"))
            if not row_date:
                continue
            normalized[row_date] = {
                "code": code,
                "date": row_date,
                "unit_nav": self.db._normalize_sql_value(record.get("unit_nav")),
                "accumulated_nav": self.db._normalize_sql_value(record.get("accumulated_nav")),
                "daily_growth_pct": self.db._normalize_sql_value(record.get("daily_growth_pct")),
                "source": source,
                "created_at": now,
                "updated_at": now,
            }
        rows = list(normalized.values())
        if not rows:
            return 0
        dates = [row["date"] for row in rows]

        def _write(session):
            existing_dates = set()
            for j in range(0, len(dates), 500):
                chunk = dates[j : j + 500]
                existing_dates.update(
                    session.execute(
                        select(FundNavDaily.date).where(
                            and_(FundNavDaily.code == code, FundNavDaily.date.in_(chunk))
                        )
                    ).scalars().all()
                )
            new_rows = [row for row in rows if row["date"] not in existing_dates]
            if self.db._is_sqlite_engine:
                for i in range(0, len(rows), 80):
                    chunk = rows[i : i + 80]
                    stmt = sqlite_insert(FundNavDaily).values(chunk)
                    excluded = stmt.excluded
                    session.execute(
                        stmt.on_conflict_do_update(
                            index_elements=["code", "date"],
                            set_={
                                "unit_nav": excluded.unit_nav,
                                "accumulated_nav": excluded.accumulated_nav,
                                "daily_growth_pct": excluded.daily_growth_pct,
                                "source": excluded.source,
                                "updated_at": excluded.updated_at,
                            },
                        )
                    )
            else:
                for row in rows:
                    item = session.execute(
                        select(FundNavDaily).where(
                            and_(FundNavDaily.code == code, FundNavDaily.date == row["date"])
                        )
                    ).scalar_one_or_none()
                    if item is None:
                        session.add(FundNavDaily(**row))
                    else:
                        item.unit_nav = row["unit_nav"]
                        item.accumulated_nav = row["accumulated_nav"]
                        item.daily_growth_pct = row["daily_growth_pct"]
                        item.source = row["source"]
                        item.updated_at = row["updated_at"]
            return len(new_rows)

        return int(self.db._run_write_transaction(f"save_fund_nav[{code}]", _write))

    def get_nav_history(self, code: str, limit: Optional[int] = None) -> List[FundNavDaily]:
        with self.db.get_session() as session:
            statement = (
                select(FundNavDaily)
                .where(FundNavDaily.code == code)
                .order_by(FundNavDaily.date.desc())
            )
            if limit:
                statement = statement.limit(limit)
            rows = list(session.execute(statement).scalars().all())
        return list(reversed(rows))

    def get_nav_dataframe(self, code: str) -> pd.DataFrame:
        rows = [row.to_dict() for row in self.get_nav_history(code)]
        if not rows:
            return pd.DataFrame(columns=["date", "unit_nav", "accumulated_nav", "daily_growth_pct"])
        df = pd.DataFrame(rows)
        df["date"] = pd.to_datetime(df["date"])
        return df.sort_values("date")

    def save_analysis_snapshot(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        row = {
            "code": payload["code"],
            "name": payload.get("name"),
            "fund_type": payload.get("fund_type"),
            "analysis_date": self.db._normalize_daily_date(payload.get("analysis_date")),
            "action": payload["action"],
            "action_label": payload["action_label"],
            "risk_level": payload["risk_level"],
            "risk_score": payload.get("risk_score"),
            "signal_score": payload.get("signal_score"),
            "summary": payload.get("summary"),
            "metrics_json": json.dumps(payload.get("metrics") or {}, ensure_ascii=False),
            "peer_json": json.dumps(payload.get("peer"), ensure_ascii=False) if payload.get("peer") is not None else None,
            "reasons_json": json.dumps(payload.get("reasons") or [], ensure_ascii=False),
            "data_quality": payload.get("data_quality") or "partial",
            "limitations_json": json.dumps(payload.get("limitations") or [], ensure_ascii=False),
            "created_at": datetime.now(),
        }

        def _write(session):
            snapshot = FundAnalysisSnapshot(**row)
            session.add(snapshot)
            session.flush()
            session.refresh(snapshot)
            return snapshot.to_dict()

        return self.db._run_write_transaction(f"save_fund_analysis[{payload['code']}]", _write)

    def get_latest_analysis_snapshot(self, code: str) -> Optional[FundAnalysisSnapshot]:
        with self.db.get_session() as session:
            return session.execute(
                select(FundAnalysisSnapshot)
                .where(FundAnalysisSnapshot.code == code)
                .order_by(desc(FundAnalysisSnapshot.created_at))
                .limit(1)
            ).scalar_one_or_none()
