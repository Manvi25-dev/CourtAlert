import logging
import os
import glob
import threading
import time
from datetime import datetime
from typing import Any, Dict
try:
    from apscheduler.schedulers.background import BackgroundScheduler
except ImportError:  # pragma: no cover - local fallback for test environments
    class BackgroundScheduler:  # type: ignore[override]
        def add_job(self, *args, **kwargs):
            return None

        def start(self):
            return None

from case_matcher import match_cases_and_alert
from models import delete_advance_list_data, log_ingestion_run
from sources import court_sources, today_iso

logger = logging.getLogger(__name__)

# Keep scheduler global so it doesn't get garbage collected
_scheduler = None
ingestion_lock = threading.Lock()
_last_ingestion_summary: Dict[str, Any] = {
    "status": "idle",
    "started_at": None,
    "finished_at": None,
    "duration_seconds": 0.0,
    "courts_checked": 0,
    "pdfs_discovered": 0,
    "pdfs_processed": 0,
    "entries_extracted": 0,
    "alerts_generated": 0,
    "errors": [],
}


# =====================================================
# INGESTION CYCLE
# =====================================================

def get_ingestion_summary() -> Dict[str, Any]:
    return dict(_last_ingestion_summary)


def is_ingestion_running() -> bool:
    return ingestion_lock.locked()


def run_ingestion_cycle(force_refresh: bool = False):
    """
    Runs one full ingestion cycle:
    1. Fetch court cause lists from registered sources
    2. Normalize entries to unified schema
      4. Match cases & trigger alerts
    """
    if not ingestion_lock.acquire(blocking=False):
        logger.warning("Ingestion already running. Skipping new request.")
        return {
            "status": "skipped",
            "reason": "ingestion already running",
            "courts_checked": 0,
            "pdfs_processed": 0,
        }

    cycle_start = time.perf_counter()
    started_at = datetime.utcnow().isoformat() + "Z"
    summary: Dict[str, Any] = {
        "status": "running",
        "started_at": started_at,
        "finished_at": None,
        "duration_seconds": 0.0,
        "courts_checked": len(court_sources),
        "pdfs_discovered": 0,
        "pdfs_processed": 0,
        "entries_extracted": 0,
        "alerts_generated": 0,
        "errors": [],
    }
    _last_ingestion_summary.update(summary)

    logger.info("Starting ingestion cycle (force_refresh=%s)", force_refresh)

    try:
        stage_start = time.perf_counter()
        logger.info("Fetching cases from %d registered court sources...", len(court_sources))
        all_source_results: list[tuple[str, list[dict[str, Any]]]] = []
        cycle_date = today_iso()

        for source_name, source in court_sources.items():
            source_start = time.perf_counter()
            try:
                entries = source.fetch_cases(cycle_date)
                all_source_results.append((source_name, entries))
                logger.info(
                    "Source '%s' fetched %d entries in %.2fs",
                    source_name,
                    len(entries),
                    time.perf_counter() - source_start,
                )
            except Exception as exc:
                logger.exception("Source '%s' failed", source_name)
                summary["errors"].append({"source": source_name, "error": str(exc)})

        logger.info("All source fetches completed in %.2fs", time.perf_counter() - stage_start)
        summary["pdfs_discovered"] = sum(len(entries) for _, entries in all_source_results)

        if not all_source_results:
            logger.info("No source results found for ingestion.")
            summary["status"] = "completed"
            return summary

        # Keep legacy refresh behavior for local advance PDFs.
        if force_refresh:
            local_adv_files = glob.glob(os.path.join("cause_lists", "*adv*.pdf"))
            for local_file in local_adv_files:
                filename = os.path.basename(local_file)
                if "adv" in filename.lower():
                    logger.info("Force refresh enabled. Clearing existing data for %s", filename)
                    delete_advance_list_data(filename)

        for source_name, entries in all_source_results:
            if not entries:
                continue

            source_start = time.perf_counter()
            try:
                doc_date = entries[0].get("hearing_date")
                source_label = f"{source_name}_source"
                alerts = match_cases_and_alert(entries, source_pdf=source_label, hearing_date=doc_date)
                summary["alerts_generated"] += len(alerts)
                summary["pdfs_processed"] += 1
                summary["entries_extracted"] += len(entries)
                logger.info(
                    "Matching complete for source '%s': entries=%d alerts=%d in %.2fs",
                    source_name,
                    len(entries),
                    len(alerts),
                    time.perf_counter() - source_start,
                )
            except Exception as exc:
                logger.exception("Matching failed for source '%s'", source_name)
                summary["errors"].append({"source": source_name, "error": str(exc)})

        summary["status"] = "completed_with_errors" if summary["errors"] else "completed"
        return summary
    except Exception as exc:
        logger.exception("Ingestion cycle failed unexpectedly")
        summary["status"] = "failed"
        summary["errors"].append({"stage": "cycle", "error": str(exc)})
        return summary
    finally:
        summary["duration_seconds"] = round(time.perf_counter() - cycle_start, 2)
        summary["finished_at"] = datetime.utcnow().isoformat() + "Z"
        _last_ingestion_summary.update(summary)
        try:
            log_ingestion_run(summary)
        except Exception:
            logger.exception("Failed to persist ingestion run record")
        ingestion_lock.release()
        logger.info("Ingestion finished. Summary: %s", summary)


def run_cause_list_check(force_refresh: bool = True):
    """Legacy alias retained for older tests/scripts."""
    run_ingestion_cycle(force_refresh=force_refresh)
    return []


# =====================================================
# SCHEDULER
# =====================================================

def start_scheduler():
    """
    Starts background scheduler to automatically run ingestion periodically.
    Called on FastAPI startup.
    """

    global _scheduler

    if _scheduler:
        logger.info("Scheduler already running.")
        return

    _scheduler = BackgroundScheduler()
    _scheduler.add_job(
        run_ingestion_cycle,
        trigger="interval",
        minutes=30,
        max_instances=1,
        replace_existing=True,
    )

    _scheduler.start()
    logger.info("Background scheduler started.")


def get_scheduler_status() -> str:
    """Returns the current state of the background scheduler."""
    global _scheduler
    if _scheduler is None:
        return "not_started"
    try:
        return "running" if _scheduler.running else "stopped"
    except AttributeError:
        return "unknown"
