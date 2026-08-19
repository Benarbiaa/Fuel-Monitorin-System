import os
from groq import Groq
from sqlalchemy.orm import Session
from sqlalchemy import func
from ..database.models import FuelData, Alert
from .prophet_service import get_prophet_prediction
from dotenv import load_dotenv

load_dotenv()

def generate_report(db: Session, station_id: str) -> str:
    client = Groq(api_key=os.getenv("GROQ_API_KEY"))

    # 1. Stock actuel
    subquery = db.query(
        FuelData.fuel_type,
        func.max(FuelData.timestamp).label('max_ts')
    ).filter(FuelData.station_id == station_id).group_by(FuelData.fuel_type).subquery()

    current_records = db.query(FuelData).join(
        subquery,
        (FuelData.fuel_type == subquery.c.fuel_type) &
        (FuelData.timestamp == subquery.c.max_ts)
    ).all()

    stock_summary = "\n".join([
        f"- {r.fuel_type}: {r.stock_liters:.0f}L / {r.capacity_liters:.0f}L ({r.stock_liters/r.capacity_liters*100:.1f}%)"
        for r in current_records
    ])

    # 2. Alertes récentes (last 10)
    alerts = db.query(Alert).filter(
        Alert.station_id == station_id
    ).order_by(Alert.timestamp.desc()).limit(10).all()

    alerts_summary = "\n".join([
        f"- [{r.severity.upper()}] {r.alert_type}: {r.message}"
        for r in alerts
    ]) or "No recent alerts."

    # 3. Forecast + narrative pour chaque carburant
    forecast_summary = ""
    for fuel_type in ["Gasoil50", "SansPlomb"]:
        result = get_prophet_prediction(db, station_id, fuel_type, periods=12)
        if result["forecast"]:
            forecast_summary += f"\n**{fuel_type}:** {result['narrative']}\n"
        else:
            forecast_summary += f"\n**{fuel_type}:** Not enough data.\n"

    # 4. Prompt LLM
    prompt = f"""You are a professional fuel station operations analyst. 
Generate a concise professional report in markdown for station {station_id}.

## Current Stock Levels
{stock_summary}

## Recent Alerts
{alerts_summary}

## Forecast Analysis
{forecast_summary}

Write a structured markdown report with:
- Executive Summary
- Stock Status
- Alert Analysis  
- Forecast & Recommendations

Be professional, concise, and actionable."""

    response = client.chat.completions.create(
        model="openai/gpt-oss-120b",  # llama-3.3-70b-versatile was deprecated by Groq on 2026-08-16
        messages=[{"role": "user", "content": prompt}]
    )
    return response.choices[0].message.content