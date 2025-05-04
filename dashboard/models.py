from django.db import models
from django.utils import timezone

class Bank(models.Model):
    name = models.CharField(max_length=100)
    logo = models.ImageField(upload_to='bank_logos/', blank=True, null=True)
    website_url = models.URLField(blank=True, null=True)
    scraper_class = models.CharField(max_length=100, help_text="The Python class name of the scraper for this bank")
    
    def __str__(self):
        return self.name

class City(models.Model):
    name = models.CharField(max_length=100)
    bank = models.ForeignKey(Bank, related_name='cities', on_delete=models.CASCADE)
    
    class Meta:
        verbose_name_plural = 'Cities'
        unique_together = ('name', 'bank')
    
    def __str__(self):
        return f"{self.name} - {self.bank.name}"

class ScrapingJob(models.Model):
    STATUS_CHOICES = (
        ('pending', 'Pending'),
        ('running', 'Running'),
        ('completed', 'Completed'),
        ('failed', 'Failed'),
        ('stopped', 'Stopped'),
    )
    
    bank = models.ForeignKey(Bank, on_delete=models.CASCADE)
    city = models.ForeignKey(City, on_delete=models.CASCADE)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    created_at = models.DateTimeField(auto_now_add=True)
    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    scheduled_for = models.DateTimeField(null=True, blank=True)
    deals_scraped = models.IntegerField(default=0)
    log_output = models.TextField(blank=True)
    process_id = models.IntegerField(null=True, blank=True, help_text="The PID of the process running this job")
    
    def __str__(self):
        return f"{self.bank.name} - {self.city.name} ({self.get_status_display()})"
    
    def start_job(self):
        """Mark a job as started and record the current process ID"""
        import os
        self.status = 'running'
        self.started_at = timezone.now()
        self.process_id = os.getpid()  # Store current process ID
        self.save()
    
    def complete_job(self, deals_count):
        self.status = 'completed'
        self.completed_at = timezone.now()
        self.deals_scraped = deals_count
        self.save()
    
    def fail_job(self, error_log):
        self.status = 'failed'
        self.completed_at = timezone.now()
        self.log_output = error_log
        self.save()
    
    def stop_job(self):
        """Stop a running job and mark it as stopped with a user-initiated message"""
        if self.status == 'running' or self.status == 'pending':
            previous_status = self.status
            self.status = 'stopped'  # Change from 'failed' to 'stopped'
            self.completed_at = timezone.now()
            self.log_output += f"\n---------------\nJob was manually stopped by user at {timezone.now().strftime('%Y-%m-%d %H:%M:%S')}"
            self.log_output += f"\nPrevious status: {previous_status}"
            self.log_output += f"\nAny ongoing operations will be terminated."
            
            # If we have a process ID, try to terminate it
            if self.process_id:
                try:
                    import os
                    import signal
                    self.log_output += f"\nAttempting to terminate process {self.process_id}"
                    os.kill(self.process_id, signal.SIGTERM)
                except Exception as e:
                    self.log_output += f"\nFailed to terminate process: {str(e)}"
            
            self.save()
            return True
        return False
        
    class Meta:
        ordering = ['-created_at']