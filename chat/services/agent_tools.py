"""
services/agent_tools.py
-----------------------
The "hands" of the conversational agent.

When Gemini calls a tool (get_current_stock, get_fuel_history, get_alerts),
this module executes it by either:
  - Calling the real backend over HTTP  (BACKEND_MODE=real)
  - Returning mock data                 (BACKEND_MODE=mock)

This is the ONLY place where the choice between real/mock matters.
gemini_service.py doesn't know the difference — it just calls execute_tool().
"""

from __future__ import annotations
import logging
from typing import Any

import httpx

from config import settings
from mocks import backend_mock

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# HTTP helpers (used only when BACKEND_MODE=real)
# ---------------------------------------------------------------------------

def _get(path: str, params: dict | None = None) -> Any:
    """Make a GET request to the main backend. Raises on failure."""
    url = f"{settings.BACKEND_URL}{path}"
    with httpx.Client(timeout=10.0) as client:
        resp = client.get(url, params=params or {})
        resp.raise_for_status()
        return resp.json()


# ---------------------------------------------------------------------------
# Tool implementations
# ---------------------------------------------------------------------------

def _all_stations() -> list[dict]:
    """Fetch all stations — used internally by tools that need to iterate."""
    if settings.is_mock():
        rows = backend_mock.get_current()
        seen: dict[str, dict] = {}
        for r in rows:
            sid = r["station_id"]
            if sid not in seen:
                seen[sid] = {"station_id": sid, "company": "", "location": r.get("station_name", sid)}
        return list(seen.values())
    return _get("/stations")


def _current_for_station(station_id: str) -> list[dict]:
    if settings.is_mock():
        return backend_mock.get_current(station_id)
    return _get("/current", {"station_id": station_id})


def _tool_get_current_stock(station_id: str | None = None) -> Any:
    if station_id:
        return _current_for_station(station_id)
    # /current requires station_id — iterate all stations and aggregate
    stations = _all_stations()
    results = []
    for s in stations:
        try:
            results.extend(_current_for_station(s["station_id"]))
        except Exception as exc:
            logger.warning("Failed to fetch current for %s: %s", s["station_id"], exc)
    return results


def _tool_get_fuel_history(station_id: str, fuel_type: str | None = None, limit: int = 100) -> Any:
    if settings.is_mock():
        return backend_mock.get_history(station_id, limit)
    params: dict = {"station_id": station_id, "limit": limit}
    if fuel_type:
        params["fuel_type"] = fuel_type
    return _get("/history", params)


def _tool_get_alerts(station_id: str | None = None, severity: str | None = None,
                     alert_type: str | None = None) -> Any:
    if settings.is_mock():
        alerts = backend_mock.get_alerts(station_id)
        if severity:
            alerts = [a for a in alerts if a.get("severity") == severity]
        return alerts
    params: dict = {}
    if station_id:
        params["station_id"] = station_id
    if severity:
        params["severity"] = severity
    if alert_type:
        params["alert_type"] = alert_type
    return _get("/alerts", params)


def _tool_get_station_count() -> Any:
    stations = _all_stations()
    return {"total": len(stations), "stations": stations}


def _tool_get_lowest_stock(fuel_type: str | None = None, limit: int = 5) -> Any:
    all_stock = _tool_get_current_stock()
    rows = []
    for row in all_stock:
        if fuel_type and row.get("fuel_type", "") != fuel_type:
            continue
        capacity = row.get("capacity_liters") or 0
        stock = row.get("stock_liters") or 0
        rows.append({
            **row,
            "stock_pct": round(stock / capacity * 100, 1) if capacity else None,
        })
    rows.sort(key=lambda r: (r["stock_pct"] is None, r["stock_pct"]))
    return rows[:limit]


def _tool_get_station_summary(station_id: str) -> Any:
    stock = _current_for_station(station_id)
    alerts = _tool_get_alerts(station_id=station_id)
    station_meta = next(
        (s for s in _all_stations() if s["station_id"] == station_id), {}
    )
    return {
        "station_id": station_id,
        "company": station_meta.get("company", ""),
        "location": station_meta.get("location", ""),
        "stock": stock,
        "alerts": alerts,
        "alert_count": len(alerts),
    }


def _tool_get_critical_alerts(severity: str | None = None) -> Any:
    if severity:
        return _tool_get_alerts(severity=severity)
    # Return both warning and critical if no filter specified
    critical = _tool_get_alerts(severity="critical")
    warning = _tool_get_alerts(severity="warning")
    return critical + warning


def _tool_predict_stock(station_id: str, fuel_type: str, periods: int = 24) -> Any:
    if settings.is_mock():
        return {"error": "predict not available in mock mode"}
    return _get("/predict", {"station_id": station_id, "fuel_type": fuel_type, "periods": periods})


def _tool_search_past_reports(query: str, station_id: str | None = None, k: int = 3) -> Any:
    """
    Semantic search over previously generated LLM reports.

    Reports are free-text narrative, so unlike alerts (small fixed taxonomy),
    exact filters don't help here — this refreshes the vector index from the
    backend's persisted reports, then does a similarity search over their
    content so the agent can answer pattern/history questions that structured
    tools can't (e.g. "what did past reports say about X").
    """
    if settings.is_mock():
        return {"error": "report search not available in mock mode"}

    # Re-fetch and re-index on every call — keeps the index fresh with no
    # separate background sync process to maintain.
    from . import report_retriever as _rr_module

    params: dict = {"limit": 200}
    if station_id:
        params["station_id"] = station_id
    reports = _get("/reports", params)
    _rr_module.report_retriever.index_reports(reports)

    context = _rr_module.report_retriever.retrieve(query, station_id=station_id, k=k)
    if not context:
        return {"result": "No relevant past reports found."}
    return {"result": context}


# ---------------------------------------------------------------------------
# Public dispatcher — called by gemini_service.py
# ---------------------------------------------------------------------------

_TOOL_MAP = {
    "get_current_stock":    _tool_get_current_stock,
    "get_fuel_history":     _tool_get_fuel_history,
    "get_alerts":           _tool_get_alerts,
    "get_station_count":    _tool_get_station_count,
    "get_lowest_stock":     _tool_get_lowest_stock,
    "get_station_summary":  _tool_get_station_summary,
    "get_critical_alerts":  _tool_get_critical_alerts,
    "predict_stock":        _tool_predict_stock,
    "search_past_reports":  _tool_search_past_reports,
}


def execute_tool(name: str, args: dict) -> Any:
    """
    Dispatch a Gemini tool call to the correct implementation.

    Parameters
    ----------
    name : Tool name (must match one of _TOOL_MAP keys).
    args : Arguments dict from Gemini's function_call.

    Returns
    -------
    Any JSON-serializable result.
    """
    fn = _TOOL_MAP.get(name)
    if fn is None:
        raise ValueError(f"Unknown tool: {name!r}. Available: {list(_TOOL_MAP)}")

    logger.debug("Executing tool %s with args %s (mode=%s)", name, args, settings.BACKEND_MODE)
    return fn(**args)