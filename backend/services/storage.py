from sqlalchemy.orm import Session
from ..database import models

# --- WRITE METHODS ---

# Best-effort display metadata for known simulator station IDs. Falls back to
# generic values for any station_id we haven't seen before, so ingestion
# never fails just because a station wasn't pre-registered.
_KNOWN_STATIONS = {
    "BI00001": {"company": "AGIL", "location": "Tunis Centre"},
    "BI00002": {"company": "AGIL", "location": "Tunis Nord"},
    "BI00003": {"company": "AGIL", "location": "Sousse"},
}


def get_or_create_station(db: Session, station_id: str) -> models.Station:
    """
    Fetch the Station row for station_id, creating it if it doesn't exist yet.

    fuel_data.station_id has a foreign key to stations.station_id. Postgres
    enforces this strictly (unlike SQLite, which ignores FKs by default), so
    every station referenced by an incoming FuelData record must exist here
    first or the insert will fail with a ForeignKeyViolation.
    """
    station = db.query(models.Station).filter(
        models.Station.station_id == station_id
    ).first()
    if station:
        return station

    meta = _KNOWN_STATIONS.get(station_id, {})
    station = models.Station(
        station_id=station_id,
        company=meta.get("company", "Unknown"),
        location=meta.get("location", station_id),
    )
    db.add(station)
    db.commit()
    db.refresh(station)
    return station


def store_fuel_data(db: Session, data):
    # Ensure the parent Station row exists before inserting the FuelData
    # record that references it (see get_or_create_station for why).
    get_or_create_station(db, data.station_id)

    new_record = models.FuelData(**data.dict())
    db.add(new_record)
    db.commit()
    db.refresh(new_record)
    return new_record


def store_fuel_data_idempotent(db: Session, data):
    """
    Like store_fuel_data, but safe to call more than once with the same
    (station_id, fuel_type, timestamp) — which happens under Kafka's
    at-least-once delivery whenever a message is reprocessed (e.g. after a
    consumer crash/restart before its offset was committed).

    Returns the inserted FuelData record, or None if a record with this
    exact key already existed (meaning: this message was already processed
    previously; the caller should skip alert generation for it and just
    move on to committing the Kafka offset).
    """
    from sqlalchemy.exc import IntegrityError

    get_or_create_station(db, data.station_id)

    new_record = models.FuelData(**data.dict())
    db.add(new_record)
    try:
        db.commit()
    except IntegrityError:
        # The unique constraint on (station_id, fuel_type, timestamp)
        # rejected this insert — we've already stored this exact reading.
        # Roll back the failed transaction so this session can keep being
        # used for the next message, and report "nothing new happened".
        db.rollback()
        return None

    db.refresh(new_record)
    return new_record

def create_alert(db: Session, station_id: str, fuel_type: str, alert_type: str, severity: str, message: str):
    new_alert = models.Alert(
        station_id=station_id,
        fuel_type=fuel_type,
        alert_type=alert_type,
        severity=severity,
        message=message,
        status="new",
    )
    db.add(new_alert)
    db.commit()
    return new_alert

# --- READ METHODS ---

def get_fuel_history(db: Session, station_id: str, fuel_type: str, limit: int = 100):
    return db.query(models.FuelData)\
             .filter(models.FuelData.station_id == station_id)\
             .filter(models.FuelData.fuel_type == fuel_type)\
             .order_by(models.FuelData.timestamp.desc())\
             .limit(limit).all()

def get_all_alerts(db: Session, station_id: str = None):
    query = db.query(models.Alert)
    if station_id:
        query = query.filter(models.Alert.station_id == station_id)
    return query.order_by(models.Alert.timestamp.desc()).all()