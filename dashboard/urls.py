from django.urls import path
from django.contrib.auth import views as auth_views
from . import views

urlpatterns = [
    path('', views.dashboard, name='dashboard'),
    path('bank/<int:bank_id>/', views.bank_detail, name='bank_detail'),
    path('bank/<int:bank_id>/edit/', views.edit_bank, name='edit_bank'),
    path('bank/<int:bank_id>/delete/', views.delete_bank, name='delete_bank'),
    path('bank/<int:bank_id>/scrape/', views.start_scraping, name='start_scraping'),
    path('bank/<int:bank_id>/city/<int:city_id>/scrape/', views.start_scraping, name='start_scraping_city'),
    path('bank/<int:bank_id>/schedule/', views.schedule_job, name='schedule_job'),
    path('bank/<int:bank_id>/city/<int:city_id>/schedule/', views.schedule_job, name='schedule_job_city'),
    path('job/<int:job_id>/', views.job_detail, name='job_detail'),
    path('job/<int:job_id>/status/', views.job_status, name='job_status'),
    path('job/<int:job_id>/stop/', views.stop_job, name='stop_job'),
    
    # Authentication URLs
    path('login/', auth_views.LoginView.as_view(template_name='dashboard/login.html'), name='login'),
    path('logout/', auth_views.LogoutView.as_view(), name='logout'),
]