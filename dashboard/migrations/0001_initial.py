# Generated by Django 4.2.8 on 2025-03-24 22:00

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    initial = True

    dependencies = [
    ]

    operations = [
        migrations.CreateModel(
            name='Bank',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=100)),
                ('logo', models.ImageField(blank=True, null=True, upload_to='bank_logos/')),
                ('website_url', models.URLField(blank=True, null=True)),
                ('scraper_class', models.CharField(help_text='The Python class name of the scraper for this bank', max_length=100)),
            ],
        ),
        migrations.CreateModel(
            name='City',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=100)),
                ('bank', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='cities', to='dashboard.bank')),
            ],
            options={
                'verbose_name_plural': 'Cities',
                'unique_together': {('name', 'bank')},
            },
        ),
        migrations.CreateModel(
            name='ScrapingJob',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('status', models.CharField(choices=[('pending', 'Pending'), ('running', 'Running'), ('completed', 'Completed'), ('failed', 'Failed')], default='pending', max_length=20)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('started_at', models.DateTimeField(blank=True, null=True)),
                ('completed_at', models.DateTimeField(blank=True, null=True)),
                ('scheduled_for', models.DateTimeField(blank=True, null=True)),
                ('deals_scraped', models.IntegerField(default=0)),
                ('log_output', models.TextField(blank=True)),
                ('bank', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='dashboard.bank')),
                ('city', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='dashboard.city')),
            ],
            options={
                'ordering': ['-created_at'],
            },
        ),
    ]
