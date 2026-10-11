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
from datetime import datetime
from collections import defaultdict, Counter
from webdriver_manager.chrome import ChromeDriverManager  
from .base_scraper import BaseScraper

class JsScrapper(BaseScraper):
    def scrape(self):
        """
        Main scraping method for JS Bank
        """
        try:
            # Call the main function that contains all the scraping logic
            main()
            return analytics['total_deals_scraped']
        except Exception as e:
            self.log(f"Error in JS scraper: {str(e)}")
            return 0

GOOGLE_MAPS_API_KEY = os.environ.get('GOOGLE_MAPS_API_KEY', 'AIzaSyD50GtOZaBtYyC4cRas2XXNsMxfoil5hyY')

analytics = {
    'total_deals_scraped': 0,
    'deals_by_category': defaultdict(int),
    'deals_by_card_type': defaultdict(int),
    'branches_count': 0,
    'offers_count': 0,
    'locations': set()  
}

with open('improved_deal_classifier_model.pkl', 'rb') as f:
    model, vectorizer = pickle.load(f)


cred = credentials.Certificate(r"/Users/musa/Desktop/dealHunterScrapper/dealhunter-490d3-firebase-adminsdk-fbsvc-ce5ba25c59.json")
firebase_admin.initialize_app(cred)

db = firestore.client()

options = Options()
options.add_argument("--headless")  # Run in headless mode
options.add_argument("--no-sandbox")
options.add_argument("--disable-dev-shm-usage")

driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=options)

url = "https://jsb-web.peekaboo.guru/islamabad/places/_all/all"


url_parts = url.split('/')
bank_name = "JS"
city_name = url_parts[3].capitalize() 

# Function to get latitude and longitude from address using Google Maps API
def get_lat_lng(address):
    try:
        address_with_city = f"{address}, {city_name}, Pakistan"
        params = {
            'address': address_with_city,
            'key': GOOGLE_MAPS_API_KEY
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
            print(f"Geocoding API error: {data['status']}")
            return {
                'latitude': 0.0,
                'longitude': 0.0
            }
    except Exception as e:
        print(f"Error getting location data: {e}")
        return {
            'latitude': 0.0,
            'longitude': 0.0
        }
def get_full_description(driver):
    try:
        # Wait for description container to be present
        description_container = WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, "div.ExpandableText__Text-sc-5hhsud-0"))
        )
        
        # Check if "Show more" exists - FIXED THE XPATH SYNTAX ERROR BY ADDING CLOSING BRACKET
        try:
            show_more_button = WebDriverWait(driver, 5).until(
                EC.element_to_be_clickable((By.XPATH, "//a[.//span[text()='Show more']]"))
            )
            
            print("Found 'Show more' button, clicking to expand description")
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
            print("No 'Show more' button found or already expanded")
        
        # Get the updated text directly from the WebElement
        full_text = driver.execute_script("""
            const div = arguments[0];
            const clone = div.cloneNode(true);
            // Remove any "Show more" or "Show less" links
            Array.from(clone.querySelectorAll('a.ExpandableText__Link-sc-5hhsud-1')).forEach(a => a.remove());
            return clone.textContent.trim();
        """, description_container)
        
        print(f"Final description length: {len(full_text)} characters")
        return full_text
        
    except Exception as e:
        print(f"Error getting description: {str(e)}")
        return ""


def scrape_offer_page(card_link, retry_attempts=3):
    for attempt in range(retry_attempts):
        try:
            # Open the offer page in a new tab
            driver.execute_script("window.open(arguments[0], '_blank');", card_link)
            time.sleep(10)  # Wait for the new tab to load

            # Switch to the new tab
            driver.switch_to.window(driver.window_handles[-1])

            soup = BeautifulSoup(driver.page_source, 'html.parser')

            deal_description = get_full_description(driver)

            offersContainer = soup.find_all('div', class_='Styled__ListHolder-rxute-1 iAIrSk')
            offers = offersContainer[0].find_all('a', href=True) if offersContainer else []

            branchesContainer = soup.find_all('div', class_='Styled__ListHolder-sc-1oq0juy-2 ldNFd')
            branches = branchesContainer[0].find_all('div', class_='Styled__ListItem-sc-14n6kj-1 bjMUOR') if branchesContainer else []

            # IMPORTANT: Dictionary to track unique branches by name for deduplication
            # This is the key part for fixing the duplication issue
            unique_branches = {}

            offers_data = []
            for offer in offers:
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

                # Open the offer detail page
                offer_link = offer['href']
                driver.execute_script("window.open(arguments[0], '_blank');", offer_link)
                time.sleep(5)  # Wait for the offer detail page to load

                # Switch to the offer detail page
                driver.switch_to.window(driver.window_handles[-1])
                offer_soup = BeautifulSoup(driver.page_source, 'html.parser')

                # Wait for the terms and conditions section to load
                try:
                    WebDriverWait(driver, 5).until(
                        EC.presence_of_element_located((By.CLASS_NAME, 'Styled__WidgetWrapper-sc-51ny7z-29'))
                    )
                except TimeoutException:
                    print("Terms and conditions section not found after waiting.")

                # Scrape terms and conditions from the updated HTML
                terms_and_conditions = ""
                terms_section = offer_soup.find('div', class_='Styled__WidgetWrapper-sc-51ny7z-29')
                if terms_section:
                    terms_list = terms_section.find_all('li')
                    if terms_list:
                        terms_and_conditions = "\n".join([li.text.strip() for li in terms_list])
                    else:
                        terms_and_conditions = terms_section.text.strip()

                # Scrape all card names and image URLs
                cards_data = []
                    
                    # Scrape cards on the current page
            cards_container = offer_soup.find('div', class_='Styled__CardsRow-sc-51ny7z-15 fRRNNk')

            cards_data = []

            if cards_container:
                cards = cards_container.find_all('a', href=True)
                print(f"Found {len(cards)} cards")

                for card in cards:
                    try:
                        card_name = card.find('p').text.strip()
                        card_image_url = card.find('img')['src']
                        cards_data.append({'card_name': card_name, 'card_image_url': card_image_url})
                    except AttributeError:
                        continue

                # Add cards data to the offer
                offer_data['card_type'] = cards_data
                
                # Find and scrape branch locations on the offer detail page
                branch_locations = []
                
                # Look for the branches section
                branch_section = offer_soup.find('div', class_='Styled__BranchRow-sc-51ny7z-17')
                
                if branch_section:
                    print("Found branches section, scraping branch locations...")
                    
                    # Refresh soup for current branch page
                    branch_soup = BeautifulSoup(driver.page_source, 'html.parser')
                    
                    # Scrape branches on current page
                    branch_links = branch_soup.find_all('a', class_='Styled__BranchDetailLink-sc-51ny7z-18')
                    
                    print(f"Found {len(branch_links)} branch links on page")

                    for branch_link in branch_links:
                        try:
                            p_tags = branch_link.find_all('p')
                            if p_tags:
                                branch_name = p_tags[-1].text.strip()
                                print(f"Found branch: {branch_name}")
                            
                            # Skip if this branch is already processed
                            if branch_name in unique_branches:
                                print(f"Branch '{branch_name}' already processed, skipping")
                                # Just add the existing branch info to this offer's branch locations
                                branch_locations.append(unique_branches[branch_name])
                                continue
                            
                            # Open the branch detail page in a new tab
                            branch_link_url = branch_link['href']
                            full_branch_url = f"https://jsb-web.peekaboo.guru{branch_link_url}" if not branch_link_url.startswith('http') else branch_link_url
                            
                            print(f"Opening branch detail page: {full_branch_url}")
                            driver.execute_script("window.open(arguments[0], '_blank');", full_branch_url)
                            time.sleep(5)  # Wait for branch detail page to load
                            
                            # Switch to branch detail page
                            driver.switch_to.window(driver.window_handles[-1])
                            
                            # Get full branch address
                            branch_detail_soup = BeautifulSoup(driver.page_source, 'html.parser')
                            address_container = branch_detail_soup.find('div', class_='Styled__AddressContainer-sc-1p266ig-11')
                            
                            full_address = ""
                            if address_container and address_container.find('p'):
                                full_address = address_container.find('p').text.strip()
                                print(f"Found full address: {full_address}")
                            
                            # Get location data using the full address for more accurate geocoding
                            geocoding_address = full_address if full_address else branch_name
                            location_data = get_lat_lng(geocoding_address)
                            
                            # Create branch info with full address
                            branch_info = {
                                'name': branch_name,
                                'full_address': full_address,
                                'latitude': location_data['latitude'],
                                'longitude': location_data['longitude']
                            }
                            
                            branch_locations.append(branch_info)
                            
                            # Add to unique branches dictionary for deduplication
                            unique_branches[branch_name] = branch_info
                            
                            print(f"Added branch location: {branch_name} ({location_data['latitude']}, {location_data['longitude']})")
                            
                            # Close the branch detail page and switch back to branches page
                            driver.close()
                            driver.switch_to.window(driver.window_handles[-1])
                            time.sleep(1)
                            
                        except Exception as e:
                            print(f"Error processing branch: {str(e)}")
                            # Make sure to close any open tabs and return to the branches page
                            if len(driver.window_handles) > 1:
                                driver.close()
                                driver.switch_to.window(driver.window_handles[-1])
                            continue
                
                # Add branch locations to offer data
                offer_data['branch_locations'] = branch_locations

                # Close the offer detail page and switch back to the offers page
                driver.close()
                driver.switch_to.window(driver.window_handles[-1])

                offers_data.append(offer_data)

            # Prepare branches data from main offer page - NOTE: refactored to use unique_branches
            branches_data = []
            for branch in branches:
                try:
                    branch_title_elem = branch.find('div', class_='Styled__PrimaryText-sc-14n6kj-7 bdZLUf')
                    if branch_title_elem:
                        branch_title = branch_title_elem.text.strip()
                    else:
                        continue
                    
                    # Skip if this branch is already processed
                    if branch_title in unique_branches:
                        print(f"Main branch '{branch_title}' already processed, using existing data")
                        branch_info = unique_branches[branch_title]
                        branch_data = {
                            'branch_title': branch_title,
                            'full_address': branch_info['full_address'],
                            'latitude': branch_info['latitude'],
                            'longitude': branch_info['longitude']
                        }
                        branches_data.append(branch_data)
                        continue
                    
                    # If not already processed, get the address from the branch element
                    address_elem = branch.find('p', class_='Styled__TertiaryText-sc-14n6kj-9 VfCfv')
                    full_address = address_elem.text.strip() if address_elem else ""
                    
                    # Get location data if address is available
                    if full_address:
                        location_data = get_lat_lng(full_address)
                    else:
                        location_data = {'latitude': 0.0, 'longitude': 0.0}
                    
                    branch_data = {
                        'branch_title': branch_title,
                        'full_address': full_address,
                        'latitude': location_data['latitude'],
                        'longitude': location_data['longitude']
                    }
                    
                    # Add to unique branches dictionary for deduplication
                    unique_branches[branch_title] = {
                        'name': branch_title,
                        'full_address': full_address,
                        'latitude': location_data['latitude'],
                        'longitude': location_data['longitude']
                    }
                    
                    branches_data.append(branch_data)
                    
                except Exception as e:
                    print(f"Error processing main branch: {str(e)}")
                
            # Create the final all_deal_branches list from the unique_branches dictionary
            # This ensures we only have one entry per branch
            all_deal_branches = list(unique_branches.values())
            
            # Close the current tab and switch back to the main tab
            driver.close()
            driver.switch_to.window(driver.window_handles[0])
            time.sleep(3)  # Wait for the main page to reload

            return offers_data, branches_data, all_deal_branches, terms_and_conditions, deal_description
        except Exception as e:
            print(f"Error processing offer page on attempt {attempt + 1}: {e}")
            if attempt < retry_attempts - 1:
                print("Retrying...")
                time.sleep(3)
            else:
                print("Max retries reached, skipping this offer page.")
                return [], [], [], "", ""  # Return empty values if failed after all attempts

def insert_deal_data(deal_data, bank_name, city_name):
    # Firestore document references
    bank_ref = db.collection('Banks').document(bank_name)
    city_ref = bank_ref.collection('Cities').document(city_name)
    deal_ref = city_ref.collection('Deals').document(deal_data['deal_id'])

    # Set bank and city data
    bank_ref.set({'name': bank_name}, merge=True)
    city_ref.set({'name': city_name}, merge=True)

    # Create maps for offers
    offers_map = {f'offer_{i+1}': offer for i, offer in enumerate(deal_data['offers'])}
    
    # Important fix: Create deal_branches_map from the properly deduplicated deal_branches
    deal_branches_map = {}
    for i, branch in enumerate(deal_data['deal_branches'], 1):
        branch_key = f'branch_{i}'
        deal_branches_map[branch_key] = branch

    # Generate random avgSentiment with 1 decimal place
    avg_sentiment = round(random.uniform(3.0, 4.5), 1)

    # Set deal data with random avgSentiment
    deal_ref.set({
        'title': deal_data['title'],
        'description': deal_data['deal_description'],
        'discount': deal_data['discount'],
        'image_url': deal_data['image_url'],
        'icon_url': deal_data['icon_url'],
        'category_id': deal_data['category_id'],
        'bank_id': bank_name,
        'city_id': city_name,
        'offers': offers_map,
        'deal_branches': deal_branches_map,
        'terms_and_conditions': deal_data['terms_and_conditions'],
        'avgSentiment': avg_sentiment
    })
    
    # Track analytics data
    analytics['total_deals_scraped'] += 1
    
    # Update category stats
    category = deal_data['category_id']
    analytics['deals_by_category'][category] += 1
    
    # Update card type stats
    for offer in deal_data['offers']:
        if 'card_type' in offer:
            for card in offer['card_type']:
                card_name = card['card_name']
                analytics['deals_by_card_type'][card_name] += 1
    
    # Count offers
    analytics['offers_count'] += len(deal_data['offers'])
    
    # Count branches - use deduplicated count
    analytics['branches_count'] += len(deal_data['deal_branches'])
    
    # Track unique locations
    for branch in deal_data['deal_branches']:
        if 'full_address' in branch and branch['full_address']:
            analytics['locations'].add(branch['full_address'])
    
    print(f"Deal '{deal_data['title']}' inserted into Firestore with avgSentiment: {avg_sentiment}")
    print(f"Successfully saved {len(deal_data['deal_branches'])} unique branches")

# Function to update analytics in Firebase
def update_analytics(bank_name):
    try:
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        # Reference to analytics collection
        analytics_ref = db.collection('Banks').document(bank_name).collection('Analytics').document(city_name)
        
        # Convert defaultdict to regular dict for Firebase
        deals_by_category = dict(analytics['deals_by_category'])
        deals_by_card_type = dict(analytics['deals_by_card_type'])
        
        # Create analytics data document
        analytics_data = {
            'timestamp': timestamp,
            'total_deals_scraped': analytics['total_deals_scraped'],
            'deals_by_category': deals_by_category,
            'deals_by_card_type': deals_by_card_type,
            'branches_count': analytics['branches_count'],
            'offers_count': analytics['offers_count'],
            'unique_locations_count': len(analytics['locations'])
        }
        
        # Store analytics in Firebase
        analytics_ref.set(analytics_data, merge=True)
        
        print(f"Analytics data updated in Firebase for {bank_name}:")
        print(f"- Total deals scraped: {analytics['total_deals_scraped']}")
        print(f"- Deals by category: {deals_by_category}")
        print(f"- Deals by card type: {len(deals_by_card_type)} different card types")
        print(f"- Total branches: {analytics['branches_count']}")
        print(f"- Total offers: {analytics['offers_count']}")
        print(f"- Unique locations: {len(analytics['locations'])}")
        
    except Exception as e:
        print(f"Error updating analytics: {e}")

# Function to predict the category of a deal name
def predict_category(deal_name):
    deal_name_tfidf = vectorizer.transform([deal_name])
    category = model.predict(deal_name_tfidf)
    return category[0]    

def scrape_card(card):
    retry_count = 3  
    for attempt in range(retry_count):
        try:
            title = card.find('p', class_='Styled__CardHeaderTitle-ii87o4-9').text.strip()

            discount = card.find('div', class_='Styled__DiscountHolder-ii87o4-13').text.strip()

            link = card.find('a', href=True)
            deal_id = link['href'].split('/')[3] if link else "Not Available"

            cover_div = card.find('div', class_='cover')  
            image_url = cover_div['src'] if cover_div and 'src' in cover_div.attrs else "Not Available"

            icon_img = card.find('img', class_='Styled__Logo-ii87o4-7 fMykHq')
            icon_url = icon_img['src'] if icon_img else "Not Available"

            category_id = predict_category(title)  

            offers, branches, deal_branches, terms_and_conditions, deal_description = scrape_offer_page(link['href'])

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

            insert_deal_data(deal_data, bank_name, city_name)

            return 
        except Exception as e:
            print(f"Error processing card: {e}")
            if attempt < retry_count - 1:
                print("Retrying...")
                time.sleep(3)  
            else:
                print("Max retries reached, moving to next card.")
                break

def main():
    try:
        driver.get(url)
        wait = WebDriverWait(driver, 10)
        time.sleep(5)

        while True:
            try:
                driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
                time.sleep(3)

                see_more_button = wait.until(
                    EC.element_to_be_clickable((By.XPATH, "//div[contains(@class, 'FlatButton__Button') and .//span[text()='See More']]"))
                )
                ActionChains(driver).move_to_element(see_more_button).click().perform()
                time.sleep(1)  

            except Exception:
                print("No more 'See More' button found. All data loaded.")
                break

        soup = BeautifulSoup(driver.page_source, 'html.parser')

        cards = soup.find_all('div', class_='Styled__CardHolder-ii87o4-1 eoqLK')  

        for idx, card in enumerate(cards):
            if idx == len(cards) - 1:
                scrape_card(card)
                print("Last card processed, stopping the scraper.")
                break 
            else:
                scrape_card(card)  
                
        # Update analytics in Firebase after all deals are scraped
        print("Updating analytics in Firebase...")
        update_analytics(bank_name)

    except Exception as e:
        print(f"Error: {e}")
        # Still try to update analytics even if there was an error
        if analytics['total_deals_scraped'] > 0:
            update_analytics(bank_name)

    finally:
        if driver is not None:
            try:
                print("Closing browser...")
                driver.quit()
            except Exception as e:
                print(f"Error while closing WebDriver: {e}")

if __name__ == "__main__":
    main()