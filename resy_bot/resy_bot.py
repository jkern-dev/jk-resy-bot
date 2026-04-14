from calendar import FRIDAY
from datetime import datetime, timedelta

from zoneinfo import ZoneInfo
import time
import logging
import yaml
import requests
from typing import List, Literal, Optional, Dict, Any
from pathlib import Path
import click

# from dropbox_client import DropboxClient
from resy_api_wrapper import ResyApiRequestWrapper

ResType = Literal["past", "upcoming"]

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
    "X-Origin": "https://resy.com",
    "Cache-Control": "no-cache",
    "DNT": "1",
    "Connection": "keep-alive",
    "Sec-Fetch-Dest": "empty",
    "Sec-Fetch-Mode": "cors",
    "Sec-Fetch-Site": "same-site",
    "Pragma": "no-cache",
    "TE": "trailers",
    "Host": "api.resy.com",
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:130.0) Gecko/20100101 Firefox/130.0",
    "Origin": "https://resy.com",
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


class ResyBot:
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
            / startup_config.get("resy_config_file", "resy_config.yaml")
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

        self.payment_method_string = None
        self.headers = None
        self._past_res_refresh_time: Optional[datetime] = None
        self._past_res_venue_ids: List[str] = []
        self.current_week_number: int = 0
        self._config_dict: Dict[str, Any] = {}
        self._last_config_sync_time: Optional[datetime] = None
        self.dbx_client = None
        self.notion_config_dict = {}
        if not self.local_config_only:
            if self._remote_config_source == "dropbox":
                logging.info(f"remote_config_source set to dropbox")
                self.dbx_client = DropboxClient(
                    secrets_file=Path.cwd() / "config_files" / dropbox_secrets_file
                )
            if self._remote_config_source == "notion":
                logging.info(f"remote_config_source set to notion")
                self.notion_config_dict = (
                    readconfig(
                        config_file=Path.cwd() / "config_files" / notion_secrets_file
                    )
                    if self._remote_config_source == "notion"
                    else {}
                )

        self.resy_api_wrapper = ResyApiRequestWrapper()

    def email_auth(self) -> Optional[str]:
        """Tries to log in using email+password auth. Returns auth token if successful and None otherwise"""
        username, password = (
            self.weekend_config["username"],
            self.weekend_config["password"],
        )
        data = {"email": username, "password": password}

        logging.debug(f"Starting email auth for {username}")
        response = self.resy_api_wrapper.post(
            "https://api.resy.com/3/auth/password", headers=self.headers, data=data
        )
        try:
            response.raise_for_status()
        except requests.HTTPError as err:
            logging.error(
                f"Failed to log in using email auth. Response body: {response.text}"
            )
            return None
        res_data = response.json()
        logging.debug(f"Email auth successful")
        return res_data

    def _send_auth_code_to_mobile_number(self, phone_number: str) -> bool:
        """Initiate the mobile auth process. This first request will trigger sending an SMS to the phone number."""

        data = {"mobile_number": phone_number, "method": "sms"}
        logging.debug(f"Starting mobile auth for {phone_number}")
        try:
            response = self.resy_api_wrapper.post(
                "https://api.resy.com/3/auth/mobile", headers=self.headers, data=data
            )
        except requests.exceptions.RetryError:
            logging.error(
                f"Failed to send auth code to {phone_number} due to throttling."
            )
            return False

        try:
            response.raise_for_status()
        except requests.exceptions.HTTPError as err:
            logging.error(
                f"Failed to send auth code to {phone_number}. Response body: {response.text}"
            )
            return False

        res_data = response.json()

        if not res_data.get("sent", False):
            logging.error(
                f"Failed to send auth code to {phone_number}. Response JSON: {res_data}"
            )
            return False

        logging.info(
            f"Started mobile auth process. A code has been sent to {phone_number}."
        )
        return True

    def _log_in_using_mobile_auth_code(
        self,
        phone_number: str,
        device_token: str = "49b8dc7e-a8c3-4d73-86a3-9a4061a531f7",
    ) -> Optional[Dict[Any, Any]]:

        mobile_auth_code = self.weekend_config["mobile_auth_code"]
        logging.debug(f"Trying to log in using mobile auth. Code in remote config: {mobile_auth_code}")

        if mobile_auth_code == "":
            logging.info(
                f"mobile_auth_code is empty. Sleeping again to allow for uploading code to remote config"
            )
            return None

        # else there is a value for mobile_auth_code. Let's hope it's not a stale one that hasn't been updated...
        data = {
            "mobile_number": phone_number,
            "code": mobile_auth_code,
            "device_type_id": "3",
            "device_token": device_token,
        }

        response = self.resy_api_wrapper.post(
            "https://api.resy.com/3/auth/mobile", headers=self.headers, data=data
        )

        try:
            response.raise_for_status()
        except requests.HTTPError as err:
            logging.error(
                f"Failed to complete mobile auth. Did you upload the right code to remote_config? Response text: {response.text}"
            )
            return None

        logging.debug("Mobile auth code challenge successful.")
        return response.json()

    def _complete_mobile_auth_challenge_workflow(
        self,
        challenge_id: str,
        email_address: str,
        device_token="49b8dc7e-a8c3-4d73-86a3-9a4061a531f7",
    ) -> Optional[Dict[Any, Any]]:
        data = {
            "challenge_id": challenge_id,
            "em_address": email_address,
            "device_type_id": "3",
            "device_token": device_token,
        }
        logging.debug(f"Completing email challenge for mobile auth")

        response = self.resy_api_wrapper.post(
            "https://api.resy.com/3/auth/challenge", headers=self.headers, data=data
        )
        try:
            response.raise_for_status()
            logging.debug("Email challenge for mobile auth completed.")
            return response.json()
        except requests.HTTPError as err:
            logging.error(
                f"Failed to complete mobile auth. Email verification failed? Response text: {response.text}"
            )
            return None

    def mobile_auth(self) -> Optional[str]:
        """Tries to log in using email+password auth. Returns auth token if successful and None otherwise"""
        phone_number = self.weekend_config["phone_number"]

        if not self._send_auth_code_to_mobile_number(phone_number=phone_number):
            logging.error("Mobile auth initiation failed.")
            return None

        login_attempts = 0
        max_login_attempts = 5
        need_to_send_new_auth_code_to_mobile_number = False

        while login_attempts < max_login_attempts:
            login_attempts += 1
            logging.debug(f"Mobile auth login workflow initiated. login_attempt: {login_attempts} of {max_login_attempts}")
            if need_to_send_new_auth_code_to_mobile_number:
                self._send_auth_code_to_mobile_number(phone_number=phone_number)
                need_to_send_new_auth_code_to_mobile_number = False
            logging.info(
                f"Sleeping for 1 minute to allow human to upload code to remote config under 'mobile_auth_code' key."
            )
            time.sleep(60)

            res_data = self._log_in_using_mobile_auth_code(phone_number=phone_number)
            if not res_data:
                logging.error("Mobile auth completion failed.")
                continue

            # In case the auth fails due to our inability to complete the challenge workflow, we would need to start over
            # with a new code being sent to the phone number
            need_to_send_new_auth_code_to_mobile_number = True
            if res_data.get("challenge"):
                # The mobile auth requires verifying the account email.

                challenge_id = res_data["challenge"]["challenge_id"]
                email_address = self.weekend_config["username"]

                res_data = self._complete_mobile_auth_challenge_workflow(
                    challenge_id=challenge_id, email_address=email_address
                )
                if not res_data:
                    logging.error("Mobile auth challenge completion failed.")
                    continue

            # If we reach this point, we have completed mobile auth including email challenges.
            return res_data

    def login(self):
        """
        Logs in and sets the first payment method on file as the one to use when making reservations.
        """

        api_key = self.weekend_config["api_key"]
        self.headers = {**HEADERS, "Authorization": f'ResyAPI api_key="{api_key}"'}

        res_data = self.email_auth() or self.mobile_auth()
        if not res_data:
            logging.error("Failed to log in with both email and mobile auth.")
            return False

        # The mobile auth workflow returns the user details nested within a 'user' key
        if "user" in res_data.keys():
            res_data = res_data["user"]
        self.auth_token = res_data["token"]
        self.payment_method_string = f'{{"id":{str(res_data["payment_method_id"])}}}'

        self.headers = {
            **self.headers,
            "X-Resy-Auth-Token": self.auth_token,
            "X-Resy-Universal-Auth": self.auth_token,
        }
        return True

    def read_config_from_dropbox(self) -> Dict[str, Any]:
        """
        Fetches the configured dropbox file, updates the local copy and returns contents.
        If fetch fails, will return existing contents of local file.
        """
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
        """
        Reads the configured code block from Notion and returns it parsed as a YAML dict.
        Returns empty dict if Notion calls fail.
        """
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
        """
        Will sync the latest version of the config_file from remote.
        If the sync fails, will fall back to previously downloaded state
        """
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
            # Ignore if notion calls failed and the code gave back an empty dict
            if updated_config:
                self._config_dict = updated_config

        return self._config_dict

    @property
    def weekend_config(self):
        """
        Parses the config file on each invocation.
        The repeated reads are because we assume the file could've been updated at any point.
        """
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
        weekend_config["venues"] = weekend_overrides.get("venues", [])
        weekend_config["ignore"] = weekend_overrides.get("ignore")
        return weekend_config

    def get_date_config(self, date_: str) -> Dict[str, Any]:
        """
        Parses the config file on each invocation.
        The repeated reads are because we assume the file could've been updated at any point.
        """
        date_overrides = self.config_dict.get("specific_dates", {}).get(date_, {}) or {}
        date_config = {}
        default_config: Dict[str, Any] = self.config_dict["default_config"]
        for key in default_config.keys():
            date_config[key] = date_overrides.get(key, default_config[key])
        date_config["venues"] = date_overrides.get("venues", [])
        date_config["ignore"] = date_overrides.get("ignore")
        return date_config

    @property
    def timezone(self) -> ZoneInfo:
        return ZoneInfo(self.weekend_config["timezone"])

    @property
    def past_reservation_venue_ids(self) -> List[str]:
        """
        Will refresh past reservations once every 6 hours.
        """
        if (
            self._past_res_refresh_time is not None
            and self._past_res_refresh_time + timedelta(minutes=60 * 6) < datetime.now()
        ):
            return self._past_res_venue_ids
        self._past_res_venue_ids = self.get_past_reservations_venue_ids()
        self._past_res_refresh_time = datetime.now()
        return self._past_res_venue_ids

    def get_reservations(self, res_type: ResType, limit: int = 100):
        """
        Returns reservations (past or upcoming) for the logged in user
        """
        params = {
            "limit": limit,
            "type": res_type,
            "book_on_behalf_of": False,
        }

        response = self.resy_api_wrapper.get(
            "https://api.resy.com/3/user/reservations",
            headers=self.headers,
            params=params,
        )
        response.raise_for_status()
        reservations = response.json()["reservations"]
        return reservations

    def get_upcoming_reservations_for_date(self, desired_datetime: datetime):
        """
        Returns all upcoming reservations for a given date.
        Does not filter on time.
        """
        reservations = self.get_reservations(res_type="upcoming")
        return [
            r
            for r in reservations
            if r["day"] == desired_datetime.date().strftime("%Y-%m-%d")
        ]

    def get_past_reservations_venue_ids(
        self, include_no_shows: bool = False
    ) -> List[int]:
        """
        Returns the Resy venue IDs for all previous reservations within the given
        number of months. Note that all months are assumed to be 30 days for simplicity.
        By default, will ignore any reservation that you held where you were marked as a no show.
        """
        reservations = self.get_reservations(res_type="past")
        cutoff_date = datetime.now(
            ZoneInfo(self.weekend_config["timezone"])
        ) - timedelta(days=self.weekend_config.get("min_days_since_last_visit", 90))
        recent_reservations = [
            r
            for r in reservations
            if datetime.strptime(r["day"], "%Y-%m-%d").replace(tzinfo=self.timezone)
            >= cutoff_date
        ]
        if not include_no_shows:
            recent_reservations = [
                r for r in recent_reservations if r["status"]["no_show"] == 0
            ]
        return [r["venue"]["id"] for r in recent_reservations]

    def get_available_slots_at_favorites(self, day: datetime, party_size: int):
        """
        For a given datetime, returns all available reservations for the given party size
        at all the venues currently in the user's Hit List in their profile.
        """
        params = {"day": day.strftime("%Y-%m-%d"), "party_size": party_size}
        response = self.resy_api_wrapper.get(
            "https://api.resy.com/3/user/favorites",
            headers=self.headers,
            params=params,
        )
        response.raise_for_status()
        json_resp = response.json()
        return json_resp["results"]["venues"]

    def get_best_slot(
        self,
        desired_datetime: datetime,
        slots,
        acceptable_delta_in_minutes: int,
        book_only_refundable_reservations: bool,
        book_prepaid_reservations: bool,
    ):
        """
        For a given date and time, will return the closest timeslot out of the ones provided
        within the provided delta in minutes in either direction.
        If no slots fall within the given delta, will return None.
        """
        if len(slots) == 0:
            return None
        slots_with_deltas = [
            {
                "slot": s,
                "delta": (
                    desired_datetime
                    - datetime.strptime(
                        s["date"]["start"], "%Y-%m-%d %H:%M:%S"
                    ).replace(tzinfo=self.timezone)
                ).total_seconds(),
            }
            for s in slots
        ]
        acceptable_delta_in_seconds = acceptable_delta_in_minutes * 60
        acceptable_slots = [
            s
            for s in slots_with_deltas
            if int(abs(s["delta"])) <= acceptable_delta_in_seconds
        ]
        if acceptable_slots == []:
            logging.info(
                "No available slots within acceptable delta from desired datetime"
            )
            return None
        best_slot = min(acceptable_slots, key=lambda x: abs(x["delta"]))["slot"]
        requires_payment = best_slot["payment"].get("is_paid", False)
        if not requires_payment:
            return best_slot

        is_prepaid_reservation = best_slot["payment"]["deposit_fee"] is not None
        if is_prepaid_reservation:
            if book_prepaid_reservations is False:
                logging.info("Reservation requires pre-payment. Skipping.")
                return None
            else:
                logging.info(
                    "Slot is prepaid and book_prepaid_reservations is set to True! Trying to book!"
                )
                return best_slot

        slot_is_refundable = self.slot_is_cancellable_for_free(slot=best_slot)

        if book_only_refundable_reservations and not slot_is_refundable:
            logging.info(
                "Reservation requires a deposit but only_refundable_reservations is True. Skipping."
            )
            return None
        return best_slot

    def find_slots_at_venue(self, desired_datetime: datetime, party_size, venue_id):
        """
        For a given Resy venue ID and a date and party size, will return a list of all
        available slots. Note that this method does not filter any slots based on time.
        """
        # convert datetime to string
        day = desired_datetime.date().strftime("%Y-%m-%d")
        params = (
            ("day", day),
            ("lat", "0"),
            ("long", "0"),
            ("party_size", str(party_size)),
            ("venue_id", str(venue_id)),
        )
        response = self.resy_api_wrapper.get(
            "https://api.resy.com/4/find",
            headers=self.headers,
            params=params,
        )
        response.raise_for_status()
        data = response.json()
        results = data["results"]
        if len(results["venues"]) == 0:
            return []
        open_slots = results["venues"][0]["slots"]
        return open_slots

    def scan_slots_and_book(
        self,
        venue_name: str,
        desired_datetime: datetime,
        party_size: int,
        slots,
        acceptable_delta_in_minutes: int,
        book_only_refundable_reservations: bool,
        book_prepaid_reservations: bool,
    ) -> bool:
        """
        Out of a given list of available slots, will try and book the best one
        that falls within the provided delta in minutes from the given datetime period.
        Returns True if a reservation is successfully made.
        """
        best_table = self.get_best_slot(
            desired_datetime=desired_datetime,
            slots=slots,
            acceptable_delta_in_minutes=acceptable_delta_in_minutes,
            book_only_refundable_reservations=book_only_refundable_reservations,
            book_prepaid_reservations=book_prepaid_reservations,
        )
        if best_table is None:
            logging.info(
                f"No acceptable slots found at {venue_name} for {party_size} people on {desired_datetime.strftime('%Y-%m-%d %H:%M')} within {acceptable_delta_in_minutes} minutes."
            )
            return False
        else:
            config_id = best_table["config"]["token"]
            logging.info(
                f"Found a table at {venue_name}! Desired datetime: {desired_datetime.strftime('%Y-%m-%d %H:%M')}, found time: {best_table['date']['start']}"
            )
            self.make_reservation(
                config_id=config_id,
                res_date=desired_datetime.date().strftime("%Y-%m-%d"),
                party_size=party_size,
            )
            logging.info("Success")
            return True

    def make_reservation(self, config_id, res_date, party_size):
        party_size = str(party_size)
        params = (
            ("config_id", str(config_id)),
            ("day", res_date),
            ("party_size", str(party_size)),
        )
        details_request = self.resy_api_wrapper.get(
            "https://api.resy.com/3/details",
            headers=self.headers,
            params=params,
        )
        details_request.raise_for_status()
        details = details_request.json()
        book_token = details["book_token"]["value"]
        data = {
            "book_token": book_token,
            "struct_payment_method": self.payment_method_string,
            "source_id": "resy.com-venue-details",
        }

        response = self.resy_api_wrapper.post(
            "https://api.resy.com/3/book",
            headers=self.headers,
            data=data,
        )
        try:
            response.raise_for_status()
        except requests.HTTPError as e:
            logging.error(f"Booking failed with error: {e}")
            logging.info(f"Request body: {response.request.body}")
            logging.info(f"Request headers: {response.request.headers}")
            logging.info(f"Response: {response.text}")
        logging.info(f"Booking response: {response.json()}")

    def cancel_reservation(self, reservation) -> bool:
        data = {"resy_token": reservation["resy_token"]}
        response = self.resy_api_wrapper.post(
            "https://api.resy.com/3/cancel", data=data, headers=self.headers
        )
        response.raise_for_status()
        return True

    def slot_is_cancellable_for_free(self, slot) -> True:
        """
        Returns True if the given slot is:
        * NOT a prepaid table
        * Is fully refundable
        * Has at least 24 hours between now and the cancellation deadline
        """
        if slot["payment"]["deposit_fee"] is not None:
            return False

        slot_datetime = datetime.strptime(
            slot["date"]["start"], "%Y-%m-%d %H:%M:%S"
        ).replace(tzinfo=self.timezone)

        # This is the time of day on the reservation date starting from when the cancellation deadline is calcuated.
        # Some reservations set the cancellation window starting from midnight on the day, as opposed to the time of
        # the reservation.
        time_cancel_cut_off = slot["payment"]["time_cancel_cut_off"]

        if time_cancel_cut_off:
            time_cancel_cut_off = datetime.strptime(
                f"{slot_datetime.strftime('%Y-%m-%d')} {time_cancel_cut_off}",
                "%Y-%m-%d %H:%M:%S",
            ).replace(tzinfo=self.timezone)
        else:
            time_cancel_cut_off = slot_datetime

        secs_cancel_cut_off = slot["payment"]["secs_cancel_cut_off"]
        cancellation_deadline = time_cancel_cut_off - timedelta(
            seconds=secs_cancel_cut_off
        )
        if datetime.now(self.timezone) + timedelta(hours=24) > cancellation_deadline:
            logging.info("Slot is too close to now to cancel for free.")
            return False

        return True

    def reservation_is_cancellable_for_free(self, reservation) -> bool:
        """
        Returns True if the reservation is:
        * NOT a prepaid table
        * Is fully refundable
        * Is far enough ahead in the future that you can cancel and get the full refund
        """
        is_paid_reservation = reservation["payment_method"] is None
        if not is_paid_reservation:
            return True
        cancellation_details = reservation["cancellation"]
        if not cancellation_details["allowed"]:
            return False

        # For reservations, resy stores the cancellation cut-off timestamps in UTC
        # Baking in a 5m buffer for free cancellation, just in case
        if datetime.strptime(
            cancellation_details["date_refund_cut_off"], "%Y-%m-%dT%H:%M:%SZ"
        ) - datetime.now() > timedelta(minutes=5):
            return True
        return False


def too_late_to_book(
    day: datetime, tzinfo: ZoneInfo, max_allowed_delta_in_hours: int = 3
) -> bool:
    """
    Returns True if there's fewer than max_allowed_delta_in_hours between the desired reservation time and now.
    Default delta is 3 hours.
    """
    now = datetime.now(tzinfo)
    return day.date() == now.date() and (
        now > day
        # Don't look for a reservation for today if the preferred time is within 3 hours of now
        or (day - now).total_seconds() < 60 * 60 * max_allowed_delta_in_hours
    )


def get_upcoming_reservations(bot: ResyBot, tzinfo: ZoneInfo) -> List[Any]:
    """
    Returns a list of upcoming reservations with an added py_datetime field that's a datetime object
    localized to the given tzinfo.
    """
    upcoming_reservations = bot.get_reservations(res_type="upcoming")
    if len(upcoming_reservations) != 0:
        upcoming_reservations = [
            {
                **r,
                "py_datetime": datetime.strptime(
                    f"{r['day']} {r['time_slot']}", "%Y-%m-%d %H:%M:%S"
                ).replace(tzinfo=tzinfo),
            }
            for r in upcoming_reservations
        ]
        return upcoming_reservations
    return []


def grab_table_for_day(
    day: datetime,
    tzinfo: ZoneInfo,
    bot: ResyBot,
    party_size: int,
    acceptable_delta_in_minutes: int,
    override_venues: List[str] = [],
    ignore_recent_bookings: bool = False,
    book_only_refundable_reservations: bool = True,
    book_prepaid_reservations: bool = False,
    book_last_minute_reservations: bool = False,
):
    logging.info(f"Looking for a table for {day.strftime('%Y-%m-%d')}")

    if too_late_to_book(day=day, tzinfo=tzinfo) and not book_last_minute_reservations:
        logging.info("Too late to seek a reservation for today. Skipping.")
        return
    upcoming_reservations = get_upcoming_reservations(bot=bot, tzinfo=tzinfo)

    # If we have another reservation on the same day within 5 hours of our desired slot,
    # don't look for another table on that day
    conflicting_reservations = [
        r
        for r in upcoming_reservations
        if abs((day - r["py_datetime"]).total_seconds()) < 5 * 60 * 60
    ]
    if len(conflicting_reservations) != 0:
        logging.info(
            f"Already have a conflicting table booked for {day.strftime('%Y-%m-%d')}. Skipping."
        )
        return

    favorites = bot.get_available_slots_at_favorites(day=day, party_size=party_size)
    for venue in favorites:
        venue_name = venue["venue"]["name"]

        if len(override_venues) and venue_name not in override_venues:
            logging.info(
                f"Venue not in weekend overrides. Venue: {venue_name}, overrides: {override_venues}"
            )
            continue

        venue_id = venue["venue"]["id"]["resy"]

        if venue_id in bot.past_reservation_venue_ids:
            if not ignore_recent_bookings:
                logging.info(f"Have been to {venue_name} in the recent past! Skipping")
                continue
            else:
                logging.info(
                    f"Have been to {venue_name} in the recent past but ignore_recent_bookings set to True! Trying to book."
                )

        upcoming_reservations_at_this_venue = None
        less_optimal_upcoming_res = None

        upcoming_reservations_at_this_venue = sorted(
            [r for r in upcoming_reservations if r["venue"]["id"] == venue_id],
            key=lambda r: r["py_datetime"],
        )
        if len(upcoming_reservations_at_this_venue):
            less_optimal_upcoming_res = upcoming_reservations_at_this_venue[0]
            if less_optimal_upcoming_res["py_datetime"] < day:
                logging.info(
                    f"Have an upcoming reservation at {venue_name} that's closer to now. Skipping."
                )
                continue
            # If the closest upcoming reservation at this venue is more than two days after
            # the weekend day for which we are searching right now,
            # we assume that the reservation is at least a week away, in which case
            # we will try to find one for this weekend day.
            if less_optimal_upcoming_res["py_datetime"] - day < timedelta(days=2):
                logging.info(
                    f"Have an upcoming reservation at {venue_name} that's within 2 days of {day.isoformat()}! Skipping"
                )
                continue
            if bot.reservation_is_cancellable_for_free(less_optimal_upcoming_res):
                logging.info(
                    f"Have an upcoming reservation at {venue_name}, but trying to get one sooner."
                )

        logging.info(f"Inspecting slots for {day.isoformat()} at {venue_name}")

        reserved = bot.scan_slots_and_book(
            venue_name=venue_name,
            desired_datetime=day,
            party_size=party_size,
            slots=venue["slots"],
            acceptable_delta_in_minutes=acceptable_delta_in_minutes,
            book_only_refundable_reservations=book_only_refundable_reservations,
            book_prepaid_reservations=book_prepaid_reservations,
        )
        if reserved:
            logging.info(f"Booked table for {day.date()} at {venue_name}!")
            if less_optimal_upcoming_res:
                logging.info(
                    f"Going to cancel future booking at {venue_name} for {less_optimal_upcoming_res['py_datetime']}"
                )
                result = bot.cancel_reservation(reservation=less_optimal_upcoming_res)
                if not result:
                    logging.warning(
                        f"Unable to cancel future reservation at {venue_name} for {less_optimal_upcoming_res['py_datetime']}!"
                    )
            break


def process_weekend(bot: ResyBot, week_to_process: int) -> bool:
    """
    Returns False if weekend was skipped, True otherwise
    """
    bot.current_week_number = week_to_process
    if bot.weekend_config["ignore"]:
        logging.debug(
            f"ignore flag set to True for {WEEKEND_OVERRIDE_KEY_MAPPING[week_to_process]}. Skipping."
        )
        return False
    logging.info(
        f"Processing weekend: {WEEKEND_OVERRIDE_KEY_MAPPING[week_to_process]}."
    )
    party_size = bot.weekend_config["party_size"]
    preferred_reservation_time = bot.weekend_config["preferred_reservation_time"]
    acceptable_delta_in_minutes = bot.weekend_config["acceptable_delta_in_minutes"]
    book_only_refundable_reservations = bot.weekend_config.get(
        "only_refundable_reservations", True
    )
    book_prepaid_reservations = bot.weekend_config.get(
        "book_prepaid_reservations", False
    )
    book_last_minute_reservations = bot.weekend_config.get(
        "book_last_minute_reservations", False
    )
    ignore_recent_bookings = bot.weekend_config.get("ignore_recent_bookings", False)
    desired_datetime = datetime.strptime(preferred_reservation_time, "%H:%M")
    tzinfo = ZoneInfo(bot.weekend_config["timezone"])
    today = datetime.now(tzinfo)
    today = today.replace(
        hour=desired_datetime.hour,
        minute=desired_datetime.minute,
        second=0,
        microsecond=0,
    )
    override_venues = bot.weekend_config["venues"]

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
            override_venues=override_venues,
            ignore_recent_bookings=ignore_recent_bookings,
            book_only_refundable_reservations=book_only_refundable_reservations,
            book_prepaid_reservations=book_prepaid_reservations,
            book_last_minute_reservations=book_last_minute_reservations,
        )
    return True


def process_specific_date(bot: ResyBot, date_: str):
    date_config = bot.get_date_config(date_=date_)
    if date_config["ignore"]:
        logging.debug(f"ignore flag set to True for specific date {date_}. Skipping.")
        return False
    party_size = date_config["party_size"]
    preferred_reservation_time = date_config["preferred_reservation_time"]
    acceptable_delta_in_minutes = date_config["acceptable_delta_in_minutes"]
    desired_datetime = datetime.strptime(preferred_reservation_time, "%H:%M")
    book_only_refundable_reservations = date_config.get(
        "only_refundable_reservations", True
    )
    book_prepaid_reservations = date_config.get("book_prepaid_reservations", False)
    book_last_minute_reservations = date_config.get(
        "book_last_minute_reservations", False
    )
    ignore_recent_bookings = date_config.get("ignore_recent_bookings", False)
    tzinfo = ZoneInfo(bot.weekend_config["timezone"])
    day = datetime.combine(date_, datetime.min.time())
    day = day.replace(
        hour=desired_datetime.hour,
        minute=desired_datetime.minute,
        second=0,
        microsecond=0,
        tzinfo=tzinfo,
    )
    override_venues = date_config["venues"]
    logging.info(f"Processing specific date {day.strftime('%Y-%m-%d')}")
    grab_table_for_day(
        day=day,
        tzinfo=tzinfo,
        bot=bot,
        party_size=party_size,
        acceptable_delta_in_minutes=acceptable_delta_in_minutes,
        override_venues=override_venues,
        ignore_recent_bookings=ignore_recent_bookings,
        book_only_refundable_reservations=book_only_refundable_reservations,
        book_prepaid_reservations=book_prepaid_reservations,
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

    bot = ResyBot(
        config_file=config_file,
    )
    is_logged_in = bot.login()
    if not is_logged_in:
        logging.error("Unable to login")
        return 1

    logging.info("Logged in succesfully")

    week_to_process = -1
    sleep_time_in_secs = bot.config_dict["default_config"].get(
        "sleep_time_in_seconds", 5
    )

    while True:
        # Process any specific dates that we want to check for reservations
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

        # Will repeatedly try and make reservations for each of the upcoming N weekends
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
