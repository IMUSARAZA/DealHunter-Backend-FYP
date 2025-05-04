from django.contrib import admin
from .models import Bank, City, ScrapingJob

@admin.register(Bank)
class BankAdmin(admin.ModelAdmin):
    list_display = ('name', 'scraper_class', 'city_count')
    search_fields = ('name',)
    
    def city_count(self, obj):
        return obj.cities.count()
    city_count.short_description = 'Cities'

@admin.register(City)
class CityAdmin(admin.ModelAdmin):
    list_display = ('name', 'bank')
    list_filter = ('bank',)
    search_fields = ('name',)

@admin.register(ScrapingJob)
class ScrapingJobAdmin(admin.ModelAdmin):
    list_display = ('id', 'bank', 'city', 'status', 'created_at', 'started_at', 'completed_at', 'deals_scraped')
    list_filter = ('status', 'bank', 'city')
    search_fields = ('bank__name', 'city__name')
    readonly_fields = ('created_at', 'started_at', 'completed_at', 'deals_scraped', 'log_output')
    date_hierarchy = 'created_at'
    
    fieldsets = (
        (None, {
            'fields': ('bank', 'city', 'status')
        }),
        ('Scheduling', {
            'fields': ('scheduled_for',)
        }),
        ('Results', {
            'fields': ('deals_scraped',)
        }),
        ('Timestamps', {
            'fields': ('created_at', 'started_at', 'completed_at'),
            'classes': ('collapse',)
        }),
        ('Logs', {
            'fields': ('log_output',),
            'classes': ('collapse',)
        }),
    )
    
    def has_delete_permission(self, request, obj=None):
        # Prevent deletion of running jobs
        if obj and obj.status == 'running':
            return False
        return super().has_delete_permission(request, obj)