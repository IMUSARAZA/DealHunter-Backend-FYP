# Bridge module to maintain compatibility with existing code
from scraper.scrapers.hbl_scraper import HBLScraper

# Re-export the class with the same name
__all__ = ['HBLScraper'] 