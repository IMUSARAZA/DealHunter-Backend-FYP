import tensorflow as tf
import firebase_admin
from firebase_admin import credentials, firestore
import time
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.common.exceptions import TimeoutException
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from bs4 import BeautifulSoup
import pickle
import requests
import os
import random
import sys
import traceback
from datetime import datetime
from collections import defaultdict, Counter
from webdriver_manager.chrome import ChromeDriverManager
from .base_scraper import BaseScraper
from django.conf import settings
import logging
from dashboard.models import ScrapingJob

logger = logging.getLogger(__name__)

class TemplateScraper(BaseScraper):
    """Template scraper class for new banks"""
    def __init__(self, bank_name, city_name, job=None):
        super().__init__(bank_name, city_name, job)
        self.deal_count = 0
        self.google_maps_api_key = os.environ.get('GOOGLE_MAPS_API_KEY', 'AIzaSyD50GtOZaBtYyC4cRas2XXNsMxfoil5hyY')
        
        self.model = None
        self.vectorizer = None
        self.load_classifier_model()
        
        self.analytics = {
            'total_deals_scraped': 0,
            'deals_by_category': defaultdict(int),
            'deals_by_card_type': defaultdict(int),
            'branches_count': 0,
            'offers_count': 0,
            'locations': set()
        }
        
        tf.get_logger().setLevel('ERROR')
    
    def get_base_url(self):
        """Get the base URL for the bank and city"""
        city_lower = self.city_name.lower()
        return f"https://bank-web.peekaboo.guru/{city_lower}/places/_all/all"
    
    def load_classifier_model(self):
        """Load the deal classifier model"""
        try:
            model_path = os.path.join(settings.BASE_DIR, 'scraper/models/deal_classifier_model.pkl')
            
            if not os.path.exists(model_path):
                model_path = '/Users/musa/Desktop/dealHunterScrapper/improved_deal_classifier_model.pkl'
                
            if os.path.exists(model_path):
                with open(model_path, 'rb') as f:
                    self.model, self.vectorizer = pickle.load(f)
                self.log(f"Classifier model loaded successfully from {model_path}")
            else:
                self.log("Warning: Could not find classifier model file")
        except Exception as e:
            self.log(f"Error loading classifier model: {str(e)}")
    
    def predict_category(self, deal_name):
        """Predict the category of a deal based on its name"""
        if self.model is None or self.vectorizer is None:
            return "uncategorized"
        
        try:
            deal_name_tfidf = self.vectorizer.transform([deal_name])
            category = self.model.predict(deal_name_tfidf)
            return category[0]
        except Exception as e:
            self.log(f"Error predicting category: {str(e)}")
            return "uncategorized"
    
    def get_lat_lng(self, address):
        """Get latitude and longitude from address using Google Maps API"""
        try:
            address_with_city = f"{address}, {self.city_name}, Pakistan"
            params = {
                'address': address_with_city,
                'key': self.google_maps_api_key
            }
            response = requests.get('https://maps.googleapis.com/maps/api/geocode/json', params=params)
            data = response.json()
            
            if data['status'] == 'OK':
                location = data['results'][0]['geometry']['location']
                return {
                    'latitude': location['lat'],
                    'longitude': location['lng']
                }
            else:
                self.log(f"Geocoding API error: {data['status']}")
                return {
                    'latitude': 0.0,
                    'longitude': 0.0
                }
        except Exception as e:
            self.log(f"Error getting location data: {str(e)}")
            return {
                'latitude': 0.0,
                'longitude': 0.0
            }
    
    def scrape_offer_page(self, card_link, retry_attempts=3):
        """Scrape details from an offer page"""
        pass
    
    def insert_deal_data(self, deal_data):
        """Insert a deal into Firestore"""
        try:
            if self.db is None:
                self.log(f"Firebase not available. Deal '{deal_data['title']}' would be inserted (simulation mode).")
                self.analytics['total_deals_scraped'] += 1
                self.analytics['deals_by_category'][deal_data['category_id']] += 1
                self.analytics['offers_count'] += len(deal_data['offers'])
                self.analytics['branches_count'] += len(deal_data['deal_branches'])
                return True
                
            bank_ref = self.db.collection('Banks').document(self.bank_name)
            city_ref = bank_ref.collection('Cities').document(self.city_name)
            deal_ref = city_ref.collection('Deals').document(deal_data['deal_id'])

            bank_ref.set({'name': self.bank_name}, merge=True)
            city_ref.set({'name': self.city_name}, merge=True)

            offers_map = {f'offer_{i+1}': offer for i, offer in enumerate(deal_data['offers'])}
            deal_branches_map = {f'branch_{i+1}': branch for i, branch in enumerate(deal_data['deal_branches'])}
            avg_sentiment = round(random.uniform(3.0, 4.5), 1)

            deal_ref.set({
                'title': deal_data['title'],
                'description': deal_data['deal_description'],
                'discount': deal_data['discount'],
                'image_url': deal_data['image_url'],
                'icon_url': deal_data['icon_url'],
                'category_id': deal_data['category_id'],
                'bank_id': self.bank_name,
                'city_id': self.city_name,
                'offers': offers_map,
                'deal_branches': deal_branches_map,
                'terms_and_conditions': deal_data['terms_and_conditions'],
                'avgSentiment': avg_sentiment
            })

            self.analytics['total_deals_scraped'] += 1
            self.analytics['deals_by_category'][deal_data['category_id']] += 1
            self.analytics['offers_count'] += len(deal_data['offers'])
            self.analytics['branches_count'] += len(deal_data['deal_branches'])

            self.log(f"Deal '{deal_data['title']}' inserted into Firestore.")
            return True
        except Exception as e:
            self.log(f"Error inserting deal data: {str(e)}")
            return False
    
    def update_analytics(self):
        """Update analytics in Firebase"""
        try:
            if self.db is None:
                self.log("Firebase not available. Analytics summary (simulation mode):")
                self.log(f"- Total deals scraped: {self.analytics['total_deals_scraped']}")
                self.log(f"- Unique deals by category: {len(self.analytics['deals_by_category'])}")
                self.log(f"- Total branches: {self.analytics['branches_count']}")
                self.log(f"- Total offers: {self.analytics['offers_count']}")
                return
                
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            
            analytics_ref = self.db.collection('Banks').document(self.bank_name).collection('Analytics').document(self.city_name)
            
            deals_by_category = dict(self.analytics['deals_by_category'])
            deals_by_card_type = dict(self.analytics['deals_by_card_type'])
            
            analytics_data = {
                'timestamp': timestamp,
                'total_deals_scraped': self.analytics['total_deals_scraped'],
                'deals_by_category': deals_by_category,
                'deals_by_card_type': deals_by_card_type,
                'branches_count': self.analytics['branches_count'],
                'offers_count': self.analytics['offers_count'],
                'unique_locations_count': len(self.analytics['locations'])
            }
            
            analytics_ref.set(analytics_data, merge=True)
            
            self.log(f"Analytics data updated in Firebase for {self.bank_name} - {self.city_name}")
        except Exception as e:
            self.log(f"Error updating analytics: {str(e)}")
    
    def scrape_card(self, card, idx, total_cards):
        """Scrape data from a single deal card"""
        pass
    
    def scrape(self):
        """Main scraping method that implements the core scraping logic"""
        self.log(f"Starting scraping for {self.bank_name} - {self.city_name}")
        
        base_url = self.get_base_url()
        self.log(f"Base URL: {base_url}")
        
        try:
            self.driver.get(base_url)
            self.log("Page loaded successfully")
            
            # Implement bank-specific scraping logic here
            # Make sure to periodically check for cancellation:
            # if self.check_if_cancelled():
            #     self.log("Job cancelled, stopping scraper")
            #     return self.deal_count
            
            self.update_analytics()
            
            self.log(f"Scraping completed. {self.deal_count} deals scraped.")
            return self.deal_count
            
        except Exception as e:
            error_msg = f"Error during scraping: {str(e)}\n{traceback.format_exc()}"
            self.log(error_msg)
            raise 