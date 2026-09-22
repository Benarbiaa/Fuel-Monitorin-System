export type AlertSeverity = 'info' | 'warning' | 'critical';

export type AlertType =
  | 'LOW_STOCK'
  | 'PRICE_ANOMALY'
  | 'HIGH_CONSUMPTION'
  | 'STATION_CRITICAL'
  | 'RESTOCK';

export interface FuelAlert {
  timestamp: string;
  station_id: string;
  fuel_type: string;
  alert_type: AlertType | string;
  severity: AlertSeverity | string;
  message: string;
}