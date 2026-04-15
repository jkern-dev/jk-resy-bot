from requests import Session
from requests.adapters import HTTPAdapter, DEFAULT_POOLSIZE
from urllib3.util import Retry

DEFAULT_NUM_RETRIES = 5
DEFAULT_BACKOFF_FACTOR = 0.5
DEFAULT_TIMEOUT_SECS = 30


class OpenTableApiRequestWrapper(object):
    """
    Helper that builds REST requests to OpenTable's Mobile API with retry logic.
    """

    def __init__(
        self,
        default_num_retries: int = DEFAULT_NUM_RETRIES,
        default_backoff_factor: float = DEFAULT_BACKOFF_FACTOR,
        default_timeout_secs: int = DEFAULT_TIMEOUT_SECS,
    ) -> None:
        self.default_timeout_secs = default_timeout_secs
        session = Session()
        retry = Retry(
            total=default_num_retries,
            backoff_factor=default_backoff_factor,
            redirect=0,
            status_forcelist=tuple(Retry.RETRY_AFTER_STATUS_CODES)
            + (502,)
            + (504,)
            + (104,),
            allowed_methods=frozenset(["GET", "POST", "PUT", "DELETE"]),
        )
        adapter = HTTPAdapter(
            pool_connections=DEFAULT_POOLSIZE,
            pool_maxsize=DEFAULT_POOLSIZE,
            max_retries=retry,
        )
        session.mount("http://", adapter)
        session.mount("https://", adapter)

        self.session = session

    def get(self, url, **kwargs):
        kwargs.setdefault("timeout", self.default_timeout_secs)
        return self.session.get(url, **kwargs)

    def post(self, url, **kwargs):
        kwargs.setdefault("timeout", self.default_timeout_secs)
        return self.session.post(url, **kwargs)

    def put(self, url, **kwargs):
        kwargs.setdefault("timeout", self.default_timeout_secs)
        return self.session.put(url, **kwargs)

    def delete(self, url, **kwargs):
        kwargs.setdefault("timeout", self.default_timeout_secs)
        return self.session.delete(url, **kwargs)
