import os
import pandas as pd
from prophet import Prophet
from sqlalchemy.orm import Session
from dotenv import load_dotenv
from ..database.models import FuelData
from sqlalchemy import text
from ..database.models import FuelData
from sqlalchemy import text
from groq import Groq


load_dotenv()



def get_narrative(forecast_records, station_id, fuel_type, recent_sales_trend):
    client = Groq(api_key=os.getenv("GROQ_API_KEY"))
    
    first = forecast_records[0]
    last = forecast_records[-1]
    min_stock = min(r['yhat'] for r in forecast_records)
    
    prompt = f"""You are a fuel inventory analyst. Write a 2-3 sentence professional summary.
Station: {station_id}, Fuel: {fuel_type}
Stock goes from {first['yhat']:.0f}L to {last['yhat']:.0f}L
Minimum predicted: {min_stock:.0f}L
Avg sales: {recent_sales_trend:.1f}L per 5min
Focus on depletion risk and recommended action."""

    response = client.chat.completions.create(
        model="openai/gpt-oss-120b",  # llama-3.3-70b-versatile was deprecated by Groq on 2026-08-16
        messages=[{"role": "user", "content": prompt}]
    )
    return response.choices[0].message.content

def get_prophet_prediction(db: Session, station_id: str, fuel_type: str, periods: int = 10):
    query = db.query(FuelData.timestamp, FuelData.stock_liters, FuelData.sales_last_5min_liters)\
              .filter(FuelData.station_id == station_id)\
              .filter(FuelData.fuel_type == fuel_type)\
              .order_by(FuelData.timestamp.asc())
    records = db.execute(query.statement).fetchall()
    df = pd.DataFrame(records, columns=['timestamp', 'stock_liters', 'sales_last_5min_liters'])

    
    if len(df) < 50:
        return {"forecast": [], "narrative": "Not enough data to generate forecast."}

    recent_sales_trend = df['sales_last_5min_liters'].tail(12).mean()

    df.rename(columns={'stock_liters': 'y'}, inplace=True)

    latest_real_time = pd.Timestamp.now().replace(microsecond=0)
    simulated_timeline = pd.date_range(end=latest_real_time, periods=len(df), freq='5min')
    df['ds'] = simulated_timeline

    model = Prophet(daily_seasonality=True, yearly_seasonality=False)
    model.fit(df)
    
    future = model.make_future_dataframe(periods=periods, freq='5min')
    forecast = model.predict(future)
    
    future_forecast = forecast[['ds', 'yhat', 'yhat_lower', 'yhat_upper']].tail(periods)
    future_forecast['ds'] = future_forecast['ds'].dt.strftime('%Y-%m-%d %H:%M:%S')
    records = future_forecast.to_dict(orient='records')

    try:
        narrative = get_narrative(records, station_id, fuel_type, recent_sales_trend)
    except Exception as e:
        narrative = f"Narrative unavailable: {e}"

    return {"forecast": records, "narrative": narrative}