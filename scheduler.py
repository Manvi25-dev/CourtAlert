"""
CourtAlert Scheduler
Handles periodic execution of cause list fetching and case matching.
Uses APScheduler for robust background scheduling.
"""

import os
import logging
from datetime import datetime
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from ingestion_service import run_cause_list_check
from models import get_db_connection
from services.whatsapp_service import send_whatsapp

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("scheduler.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Environment Configuration
ENV = os.getenv("ENV", "DEV").upper()


def _dispatch_pending_alerts(limit: int = 100) -> dict:
    """Send pending alerts and mark delivery status."""
    conn = get_db_connection()
    try:
        rows = conn.execute(
            "SELECT id, user_phone, message FROM alerts "
            "WHERE delivery_status = 'pending' "
            "ORDER BY created_at ASC LIMIT ?",
            (limit,),
        ).fetchall()

        sent = 0
        failed = 0
        for row in rows:
            alert_id = row["id"]
            try:
                send_whatsapp(row["user_phone"], row["message"])
                conn.execute(
                    "UPDATE alerts SET delivery_status = 'sent', sent_at = CURRENT_TIMESTAMP WHERE id = ?",
                    (alert_id,),
                )
                sent += 1
            except Exception as exc:
                logger.error("Failed to dispatch alert id=%s error=%s", alert_id, exc)
                conn.execute(
                    "UPDATE alerts SET delivery_status = 'failed' WHERE id = ?",
                    (alert_id,),
                )
                failed += 1

        conn.commit()
        return {
            "checked": len(rows),
            "sent": sent,
            "failed": failed,
        }
    finally:
        conn.close()

def scheduled_job():
    """
    The job to be executed by the scheduler.
    Wraps the ingestion service with logging and environment handling.
    """
    logger.info(f"⏰ STARTING SCHEDULED JOB (ENV={ENV})")
    
    try:
        # Run the ingestion pipeline
        alerts = run_cause_list_check()
        
        logger.info(f"✅ Job completed. Generated {len(alerts)} alerts.")
        
        dispatch_result = _dispatch_pending_alerts()
        logger.info(
            "Alert dispatch summary: checked=%s sent=%s failed=%s",
            dispatch_result["checked"],
            dispatch_result["sent"],
            dispatch_result["failed"],
        )

        if alerts:
            logger.info("Legacy ingestion return size: %d", len(alerts))
                
    except Exception as e:
        logger.error(f"❌ Error in scheduled job: {e}", exc_info=True)

def start_scheduler():
    """
    Initialize and start the background scheduler.
    """
    scheduler = BackgroundScheduler()
    
    # Schedule to run daily at 7:00 AM IST
    # Note: Server time might be UTC, so adjust accordingly if needed.
    # For simplicity, we'll use system time.
    trigger = CronTrigger(hour=7, minute=0)
    
    scheduler.add_job(
        scheduled_job,
        trigger=trigger,
        id='daily_cause_list_check',
        name='Daily Cause List Check',
        replace_existing=True
    )
    
    logger.info("⏳ Scheduler initialized. Job scheduled for 7:00 AM daily.")
    
    # Start the scheduler
    scheduler.start()
    
    # Run once on startup if requested via env var (useful for testing deployments)
    if os.getenv("RUN_ON_STARTUP", "False").lower() == "true":
        logger.info("🚀 RUN_ON_STARTUP is True. Executing job immediately...")
        scheduler.add_job(scheduled_job, 'date', run_date=datetime.now())

    return scheduler

if __name__ == "__main__":
    # If run directly, start scheduler and keep main thread alive
    import time
    sched = start_scheduler()
    
    # Also run immediately for testing when executed as script
    print("Running immediate check for testing...")
    scheduled_job()
    
    try:
        while True:
            time.sleep(2)
    except (KeyboardInterrupt, SystemExit):
        sched.shutdown()
