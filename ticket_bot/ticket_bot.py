import os
import time
import random
from typing import Dict, Optional, Tuple, List
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.action_chains import ActionChains
from webdriver_manager.chrome import ChromeDriverManager
from bs4 import BeautifulSoup
from fake_useragent import UserAgent
from dotenv import load_dotenv
import requests
import platform
import json
import logging
import subprocess
logging.basicConfig(level=logging.INFO)


class TicketBot:
    def __init__(self):
        """Initialize the ticket bot with browser setup and configuration."""
        load_dotenv()
        self.base_url = "https://www.eticketing.co.uk/arsenal/"
        self.login_url = "https://myaccount.arsenal.com/login"
        self.driver = None
        self.cookies = {}
        self.headers = {}
        self.setup_browser()

    def setup_browser(self):
        """Set up the Chrome browser with appropriate options."""
        chrome_options = Options()
        # chrome_options.add_argument('--headless')  # Uncomment for headless mode
        chrome_options.add_argument("--no-sandbox")
        chrome_options.add_argument("--disable-dev-shm-usage")
        chrome_options.add_argument(f"user-agent={UserAgent().random}")

        # Enable network request logging
        chrome_options.set_capability("goog:loggingPrefs", {"performance": "ALL"})

        # Handle Mac ARM64 architecture
        if platform.system() == "Darwin" and platform.machine() == "arm64":
            chrome_options.binary_location = (
                "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
            )
            service = Service()
        else:
            service = Service(ChromeDriverManager().install())

        self.driver = webdriver.Chrome(service=service, options=chrome_options)

    def simulate_human_movement(self, element):
        """Simulate human-like mouse movement to an element."""
        action = ActionChains(self.driver)
        action.move_to_element(element)
        action.perform()
        time.sleep(random.uniform(0.5, 1.5))  # Random delay to simulate human behavior

    def accept_cookies(self) -> bool:
        """Accept the cookie consent popup."""
        try:
            cookie_button = WebDriverWait(self.driver, 10).until(
                EC.element_to_be_clickable((By.ID, "onetrust-accept-btn-handler"))
            )
            self.simulate_human_movement(cookie_button)
            cookie_button.click()
            time.sleep(random.uniform(1, 2))  # Wait after clicking
            return True
        except Exception as e:
            print(f"Failed to accept cookies: {str(e)}")
            return False

    def login(self, username: str, password: str) -> bool:
        """
        Simulate login process with human-like behavior.

        Args:
            username: Login username
            password: Login password

        Returns:
            bool: True if login successful, False otherwise
        """
        try:
            logging.info("Starting login process...")
            # Navigate to the main page
            logging.info("Navigating to main page...")
            self.driver.get(self.base_url)

            # Wait for page to be fully loaded
            print("Waiting for page to load completely...")
            WebDriverWait(self.driver, 20).until(
                lambda driver: driver.execute_script("return document.readyState")
                == "complete"
            )
            time.sleep(5)  # Additional wait to ensure dynamic content is loaded

            # Print debugging information
            logging.info(f"Current page title: {self.driver.title}")
            logging.debug(f"Current URL: {self.driver.current_url}")

            # Check for iframes
            iframes = self.driver.find_elements(By.TAG_NAME, "iframe")
            logging.debug(f"Found {len(iframes)} iframes on the page")

            # Try to find the login button in the main document first
            logging.debug("Looking for login button in main document...")
            try:
                # Get all links on the page
                links = self.driver.find_elements(By.TAG_NAME, "a")
                logging.debug(f"Found {len(links)} links on the page")
                for link in links:
                    try:
                        text = link.text
                        href = link.get_attribute("href")
                        logging.debug(f"Link text: '{text}', href: '{href}'")
                    except:
                        continue
            except Exception as e:
                logging.error(f"Error getting links: {str(e)}")

            # Try to find the login button using JavaScript
            logging.debug("Trying to find login button using JavaScript...")
            login_button = self.driver.execute_script(
                """
                return Array.from(document.querySelectorAll('a')).find(
                    el => el.textContent.toLowerCase().includes('login') || 
                         (el.href && el.href.toLowerCase().includes('login'))
                );
            """
            )

            if login_button:
                logging.debug("Found login button using JavaScript")
                # Try to click using JavaScript
                self.driver.execute_script("arguments[0].click();", login_button)
            else:
                logging.error("Could not find login button using JavaScript")
                # Take a screenshot for debugging
                self.driver.save_screenshot("login_button_not_found.png")
                return False

            # Wait for login page to load
            logging.info("Waiting for login page to load...")
            time.sleep(random.uniform(3, 5))

            # Accept cookies if present
            logging.debug("Attempting to accept cookies...")
            self.accept_cookies()

            # Wait for login form to be present
            logging.debug("Looking for login form fields...")
            email_field = WebDriverWait(self.driver, 10).until(
                EC.presence_of_element_located((By.ID, "email"))
            )
            password_field = self.driver.find_element(By.ID, "password")
            submit_button = self.driver.find_element(
                By.CSS_SELECTOR, "button[type='submit']"
            )
            logging.debug("Found all form fields...")

            # Simulate human-like typing
            logging.debug("Typing username...")
            for char in username:
                email_field.send_keys(char)
                time.sleep(random.uniform(0.1, 0.3))

            time.sleep(random.uniform(0.5, 1))

            logging.debug("Typing password...")
            for char in password:
                password_field.send_keys(char)
                time.sleep(random.uniform(0.1, 0.3))

            time.sleep(random.uniform(0.5, 1))

            # Click submit button
            logging.debug("Clicking submit button...")
            self.simulate_human_movement(submit_button)
            submit_button.click()

            # Wait for login to complete
            logging.info("Waiting for login to complete...")
            time.sleep(random.uniform(8, 10))

            # Store cookies and headers after successful login
            logging.debug("Storing cookies and headers...")
            self.cookies = {
                cookie["name"]: cookie["value"] for cookie in self.driver.get_cookies()
            }
            self.headers = {
                "User-Agent": self.driver.execute_script("return navigator.userAgent"),
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.5",
            }

            # Check if login was successful by looking for various indicators
            logging.debug("Checking login success...")
            try:
                # Check if we're redirected to a different URL
                current_url = self.driver.current_url
                if "login" not in current_url.lower():
                    logging.info("Login successful: Redirected away from login page")
                    return True

                # Check for common elements that indicate successful login
                success_indicators = [
                    "//a[contains(text(), 'My Account')]",
                    "//a[contains(text(), 'Account')]",
                    "//a[contains(text(), 'Profile')]",
                    "//a[contains(text(), 'Logout')]",
                    "//a[contains(text(), 'Sign Out')]",
                ]

                for indicator in success_indicators:
                    try:
                        element = self.driver.find_element(By.XPATH, indicator)
                        if element:
                            logging.info(
                                f"Login successful: Found indicator '{indicator}'"
                            )
                            return True
                    except:
                        continue

                # If we get here, we couldn't find any success indicators
                logging.error("Could not find login success indicators")
                self.driver.save_screenshot("login_success_check_failed.png")
                return False

            except Exception as e:
                logging.error(f"Error checking login success: {str(e)}")
                return False

        except Exception as e:
            logging.error(f"Login failed with error: {str(e)}")
            logging.error(f"Current URL: {self.driver.current_url}")
            return False

    def extract_ticket_info(self, ticket_data: Dict) -> Dict:
        """
        Extract relevant information from a ticket response.

        Args:
            ticket_data: The ticket data from the API response

        Returns:
            Dict containing the extracted ticket information
        """
        try:
            area_id = ticket_data.get("AreaId")
            price_band = ticket_data.get("PriceBands", [{}])[0]
            price_band_id = price_band.get("PriceBandCode")

            # Get the first available seat interval
            seat_intervals = price_band.get("AvailableSeatsIntervals", [])
            if not seat_intervals:
                return None

            first_interval = seat_intervals[0]
            return {
                "AreaId": area_id,
                "PriceBandId": price_band_id,
                "SeatRow": first_interval.get("YCoord"),
                "SeatStart": first_interval.get("StartXCoord"),
                "SeatEnd": first_interval.get("EndXCoord"),
            }
        except Exception as e:
            logging.error(f"Error extracting ticket info: {str(e)}")
            return None

    def get_request_verification_token(self) -> Optional[str]:
        """
        Extract the RequestVerificationToken from the current page.

        Returns:
            str: The token value if found, None otherwise
        """
        try:
            # Wait for the input field to be present
            token_input = WebDriverWait(self.driver, 10).until(
                EC.presence_of_element_located((By.NAME, "__RequestVerificationToken"))
            )
            token_value = token_input.get_attribute("value")
            if token_value:
                logging.info("Successfully extracted RequestVerificationToken")
                return token_value
            else:
                logging.error("RequestVerificationToken input field is empty")
                return None
        except Exception as e:
            logging.error(f"Error extracting RequestVerificationToken: {str(e)}")
            return None

    def acquire_seat_lock(
        self,
        ticket_info: Dict,
        event_id: str,
        headers: Dict,
        cookies: Dict,
        verification_token: str,
    ) -> Optional[Dict]:
        """
        Attempt to acquire a lock on a specific seat.

        Args:
            ticket_info: Information about the ticket to lock
            event_id: The ID of the event
            headers: Headers to use for the request
            cookies: Cookies to use for the request

        Returns:
            Dict containing the lock response if successful, None otherwise
        """
        try:
            lock_url = (
                "https://www.eticketing.co.uk/arsenal/EDP/BestAvailable/ResaleSeats"
            )

            # Prepare the lock request payload
            payload = {
                "EventId": int(event_id),
                "Quantity": 1,
                "AreSeatsTogether": False,
                "AreaId": int(ticket_info["AreaId"]),
                "PriceBandId": int(ticket_info["PriceBandId"]),
                "SeatAttributeIds": [],
                "MinimumPrice": 0,
                "MaximumPrice": 10000000,
                "IsGeneralAdmissionEnabled": False,
            }

            # Convert cookies dict to requests format
            cookies_dict = {cookie["name"]: cookie["value"] for cookie in cookies}

            # Add the RequestVerificationToken to headers
            request_headers = headers.copy()
            request_headers["RequestVerificationToken"] = verification_token
            logging.info(f"Request headers: {';'.join([f'{k}: {v}' for k, v in request_headers.items()])}")
            logging.info(f"Cookies dict: {';'.join([f'{k}={v}' for k, v in cookies_dict.items()])}")
            logging.info(f"Payload: {payload}")

            # Make the lock request
            response = requests.post(
                lock_url,
                json=payload,
                headers=request_headers,
                cookies=cookies_dict,
                timeout=10,
            )

            if response.status_code == 200:
                logging.info(
                    f"Successfully acquired lock for seat in area {ticket_info['AreaId']}"
                )
                return response
            else:
                logging.error(
                    f"Failed to acquire lock. Status code: {response.status_code}"
                )
                logging.error(f"Response: {response.text}")
                return None

        except Exception as e:
            logging.error(f"Error acquiring seat lock: {str(e)}")
            return None

    def update_browser_cookies(
        self, response_cookies: requests.cookies.RequestsCookieJar
    ) -> bool:
        """
        Update the browser's cookies with the cookies from an API response.

        Args:
            response_cookies: Cookies from the API response

        Returns:
            bool: True if cookies were updated successfully, False otherwise
        """
        try:
            # Convert response cookies to a format that Selenium can use
            selenium_cookies = []
            for cookie in response_cookies:
                selenium_cookies.append(
                    {
                        "name": cookie.name,
                        "value": cookie.value,
                        "domain": cookie.domain if hasattr(cookie, "domain") else None,
                        "path": cookie.path if hasattr(cookie, "path") else "/",
                    }
                )
            logging.info(f"Selenium cookies: {selenium_cookies}")

            # Delete existing cookies
            self.driver.delete_all_cookies()

            # Add new cookies
            for cookie in selenium_cookies:
                try:
                    self.driver.add_cookie(cookie)
                except Exception as e:
                    logging.error(f"Error adding cookie {cookie['name']}: {str(e)}")
                    continue

            logging.info("Successfully updated browser cookies")
            return True

        except Exception as e:
            logging.error(f"Error updating browser cookies: {str(e)}")
            return False

    def initiate_checkout(self, headers: Dict, cookies: Dict) -> bool:
        """
        Initiate the checkout process by making the required API calls.

        Args:
            headers: Headers to use for the request
            cookies: Cookies to use for the request

        Returns:
            bool: True if checkout initiated successfully, False otherwise
        """
        try:
            checkout_url = (
                "https://www.eticketing.co.uk/arsenal/Checkout/Payment/Confirm"
            )

            # # Convert cookies dict to requests format
            # cookies_dict = {cookie["name"]: cookie["value"] for cookie in cookies}

            # First request - Payment method selection
            payment_payload = {
                "TimezoneOffset": "240",
                "DeviceInformation.HttpBrowserScreenHeight": "1107",
                "DeviceInformation.HttpBrowserScreenWidth": "1710",
                "DeviceInformation.HttpBrowserColorDepth": "30",
                "DeviceInformation.HttpBrowserJavaEnabled": "false",
                "DeviceInformation.HttpBrowserLanguage": "en-US",
                "DeviceInformation.HttpBrowserTimeDifference": "240",
                "paymentMethodFee": "No Fee",
                "PaymentMethods[0].Fee": "0",
                "PaymentMethods[0].Type": "CardPayment",
                "PaymentMethods[0].Id": "99",
                "SelectPaymentMethod": "CardPayment",
                "PaymentMethods[0].SelectedStoredCard": "148575",
                "SelectedPaymentId": "99",
            }

            # Make the first request
            logging.info("Making first checkout request...")
            response = requests.post(
                checkout_url,
                data=payment_payload,
                headers=headers,
                cookies=cookies,
                allow_redirects=False,  # Don't follow redirects
                timeout=10,
            )

            if response.status_code != 302:
                logging.error(
                    f"First checkout request failed. Status code: {response.status_code}"
                )
                logging.error(f"Response: {response.text}")
                return False

            logging.info("First checkout request successful")

            # Second request - Terms and conditions acknowledgment
            terms_payload = {"AcknowledgeTermsAndConditions": "true", "AcknowledgeTermsAndConditions": "false"}

            # Make the second request
            logging.info("Making second checkout request...")
            response = requests.post(
                checkout_url,
                data=terms_payload,
                headers=headers,
                cookies=cookies,
                timeout=10,
            )

            if response.status_code == 200:
                logging.info("Checkout process initiated successfully")
                return True
            else:
                logging.error(
                    f"Second checkout request failed. Status code: {response.status_code}"
                )
                logging.error(f"Response: {response.text}")
                return False

        except Exception as e:
            logging.error(f"Error during checkout process: {str(e)}")
            return False

    def add_to_cart(
        self,
        ticket_info: Dict,
        event_id: str,
        headers: Dict,
        cookies: Dict,
        verification_token: str,
    ) -> bool:
        """
        Add a ticket to the cart by first acquiring a lock.

        Args:
            ticket_info: Information about the ticket to add
            event_id: The ID of the event
            headers: Headers to use for the request
            cookies: Cookies to use for the request

        Returns:
            bool: True if successfully added to cart, False otherwise
        """
        try:
            logging.info(f"Attempting to add ticket to cart: {ticket_info}")

            # First acquire a lock on the seat
            lock_response: requests.Response = self.acquire_seat_lock(
                ticket_info, event_id, headers, cookies, verification_token
            )
            if not lock_response:
                logging.error("Failed to acquire seat lock")
                return False

            # Extract the locked seat ID from the response
            locked_seats = lock_response.json().get("LockedSeats", [])
            if not locked_seats:
                logging.error("No locked seats in response")
                return False

            logging.info(f"Locked seats: {locked_seats}")
            locked_seat_id = locked_seats[0].get("Id")
            if not locked_seat_id:
                logging.error("No seat ID in locked seats response")
                return False

            # Prepare the add to cart payload
            cart_payload = {
                "EventId": int(event_id),
                "Seats": [{"Id": 87499287, "PriceClassId": 1}],
            }

            # Prepare headers for add to cart request
            request_headers = headers.copy()
            request_headers["RequestVerificationToken"] = verification_token
            request_headers["Content-Type"] = "application/json"

            # Convert cookies dict to requests format
            cookies_dict = {cookie["name"]: cookie["value"] for cookie in cookies}

            # Append cookie from lock response
            lock_response_cookies = lock_response.cookies
            cookies_dict.update(
                {
                    cookie.name: cookie.value
                    for cookie in lock_response_cookies
                    if "eticket" in cookie.name
                }
            )

            # Make the add to cart request
            logging.info(f"Adding to cart. Seat ID: {locked_seat_id}")
            response = requests.put(
                "https://www.eticketing.co.uk/arsenal/EDP/BestAvailable/ResaleSeats",
                json=cart_payload,
                headers=request_headers,
                cookies=cookies_dict,
                timeout=10,
            )

            if response.status_code == 200:
                logging.info("Successfully added ticket to cart")
                # Make call to BasketSeats endpoint to ensure ticket is in basket
                basket_response = requests.post(
                    "https://www.eticketing.co.uk/arsenal/EDP/Ism/BasketSeats",
                    json={"eventId": int(event_id)},
                    headers=request_headers,
                    cookies=cookies_dict,
                )
                if basket_response.status_code == 200:
                    logging.info("Successfully added ticket to basket!")
                    # Launch VLC to play a song
                    path = "/Users/rohit/Documents/Laura Marling - Laura Sings Raffi (2024) {Vinyl} [FLAC]/01 - Peanut Butter Sandwich.flac"
                    subprocess.Popen(["open", "-a", "/Applications/VLC.app/Contents/MacOS/VLC", path])

                    # Update cookies with basket response cookies
                    cookies_dict.update(
                        {
                            cookie.name: cookie.value
                            for cookie in basket_response.cookies
                            if "eticket" in cookie.name
                        }
                    )

                    # Initiate checkout process
                    if self.initiate_checkout(request_headers, cookies_dict):
                        logging.info("Checkout process initiated successfully")
                        return True
                    else:
                        logging.error("Failed to initiate checkout process")
                        return False
                else:
                    logging.error("Failed to add ticket to basket")
            else:
                logging.error(
                    f"Failed to add to cart. Status code: {response.status_code}"
                )
                logging.error(f"Response: {response.text}")
                return False

        except Exception as e:
            logging.error(f"Error adding ticket to cart: {str(e)}")
            return False

    def check_ticket_availability(
        self,
        request_url: str,
        headers: Dict,
        cookies: Dict,
        event_id: str,
    ) -> Optional[Dict]:
        """
        Check for ticket availability by making an API request.

        Args:
            request_url: The URL to check for ticket availability
            headers: Headers to use for the request
            cookies: Cookies to use for the request

        Returns:
            Dict containing ticket information if available, None otherwise
        """
        try:
            params = {"AreSeatsTogether": False, "EventId": event_id, "MarketType": 1, "MaximumPrice": 10000000, "MinimumPrice": 0, "Quantity": 1}
            logging.debug(f"Making API request with params: {params}")
            logging.debug(f"Request URL: {request_url}")
            response = self.make_api_request(request_url, params=params, headers=headers, cookies=cookies)
            if response is None:
                logging.error(f"Failed to check for tickets. Session is probably expired.")
                return None
            logging.debug(f"Response: {response}")
            if response.status_code == 500:
                logging.error(f"Request failed with a 500 error. Response: {response.text}")
                return None
            if response.status_code != 200:
                logging.error(
                    f"Failed to check ticket availability: {response.status_code if response else 'None'}"
                )
                return None

            # Parse the JSON response
            data = response.json()
            if not data:  # Empty array means no tickets
                return {}

            return data

        except Exception as e:
            logging.error(f"Error checking ticket availability: {str(e)}")
            return None

    def monitor_tickets(
        self,
        request_url: str,
        headers: Dict,
        cookies: Dict,
        event_id: str,
        verification_token: str,
        max_attempts: int = None,
    ) -> bool:
        """
        Continuously monitor for ticket availability.

        Args:
            request_url: The URL to check for ticket availability
            headers: Headers to use for the request
            cookies: Cookies to use for the request
            event_id: The ID of the event
            max_attempts: Maximum number of attempts (None for infinite)
        """
        attempt = 0
        while True:
            if max_attempts and attempt >= max_attempts:
                logging.info("Reached maximum number of attempts")
                break

            logging.info(f"\nChecking for tickets (attempt {attempt + 1})...")

            tickets = self.check_ticket_availability(request_url, headers, cookies, event_id)
            if tickets == {}:
                logging.info("No tickets found")
            elif tickets is None:
                logging.error("Monitoring failed. Session is probably expired.")
                break
            else:
                logging.info("Tickets found! Attempting to add to cart...")
                for ticket in tickets:
                    ticket_info = self.extract_ticket_info(ticket)
                    if self.add_to_cart(
                        ticket_info, event_id, headers, cookies, verification_token
                    ):
                        logging.info("Successfully added ticket to cart!")
                        return True
                    else:
                        logging.error("Failed to add ticket to cart")

            # Random delay between 5-8 seconds
            delay = 3 + random.uniform(0, 3)
            logging.info(f"Waiting {delay:.1f} seconds before next check...")
            time.sleep(delay)
            attempt += 1

        return False


    def close(self):
        """Close the browser and clean up resources."""
        if self.driver:
            self.driver.quit()

    def get_network_requests(self, url_pattern: str) -> List[Dict]:
        """Get network requests matching the given URL pattern."""
        logs = self.driver.get_log("performance")
        requests = []

        for log in logs:
            try:
                log_data = json.loads(log["message"])["message"]
                if "Network.requestWillBeSent" in log_data["method"]:
                    request = log_data["params"]["request"]
                    if url_pattern in request["url"]:
                        requests.append(
                            {
                                "url": request["url"],
                                "headers": request["headers"],
                                "cookies": self.driver.get_cookies(),
                            }
                        )
            except:
                continue

        return requests

    def make_api_request(
        self, url: str, headers: Dict, cookies: Dict, params: Dict = {},
    ) -> Optional[requests.Response]:
        """Make an API request with the given headers and cookies."""
        try:
            # Convert cookies dict to requests format
            cookies_dict = {cookie["name"]: cookie["value"] for cookie in cookies}
            logging.debug(f"Cookies: {cookies_dict}")
            logging.debug(f"Headers: {headers}")

            response = requests.get(
                url, headers=headers, cookies=cookies_dict, params=params, timeout=10
            )
            return response
        except Exception as e:
            logging.error(f"Error making API request: {str(e)}")
            return None

    def navigate_to_game(self, game_url: str) -> bool:
        """
        Navigate to the specific game page.

        Args:
            game_url: The URL of the game page

        Returns:
            bool: True if navigation successful, False otherwise
        """
        try:
            logging.info(f"Navigating to game page: {game_url}")
            self.driver.get(game_url)

            # Wait for page to load completely
            WebDriverWait(self.driver, 20).until(
                lambda driver: driver.execute_script("return document.readyState")
                == "complete"
            )
            time.sleep(random.uniform(3, 5))  # Additional wait for dynamic content

            logging.info(f"Current page title: {self.driver.title}")
            logging.info(f"Current URL: {self.driver.current_url}")

            return True

        except Exception as e:
            logging.error(f"Failed to navigate to game page: {str(e)}")
            return False


def read_credentials() -> Tuple[str, str]:
    """Read credentials from the credentials file."""
    try:
        with open("ticket_bot/credentials", "r") as f:
            lines = f.readlines()
            if len(lines) >= 2:
                return lines[0].strip(), lines[1].strip()
    except Exception as e:
        logging.error(f"Error reading credentials: {str(e)}")
    return None, None


def start_bot():
    """Main function to run the ticket bot."""
    bot = TicketBot()
    try:
        username, password = read_credentials()
        event_id = "3597"  # Extract from game_url
        seat_type = "Resale"
        game_url = f"https://www.eticketing.co.uk/arsenal/EDP/Event/Index/{event_id}?position=1"

        if not username or not password:
            logging.error("Failed to read credentials from credentials file")
            return

        if bot.login(username, password):
            logging.info("Successfully logged in")
            if bot.navigate_to_game(game_url):
                logging.info("Successfully navigated to game page")
                # Get the RequestVerificationToken
                verification_token = bot.get_request_verification_token()
                if not verification_token:
                    logging.error("Failed to get RequestVerificationToken")
                    return None
                # Get the request details from the last successful API call
                requests = bot.get_network_requests(f"EDP/Seats/AvailableRegular")
                if requests:
                    request = requests[0]
                    logging.info("Starting ticket monitoring...")
                    monitoring_status = bot.monitor_tickets(
                        f"https://www.eticketing.co.uk/arsenal/EDP/Seats/Available{seat_type}",
                        request["headers"],
                        request["cookies"],
                        event_id,
                        verification_token,
                    )
                    if not monitoring_status:
                        logging.error("Failed to monitor tickets. Session is probably expired.")
                        return False
                    else:
                        logging.info("Successfully got ticket")
                        return True
                else:
                    logging.error("Failed to get request details for ticket monitoring")
            else:
                logging.error("Failed to navigate to game page")
        else:
            logging.error("Failed to login")

    finally:
        bot.close()


if __name__ == "__main__":
    while True:
        got_ticket = start_bot()
        if got_ticket:
            logging.info("Successfully got ticket")
            break
        else:
            logging.info("Failed to get ticket. Retrying...")