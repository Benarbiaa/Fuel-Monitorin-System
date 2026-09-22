from datetime import datetime, timezone
from typing import List, Literal, Optional

from fastapi import APIRouter, Query, Depends
from sqlalchemy.orm import Session
from sqlalchemy import func
from backend.schemas import AlertResponse, FuelData, FuelDataResponse
from backend.services import storage
from backend.database import models
from backend.database.database import get_db

router = APIRouter()


def _append_alert(db: Session, station_id: str, fuel_type: str, alert_type: str, severity: str, message: str) -> None:
    """
    Saves a new alert to the SQLite database using the storage service.
    """
    storage.create_alert(
        db=db,
        station_id=station_id,
        fuel_type=fuel_type,
        alert_type=alert_type,
        severity=severity,
        message=f"[{severity.upper()}] {message}" 
    )
# Minimum stock increase (liters) between two consecutive readings for the
# same station/fuel_type before we treat it as a delivery rather than noise.
# In this system stock only ever decreases from sales (see the station
# simulator), so any real increase can only mean a delivery truck arrived —
# there's no explicit "delivery" flag in the telemetry, exactly like a real
# tank sensor wouldn't report one; we infer it from the data itself.
RESTOCK_MIN_INCREASE_LITERS = 50.0


def _check_restock(db: Session, record: FuelDataResponse) -> int:
    """
    Compares this reading against the immediately preceding reading for the
    same station/fuel_type. If stock jumped up by a meaningful amount, logs
    an informational RESTOCK alert so the delivery is visible in the app
    (dashboard alerts feed, chat assistant, automation agent) instead of
    only being observable as a silent jump in the stock history chart.
    """
    previous = (
        db.query(models.FuelData)
        .filter(
            models.FuelData.station_id == record.station_id,
            models.FuelData.fuel_type == record.fuel_type,
            models.FuelData.timestamp < record.timestamp,
        )
        .order_by(models.FuelData.timestamp.desc())
        .first()
    )

    if previous is None:
        return 0  # first reading ever for this tank — nothing to compare against

    increase = record.stock_liters - previous.stock_liters
    if increase < RESTOCK_MIN_INCREASE_LITERS:
        return 0

    pct_of_capacity = increase / record.capacity_liters if record.capacity_liters else 0
    _append_alert(
        db,
        record.station_id,
        record.fuel_type,
        "RESTOCK",
        "info",
        f"Delivery received: stock rose by {increase:.0f}L "
        f"({pct_of_capacity:.0%} of capacity) to {record.stock_liters:.0f}L",
    )
    return 1


def generate_alerts_from_record(db :Session ,record: FuelDataResponse) -> int:
    generated = 0

    generated += _check_restock(db, record)

    if record.capacity_liters > 0:
        stock_pct = record.stock_liters / record.capacity_liters
        if stock_pct < 0.05:
            _append_alert(db,
                record.station_id,
                record.fuel_type,
                "LOW_STOCK",
                "critical",
                f"CRITICAL: Stock at {stock_pct:.1%} of capacity ({record.stock_liters:.0f}L remaining)",
            )
            generated += 1
        elif stock_pct < 0.15:
            _append_alert(db,
                record.station_id,
                record.fuel_type,
                "LOW_STOCK",
                "warning",
                f"Stock at {stock_pct:.1%} of capacity ({record.stock_liters:.0f}L remaining)",
            )
            generated += 1

    if record.official_price_tnd > 0:
        deviation_pct = abs(record.price_tnd - record.official_price_tnd) / record.official_price_tnd
        if deviation_pct > 0.10:
            _append_alert(db,
                record.station_id,
                record.fuel_type,
                "PRICE_ANOMALY",
                "critical",
                f"Price deviation of {deviation_pct:.1%} from official price ({record.price_tnd:.3f} vs {record.official_price_tnd:.3f} TND)",
            )
            generated += 1
        elif deviation_pct > 0.05:
            _append_alert(db,
                record.station_id,
                record.fuel_type,
                "PRICE_ANOMALY",
                "warning",
                f"Price deviation of {deviation_pct:.1%} from official price ({record.price_tnd:.3f} vs {record.official_price_tnd:.3f} TND)",
            )
            generated += 1

    if record.sales_last_5min_liters > 200:
        _append_alert(db,
            record.station_id,
            record.fuel_type,
            "HIGH_CONSUMPTION",
            "warning",
            f"Unusually high sales: {record.sales_last_5min_liters:.0f}L in last 5 minutes",
        )
        generated += 1

    if record.stock_liters == 0:
        _append_alert(db,
            record.station_id,
            record.fuel_type,
            "STATION_CRITICAL",
            "critical",
            f"Station is OUT OF STOCK for {record.fuel_type}",
        )
        generated += 1

    return generated


@router.get("/stations")
def get_stations(db: Session = Depends(get_db)):
    """Get all stations that have been registered via ingestion."""
    stations = db.query(models.Station).all()
    return [
        {
            "station_id": s.station_id,
            "company": s.company,
            "location": s.location,
        }
        for s in stations
    ]







@router.get("/current", response_model=List[FuelDataResponse])
def get_current(station_id: str = Query(...), db: Session = Depends(get_db)):
    # Get the latest record for each fuel_type for the station
    subquery = db.query(
        models.FuelData.fuel_type,
        func.max(models.FuelData.timestamp).label('max_ts')
    ).filter(models.FuelData.station_id == station_id).group_by(models.FuelData.fuel_type).subquery()
    
    results = db.query(models.FuelData).join(
        subquery,
        (models.FuelData.fuel_type == subquery.c.fuel_type) & (models.FuelData.timestamp == subquery.c.max_ts)
    ).all()
    
    return results


@router.get("/history", response_model=List[FuelDataResponse])
def get_history(
    station_id: str = Query(...),
    fuel_type: Optional[Literal["Gasoil50", "SansPlomb"]] = Query(None),
    limit: int = Query(500, le=2000),
    db: Session = Depends(get_db),
):
    query = db.query(models.FuelData).filter(models.FuelData.station_id == station_id)
    if fuel_type:
        query = query.filter(models.FuelData.fuel_type == fuel_type)
    results = query.order_by(models.FuelData.timestamp.desc()).limit(limit).all()
    return results[::-1]  # Return in ascending order


@router.get("/alerts", response_model=List[AlertResponse])
def get_alerts(
    station_id: Optional[str] = Query(None),
    severity: Optional[Literal["info", "warning", "critical"]] = Query(None),
    alert_type: Optional[Literal["LOW_STOCK", "PRICE_ANOMALY", "HIGH_CONSUMPTION", "STATION_CRITICAL", "RESTOCK"]] = Query(None),
    limit: int = Query(50, le=500),
    db: Session = Depends(get_db),
):
    query = db.query(models.Alert)
    if station_id:
        query = query.filter(models.Alert.station_id == station_id)
    if severity:
        query = query.filter(models.Alert.severity == severity)
    if alert_type:
        query = query.filter(models.Alert.alert_type == alert_type)
    results = query.order_by(models.Alert.timestamp.desc()).limit(limit).all()
    return results





@router.get("/companies")
def get_companies(db: Session = Depends(get_db)):
    """Get all unique companies from registered stations."""
    companies = db.query(models.Station.company).distinct().all()
    return [c[0] for c in companies if c[0]]