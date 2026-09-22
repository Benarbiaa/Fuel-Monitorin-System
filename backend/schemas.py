from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field


class FuelData(BaseModel):
    timestamp: datetime
    station_id: str = Field(..., min_length=1)
    fuel_type: Literal["Gasoil50", "SansPlomb"]
    price_tnd: float = Field(..., gt=0)
    official_price_tnd: float = Field(..., gt=0)
    stock_liters: float = Field(..., ge=0)
    capacity_liters: float = Field(..., gt=0)
    sales_last_5min_liters: float = Field(..., ge=0)


class IngestAcceptedResponse(BaseModel):
    """
    Returned by POST /ingest once ingestion is Kafka-backed. Deliberately
    does NOT include an `id` — unlike FuelDataResponse, nothing has been
    written to the database yet at the point this response is sent. The
    actual write happens moments later, asynchronously, in the ingestion
    consumer. This schema exists so the response honestly reflects "queued
    for processing", not "stored", which is what /ingest used to (and can
    no longer truthfully) claim.
    """
    status: Literal["accepted"] = "accepted"
    station_id: str
    fuel_type: str
    timestamp: datetime


class FuelDataResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    timestamp: datetime
    station_id: str
    fuel_type: Literal["Gasoil50", "SansPlomb"]
    price_tnd: float
    official_price_tnd: float
    stock_liters: float
    capacity_liters: float
    sales_last_5min_liters: float


class AlertResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    timestamp: datetime
    station_id: str
    fuel_type: str
    alert_type: str
    severity: str
    message: str