# Deal Hunter - Bank Deals Scraper

A Django application that scrapes deals and offers from Pakistani bank websites.

## Overview

Deal Hunter scrapes and aggregates discount deals and offers from various Pakistani banks. The scraped data is stored in Firebase Firestore and displayed through a Django dashboard.

## Features

- **Multiple Bank Support**: Scrapes deals from HBL, MCB, UBL, and Meezan Bank
- **Job Management**: Create, schedule, monitor, and stop scraping jobs
- **Dashboard**: View scraping statistics and results
- **Firebase Integration**: Store and organize scraped data in Firestore
- **Categorization**: Automatically categorize deals using a machine learning model

## Requirements

- Python 3.8+
- Django 4.2+
- Chrome/Chromium browser (for Selenium)
- Firebase account (for data storage)

## Installation

1. Clone the repository
2. Create a virtual environment:
   ```bash
   python -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   ```
3. Install the dependencies:
   ```bash
   pip install -r requirements.txt
   ```
4. Configure Firebase:
   - Create a Firebase project
   - Generate a service account key (JSON file)
   - Save the key file securely and update the path in `settings.py`

5. Run migrations:
   ```bash
   python manage.py migrate
   ```
6. Create a superuser:
   ```bash
   python manage.py createsuperuser
   ```
7. Run the development server:
   ```bash
   python manage.py runserver
   ```

## Running Scrapers

### From the Dashboard

1. Log in to the admin dashboard
2. Navigate to a bank's detail page
3. Select a city and click "Start Scraping" or "Schedule Job"
4. Monitor the job progress from the job detail page

### From the Command Line

```bash
python manage.py shell

# Run HBL scraper
from scraper.scrapers.hbl_scraper import HBLScraper
scraper = HBLScraper("HBL", "Karachi")
scraper.run()

# Run MCB scraper
from scraper.scrapers.mcb_scraper import MCBScraper
scraper = MCBScraper("MCB", "Karachi")
scraper.run()

# Run UBL scraper
from scraper.scrapers.ubl_scraper import UBLScraper
scraper = UBLScraper("UBL", "Karachi")
scraper.run()

# Run Meezan Bank scraper
from scraper.scrapers.meezan_scraper import MeezanScraper
scraper = MeezanScraper("Meezan Bank", "Karachi")
scraper.run()
```

## Creating New Scrapers

To add a new bank scraper:

1. Create a new scraper class file in `scraper/scrapers/` by copying `template_scraper.py`
2. Name the file appropriately, e.g., `bank_name_scraper.py`
3. Implement the bank-specific scraping logic
4. Add the bank to the database:
   ```bash
   python manage.py shell
   from dashboard.models import Bank
   Bank.objects.create(name="Bank Name", scraper_class="BankNameScraper")
   ```

## Adding Cities

```bash
python manage.py shell
from dashboard.models import Bank, City
bank = Bank.objects.get(name="Bank Name")
City.objects.create(name="City Name", bank=bank)
```

## Troubleshooting

### Selenium Issues

If ChromeDriver fails to start:
- Ensure Chrome/Chromium is installed
- The application uses `webdriver_manager` to automatically download the correct ChromeDriver version

### Firebase Issues

If Firebase connection fails:
- Check that your Firebase credentials file exists and is correctly referenced
- Verify that your Firebase project has Firestore enabled
- The application has a fallback mode when Firebase is unavailable

## License

This project is licensed under the MIT License - see the LICENSE file for details. 