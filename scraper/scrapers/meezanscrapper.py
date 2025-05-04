# Bridge module to maintain compatibility with "meezanscrapper" spelling
from scraper.scrapers.meezan_scraper import MeezanScraper

# Create an alias with the double 'p' spelling that matches what's in the database
MeezanScrapper = MeezanScraper

# Export the class name that the system is looking for
__all__ = ['MeezanScrapper'] 