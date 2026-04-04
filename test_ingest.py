from ingestion_service import run_ingestion_cycle

print("Testing FULL ingestion cycle...")
run_ingestion_cycle(force_refresh=True)
