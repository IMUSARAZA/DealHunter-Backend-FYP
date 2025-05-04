import logging
from abc import ABC, abstractmethod
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from firebase_admin import credentials, firestore, initialize_app
from django.conf import settings
import os
import traceback
import time
import threading
import signal
import sys
import psutil
import atexit
from webdriver_manager.chrome import ChromeDriverManager
from webdriver_manager.core.os_manager import ChromeType

logger = logging.getLogger(__name__)

class BaseScraper(ABC):
    """Base class for all bank scrapers"""
    # Class-level tracking to manage all running scrapers
    _running_scrapers = {}
    _scrapers_lock = threading.Lock()
    
    @classmethod
    def register_scraper(cls, job_id, scraper_instance):
        """Register a running scraper for global tracking"""
        with cls._scrapers_lock:
            cls._running_scrapers[job_id] = scraper_instance
            
    @classmethod
    def unregister_scraper(cls, job_id):
        """Remove a scraper from global tracking"""
        with cls._scrapers_lock:
            if job_id in cls._running_scrapers:
                del cls._running_scrapers[job_id]
                
    @classmethod
    def get_scraper(cls, job_id):
        """Get a registered scraper by job ID"""
        with cls._scrapers_lock:
            return cls._running_scrapers.get(job_id)
    
    def __init__(self, bank_name, city_name, job=None):
        self.bank_name = bank_name
        self.city_name = city_name
        self.job = job
        self.driver = None
        self.driver_pid = None
        self.db = None
        self.initialize_firebase()
        self.last_cancellation_check = time.time()
        self.cancellation_check_interval = 5  # Check for cancellation every 5 seconds
        self._is_cancelled = False
        self._monitor_thread = None
        self._stop_monitor = False
        
        # Register this scraper globally
        if job:
            self.__class__.register_scraper(job.id, self)
            
        # Ensure cleanup on program exit
        atexit.register(self.cleanup)
        
    def initialize_firebase(self):
        """Initialize Firebase connection"""
        try:
            try:
                self.db = firestore.client()
                logger.info("Firebase client already initialized")
                self.log("Firebase client already initialized")
            except:
                from scraper.scrapers.hbl_scraper import get_firebase_credentials_path
                cred_path = get_firebase_credentials_path()
                
                if cred_path and os.path.exists(cred_path):
                    cred = credentials.Certificate(cred_path)
                    initialize_app(cred)
                    self.db = firestore.client()
                    logger.info(f"Firebase client initialized with credentials at {cred_path}")
                    self.log(f"Firebase client initialized with credentials at {cred_path}")
                else:
                    error_msg = "Firebase credentials file not found. Some functionality may be limited."
                    logger.warning(error_msg)
                    self.log(error_msg)
                    self.db = None
        except Exception as e:
            error_msg = f"Error initializing Firebase: {str(e)}"
            logger.error(error_msg)
            if self.job:
                self.job.log_output += f"\n{error_msg}"
                self.job.save()
            self.db = None
    
    def start_cancellation_monitor(self):
        """Start a background thread that monitors for job cancellation"""
        if not self.job:
            return
            
        self._stop_monitor = False
        self._monitor_thread = threading.Thread(target=self._cancellation_monitor)
        self._monitor_thread.daemon = True
        self._monitor_thread.start()
        self.log("Cancellation monitor started")
        
    def stop_cancellation_monitor(self):
        """Stop the cancellation monitor thread"""
        if self._monitor_thread:
            self._stop_monitor = True
            self._monitor_thread.join(timeout=2)
            self._monitor_thread = None
            self.log("Cancellation monitor stopped")
            
    def _cancellation_monitor(self):
        """Background thread that checks for job cancellation"""
        from dashboard.models import ScrapingJob
        import time
        
        self.log("Cancellation monitor running")
        check_count = 0
        while not self._stop_monitor:
            try:
                # Check job status directly from database
                if self.job:
                    # Reload the job from the database to get the latest status
                    try:
                        job_fresh = ScrapingJob.objects.get(id=self.job.id)
                        if job_fresh.status != 'running':
                            status_msg = "cancelled" if job_fresh.status == 'stopped' else f"status changed to {job_fresh.status}"
                            self.log(f"Cancellation monitor detected job was {status_msg}")
                            self._is_cancelled = True
                            
                            # Force close the driver and terminate processes
                            self._emergency_shutdown()
                            
                            # Exit the monitor thread
                            return
                    except Exception as e:
                        self.log(f"Error checking job status: {str(e)}")
                
                # Every 10 checks, log that we're still monitoring (for debugging)
                check_count += 1
                if check_count % 10 == 0:
                    self.log(f"Cancellation monitor still active (check #{check_count})")
                        
            except Exception as e:
                self.log(f"Error in cancellation monitor: {str(e)}")
                
            # Sleep for a short interval before checking again (reduced from 1 second to 0.5 seconds)
            time.sleep(0.5)
    
    def _emergency_shutdown(self):
        """Forces the complete shutdown of the scraper, including all child processes"""
        try:
            self.log("EMERGENCY SHUTDOWN: Forcefully terminating all scraper processes")
            
            # Get current process
            current_process = psutil.Process(os.getpid())
            
            # Log all child processes before killing
            for child in current_process.children(recursive=True):
                try:
                    self.log(f"Found child process: {child.pid} {child.name()}")
                except:
                    pass
            
            # Try to quit the driver gracefully first
            try:
                if self.driver:
                    self.log("Attempting to close driver gracefully")
                    self.driver.quit()
            except Exception as e:
                self.log(f"Error during graceful driver shutdown: {str(e)}")
            
            # Kill chromedriver process directly if we know the PID
            if self.driver_pid:
                try:
                    self.log(f"Killing chromedriver process {self.driver_pid}")
                    # Try to kill the process directly with SIGKILL
                    os.kill(self.driver_pid, signal.SIGKILL)
                except Exception as e:
                    self.log(f"Error killing chromedriver process: {str(e)}")
            
            # Force kill all Chrome and chromedriver processes by name
            try:
                import subprocess
                self.log("Force killing all chrome and chromedriver processes")
                if sys.platform == 'darwin':  # macOS
                    subprocess.run(["pkill", "-9", "chromedriver"], check=False)
                    subprocess.run(["pkill", "-9", "Chrome"], check=False)
                    subprocess.run(["pkill", "-9", "Google Chrome"], check=False)
                elif sys.platform.startswith('linux'):
                    subprocess.run(["pkill", "-9", "-f", "chromedriver"], check=False)
                    subprocess.run(["pkill", "-9", "-f", "chrome"], check=False)
                elif sys.platform == 'win32':
                    subprocess.run(["taskkill", "/F", "/IM", "chromedriver.exe"], check=False)
                    subprocess.run(["taskkill", "/F", "/IM", "chrome.exe"], check=False)
            except Exception as e:
                self.log(f"Error during force kill of chrome processes: {str(e)}")
            
            # Find and kill all chrome/chromedriver processes that might be related
            try:
                for proc in psutil.process_iter(['pid', 'name']):
                    # Kill any Chrome or chromedriver processes
                    if 'chrome' in proc.info['name'].lower():
                        try:
                            self.log(f"Killing chrome-related process: {proc.info['pid']} {proc.info['name']}")
                            proc.kill()
                        except:
                            pass
            except Exception as e:
                self.log(f"Error killing chrome processes: {str(e)}")

            # Update job status one final time
            try:
                if self.job and not self._stop_monitor:
                    self.job.log_output += f"\nEMERGENCY SHUTDOWN COMPLETED at {time.strftime('%Y-%m-%d %H:%M:%S')}"
                    self.job.save()
            except Exception as e:
                self.log(f"Error updating job during emergency shutdown: {str(e)}")
                
            # Last resort: Kill the entire Python process if this was called from a thread
            # Only do this if we're in a thread and not the main process
            if threading.current_thread() is not threading.main_thread():
                self.log("EMERGENCY SHUTDOWN: Taking extreme measures - killing this process!")
                # Use os._exit as a last resort to force immediate termination
                os._exit(1)
            
        except Exception as e:
            self.log(f"Error in emergency shutdown: {str(e)}")
    
    def _force_quit_driver(self):
        """Force quit the driver from a separate thread"""
        try:
            if self.driver:
                self.driver.quit()
        except Exception as e:
            self.log(f"Error in force quit: {str(e)}")
    
    def setup_webdriver(self):
        """Set up and return a selenium webdriver"""
        try:
            chrome_options = Options()
            chrome_options.add_argument("--headless")
            chrome_options.add_argument("--no-sandbox")
            chrome_options.add_argument("--disable-dev-shm-usage")
            # Add an option to make it easier to identify processes
            chrome_options.add_argument(f"--user-data-dir=/tmp/chrome-scraper-{self.job.id if self.job else 'nojob'}")
            
            self.log("Using webdriver_manager to get the correct ChromeDriver")
            driver_path = ChromeDriverManager().install()
            service = Service(driver_path)
            
            self.log(f"ChromeDriver path: {driver_path}")
            self.driver = webdriver.Chrome(service=service, options=chrome_options)
            
            # Store the chromedriver process ID if possible
            if hasattr(self.driver.service, 'process') and self.driver.service.process:
                self.driver_pid = self.driver.service.process.pid
                self.log(f"ChromeDriver process ID: {self.driver_pid}")
            
            logger.info("WebDriver initialized successfully")
            return self.driver
        except Exception as e:
            error_msg = f"Error setting up WebDriver: {str(e)}"
            logger.error(error_msg)
            self.log(error_msg)
            if self.job:
                self.job.log_output += f"\n{error_msg}"
                self.job.save()
            raise
    
    def cleanup(self):
        """Clean up resources"""
        # Remove from global tracking
        if self.job:
            self.__class__.unregister_scraper(self.job.id)
            
        # Stop the cancellation monitor
        self.stop_cancellation_monitor()
        
        # Close the driver
        if self.driver:
            try:
                self.driver.quit()
                logger.info("WebDriver closed successfully")
            except Exception as e:
                logger.error(f"Error closing WebDriver: {str(e)}")
    
    def run(self):
        """Main method to run the scraper"""
        try:
            if self.job:
                self.job.start_job()
                self.job.log_output += "\nInitializing scraper..."
                self.job.save()
            
            self.setup_webdriver()
            
            # Start the cancellation monitor thread
            self.start_cancellation_monitor()
            
            if self.check_if_cancelled():
                return 0
                
            deal_count = self.scrape()
            
            if self.job and not self._is_cancelled:
                self.job.complete_job(deal_count)
                self.job.log_output += f"\nScraping completed. {deal_count} deals scraped."
                self.job.save()
                
            return deal_count
        except Exception as e:
            error_msg = f"Error running scraper: {str(e)}\n{traceback.format_exc()}"
            logger.error(error_msg)
            if self.job and not self._is_cancelled:
                self.job.fail_job(error_msg)
            raise
        finally:
            self.cleanup()
    
    @abstractmethod
    def scrape(self):
        """Main scraping method, to be implemented by subclasses"""
        pass
    
    def log(self, message):
        """Log a message and update job log if available"""
        logger.info(message)
        if self.job:
            try:
                self.job.log_output += f"\n{message}"
                self.job.save()
            except Exception as e:
                logger.error(f"Error saving log message: {str(e)}")
    
    def check_if_cancelled(self):
        """Check if the job has been cancelled by the user"""
        # If already marked as cancelled by the monitor, return True immediately
        if self._is_cancelled:
            return True
            
        if self.job:
            try:
                from dashboard.models import ScrapingJob
                job_fresh = ScrapingJob.objects.get(id=self.job.id)
                if job_fresh.status != 'running':
                    status_msg = "cancelled" if job_fresh.status == 'stopped' else f"status changed to {job_fresh.status}"
                    self.log(f"Job was {status_msg}, stopping scraper")
                    self._is_cancelled = True
                    return True
            except Exception as e:
                self.log(f"Error checking job status: {str(e)}")
        return False
    
    def should_check_cancellation(self):
        """Check if it's time to check for cancellation based on the interval"""
        current_time = time.time()
        if current_time - self.last_cancellation_check >= self.cancellation_check_interval:
            self.last_cancellation_check = current_time
            return True
        return False
    
    def maybe_check_if_cancelled(self):
        """Check for cancellation if the check interval has elapsed"""
        # If already marked as cancelled by the monitor, return True immediately
        if self._is_cancelled:
            return True
            
        if self.should_check_cancellation():
            return self.check_if_cancelled()
        return False
    
    def get_base_url(self):
        """Get the base URL for the bank and city, to be implemented by subclasses"""
        pass