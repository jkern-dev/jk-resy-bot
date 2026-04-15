from calendar import FRIDAY
from datetime import datetime, timedelta

from zoneinfo import ZoneInfo
import time
import logging
import yaml
import uuid
import requests
from requests.exceptions import RetryError
from curl_cffi import requests as cffi_requests
from typing import List, Optional, Dict, Any, Tuple
from pathlib import Path
import click

from dropbox_client import DropboxClient
from opentable_api_wrapper import OpenTableApiRequestWrapper

GQL_URL = "https://www.opentable.com/dapi/fe/gql"

AVAILABILITY_HASH = "cbcf4838a9b399f742e3741785df64560a826d8d3cc2828aa01ab09a8455e29e"
SLOT_LOCK_HASH = "1100bf68905fd7cb1d4fd0f4504a4954aa28ec45fb22913fa977af8b06fd97fa"
WISHLIST_HASH = "75b24400bfc8a67b16ecdc3f0b677d26f3238c6079a83343a1d909b074c23889"

WEEKEND_OVERRIDE_KEY_MAPPING = [
    "this_weekend",
    "next_weekend",
    "third_weekend",
    "fourth_weekend",
    "fifth_weekend",
    "sixth_weekend",
    "seventh_weekend",
    "eighth_weekend",
    "ninth_weekend",
    "tenth_weekend",
    "eleventh_weekend",
    "twelfth_weekend",
]

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/144.0.0.0 Safari/537.36",
    "Accept": "application/json",
    "Content-Type": "application/json",
    "Accept-Language": "en-US,en;q=0.9",
    "Origin": "https://www.opentable.com",
    "Referer": "https://www.opentable.com/",
}

basic_config = {
    "level": logging.INFO,
    "format": "[%(asctime)s][%(levelname)s] %(message)s",
    "datefmt": "%Y-%m-%d %H:%M:%S",
}


def readconfig(config_file: str) -> Dict[str, Any]:
    with open(config_file) as f:
        config = yaml.safe_load(f)
    return config


class OpenTableBot:
    def __init__(
        self,
        config_file: Path,
    ):
        startup_config = readconfig(config_file=config_file)
        local_config_only = startup_config.get("local_config_only", False)
        dropbox_secrets_file = startup_config.get("dropbox_secrets_file")
        notion_secrets_file = startup_config.get("notion_secrets_file")
        self._remote_config_source: str = startup_config.get(
            "remote_config_source", ""
        ).lower()
        self._local_config_filepath = (
            Path.cwd()
            / "config_files"
            / startup_config.get("opentable_config_file", "opentable_config.yaml")
        )
        if not local_config_only:
            if self._remote_config_source == "dropbox" and dropbox_secrets_file is None:
                raise ValueError(
                    "Dropbox secrets file must be provided if using it for remote config source"
                )
            if self._remote_config_source == "notion" and notion_secrets_file is None:
                raise ValueError(
                    "Notion secrets file must be provided if using it for remote config source"
                )
        self.local_config_only = local_config_only
        self.dropbox_prefix = startup_config.get("dropbox_prefix")

        self.headers = None
        self.current_week_number: int = 0
        self._config_dict: Dict[str, Any] = {}
        self._last_config_sync_time: Optional[datetime] = None
        self.dbx_client = None
        self.notion_config_dict = {}
        if not self.local_config_only:
            if self._remote_config_source == "dropbox":
                logging.info("remote_config_source set to dropbox")
                self.dbx_client = DropboxClient(
                    secrets_file=Path.cwd() / "config_files" / dropbox_secrets_file
                )
            if self._remote_config_source == "notion":
                logging.info("remote_config_source set to notion")
                self.notion_config_dict = (
                    readconfig(
                        config_file=Path.cwd() / "config_files" / notion_secrets_file
                    )
                    if self._remote_config_source == "notion"
                    else {}
                )

        self.api = OpenTableApiRequestWrapper()
        self._wishlist_cache: List[Dict[str, Any]] = []
        self._wishlist_cache_time: Optional[datetime] = None

    def login(self) -> bool:
        """
        Sets up headers with the bearer token from config.
        The token is extracted from the authCke cookie in browser dev tools.
        """
        bearer_token = self.weekend_config.get("bearer_token")

        if bearer_token:
            self.headers = {
                **HEADERS,
                "Authorization": f"Bearer {bearer_token}",
            }
            self.full_cookies = ""
            self.auth_cookies = ""
            cookie_file = self.weekend_config.get("cookie_file")
            if cookie_file:
                cookie_path = Path.cwd() / "config_files" / cookie_file
                try:
                    self.full_cookies = cookie_path.read_text().strip()
                    # Auth-only cookies for endpoints that choke on Akamai cookies
                    auth_cookie_prefixes = (
                        "authCke", "OT-SessionId", "otuvid", "ha_userSession",
                    )
                    self.auth_cookies = "; ".join(
                        part.strip() for part in self.full_cookies.split(";")
                        if any(part.strip().startswith(p) for p in auth_cookie_prefixes)
                    )
                    logging.info(f"Cookies loaded from {cookie_file}")
                except FileNotFoundError:
                    logging.warning(
                        f"Cookie file {cookie_path} not found. "
                        "API calls may fail without cookies."
                    )
            logging.info("Bearer token set. Will validate on first API call.")
            return True

        logging.error("No bearer_token provided in config. "
                      "Extract the 'atk' value from the authCke cookie in browser dev tools.")
        return False

    def get_wishlist_restaurant_ids(self) -> List[Dict[str, Any]]:
        """
        Fetch the user's OpenTable Favorites/Wishlist via GraphQL.
        Returns a list of dicts with 'id' and 'name' keys.
        Results are cached for 6 hours.
        """
        if (
            self._wishlist_cache
            and self._wishlist_cache_time
            and self._wishlist_cache_time + timedelta(hours=6) > datetime.now()
        ):
            return self._wishlist_cache

        logging.info("Fetching restaurant wishlist from OpenTable...")
        payload = {
            "operationName": "UserWishlist",
            "variables": {"wishlistName": "Favorites", "gpid": 0},
            "extensions": {
                "persistedQuery": {
                    "version": 1,
                    "sha256Hash": WISHLIST_HASH,
                }
            },
        }
        wishlist_headers = {
            **self.headers,
            "Accept": "*/*",
            "Accept-Encoding": "gzip, deflate, br, zstd",
            "Cookie": self.auth_cookies,
            "x-csrf-token": self.weekend_config.get("csrf_token", ""),
            "ot-page-type": "user-favorites",
            "ot-page-group": "user",
            "sec-fetch-dest": "empty",
            "sec-fetch-mode": "cors",
            "sec-fetch-site": "same-origin",
            "x-query-timeout": "2000",
        }
        try:
            response = cffi_requests.post(
                f"{GQL_URL}?optype=query&opname=UserWishlist",
                headers=wishlist_headers,
                json=payload,
                timeout=15,
                impersonate="chrome",
            )
            logging.info(f"Wishlist response status: {response.status_code}")
            response.raise_for_status()
            data = response.json()

            if "errors" in data:
                logging.error(f"GraphQL errors fetching wishlist: {data['errors']}")
                return self._wishlist_cache

            restaurants_raw = (
                data.get("data", {}).get("userWishlist", {}).get("restaurants", [])
            )
            self._wishlist_cache = [
                {"id": r["rid"], "name": f"Restaurant {r['rid']}"}
                for r in restaurants_raw
                if "rid" in r
            ]
            self._wishlist_cache_time = datetime.now()
            logging.info(
                f"Fetched {len(self._wishlist_cache)} restaurants from wishlist"
            )
        except Exception as err:
            logging.error(
                f"Failed to fetch wishlist: {type(err).__name__}: {err}. "
                "Check that cookie_file and csrf_token are up to date from browser dev tools."
            )
            # Return stale cache if available
        return self._wishlist_cache

    def read_config_from_dropbox(self) -> Dict[str, Any]:
        refreshed_file = self.dbx_client.download_file(
            prefix=self.dropbox_prefix,
            local_path=self._local_config_filepath,
        )
        if not refreshed_file:
            logging.warning(
                "Failed to download config file from Dropbox. Falling back to local version"
            )
        return readconfig(str(self._local_config_filepath))

    def read_config_from_notion(self) -> Dict[str, Any]:
        api_key = self.notion_config_dict["api_key"]
        block_id = self.notion_config_dict["block_id"]
        resp = requests.get(
            f"https://api.notion.com/v1/blocks/{block_id}/",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Notion-Version": "2022-06-28",
            },
            timeout=30,
        )
        try:
            resp.raise_for_status()
        except requests.HTTPError as err:
            logging.warning(f"Failed to fetch config from Notion. Error: {str(err)}.")
            return {}
        json_text = resp.json()
        config_text = json_text["code"]["rich_text"][0]["plain_text"]
        return yaml.safe_load(config_text)

    @property
    def config_dict(self) -> Dict[str, Any]:
        if (
            self._last_config_sync_time
            and self._last_config_sync_time + timedelta(minutes=1) > datetime.now()
        ):
            return self._config_dict

        logging.debug("Cache time expired for config file. Refreshing.")

        self._last_config_sync_time = datetime.now()
        if self.local_config_only:
            self._config_dict = readconfig(self._local_config_filepath)
            return self._config_dict

        if self._remote_config_source == "dropbox":
            self._config_dict = self.read_config_from_dropbox()
        if self._remote_config_source == "notion":
            updated_config = self.read_config_from_notion()
            if updated_config:
                self._config_dict = updated_config

        return self._config_dict

    @property
    def weekend_config(self):
        weekend_overrides = (
            self.config_dict.get("weekend_overrides", {}).get(
                WEEKEND_OVERRIDE_KEY_MAPPING[self.current_week_number], {}
            )
            or {}
        )
        weekend_config = {}
        default_config: Dict[str, Any] = self.config_dict["default_config"]
        for key in default_config.keys():
            weekend_config[key] = weekend_overrides.get(key, default_config[key])
        weekend_config["restaurants"] = weekend_overrides.get(
            "restaurants", default_config.get("restaurants", [])
        )
        weekend_config["ignore"] = weekend_overrides.get("ignore")
        return weekend_config

    def get_date_config(self, date_: str) -> Dict[str, Any]:
        date_overrides = self.config_dict.get("specific_dates", {}).get(date_, {}) or {}
        date_config = {}
        default_config: Dict[str, Any] = self.config_dict["default_config"]
        for key in default_config.keys():
            date_config[key] = date_overrides.get(key, default_config[key])
        date_config["restaurants"] = date_overrides.get(
            "restaurants", default_config.get("restaurants", [])
        )
        date_config["ignore"] = date_overrides.get("ignore")
        return date_config

    @property
    def timezone(self) -> ZoneInfo:
        return ZoneInfo(self.weekend_config["timezone"])

    def get_availability(
        self, restaurant_id: int, date: str, time_str: str, party_size: int
    ) -> Tuple[List[Dict[str, Any]], str]:
        """
        Get available time slots for a restaurant on a given date via GraphQL.
        Returns a tuple of (available slot list, attributionToken).
        """
        payload = {
            "operationName": "RestaurantsAvailability",
            "variables": {
                "onlyPop": False,
                "forwardDays": 0,
                "requireTimes": False,
                "requireTypes": ["Standard", "Experience"],
                "useCBR": False,
                "privilegedAccess": [],
                "restaurantIds": [restaurant_id],
                "date": date,
                "time": time_str,
                "partySize": party_size,
                "databaseRegion": "NA",
                "restaurantAvailabilityTokens": [],
                "loyaltyRedemptionTiers": [],
                "attributionToken": "",
                "correlationId": str(uuid.uuid4()),
                "forwardMinutes": 210,
                "backwardMinutes": 210,
            },
            "extensions": {
                "persistedQuery": {
                    "version": 1,
                    "sha256Hash": AVAILABILITY_HASH,
                }
            },
        }
        avail_headers = {
            **self.headers,
            "Accept": "*/*",
            "Accept-Encoding": "gzip, deflate, br, zstd",
            "Cookie": self.full_cookies,
            "x-csrf-token": self.weekend_config.get("csrf_token", ""),
            "ot-page-group": "rest-profile",
            "ot-page-type": "restprofilepage",
            "sec-fetch-dest": "empty",
            "sec-fetch-mode": "cors",
            "sec-fetch-site": "same-origin",
            "sec-ch-ua": '"Not(A:Brand";v="8", "Chromium";v="144"',
            "sec-ch-ua-mobile": "?0",
            "sec-ch-ua-platform": '"macOS"',
        }
        try:
            response = cffi_requests.post(
                f"{GQL_URL}?optype=query&opname=RestaurantsAvailability",
                headers=avail_headers,
                json=payload,
                timeout=15,
                impersonate="chrome",
            )
            response.raise_for_status()
        except Exception as err:
            resp = getattr(err, 'response', None)
            if resp is not None:
                logging.error(
                    f"Failed to get availability for restaurant {restaurant_id}. "
                    f"Status: {resp.status_code}, Body: {resp.text[:500]}"
                )
            else:
                logging.error(
                    f"Failed to get availability for restaurant {restaurant_id}. "
                    f"Error: {type(err).__name__}: {err}"
                )
            return [], ""

        data = response.json()

        if "errors" in data:
            logging.error(f"GraphQL errors for restaurant {restaurant_id}: {data['errors']}")
            return [], ""

        availability_list = data.get("data", {}).get("availability", [])
        if not availability_list:
            return [], ""

        restaurant_avail = availability_list[0]
        attribution_token = restaurant_avail.get("restaurantAvailabilityToken", "")
        availability_days = restaurant_avail.get("availabilityDays", [])
        if not availability_days:
            return [], ""

        # Get slots from the first (and usually only) day
        day_data = availability_days[0]
        slots = day_data.get("slots", [])

        # Filter to only available slots
        available_slots = [s for s in slots if s.get("isAvailable", False)]
        return available_slots, attribution_token

    def lock_slot(
        self,
        restaurant_id: int,
        date_time_str: str,
        party_size: int,
        slot_hash: str,
        dining_area_id: int = 1,
    ) -> Optional[int]:
        """
        Lock a slot before booking. Returns slotLockId on success, None on failure.
        date_time_str should be in format "2026-04-24T19:00".
        """
        payload = {
            "operationName": "BookDetailsStandardSlotLock",
            "variables": {
                "input": {
                    "restaurantId": restaurant_id,
                    "seatingOption": "DEFAULT",
                    "reservationDateTime": date_time_str,
                    "partySize": party_size,
                    "databaseRegion": "NA",
                    "slotHash": slot_hash,
                    "reservationType": "STANDARD",
                    "diningAreaId": dining_area_id,
                }
            },
            "extensions": {
                "persistedQuery": {
                    "version": 1,
                    "sha256Hash": SLOT_LOCK_HASH,
                }
            },
        }
        lock_headers = {
            **self.headers,
            "Accept": "*/*",
            "Accept-Encoding": "gzip, deflate, br, zstd",
            "Cookie": self.full_cookies,
            "x-csrf-token": self.weekend_config.get("csrf_token", ""),
            "ot-page-group": "booking",
            "ot-page-type": "network_details",
            "sec-fetch-dest": "empty",
            "sec-fetch-mode": "cors",
            "sec-fetch-site": "same-origin",
            "sec-ch-ua": '"Not(A:Brand";v="8", "Chromium";v="144"',
            "sec-ch-ua-mobile": "?0",
            "sec-ch-ua-platform": '"macOS"',
        }
        try:
            response = cffi_requests.post(
                f"{GQL_URL}?optype=mutation&opname=BookDetailsStandardSlotLock",
                headers=lock_headers,
                json=payload,
                timeout=15,
                impersonate="chrome",
            )
            response.raise_for_status()
            data = response.json()

            lock_data = data.get("data", {}).get("lockSlot", {})
            if lock_data.get("success"):
                lock_id = lock_data["slotLock"]["slotLockId"]
                logging.info(f"Slot locked successfully. slotLockId: {lock_id}")
                return lock_id

            errors = lock_data.get("slotLockErrors")
            logging.error(f"Failed to lock slot: {errors}")
            return None
        except Exception as err:
            logging.error(f"Error locking slot: {type(err).__name__}: {err}")
            return None

    def book_reservation(
        self,
        restaurant_id: int,
        date_time_str: str,
        party_size: int,
        slot_hash: str,
        slot_lock_id: int,
        slot_availability_token: str,
        attribution_token: str = "",
        dining_area_id: int = 1,
    ) -> Optional[Dict[str, Any]]:
        """
        Complete a reservation via the REST booking endpoint.
        Returns the reservation response dict on success, None on failure.
        """
        config = self.weekend_config
        payload = {
            "additionalServiceFees": [],
            "attributionToken": attribution_token,
            "correlationId": str(uuid.uuid4()),
            "country": "US",
            "diningAreaId": dining_area_id,
            "email": config.get("email", ""),
            "firstName": config.get("first_name", ""),
            "isModify": False,
            "katakanaFirstName": "",
            "katakanaLastName": "",
            "lastName": config.get("last_name", ""),
            "nonBookableExperiences": [],
            "partySize": party_size,
            "points": 0,
            "pointsType": "POP",
            "reservationAttribute": "default",
            "reservationDateTime": date_time_str,
            "reservationType": "Standard",
            "restaurantId": restaurant_id,
            "slotAvailabilityToken": slot_availability_token,
            "slotHash": slot_hash,
            "slotLockId": slot_lock_id,
            "tipAmount": 0,
            "tipPercent": 0,
            "phoneNumber": config.get("phone", "").removeprefix("+1"),
            "phoneNumberCountryId": "US",
            "confirmPoints": False,
            "optInEmailRestaurant": False,
        }
        book_headers = {
            **self.headers,
            "Accept": "application/json",
            "Accept-Encoding": "gzip, deflate, br, zstd",
            "Accept-Language": "en-US, en, *",
            "Cookie": self.full_cookies,
            "x-csrf-token": config.get("csrf_token", ""),
            "sec-fetch-dest": "empty",
            "sec-fetch-mode": "cors",
            "sec-fetch-site": "same-origin",
            "sec-ch-ua": '"Not(A:Brand";v="8", "Chromium";v="144"',
            "sec-ch-ua-mobile": "?0",
            "sec-ch-ua-platform": '"macOS"',
        }
        try:
            response = cffi_requests.post(
                "https://www.opentable.com/dapi/booking/make-reservation",
                headers=book_headers,
                json=payload,
                timeout=15,
                impersonate="chrome",
            )
            if response.status_code >= 400:
                logging.error(
                    f"Booking request failed with status {response.status_code}. "
                    f"Response body: {response.text}"
                )
                response.raise_for_status()
            data = response.json()

            if data.get("success"):
                conf_num = data.get("confirmationNumber")
                res_id = data.get("reservationId")
                logging.info(
                    f"RESERVATION CONFIRMED! confirmationNumber={conf_num}, "
                    f"reservationId={res_id}"
                )
                return data

            logging.error(f"Booking failed. Response: {data}")
            return None
        except Exception as err:
            logging.error(f"Error booking reservation: {type(err).__name__}: {err}")
            return None

    def get_best_slot(
        self,
        slots: List[Dict[str, Any]],
        acceptable_delta_in_minutes: int,
    ) -> Optional[Dict[str, Any]]:
        """
        Returns the slot closest to the requested time (timeOffsetMinutes == 0)
        within the acceptable delta. Slots use timeOffsetMinutes relative to
        the requested time, so offset 0 = exact match, -30 = 30 min earlier, etc.
        """
        if not slots:
            return None

        acceptable_slots = [
            s for s in slots
            if abs(s.get("timeOffsetMinutes", 9999)) <= acceptable_delta_in_minutes
        ]
        if not acceptable_slots:
            logging.info(
                "No available slots within acceptable delta from desired time"
            )
            return None
        best = min(acceptable_slots, key=lambda x: abs(x.get("timeOffsetMinutes", 9999)))
        return best

    def scan_slots_and_book(
        self,
        restaurant_name: str,
        restaurant_id: int,
        desired_datetime: datetime,
        party_size: int,
        slots: List[Dict[str, Any]],
        acceptable_delta_in_minutes: int,
        attribution_token: str = "",
    ) -> bool:
        """
        Find the best slot and book it. Returns True if reservation is made.
        """
        best_slot = self.get_best_slot(
            slots=slots,
            acceptable_delta_in_minutes=acceptable_delta_in_minutes,
        )
        if best_slot is None:
            logging.info(
                f"No acceptable slots found at {restaurant_name} for {party_size} people "
                f"on {desired_datetime.strftime('%Y-%m-%d %H:%M')} "
                f"within {acceptable_delta_in_minutes} minutes."
            )
            return False

        offset = best_slot["timeOffsetMinutes"]
        slot_hash = best_slot.get("slotHash", "")
        slot_token = best_slot.get("slotAvailabilityToken", "")
        actual_time = desired_datetime + timedelta(minutes=offset)

        logging.info(
            f"Found a table at {restaurant_name}! "
            f"Desired: {desired_datetime.strftime('%Y-%m-%d %H:%M')}, "
            f"Found: {actual_time.strftime('%H:%M')} (offset: {offset} min), "
            f"slotHash: {slot_hash}"
        )

        # Step 1: Lock the slot
        date_time_str = actual_time.strftime("%Y-%m-%dT%H:%M")
        lock_id = self.lock_slot(
            restaurant_id=restaurant_id,
            date_time_str=date_time_str,
            party_size=party_size,
            slot_hash=slot_hash,
        )
        if lock_id is None:
            logging.error(f"Failed to lock slot at {restaurant_name}. Skipping.")
            return False

        # Step 2: Book the reservation
        result = self.book_reservation(
            restaurant_id=restaurant_id,
            date_time_str=date_time_str,
            party_size=party_size,
            slot_hash=slot_hash,
            slot_lock_id=lock_id,
            slot_availability_token=slot_token,
            attribution_token=attribution_token,
        )
        if result:
            logging.info(
                f"Successfully booked {restaurant_name} for {party_size} people "
                f"on {actual_time.strftime('%Y-%m-%d %H:%M')}! "
                f"Confirmation: {result.get('confirmationNumber')}"
            )
            return True

        logging.error(
            f"Locked slot at {restaurant_name} (lockId={lock_id}) but booking failed."
        )
        return False


def too_late_to_book(
    day: datetime, tzinfo: ZoneInfo, max_allowed_delta_in_hours: int = 3
) -> bool:
    now = datetime.now(tzinfo)
    return day.date() == now.date() and (
        now > day
        or (day - now).total_seconds() < 60 * 60 * max_allowed_delta_in_hours
    )


def grab_table_for_day(
    day: datetime,
    tzinfo: ZoneInfo,
    bot: OpenTableBot,
    party_size: int,
    acceptable_delta_in_minutes: int,
    restaurants: List[Dict[str, Any]],
    override_restaurants: List[Dict[str, Any]] = [],
    book_last_minute_reservations: bool = False,
):
    logging.info(f"Looking for a table for {day.strftime('%Y-%m-%d')}")

    if too_late_to_book(day=day, tzinfo=tzinfo) and not book_last_minute_reservations:
        logging.info("Too late to seek a reservation for today. Skipping.")
        return

    date_str = day.strftime("%Y-%m-%d")
    time_str = day.strftime("%H:%M")

    # Use override restaurants if provided, then static list, then wishlist
    restaurants_to_check = override_restaurants if override_restaurants else restaurants
    if not restaurants_to_check:
        restaurants_to_check = bot.get_wishlist_restaurant_ids()

    for i, restaurant in enumerate(restaurants_to_check):
        rid = restaurant["id"]
        rname = restaurant["name"]

        if i > 0:
            time.sleep(2)

        logging.info(f"Checking availability at {rname} for {date_str}")

        slots, attribution_token = bot.get_availability(
            restaurant_id=rid,
            date=date_str,
            time_str=time_str,
            party_size=party_size,
        )

        if not slots:
            logging.info(f"No slots available at {rname} for {date_str}")
            continue

        logging.info(f"Found {len(slots)} slots at {rname} for {date_str}")

        reserved = bot.scan_slots_and_book(
            restaurant_name=rname,
            restaurant_id=rid,
            desired_datetime=day,
            party_size=party_size,
            slots=slots,
            acceptable_delta_in_minutes=acceptable_delta_in_minutes,
            attribution_token=attribution_token,
        )
        if reserved:
            logging.info(f"Booked table for {date_str} at {rname}!")
            break


def process_weekend(bot: OpenTableBot, week_to_process: int) -> bool:
    """Returns False if weekend was skipped, True otherwise."""
    bot.current_week_number = week_to_process
    if bot.weekend_config["ignore"]:
        logging.debug(
            f"ignore flag set to True for {WEEKEND_OVERRIDE_KEY_MAPPING[week_to_process]}. Skipping."
        )
        return False
    logging.info(
        f"Processing weekend: {WEEKEND_OVERRIDE_KEY_MAPPING[week_to_process]}."
    )
    config = bot.weekend_config
    party_size = config["party_size"]
    preferred_reservation_time = config["preferred_reservation_time"]
    acceptable_delta_in_minutes = config["acceptable_delta_in_minutes"]
    book_last_minute_reservations = config.get("book_last_minute_reservations", False)
    desired_datetime = datetime.strptime(preferred_reservation_time, "%H:%M")
    tzinfo = ZoneInfo(config["timezone"])
    today = datetime.now(tzinfo)
    today = today.replace(
        hour=desired_datetime.hour,
        minute=desired_datetime.minute,
        second=0,
        microsecond=0,
    )
    restaurants = config.get("restaurants", [])
    # If the weekend override has its own restaurant list, use that as override
    weekend_overrides = (
        bot.config_dict.get("weekend_overrides", {}).get(
            WEEKEND_OVERRIDE_KEY_MAPPING[week_to_process], {}
        )
        or {}
    )
    override_restaurants = weekend_overrides.get("restaurants", [])

    next_friday = (
        today
        + timedelta(days=(7 * week_to_process))
        + timedelta(days=(FRIDAY - today.weekday()) % 7)
    )
    next_saturday = next_friday + timedelta(days=1)

    specific_dates_configs = bot.config_dict.get("specific_dates", {}) or {}
    specific_dates_list = specific_dates_configs.keys()
    for day in [next_friday, next_saturday]:
        if day.strftime("%Y-%m-%d") in specific_dates_list:
            logging.info(
                f"Found weekend date {day.strftime('%Y-%m-%d')} in specific_dates list. Ignoring during weekend processing."
            )
            continue
        grab_table_for_day(
            day=day,
            tzinfo=tzinfo,
            bot=bot,
            party_size=party_size,
            acceptable_delta_in_minutes=acceptable_delta_in_minutes,
            restaurants=restaurants,
            override_restaurants=override_restaurants,
            book_last_minute_reservations=book_last_minute_reservations,
        )
    return True


def process_specific_date(bot: OpenTableBot, date_: str):
    date_config = bot.get_date_config(date_=date_)
    if date_config["ignore"]:
        logging.debug(f"ignore flag set to True for specific date {date_}. Skipping.")
        return False
    party_size = date_config["party_size"]
    preferred_reservation_time = date_config["preferred_reservation_time"]
    acceptable_delta_in_minutes = date_config["acceptable_delta_in_minutes"]
    book_last_minute_reservations = date_config.get(
        "book_last_minute_reservations", False
    )
    desired_datetime = datetime.strptime(preferred_reservation_time, "%H:%M")
    tzinfo = ZoneInfo(date_config["timezone"])
    day = datetime.combine(date_, datetime.min.time())
    day = day.replace(
        hour=desired_datetime.hour,
        minute=desired_datetime.minute,
        second=0,
        microsecond=0,
        tzinfo=tzinfo,
    )
    restaurants = date_config.get("restaurants", [])
    override_restaurants = date_config.get("restaurants", [])
    logging.info(f"Processing specific date {day.strftime('%Y-%m-%d')}")
    grab_table_for_day(
        day=day,
        tzinfo=tzinfo,
        bot=bot,
        party_size=party_size,
        acceptable_delta_in_minutes=acceptable_delta_in_minutes,
        restaurants=restaurants,
        override_restaurants=override_restaurants,
        book_last_minute_reservations=book_last_minute_reservations,
    )


@click.command()
@click.option(
    "--config-file",
    required=True,
    default=Path.cwd() / "config_files/startup_config.yaml",
    help="Path to file containing startup configuration info",
    show_default=True,
)
@click.option(
    "--debug/--no-debug",
    default=False,
)
def main(
    config_file: Path,
    debug: bool,
):
    basic_config["level"] = logging.INFO if not debug else logging.DEBUG
    logging.basicConfig(**basic_config)

    bot = OpenTableBot(
        config_file=config_file,
    )
    is_logged_in = bot.login()
    if not is_logged_in:
        logging.error("Unable to login")
        return 1

    logging.info("Logged in successfully")

    # Pre-fetch and report wishlist if no static restaurant list is configured
    static_restaurants = bot.config_dict["default_config"].get("restaurants", [])
    if static_restaurants:
        logging.info(
            f"Using {len(static_restaurants)} statically configured restaurant(s): "
            + ", ".join(f"{r['name']} ({r['id']})" for r in static_restaurants)
        )
    else:
        wishlist = bot.get_wishlist_restaurant_ids()
        if wishlist:
            logging.info(
                f"Using {len(wishlist)} restaurant(s) from OpenTable wishlist: "
                + ", ".join(str(r["id"]) for r in wishlist)
            )
        else:
            logging.warning(
                "No restaurants configured and wishlist is empty. "
                "Add restaurants to your config or save favorites on OpenTable."
            )
            return 1

    week_to_process = -1
    sleep_time_in_secs = bot.config_dict["default_config"].get(
        "sleep_time_in_seconds", 5
    )

    while True:
        # Process any specific dates
        specific_dates_configs: Dict[datetime.date, Any] = (
            bot.config_dict.get("specific_dates", {}) or {}
        )
        for date_ in specific_dates_configs.keys():
            if date_ < datetime.now().date():
                logging.debug(f"Skipping {date_} as it's in the past")
                continue
            process_specific_date(bot=bot, date_=date_)

            logging.debug(f"Sleeping for {sleep_time_in_secs}s")
            time.sleep(sleep_time_in_secs)

        # Process upcoming weekends
        for _ in range(bot.config_dict["default_config"].get("weeks_to_process", 8)):
            week_to_process = (week_to_process + 1) % bot.config_dict[
                "default_config"
            ].get("weeks_to_process", 8)
            need_to_sleep = process_weekend(bot=bot, week_to_process=week_to_process)

            if need_to_sleep:
                logging.debug(f"Sleeping for {sleep_time_in_secs}s")
                time.sleep(sleep_time_in_secs)


if __name__ == "__main__":
    main()
