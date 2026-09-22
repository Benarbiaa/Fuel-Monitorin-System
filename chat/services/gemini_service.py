"""
services/gemini_service.py
--------------------------
All LLM interactions live here. No other file imports groq directly.

Responsibilities
----------------
- Configure the Groq client once at import time.
- Expose two simple functions:
    chat_with_tools()  — runs the agentic tool-calling loop for /chat
    explain_alert()    — single-shot call that explains one alert

To swap providers later: rewrite only this file.
"""

from __future__ import annotations
import json
import logging

from groq import Groq

from config import settings

logger = logging.getLogger(__name__)

_client = Groq(api_key=settings.GROQ_API_KEY)

# ---------------------------------------------------------------------------
# Tool declarations (OpenAI-compatible format)
# ---------------------------------------------------------------------------

_TOOL_DECLARATIONS = [
    {
        "type": "function",
        "function": {
            "name": "get_current_stock",
            "description": (
                "Fetch the latest fuel stock levels and prices for one or all stations. "
                "Each row contains: station_id, fuel_type (Gasoil50 or SansPlomb), "
                "stock_liters, capacity_liters, price_tnd, official_price_tnd, sales_last_5min_liters. "
                "Use when the operator asks about current stock or fuel levels."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "station_id": {
                        "type": "string",
                        "description": "Station ID (e.g. 'BI00001'). Omit to get all stations.",
                    },
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_fuel_history",
            "description": (
                "Fetch historical fuel data for a station. "
                "Use when the operator asks about trends, past consumption, or price history."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "station_id": {
                        "type": "string",
                        "description": "Station ID (e.g. 'BI00001').",
                    },
                    "fuel_type": {
                        "type": "string",
                        "enum": ["Gasoil50", "SansPlomb"],
                        "description": "Filter to a specific fuel type. Omit for both.",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Number of records to return (default 100, max 2000).",
                    },
                },
                "required": ["station_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_alerts",
            "description": (
                "Fetch active alerts. Severity levels: 'info', 'warning', or 'critical'. "
                "Alert types: LOW_STOCK, PRICE_ANOMALY, HIGH_CONSUMPTION, STATION_CRITICAL, RESTOCK "
                "(RESTOCK is informational only — logged when a delivery truck refills a tank, not a problem). "
                "Use when the operator asks about warnings, problems, or anything that needs attention."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "station_id": {
                        "type": "string",
                        "description": "Filter by station ID. Omit for all stations.",
                    },
                    "severity": {
                        "type": "string",
                        "enum": ["info", "warning", "critical"],
                        "description": "Filter by severity level.",
                    },
                    "alert_type": {
                        "type": "string",
                        "enum": ["LOW_STOCK", "PRICE_ANOMALY", "HIGH_CONSUMPTION", "STATION_CRITICAL", "RESTOCK"],
                        "description": "Filter by alert type.",
                    },
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_station_count",
            "description": (
                "Return the total number of stations in the network with their IDs, company, and location. "
                "Use when the operator asks how many stations there are."
            ),
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_lowest_stock",
            "description": (
                "Return stations ranked by lowest fuel stock percentage (stock_liters / capacity_liters). "
                "Use when the operator asks which station is running lowest or needs resupply first."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "fuel_type": {
                        "type": "string",
                        "enum": ["Gasoil50", "SansPlomb"],
                        "description": "Filter to a specific fuel type. Omit for all.",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "How many results to return (default 5).",
                    },
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_station_summary",
            "description": (
                "Return a full snapshot of one station: current stock for all fuel types "
                "plus all active alerts. Use when the operator asks for an overview or "
                "status of a specific station."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "station_id": {
                        "type": "string",
                        "description": "The station ID to summarise (e.g. 'BI00001').",
                    },
                },
                "required": ["station_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_critical_alerts",
            "description": (
                "Return urgent alerts across the network. "
                "Omit severity to get both 'warning' and 'critical'. "
                "Use when the operator asks what needs immediate attention."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "severity": {
                        "type": "string",
                        "enum": ["warning", "critical"],
                        "description": "Filter to one severity level. Omit for both.",
                    },
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "predict_stock",
            "description": (
                "Forecast future stock levels for a station and fuel type. "
                "Each period is 5 minutes. Use when the operator asks when a station will run out, "
                "or wants to plan ahead."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "station_id": {
                        "type": "string",
                        "description": "Station ID (e.g. 'BI00001').",
                    },
                    "fuel_type": {
                        "type": "string",
                        "enum": ["Gasoil50", "SansPlomb"],
                        "description": "Fuel type to forecast.",
                    },
                    "periods": {
                        "type": "integer",
                        "description": "Number of 5-minute intervals to forecast (default 24 = 2 hours).",
                    },
                },
                "required": ["station_id", "fuel_type"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_past_reports",
            "description": (
                "Semantic search over previously generated station reports (free-text narrative "
                "covering stock status, alert analysis, and forecasts). Use this for pattern or "
                "history questions that don't map to an exact filter — e.g. 'what did past reports "
                "say about SansPlomb consumption spikes?' or 'has this kind of issue come up before?'. "
                "Do NOT use this for current/live data — use get_current_stock, get_alerts, or "
                "predict_stock instead."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Natural-language description of what to search for in past reports.",
                    },
                    "station_id": {
                        "type": "string",
                        "description": "Restrict the search to one station. Omit to search across all stations.",
                    },
                    "k": {
                        "type": "integer",
                        "description": "Number of past reports to return (default 3).",
                    },
                },
                "required": ["query"],
            },
        },
    },
]

# ---------------------------------------------------------------------------
# System prompt for the conversational agent
# ---------------------------------------------------------------------------

_CHAT_SYSTEM_PROMPT = """
You are a helpful fuel station operations assistant.
You have access to real-time tools to fetch stock levels, history, alerts, and forecasts.

Key domain facts:
- Fuel types are exactly "Gasoil50" and "SansPlomb" — use these exact strings with tools.
- Prices are in TND (Tunisian Dinar). The field is price_tnd; official_price_tnd is the regulated price.
- Stock percentage = stock_liters / capacity_liters × 100.
- Alert severities are "warning" and "critical" only.
- Each prediction period = 5 minutes.

Guidelines:
- Always call the appropriate tool before answering questions about stock, alerts, or forecasts.
- For questions about past reports, patterns, or "has this happened before" that don't map to an exact filter, use search_past_reports instead of guessing.
- Give concise, actionable answers. When stock is low, suggest reordering.
- Do not fabricate numbers — if a tool returns no data, say so.
- Respond in the same language the operator uses (French or English).
""".strip()

# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def chat_with_tools(
    user_message: str,
    history: list[dict],
    tool_executor,         # callable: (name: str, args: dict) -> Any
) -> tuple[str, list[str]]:
    """
    Run a multi-turn tool-calling loop.

    Parameters
    ----------
    user_message  : The latest user turn.
    history       : Previous turns as list of {"role": ..., "content": ...}.
    tool_executor : A callable that receives (tool_name, tool_args) and returns
                    the result. Injected from agent_tools.py.

    Returns
    -------
    (answer_text, sources_used)
    """
    messages = [{"role": "system", "content": _CHAT_SYSTEM_PROMPT}]
    for turn in history:
        role = "user" if turn["role"] == "user" else "assistant"
        messages.append({"role": role, "content": turn["content"]})
    messages.append({"role": "user", "content": user_message})

    sources_used: list[str] = []
    MAX_ITERATIONS = 5

    for _ in range(MAX_ITERATIONS):
        response = _client.chat.completions.create(
            model=settings.GROQ_MODEL,
            messages=messages,
            tools=_TOOL_DECLARATIONS,
            tool_choice="auto",
        )
        msg = response.choices[0].message

        if not msg.tool_calls:
            return msg.content or "I was unable to generate a response. Please try again.", sources_used

        # Append assistant message as a plain dict — the SDK object doesn't re-serialize correctly
        messages.append({
            "role": "assistant",
            "content": msg.content,
            "tool_calls": [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {
                        "name": tc.function.name,
                        "arguments": tc.function.arguments,
                    },
                }
                for tc in msg.tool_calls
            ],
        })

        for tc in msg.tool_calls:
            tool_name = tc.function.name
            tool_args = json.loads(tc.function.arguments) if tc.function.arguments else {}
            logger.info("Tool call: %s(%s)", tool_name, tool_args)

            if tool_name not in sources_used:
                sources_used.append(tool_name)

            try:
                result = tool_executor(tool_name, tool_args)
            except Exception as exc:
                result = {"error": str(exc)}

            messages.append({
                "role": "tool",
                "tool_call_id": tc.id,
                "content": json.dumps(result, default=str),
            })

    return "I was unable to generate a response after multiple attempts.", sources_used


def explain_alert(alert: dict) -> tuple[str, str]:
    """
    Generate a plain-English explanation and recommended action for one alert.

    Returns
    -------
    (explanation, recommended_action)
    """
    prompt = f"""
You are a fuel station operations expert.

Given this alert, write:
1. A plain-English explanation (1-2 sentences) of what is happening and why it matters.
2. A concrete recommended action (1 sentence) for the station operator.

Alert details:
- Station: {alert.get('station_id')}
- Fuel type: {alert.get('fuel_type')}
- Alert type: {alert.get('alert_type')}
- Severity: {alert.get('severity')}
- Message: {alert.get('message')}

Respond ONLY as valid JSON with exactly these two keys:
{{"explanation": "...", "recommended_action": "..."}}
""".strip()

    try:
        response = _client.chat.completions.create(
            model=settings.GROQ_MODEL,
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"},
        )
        raw = response.choices[0].message.content or "{}"
        data = json.loads(raw)
        return data.get("explanation", ""), data.get("recommended_action", "")
    except Exception as exc:
        logger.warning("explain_alert failed for alert %s: %s", alert.get("id"), exc)
        return "Unable to generate explanation.", "Please review this alert manually."  