from fastapi import APIRouter, HTTPException, BackgroundTasks
from pydantic import BaseModel
import logging

from pipeline.config import list_source_ids, get_source_config
from pipeline.flows.ingest_flow import ingest_flow
from pipeline.db.warehouse import log_run_start, log_run_finish

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/scrape", tags=["Scraping Orchestrator"])

class ScrapeResponse(BaseModel):
    status: str
    source_id: str
    message: str
    details: dict

@router.post("/source/{source_id}", response_model=ScrapeResponse)
def trigger_scrape_for_source(source_id: str, background_tasks: BackgroundTasks):
    """
    Trigger scraping and ingestion for a specific data source.
    The ingestion runs synchronously for now, but could be pushed to a background task
    or Prefect deployment in the future.
    """
    valid_sources = list_source_ids()
    # Handle case sensitivity
    matching_source = next((s for s in valid_sources if s.lower() == source_id.lower()), None)
    
    if not matching_source:
        raise HTTPException(status_code=404, detail=f"Source '{source_id}' not configured or inactive.")
    
    source_id = matching_source
    logger.info(f"Triggering ingest_flow for source: {source_id}")
    
    try:
        # Run the flow (this fetches/scrapes data and loads it into CDM)
        summary = ingest_flow(source_id=source_id)
        
        # Check overall status
        failed = sum(1 for v in summary.values() if v.get("status") == "failed")
        success = sum(1 for v in summary.values() if v.get("status") == "success")
        
        total_rows = sum(v.get("rows", 0) for v in summary.values())
        
        status = "success"
        if failed > 0 and success == 0:
            status = "failed"
        elif failed > 0 and success > 0:
            status = "partial_success"
            
        return ScrapeResponse(
            status=status,
            source_id=source_id,
            message=f"Ingestion complete. {success} indicators successful, {failed} failed.",
            details={
                "total_rows_ingested": total_rows,
                "indicator_summaries": summary
            }
        )
    except Exception as e:
        logger.error(f"Scrape for {source_id} failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Ingestion failed: {str(e)}")

@router.post("/batch")
def trigger_scrape_all():
    """
    Trigger scraping and ingestion for all configured data sources sequentially.
    """
    sources = list_source_ids()
    results = {}
    
    for source_id in sources:
        logger.info(f"Batch: Triggering ingest_flow for source: {source_id}")
        try:
            summary = ingest_flow(source_id=source_id)
            results[source_id] = summary
        except Exception as e:
            logger.error(f"Batch scrape for {source_id} failed: {e}")
            results[source_id] = {"error": str(e)}
            
    return {
        "status": "completed",
        "sources_processed": len(sources),
        "details": results
    }
