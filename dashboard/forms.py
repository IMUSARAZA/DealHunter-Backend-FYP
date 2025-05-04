from django import forms
from django.utils import timezone
from .models import City, ScrapingJob, Bank

class BankForm(forms.ModelForm):
    """
    Form for creating and editing banks
    """
    class Meta:
        model = Bank
        fields = ['name', 'logo', 'website_url', 'scraper_class']
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-control'}),
            'logo': forms.FileInput(attrs={'class': 'form-control'}),
            'website_url': forms.URLInput(attrs={'class': 'form-control'}),
            'scraper_class': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'e.g. MeezanScraper'})
        }
        help_texts = {
            'scraper_class': 'The exact class name of the scraper (case sensitive, no underscores)'
        }

class ScrapingJobForm(forms.Form):
    """
    Form for creating a new scraping job
    """
    city = forms.ModelChoiceField(
        queryset=City.objects.none(),
        empty_label="Select a city",
        widget=forms.Select(attrs={'class': 'form-select'}),
        required=True
    )
    
    def __init__(self, *args, **kwargs):
        bank_id = kwargs.pop('bank_id', None)
        super(ScrapingJobForm, self).__init__(*args, **kwargs)
        
        if bank_id:
            self.fields['city'].queryset = City.objects.filter(bank_id=bank_id)

class ScheduleJobForm(forms.Form):
    """
    Form for scheduling a scraping job
    """
    city = forms.ModelChoiceField(
        queryset=City.objects.none(),
        empty_label="Select a city",
        widget=forms.Select(attrs={'class': 'form-select'})
    )
    
    scheduled_for = forms.DateTimeField(
        widget=forms.DateTimeInput(
            attrs={'type': 'datetime-local', 'class': 'form-control'},
            format='%Y-%m-%dT%H:%M'
        ),
        input_formats=['%Y-%m-%dT%H:%M'],
        help_text="Select the date and time to run the scraper"
    )
    
    def __init__(self, *args, **kwargs):
        bank_id = kwargs.pop('bank_id', None)
        super(ScheduleJobForm, self).__init__(*args, **kwargs)
        
        if bank_id:
            self.fields['city'].queryset = City.objects.filter(bank_id=bank_id)
    
    def clean_scheduled_for(self):
        scheduled_for = self.cleaned_data['scheduled_for']
        now = timezone.now()
        
        if scheduled_for < now:
            raise forms.ValidationError("Scheduled time must be in the future")
        
        return scheduled_for