import yaml
from datetime import datetime, timedelta
import logging
from typing import Dict, Optional
from pathlib import Path
import dropbox

DROPBOX_API_BASE = "https://api.dropboxapi.com"


class DropboxClient:
    """
    Wrapper around Dropbox's API that handles OAuth2 concerns around refreshing tokens.
    """

    def __init__(self, secrets_file: Path):
        self._secrets_file = secrets_file
        self._secrets: Dict[str, str] = {}
        self._secrets_last_refresh_time: Optional[datetime] = None
        self._dbx = dropbox.Dropbox(
            oauth2_access_token=self.secrets["access_token"],
            oauth2_refresh_token=self.secrets["refresh_token"],
            app_key=self.secrets["app_key"],
            app_secret=self.secrets["app_secret"],
        )

    @property
    def secrets(self) -> Dict[str, str]:
        if (
            self._secrets_last_refresh_time is not None
            and self._secrets_last_refresh_time + timedelta(minutes=1) < datetime.now()
        ):
            logging.info("Using cached secrets file")
            return self._secrets

        with self._secrets_file.open() as f:
            self._secrets = yaml.safe_load(f)
        return self._secrets

    def download_file(self, prefix: str, local_path: Path) -> bool:
        """
        Downloads file from given prefix in Dropbox to local_path. Will overwrite if existing locally.
        """
        self._dbx.check_and_refresh_access_token()
        self._dbx.files_download_to_file(download_path=str(local_path), path=prefix)
        try:
            self._dbx.files_download_to_file(download_path=str(local_path), path=prefix)
            return True
        except dropbox.exceptions.HttpError as err:
            logging.error(f"Error downloading file from dropbox: {str(err)}")
            return False
