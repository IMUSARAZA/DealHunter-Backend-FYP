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

def get_firebase_credentials_path():
    """Get the path to Firebase credentials, checking multiple possible locations"""
    # Check the settings path first
    if hasattr(settings, 'FIREBASE_CREDENTIALS_PATH') and os.path.exists(settings.FIREBASE_CREDENTIALS_PATH):
        return settings.FIREBASE_CREDENTIALS_PATH
    
    # Check common paths
    possible_paths = [
        '/Users/musa/Desktop/dealHunterScrapper/dealhunter-490d3-firebase-adminsdk-fbsvc-ce5ba25c59.json',
        os.path.join(settings.BASE_DIR, 'firebase-credentials.json'),
        os.path.join(settings.BASE_DIR, 'dealhunter-490d3-firebase-adminsdk-fbsvc-ce5ba25c59.json')
    ]
    
    for path in possible_paths:
        if os.path.exists(path):
            return path
    
    return None

class MeezanScraper(BaseScraper):
    """
    Scraper for Meezan Bank deals
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
        """Get the base URL for Meezan bank and city"""
        # Convert city name to lowercase for URL
        city_lower = self.city_name.lower()
        return f"https://meezan-web.peekaboo.guru/{city_lower}/places/_all/all"
    
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
    
    def get_full_description(self, driver):
        """Get the full description text from a deal page"""
        try:
            # Wait for description container to be present
            description_container = WebDriverWait(driver, 10).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, "div.ExpandableText__Text-sc-5hhsud-0"))
            )
            
            # Check if "Show more" exists
            try:
                show_more_button = WebDriverWait(driver, 5).until(
                    EC.element_to_be_clickable((By.XPATH, "//a[.//span[text()='Show more']]"))
                )
                
                self.log("Found 'Show more' button, clicking to expand description")
                # Scroll into view and click using JavaScript
                driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", show_more_button)
                time.sleep(0.5)
                driver.execute_script("arguments[0].click();", show_more_button)
                
                # Wait for text to expand
                time.sleep(2)  # Give it time to expand
                
                # Get the expanded text
                description_container = WebDriverWait(driver, 10).until(
                    EC.presence_of_element_located((By.CSS_SELECTOR, "div.ExpandableText__Text-sc-5hhsud-0"))
                )
            except TimeoutException:
                self.log("No 'Show more' button found or already expanded")
            
            # Get the updated text directly from the WebElement
            full_text = driver.execute_script("""
                const div = arguments[0];
                const clone = div.cloneNode(true);
                // Remove any "Show more" or "Show less" links
                Array.from(clone.querySelectorAll('a.ExpandableText__Link-sc-5hhsud-1')).forEach(a => a.remove());
                return clone.textContent.trim();
            """, description_container)
            
            self.log(f"Got description with length: {len(full_text)} characters")
            return full_text
            
        except Exception as e:
            self.log(f"Error getting description: {str(e)}")
            return ""
    
    def scrape_offer_page(self, card_link, retry_attempts=3):
        """Scrape details from an offer page"""
        for attempt in range(retry_attempts):
            try:
                self.log(f"Scraping offer page: {card_link}")
                
                # Open the offer page in a new tab
                self.driver.execute_script("window.open(arguments[0], '_blank');", card_link)
                time.sleep(5)  # Wait for the new tab to load

                # Switch to the new tab
                self.driver.switch_to.window(self.driver.window_handles[-1])

                soup = BeautifulSoup(self.driver.page_source, 'html.parser')

                deal_description = self.get_full_description(self.driver)
                
                # Extract offers, branches, etc.
                offersContainer = soup.find_all('div', class_='Styled__ListHolder-rxute-1 iAIrSk')
                offers = offersContainer[0].find_all('a', href=True) if offersContainer else []

                branchesContainer = soup.find_all('div', class_='Styled__ListHolder-sc-1oq0juy-2 ldNFd')
                branches = branchesContainer[0].find_all('div', class_='Styled__ListItem-sc-14n6kj-1 bjMUOR') if branchesContainer else []

                # List to store all branch locations from all offers
                all_deal_branches = []
                
                # Process offers
                offers_data = []
                terms_and_conditions = ""
                
                # Update progress
                if self.job:
                    self.job.log_output += f"\nProcessing deal details..."
                    self.job.save()
                
                for offer in offers:
                    # Check if job was cancelled
                    if self.maybe_check_if_cancelled():
                        self.log("Job cancelled, stopping scraper")
                        return [], [], [], "", ""
                        
                    offer_data = {}
                    try:
                        # Extract offer title
                        offer_data['title'] = offer.find('div', class_='Styled__PrimaryText-sc-14n6kj-7 bdZLUf').text.strip()
                    except AttributeError:
                        offer_data['title'] = None

                    try:
                        # Extract valid till date
                        spans = offer.find_all('span')
                        valid_till = None
                        for i in range(len(spans) - 1):
                            if spans[i].text.strip() == "Valid Till":
                                valid_till = spans[i + 1].text.strip()  # The next span contains the date
                                break
                        offer_data['valid_till'] = valid_till
                    except AttributeError:
                        offer_data['valid_till'] = None

                    try:
                        # Extract offer branches
                        offer_data['offer_branches'] = offer.find_all('span')[-2].text.strip()
                    except (AttributeError, IndexError):
                        offer_data['offer_branches'] = None

                    # Collect card types for this offer
                    offer_data['card_type'] = []
                    
                    offers_data.append(offer_data)
                
                # Prepare branches data
                branches_data = []
                for branch in branches:
                    branch_data = {}
                    try:
                        branch_data['branch_title'] = branch.find('p', class_='Styled__TertiaryText-sc-14n6kj-9 VfCfv').text.strip()
                        
                        # Get location data
                        location_data = self.get_lat_lng(branch_data['branch_title'])
                        branch_data['full_address'] = branch_data['branch_title']
                        branch_data['latitude'] = location_data['latitude']
                        branch_data['longitude'] = location_data['longitude']
                        
                        # Add to the combined list
                        if not any(b.get('name') == branch_data['branch_title'] for b in all_deal_branches):
                            all_deal_branches.append({
                                'name': branch_data['branch_title'],
                                'full_address': branch_data['branch_title'],
                                'latitude': location_data['latitude'],
                                'longitude': location_data['longitude']
                            })
                            
                    except (AttributeError, Exception) as e:
                        self.log(f"Error processing branch: {str(e)}")
                        branch_data['branch_title'] = None
                        branch_data['full_address'] = ""
                        branch_data['latitude'] = 0.0
                        branch_data['longitude'] = 0.0

                    branches_data.append(branch_data)
                
                # Close the current tab and switch back to the main tab
                self.driver.close()
                self.driver.switch_to.window(self.driver.window_handles[0])
                
                return offers_data, branches_data, all_deal_branches, terms_and_conditions, deal_description
                
            except Exception as e:
                self.log(f"Error processing offer page on attempt {attempt + 1}: {str(e)}")
                if attempt < retry_attempts - 1:
                    self.log("Retrying...")
                    time.sleep(3)
                else:
                    self.log("Max retries reached, skipping this offer page.")
                    # Close any remaining tabs and switch back to main tab
                    if len(self.driver.window_handles) > 1:
                        self.driver.switch_to.window(self.driver.window_handles[-1])
                        self.driver.close()
                        self.driver.switch_to.window(self.driver.window_handles[0])
                    return [], [], [], "", ""
    
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
    
    def scrape_card(self, card, idx, total_cards):
        """Scrape data from a single deal card"""
        retry_count = 3  
        for attempt in range(retry_count):
            try:
                # Update progress
                progress_pct = int((idx / total_cards) * 100)
                if self.job:
                    self.job.log_output += f"\nProcessing deal card {idx+1} of {total_cards} ({progress_pct}% complete)"
                    self.job.save()
                
                title = card.find('p', class_='Styled__CardHeaderTitle-ii87o4-9').text.strip()
                self.log(f"Processing card: {title}")

                discount = card.find('div', class_='Styled__DiscountHolder-ii87o4-13').text.strip()

                link = card.find('a', href=True)
                deal_id = link['href'].split('/')[3] if link else "Not Available"

                cover_div = card.find('div', class_='cover')  
                image_url = cover_div['src'] if cover_div and 'src' in cover_div.attrs else "Not Available"

                icon_img = card.find('img', class_='Styled__Logo-ii87o4-7 fMykHq')
                icon_url = icon_img['src'] if icon_img else "Not Available"

                category_id = self.predict_category(title)  

                offers, branches, deal_branches, terms_and_conditions, deal_description = self.scrape_offer_page(link['href'])

                deal_data = {
                    'title': title,
                    'deal_description': deal_description,
                    'discount': discount,
                    'deal_id': deal_id,
                    'image_url': image_url,
                    'icon_url': icon_url,
                    'category_id': category_id,
                    'offers': offers,
                    'branches': branches,
                    'deal_branches': deal_branches,
                    'terms_and_conditions': terms_and_conditions
                }

                if self.insert_deal_data(deal_data):
                    self.deal_count += 1
                
                return True
            except Exception as e:
                self.log(f"Error processing card on attempt {attempt+1}: {str(e)}")
                if attempt < retry_count - 1:
                    self.log("Retrying...")
                    time.sleep(3)  
                else:
                    self.log("Max retries reached, moving to next card.")
                    return False
    
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
            
            # Check cancellation after initial page load
            if self.maybe_check_if_cancelled():
                self.log("Job cancelled after loading initial page")
                return self.deal_count
            
            wait = WebDriverWait(self.driver, 10)
            time.sleep(5)  # Initial wait for page to load

            # Click "See More" until all deals are loaded
            self.log("Loading all deals...")
            try_count = 0
            max_tries = 10  # Limit number of attempts to avoid infinite loop
            
            while try_count < max_tries:
                try:
                    self.driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
                    time.sleep(2)

                    see_more_button = wait.until(
                        EC.element_to_be_clickable((By.XPATH, "//div[contains(@class, 'FlatButton__Button') and .//span[text()='See More']]"))
                    )
                    ActionChains(self.driver).move_to_element(see_more_button).click().perform()
                    self.log("Clicked 'See More' button")
                    time.sleep(3)
                    try_count += 1
                    
                    # Update progress
                    if self.job:
                        self.job.log_output += f"\nLoading more deals... (page {try_count})"
                        self.job.save()
                except Exception:
                    self.log("No more 'See More' button found. All data loaded.")
                    break

            # Parse the page with BeautifulSoup
            soup = BeautifulSoup(self.driver.page_source, 'html.parser')
            cards = soup.find_all('div', class_='Styled__CardHolder-ii87o4-1 eoqLK')
            
            self.log(f"Found {len(cards)} deal cards")
            
            # Update initial progress
            if self.job:
                self.job.log_output += f"\nFound {len(cards)} deals to process"
                self.job.save()
            
            # Process each card
            for idx, card in enumerate(cards):
                # Check if job was cancelled
                if self.maybe_check_if_cancelled():
                    self.log("Job cancelled, stopping scraper")
                    return self.deal_count
                
                self.scrape_card(card, idx, len(cards))
                
                # For testing/development, limit to a few cards
                if self.deal_count >= 5 and 'DEVELOPMENT' in os.environ:
                    self.log("Development mode: Processed sample of cards, stopping")
                    break
                
                # Check if job was cancelled
                if self.maybe_check_if_cancelled():
                    self.log("Job cancelled, stopping scraper")
                    return self.deal_count
            
            # Update analytics in Firebase
            self.update_analytics()
            
            self.log(f"Scraping completed. {self.deal_count} deals scraped.")
            return self.deal_count
            
        except Exception as e:
            error_msg = f"Error during scraping: {str(e)}\n{traceback.format_exc()}"
            self.log(error_msg)
            raise 