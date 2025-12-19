import logging
import requests
from typing import Dict, Any
from src.core.config_manager import config_manager

logger = logging.getLogger(__name__)

def send_webhook_notification(event_type: str, data: Dict[str, Any]):
    """
    Send a notification to the configured webhook (Dynamic Config).
    """
    # 1. Load config
    config = config_manager.get_config("notifications")
    
    # 2. Check enable switch
    if not config.get("enable", False):
        return

    # 3. Check Webhook URL
    webhook_url = config.get("webhook_url", "")
    if not webhook_url:
        logger.debug("Webhook enabled but URL not set, skipping.")
        return

    # 4. Check Event Filter (Simple implementation)
    # events option: "all" | "error" | "task_done"
    filter_mode = config.get("events", "all")
    if filter_mode == "error" and event_type not in ["error", "exception", "failure"]:
        return
    # Add more filter logic here if needed

    payload = {
        "event": event_type,
        "data": data,
        "source": "memex_system"
    }

    try:
        response = requests.post(webhook_url, json=payload, timeout=5)
        if response.status_code >= 400:
            logger.warning(f"Webhook returned status {response.status_code}: {response.text}")
        else:
            logger.info(f"Notification sent: {event_type}")
    except Exception as e:
        logger.error(f"Failed to send webhook notification: {e}")
