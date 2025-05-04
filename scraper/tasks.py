import importlib
import logging
import traceback
from datetime import timezone
from celery import shared_task
from django.utils import timezone
from dashboard.models import Bank, City, ScrapingJob

logger = logging.getLogger(__name__)

try:
    from deal_hunter.celery import app
    celery_available = getattr(app, 'is_functional', False)
except Exception:
    celery_available = False
    logger.warning("Celery is not available. Scraping tasks will run directly.")

@shared_task
def run_scraping_job(job_id):
    """
    Celery task to run a scraping job
    """
    try:
        job = ScrapingJob.objects.get(id=job_id)
        logger.info(f"Starting scraping job {job_id} for {job.bank.name} - {job.city.name}")
        
        # Import the scraper class dynamically
        try:
            module_path = f"scraper.scrapers.{job.bank.scraper_class.lower()}"
            module = importlib.import_module(module_path)
            scraper_class = getattr(module, job.bank.scraper_class)
        except (ImportError, AttributeError) as e:
            error_msg = f"Could not import scraper class: {str(e)}"
            logger.error(error_msg)
            job.fail_job(error_msg)
            return False
        
        # Initialize and run the scraper
        scraper = scraper_class(job.bank.name, job.city.name, job)
        deal_count = scraper.run()
        
        logger.info(f"Scraping job {job_id} completed with {deal_count} deals scraped")
        return True
    except Exception as e:
        error_msg = f"Error in scraping task for job {job_id}: {str(e)}\n{traceback.format_exc()}"
        logger.error(error_msg)
        try:
            job = ScrapingJob.objects.get(id=job_id)
            job.fail_job(error_msg)
        except:
            pass
        return False

@shared_task
def check_scheduled_jobs():
    """
    Periodic task to check for scheduled jobs that need to be run
    """
    now = timezone.now()
    scheduled_jobs = ScrapingJob.objects.filter(
        status='pending', 
        scheduled_for__lte=now
    )
    
    for job in scheduled_jobs:
        logger.info(f"Running scheduled job {job.id} for {job.bank.name} - {job.city.name}")
        
        # If celery is available use it, otherwise run directly in thread
        if celery_available:
            run_scraping_job.delay(job.id)
        else:
            from dashboard.views import run_scraper_thread
            import threading
            thread = threading.Thread(target=run_scraper_thread, args=(job.id,))
            thread.daemon = True
            thread.start()
            logger.info(f"Started direct thread for job {job.id} (Celery unavailable)")
    
    return f"Checked for scheduled jobs: {scheduled_jobs.count()} jobs started"