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

class UBLScraper(BaseScraper):
    """
    UBL Bank scraper class
    """
    def __init__(self, bank_name, city_name, job=None):
        super().__init__(bank_name, city_name, job)
        self.deal_count = 0
        self.google_maps_api_key = os.environ.get('GOOGLE_MAPS_API_KEY', 'AIzaSyD50GtOZaBtYyC4cRas2XXNsMxfoil5hyY')
        
        # Load the classifier model
        self.model = None
        self.vectorizer = None
        self.load_classifier_model()
        
        # Initialize analytics tracking
        self.analytics = {
            'total_deals_scraped': 0,
            'deals_by_category': defaultdict(int),
            'deals_by_card_type': defaultdict(int),
            'branches_count': 0,
            'offers_count': 0,
            'locations': set()  # Track unique locations
        }
        
        # Suppress TensorFlow logging
        tf.get_logger().setLevel('ERROR')
    
    def get_base_url(self):
        """Get the base URL for the bank and city"""
        # UBL Discounts and offers URL
        return "https://www.ubldigital.com/Cards/Discounts-/-Privileges"
    
    def load_classifier_model(self):
        """Load the deal classifier model"""
        try:
            # Try different paths for the improved model
            possible_paths = [
                # Direct project location
                os.path.join(settings.BASE_DIR, 'improved_deal_classifier_model.pkl'),
                # Models folder
                os.path.join(settings.BASE_DIR, 'scraper/models/improved_deal_classifier_model.pkl'),
                # Original hardcoded path
                '/Users/musa/Desktop/dealHunterScrapper/improved_deal_classifier_model.pkl',
                # Legacy filename path
                os.path.join(settings.BASE_DIR, 'scraper/models/deal_classifier_model.pkl')
            ]
            
            # Try each path
            model_path = None
            for path in possible_paths:
                if os.path.exists(path):
                    model_path = path
                    break
                
            if model_path:
                self.log(f"Loading classifier model from: {model_path}")
                with open(model_path, 'rb') as f:
                    self.model, self.vectorizer = pickle.load(f)
                self.log(f"Classifier model loaded successfully from {model_path}")
            else:
                self.log("Warning: Could not find any classifier model file. Category prediction will be limited.")
                self.model = None
                self.vectorizer = None
        except Exception as e:
            self.log(f"Error loading classifier model: {str(e)}")
            self.model = None
            self.vectorizer = None
    
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
    
    def scrape_offer_page(self, offer_link, retry_attempts=3):
        """Scrape details from an offer page"""
        for attempt in range(retry_attempts):
            try:
                # Check if job was cancelled
                if self.maybe_check_if_cancelled():
                    self.log("Job cancelled during offer page scraping")
                    return None
                
                self.driver.get(offer_link)
                self.log(f"Navigated to offer page: {offer_link}")
                
                # Wait for content to load
                WebDriverWait(self.driver, 10).until(
                    EC.presence_of_element_located((By.CSS_SELECTOR, "div.main-content"))
                )
                
                # Check cancellation again after page load
                if self.maybe_check_if_cancelled():
                    self.log("Job cancelled after loading offer page")
                    return None
                
                # Get offer details
                soup = BeautifulSoup(self.driver.page_source, 'html.parser')
                
                # Extract offer title
                title_element = soup.select_one('h1.offer-title, h2.offer-title, div.offer-heading')
                title = title_element.text.strip() if title_element else "Unnamed Offer"
                
                # Extract offer description
                desc_element = soup.select_one('div.offer-description, div.offer-details')
                description = desc_element.text.strip() if desc_element else ""
                
                # Extract discount percentage (if available)
                discount_element = soup.select_one('span.discount-percentage, div.discount-value')
                discount = discount_element.text.strip() if discount_element else "Special Offer"
                
                # If discount doesn't contain a percentage, try to extract it from the title or description
                if "%" not in discount:
                    # Try to find a percentage in the title or description
                    import re
                    percentage_match = re.search(r'(\d+)%', title + " " + description)
                    if percentage_match:
                        discount = percentage_match.group(0)
                    else:
                        discount = "Special Offer"
                
                # Extract image URL
                image_element = soup.select_one('img.offer-image, div.offer-banner img')
                image_url = image_element['src'] if image_element and 'src' in image_element.attrs else ""
                
                # Make image URL absolute if it's relative
                if image_url and not image_url.startswith(('http://', 'https://')):
                    base_url = self.get_base_url()
                    image_url = f"{base_url.rstrip('/')}/{image_url.lstrip('/')}"
                
                # Extract terms and conditions
                terms_element = soup.select_one('div.terms-conditions, div.offer-terms')
                terms = terms_element.text.strip() if terms_element else "Terms and conditions apply."
                
                # Extract locations/branches
                branches = []
                branch_elements = soup.select('div.branch-location, div.offer-location')
                
                if branch_elements:
                    for branch_elem in branch_elements:
                        branch_name = branch_elem.select_one('h3, h4, strong').text.strip()
                        branch_address = branch_elem.select_one('p, div.address').text.strip()
                        
                        # Get coordinates for the branch
                        coordinates = self.get_lat_lng(branch_address)
                        
                        branches.append({
                            'name': branch_name,
                            'address': branch_address,
                            'latitude': coordinates['latitude'],
                            'longitude': coordinates['longitude']
                        })
                else:
                    # If no specific branches are listed, assume it's available at all branches
                    branches.append({
                        'name': f"All {self.bank_name} Branches",
                        'address': f"{self.city_name}, Pakistan",
                        'latitude': 0.0,
                        'longitude': 0.0
                    })
                
                # Create offer object
                offers = [{
                    'title': title,
                    'description': description,
                    'discount': discount,
                    'terms': terms,
                    'image_url': image_url,
                    'branches': branches
                }]
                
                # Predict category
                category = self.predict_category(title + " " + description)
                
                # Create unique deal ID
                import hashlib
                deal_id = hashlib.md5(f"{self.bank_name}_{self.city_name}_{title}".encode()).hexdigest()
                
                # Create deal data object
                deal_data = {
                    'deal_id': deal_id,
                    'title': title,
                    'deal_description': description,
                    'discount': discount,
                    'image_url': image_url,
                    'icon_url': image_url,  # Use same image for icon
                    'category_id': category,
                    'offers': offers,
                    'deal_branches': branches,
                    'terms_and_conditions': terms
                }
                
                return deal_data
                
            except Exception as e:
                self.log(f"Error scraping offer (attempt {attempt+1}/{retry_attempts}): {str(e)}")
                if attempt < retry_attempts - 1:
                    time.sleep(2)  # Wait before retrying
                else:
                    self.log(f"Failed to scrape offer after {retry_attempts} attempts")
                    return None
    
    def insert_deal_data(self, deal_data):
        """Insert a deal into Firestore"""
        try:
            # If Firebase is not available, just log the deal
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

            # Create maps with enhanced branch data including location and full address
            offers_map = {f'offer_{i+1}': offer for i, offer in enumerate(deal_data['offers'])}
            
            # Create map for all combined branches across all offers
            deal_branches_map = {f'branch_{i+1}': branch for i, branch in enumerate(deal_data['deal_branches'])}

            # Generate random avgSentiment with 1 decimal place
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

            # Update analytics
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
            # If Firebase is not available, just log the analytics summary
            if self.db is None:
                self.log("Firebase not available. Analytics summary (simulation mode):")
                self.log(f"- Total deals scraped: {self.analytics['total_deals_scraped']}")
                self.log(f"- Unique deals by category: {len(self.analytics['deals_by_category'])}")
                self.log(f"- Total branches: {self.analytics['branches_count']}")
                self.log(f"- Total offers: {self.analytics['offers_count']}")
                return
                
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            
            # Reference to analytics collection
            analytics_ref = self.db.collection('Banks').document(self.bank_name).collection('Analytics').document(self.city_name)
            
            # Convert defaultdict to regular dict for Firebase
            deals_by_category = dict(self.analytics['deals_by_category'])
            deals_by_card_type = dict(self.analytics['deals_by_card_type'])
            
            # Create analytics data document
            analytics_data = {
                'timestamp': timestamp,
                'total_deals_scraped': self.analytics['total_deals_scraped'],
                'deals_by_category': deals_by_category,
                'deals_by_card_type': deals_by_card_type,
                'branches_count': self.analytics['branches_count'],
                'offers_count': self.analytics['offers_count'],
                'unique_locations_count': len(self.analytics['locations'])
            }
            
            # Store analytics in Firebase
            analytics_ref.set(analytics_data, merge=True)
            
            self.log(f"Analytics data updated in Firebase for {self.bank_name} - {self.city_name}")
        except Exception as e:
            self.log(f"Error updating analytics: {str(e)}")
    
    def scrape_card(self, card_element, idx, total_cards):
        """Scrape data from a single deal card"""
        try:
            # Check if job was cancelled
            if self.maybe_check_if_cancelled():
                self.log("Job cancelled, stopping scraper")
                return None
                
            # Log progress
            self.log(f"Processing deal card {idx} of {total_cards} ({int(idx/total_cards*100)}% complete)")
            
            # Extract title
            title_element = card_element.select_one('h3.card-title, div.offer-title')
            title = title_element.text.strip() if title_element else "Unnamed Deal"
            
            # Extract link to detail page
            link_element = card_element.select_one('a.card-link, a.offer-link')
            if not link_element or 'href' not in link_element.attrs:
                self.log(f"No detail link found for card {idx}, skipping")
                return None
                
            detail_link = link_element['href']
            
            # Make link absolute if it's relative
            if not detail_link.startswith(('http://', 'https://')):
                base_url = self.get_base_url()
                if '/' in base_url:
                    base_domain = base_url.split('/')[0] + '//' + base_url.split('/')[2]
                    detail_link = f"{base_domain}/{detail_link.lstrip('/')}"
                else:
                    detail_link = f"{base_url.rstrip('/')}/{detail_link.lstrip('/')}"
            
            self.log(f"Found deal '{title}' with detail link: {detail_link}")
            
            # Scrape the detail page
            deal_data = self.scrape_offer_page(detail_link)
            
            if deal_data and self.insert_deal_data(deal_data):
                self.deal_count += 1
                self.log(f"Successfully scraped and inserted deal #{self.deal_count}: {title}")
                return deal_data
            
            return None
            
        except Exception as e:
            self.log(f"Error scraping card {idx}: {str(e)}")
            return None
    
    def scrape(self):
        """
        Main scraping method that implements the core scraping logic
        Returns the number of deals scraped
        """
        self.log(f"Starting scraping for {self.bank_name} - {self.city_name}")
        
        base_url = self.get_base_url()
        self.log(f"Base URL: {base_url}")
        
        try:
            self.driver.get(base_url)
            self.log("Page loaded successfully")
            
            # Wait for the deals to load
            WebDriverWait(self.driver, 10).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, "div.offer-card, div.discount-card"))
            )
            
            # Check cancellation after initial page load
            if self.maybe_check_if_cancelled():
                self.log("Job cancelled after loading initial page")
                return self.deal_count
            
            # Get all deal cards
            soup = BeautifulSoup(self.driver.page_source, 'html.parser')
            cards = soup.select('div.offer-card, div.discount-card, div.privilege-card')
            
            if not cards:
                self.log("No deal cards found. Trying alternative selectors...")
                cards = soup.select('div.offer, div.discount, div.privilege')
            
            total_cards = len(cards)
            self.log(f"Found {total_cards} deal cards")
            
            # Process each card
            for idx, card in enumerate(cards, 1):
                # Check if job was cancelled
                if self.maybe_check_if_cancelled():
                    self.log("Job cancelled, stopping scraper")
                    return self.deal_count
                    
                self.scrape_card(card, idx, total_cards)
                
                # Add a small delay between requests to avoid overloading the server
                time.sleep(random.uniform(1, 3))
            
            # Update analytics after all deals are scraped
            self.update_analytics()
            
            self.log(f"Completed scraping for {self.bank_name} - {self.city_name}. Total deals scraped: {self.deal_count}")
            return self.deal_count
            
        except Exception as e:
            error_msg = f"Error during scraping: {str(e)}\n{traceback.format_exc()}"
            self.log(error_msg)
            raise 