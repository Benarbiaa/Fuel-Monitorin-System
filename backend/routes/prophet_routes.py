from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from ..database.database import get_db
from ..services.prophet_service import get_prophet_prediction

router = APIRouter()

@router.get("/predict")
def predict_stock(
    station_id: str, 
    fuel_type: str, 
    periods: int = Query(24, description="Number of 5-min intervals to predict"),
    db: Session = Depends(get_db)
):
    """Returns forecasted stock levels with LLM narrative annotation."""
    result = get_prophet_prediction(db, station_id, fuel_type, periods)
    return result