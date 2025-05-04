from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.utils import timezone
from django.http import JsonResponse, HttpResponseNotAllowed
from datetime import datetime, timedelta
import importlib
import threading
from .models import Bank, City, ScrapingJob
from .forms import ScrapingJobForm, ScheduleJobForm, BankForm
from scraper.tasks import run_scraping_job

# Function to run the scraping job in a thread for direct execution
def run_scraper_thread(job_id):
    """
    Run a scraping job directly in a thread (without Celery)
    """
    try:
        from dashboard.models import ScrapingJob, Bank
        
        # Add verbose debugging
        print(f"Starting scraper thread for job {job_id}")
        
        job = ScrapingJob.objects.get(id=job_id)
        
        # Start the job
        job.start_job()
        job.log_output += "\nStarting scraping job directly (without Celery)...\n"
        job.log_output += f"Thread started at {timezone.now()}\n"
        job.save()
        
        try:
            # Import the scraper class dynamically
            try:
                # Log the import attempt
                module_path = f"scraper.scrapers.{job.bank.scraper_class.lower()}"
                job.log_output += f"Attempting to import scraper from {module_path}\n"
                job.save()
                
                module = importlib.import_module(module_path)
                scraper_class = getattr(module, job.bank.scraper_class)
                
                job.log_output += f"Successfully imported {job.bank.scraper_class} class\n"
                job.save()
                
            except (ImportError, AttributeError) as e:
                error_msg = f"Could not import scraper class: {str(e)}"
                job.fail_job(error_msg)
                print(f"Import error: {error_msg}")
                return
            
            # Initialize and run the scraper
            try:
                job.log_output += f"Initializing scraper with bank={job.bank.name}, city={job.city.name}\n"
                job.save()
                
                scraper = scraper_class(job.bank.name, job.city.name, job)
                
                job.log_output += f"Scraper initialized, starting run()\n"
                job.save()
                
                deal_count = scraper.run()
                
                # Update job status
                job.complete_job(deal_count)
                job.log_output += f"\nScraping job completed directly. {deal_count} deals scraped."
                job.save()
            except Exception as e:
                import traceback
                error_msg = f"Error running scraper: {str(e)}\n{traceback.format_exc()}"
                job.fail_job(error_msg)
                print(f"Scraper error: {error_msg}")
                
        except Exception as e:
            import traceback
            error_msg = f"Error in scraping job: {str(e)}\n{traceback.format_exc()}"
            job.fail_job(error_msg)
            print(f"General error: {error_msg}")
            
    except Exception as e:
        import traceback
        print(f"Error in thread for job {job_id}: {str(e)}\n{traceback.format_exc()}")

@login_required
def dashboard(request):
    """
    Main dashboard view showing all banks and recent jobs
    """
    banks = Bank.objects.all()
    recent_jobs = ScrapingJob.objects.all().order_by('-created_at')[:10]
    
    # Count stats
    pending_jobs = ScrapingJob.objects.filter(status='pending').count()
    running_jobs = ScrapingJob.objects.filter(status='running').count()
    completed_jobs = ScrapingJob.objects.filter(status='completed').count()
    failed_jobs = ScrapingJob.objects.filter(status='failed').count()
    stopped_jobs = ScrapingJob.objects.filter(status='stopped').count()
    
    # Get total deals scraped
    total_deals = ScrapingJob.objects.filter(status='completed').values_list('deals_scraped', flat=True)
    total_deals_count = sum(total_deals)
    
    context = {
        'banks': banks,
        'recent_jobs': recent_jobs,
        'pending_jobs': pending_jobs,
        'running_jobs': running_jobs,
        'completed_jobs': completed_jobs,
        'failed_jobs': failed_jobs,
        'stopped_jobs': stopped_jobs,
        'total_deals_count': total_deals_count,
    }
    
    return render(request, 'dashboard/dashboard.html', context)

@login_required
def edit_bank(request, bank_id):
    """
    Edit an existing bank
    """
    bank = get_object_or_404(Bank, id=bank_id)
    
    if request.method == 'POST':
        form = BankForm(request.POST, request.FILES, instance=bank)
        if form.is_valid():
            form.save()
            messages.success(request, f"Bank '{bank.name}' has been updated successfully!")
            return redirect('bank_detail', bank_id=bank.id)
    else:
        form = BankForm(instance=bank)
    
    context = {
        'form': form,
        'bank': bank,
        'is_edit': True,
    }
    
    return render(request, 'dashboard/edit_bank.html', context)

@login_required
def delete_bank(request, bank_id):
    """
    Delete a bank
    """
    bank = get_object_or_404(Bank, id=bank_id)
    
    if request.method == 'POST':
        bank_name = bank.name
        bank.delete()
        messages.success(request, f"Bank '{bank_name}' has been deleted successfully!")
        return redirect('dashboard')
    
    context = {
        'bank': bank,
    }
    
    return render(request, 'dashboard/delete_bank_confirm.html', context)

@login_required
def bank_detail(request, bank_id):
    """
    View for bank details and its cities
    """
    bank = get_object_or_404(Bank, id=bank_id)
    cities = bank.cities.all()
    
    # Get recent jobs for this bank
    recent_jobs = ScrapingJob.objects.filter(bank=bank).order_by('-created_at')[:10]
    
    context = {
        'bank': bank,
        'cities': cities,
        'recent_jobs': recent_jobs,
    }
    
    return render(request, 'dashboard/bank_detail.html', context)

@login_required
def start_scraping(request, bank_id, city_id=None):
    """
    Start a scraping job for a bank and city
    """
    bank = get_object_or_404(Bank, id=bank_id)
    
    if request.method == 'POST':
        # Use the bank_id in form initialization
        form = ScrapingJobForm(request.POST, bank_id=bank_id)
        
        if form.is_valid():
            city = form.cleaned_data['city']
            
            # Create the job
            job = ScrapingJob.objects.create(
                bank=bank,
                city=city,
                status='pending'
            )
            
            # Try to use Celery, but fall back to direct execution if it fails
            try:
                # Try to enqueue the job with Celery
                run_scraping_job.delay(job.id)
                messages.success(request, f"Scraping job for {bank.name} - {city.name} started with Celery!")
            except Exception as e:
                # If Celery fails, run the job directly in a thread
                messages.warning(request, f"Celery unavailable. Running job directly (this might take a while): {str(e)}")
                
                # Start a thread to run the scraper
                thread = threading.Thread(target=run_scraper_thread, args=(job.id,))
                thread.daemon = True
                thread.start()
                
                messages.success(request, f"Scraping job for {bank.name} - {city.name} started directly!")
            
            return redirect('job_detail', job_id=job.id)
        else:
            # For debugging
            print(f"Form errors: {form.errors}")
            for field in form:
                print(f"Field {field.name} value: {field.value()}")
                print(f"Field {field.name} choices: {[c for c in field.field.choices]}")
    else:
        # Pre-select city if provided in URL
        initial = {}
        if city_id:
            city = get_object_or_404(City, id=city_id, bank=bank)
            initial['city'] = city
        
        form = ScrapingJobForm(initial=initial, bank_id=bank_id)
    
    context = {
        'bank': bank,
        'form': form,
    }
    
    return render(request, 'dashboard/start_scraping.html', context)

@login_required
def schedule_job(request, bank_id, city_id=None):
    """
    Schedule a scraping job for future execution
    """
    bank = get_object_or_404(Bank, id=bank_id)
    
    if request.method == 'POST':
        form = ScheduleJobForm(request.POST, bank_id=bank_id)
        
        if form.is_valid():
            city = form.cleaned_data['city']
            scheduled_for = form.cleaned_data['scheduled_for']
            
            # Create the scheduled job
            job = ScrapingJob.objects.create(
                bank=bank,
                city=city,
                status='pending',
                scheduled_for=scheduled_for
            )
            
            messages.success(
                request, 
                f"Scraping job for {bank.name} - {city.name} scheduled for {scheduled_for.strftime('%Y-%m-%d %H:%M')}!"
            )
            return redirect('bank_detail', bank_id=bank.id)
    else:
        # Pre-select city if provided in URL
        initial = {
            'scheduled_for': timezone.now() + timedelta(hours=1)
        }
        if city_id:
            city = get_object_or_404(City, id=city_id, bank=bank)
            initial['city'] = city
        
        form = ScheduleJobForm(initial=initial, bank_id=bank_id)
    
    context = {
        'bank': bank,
        'form': form,
    }
    
    return render(request, 'dashboard/schedule_job.html', context)

@login_required
def job_detail(request, job_id):
    """
    View details of a specific job
    """
    job = get_object_or_404(ScrapingJob, id=job_id)
    
    context = {
        'job': job,
    }
    
    return render(request, 'dashboard/job_detail.html', context)

@login_required
def job_status(request, job_id):
    """
    AJAX endpoint to get the current status of a job
    """
    try:
        job = ScrapingJob.objects.get(id=job_id)
        return JsonResponse({
            'status': job.status,
            'started_at': job.started_at.isoformat() if job.started_at else None,
            'completed_at': job.completed_at.isoformat() if job.completed_at else None,
            'deals_scraped': job.deals_scraped,
            'log_output': job.log_output
        })
    except ScrapingJob.DoesNotExist:
        return JsonResponse({'error': 'Job not found'}, status=404)

@login_required
def stop_job(request, job_id):
    """
    Stop a running job with immediate process termination
    """
    if request.method == 'POST':
        try:
            job = ScrapingJob.objects.get(id=job_id)
            
            # First, mark the job as stopped in the database
            if job.status == 'running' or job.status == 'pending':
                job.stop_job()
                
            # Get access to the running scraper if possible
            try:
                from scraper.scrapers.base_scraper import BaseScraper
                scraper_instance = BaseScraper.get_scraper(job.id)
                
                if scraper_instance:
                    # Directly trigger emergency shutdown
                    scraper_instance._emergency_shutdown()
                    messages.success(request, f"Job {job_id} has been forcefully terminated. All related processes have been killed.")
                else:
                    # Try to kill any Chrome/chromedriver processes that might be related to the job
                    try:
                        import subprocess
                        import sys
                        import os
                        
                        # Use system commands to kill processes based on the platform
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
                            
                        # Add a log entry about the force kill attempt
                        job.log_output += f"\nForce-kill attempt on all Chrome/chromedriver processes at {timezone.now().strftime('%Y-%m-%d %H:%M:%S')}"
                        job.save()
                        
                        messages.success(request, f"Job {job_id} has been stopped. Attempted to terminate all Chrome/chromedriver processes.")
                    except Exception as e:
                        job.log_output += f"\nError during force-kill attempt: {str(e)}"
                        job.save()
                        messages.warning(request, f"Job {job_id} has been stopped but couldn't terminate all processes: {str(e)}")
            except Exception as e:
                # Fall back to regular stopping if direct access fails
                job.log_output += f"\nError during job termination: {str(e)}"
                job.save()
                messages.warning(request, f"Job {job_id} has been marked as stopped, but could not directly terminate processes: {str(e)}")
                    
            return redirect('job_detail', job_id=job_id)
        except ScrapingJob.DoesNotExist:
            messages.error(request, f"Job {job_id} not found.")
            return redirect('dashboard')
    else:
        return HttpResponseNotAllowed(['POST'])