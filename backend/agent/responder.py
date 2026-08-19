import json
import logging
import os
from datetime import datetime, timezone
import httpx
from sqlalchemy.orm import Session
from backend.agent.actions import execute_action
from backend.database.database import SessionLocal
from backend.database import models

logger = logging.getLogger(__name__)

async def process_alert(alert_id: int):
    """
    Process an alert by calling the LLM responder and executing the chosen action.
    Opens a fresh DB session to avoid issues with async/await boundaries.
    """
    # Open fresh session for this async operation
    db: Session = SessionLocal()
    
    try:
        # Fetch the alert fresh from DB
        alert = db.query(models.Alert).filter(models.Alert.id == alert_id).first()
        if not alert:
            logger.error(f"Alert {alert_id} not found")
            return
        
        logger.info(f"Processing alert {alert.id}: {alert.alert_type} at {alert.station_id}")

        api_key = os.getenv("GROQ_API_KEY")
        if not api_key:
            logger.warning("GROQ_API_KEY not set in .env; defaulting to 'escalate' action")
            action = "escalate"
            reason = "GROQ_API_KEY not configured; using default escalation"
            await execute_action(action, alert, db, reason)
            alert.status = "acknowledged"
            alert.handled_by = "agent"
            alert.handled_at = datetime.now(timezone.utc)
            db.commit()
            logger.info(f"Alert {alert.id} defaulted to escalation")
            return

        context = {
            "alert_id": alert.id,
            "station_id": alert.station_id,
            "fuel_type": alert.fuel_type,
            "alert_type": alert.alert_type,
            "severity": alert.severity,
            "message": alert.message,
            "timestamp": alert.timestamp.isoformat() if alert.timestamp else None,
        }

        prompt = (
            "Alert Context:\n"
            + json.dumps(context, indent=2)
            + "\n\nChoose ONE action:\n"
            '1. "reorder" - stock is critically low\n'
            '2. "notify_manager" - price anomaly or high consumption\n'
            '3. "escalate" - critical situation needing human intervention\n\n'
            'Respond with ONLY JSON: {"action": "...", "reason": "..."}'
        )

        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.post(
                "https://api.groq.com/openai/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": "openai/gpt-oss-20b",  # llama-3.1-8b-instant was deprecated by Groq on 2026-08-16
                    "messages": [
                        {
                            "role": "system",
                            "content": 'You are an autonomous fuel station monitoring agent. Choose exactly one action: reorder, notify_manager, or escalate. Respond ONLY with valid JSON: {"action": "...", "reason": "..."} No extra text outside the JSON.'
                        },
                        {"role": "user", "content": prompt}
                    ],
                    "max_tokens": 256,
                    "temperature": 0.2,
                },
            )
            if response.status_code != 200:
                logger.error(f"Groq error body: {response.text}")
            response.raise_for_status()

        response_data = response.json()
        response_text = response_data["choices"][0]["message"]["content"].strip()
        logger.info(f"LLM response: {response_text}")

        try:
            parsed = json.loads(response_text)
            action = parsed.get("action", "escalate")
            reason = parsed.get("reason", "No reason provided")
        except json.JSONDecodeError:
            logger.error(f"Failed to parse response: {response_text}")
            action = "escalate"
            reason = "Failed to parse LLM response"

        await execute_action(action, alert, db, reason)

        # Mark as acknowledged with correct timestamp
        alert.status = "acknowledged"
        alert.handled_by = "agent"
        alert.handled_at = datetime.now(timezone.utc)
        db.commit()

        logger.info(f"Alert {alert.id} processed with action: {action}")

    except Exception as e:
        logger.error(f"Error in responder: {e}")
        # Don't mark as acknowledged on auth errors (will be retried next poll)
        if "403" not in str(e) and "401" not in str(e):
            # Refetch alert to get latest state
            alert = db.query(models.Alert).filter(models.Alert.id == alert_id).first()
            if alert:
                alert.status = "acknowledged"
                alert.handled_by = "system"
                alert.handled_at = datetime.now(timezone.utc)
                db.commit()
    finally:
        db.close()