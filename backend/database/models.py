from sqlalchemy import Column, Integer, String, Float, DateTime, ForeignKey, func
from sqlalchemy.orm import relationship
from .database import Base

# 1. Station Table: Static metadata [cite: 145]
class Station(Base):
    __tablename__ = "stations"
    
    station_id = Column(String, primary_key=True, index=True) # e.g., "BI00001" [cite: 6, 146]
    company = Column(String) # e.g., "AGIL" [cite: 7, 147]
    location = Column(String) # [cite: 148]
    
    # Relationship: One station has many fuel updates
    fuel_records = relationship("FuelData", back_populates="station")

# 2. FuelData Table: Core time-series records [cite: 152]
class FuelData(Base):
    __tablename__ = "fuel_data"
    
    id = Column(Integer, primary_key=True, index=True) 
    timestamp = Column(DateTime, server_default=func.now())
    station_id = Column(String, ForeignKey("stations.station_id")) 
    fuel_type = Column(String) # "Gasoil50" or "SansPlomb" [cite: 8, 25, 157]
    
    # Financials and Inventory [cite: 158-162]
    price_tnd = Column(Float)
    official_price_tnd = Column(Float)
    stock_liters = Column(Float)
    capacity_liters = Column(Float)
    sales_last_5min_liters = Column(Float)
    
    station = relationship("Station", back_populates="fuel_records")

# 3. Alert Table: System decisions/problems [cite: 168]
class Alert(Base):
    __tablename__ = "alerts"
    
    id = Column(Integer, primary_key=True, index=True) 
    timestamp = Column(DateTime, default=func.now())
    station_id = Column(String, ForeignKey("stations.station_id")) 
    fuel_type = Column(String) 
    alert_type = Column(String)
    severity = Column(String)
    message = Column(String)

    # Automation-agent workflow fields
    status = Column(String, default="new")  # new | processing | acknowledged
    handled_by = Column(String, nullable=True)  # "agent" | "system" | None
    handled_at = Column(DateTime, nullable=True)


# 4. IncidentLog Table: Audit trail of actions taken by the automation agent
class IncidentLog(Base):
    __tablename__ = "incident_logs"

    id = Column(Integer, primary_key=True, index=True)
    timestamp = Column(DateTime, default=func.now())
    alert_id = Column(Integer, ForeignKey("alerts.id"))
    action = Column(String)  # reorder | notify_manager | escalate
    reason = Column(String)
    payload = Column(String)  # JSON-encoded snapshot of the alert context
    actor = Column(String, default="agent")