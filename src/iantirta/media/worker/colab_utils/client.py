from urllib.parse import urljoin, urlparse
import os
import logging
from dataclasses import dataclass
import json

XSSI_PREFIX = ")]}'\n"
TUN_ENDPOINT = "/tun/m"

COLAB_XSRF_TOKEN_HEADER = {"key": "X-Goog-Colab-Token", "value": ""}


@dataclass(slots=True, frozen=True)
class ConsumptionUserInfo:
    currentBalance: float
    consumptionRateHourly: float
    assignmentsCount: float
    eligibleGpus: list[str]
    ineligibleGpus: list[str]
    eligibleTpus: list[str]
    ineligibleTpus: list[str]

@dataclass(slots=True, frozen=True)
class ListedAssignments:
    assignments: List[ListedAssignment]


class ColabRequestError(Exception):
    def __init__(self, message, request, response, response_body=None):
        super().__init__(message)
        self.request = request
        self.response = response
        self.response_body = response_body


class Client:
    colab_domain: str = "https://colab.research.google.com"
    colab_api_domain: str = "https://colab.pa.googleapis.com"

    def __init__(self, session, logger=None):
        self.session = session
        self.logger = logger or logging.getLogger(__name__)

    def _strip_xssi_prefix(self, v: str) -> str:
        if not v.startswith(XSSI_PREFIX):
            return v
        return v[len(XSSI_PREFIX) :]

    def _issue_request(
        self,
        endpoint: str,
        method: str = "GET",
        headers: Dict[str, str] = None,
        params: Dict[str, str] = None,
        **kwargs,
    ):
        parsed_endpoint = urlparse(endpoint)
        if parsed_endpoint.hostname in urlparse(self.colab_domain).hostname:
            if params is None:
                params = {}
            params["authuser"] = "0"

        request_headers = headers.copy() if headers else {}
        request_headers.update({
            'Accept': 'application/json',
            'X-Colab-Client-Agent': 'colab-cli',
            
        })

        # Slow allocations may outlive AuthorizedSession's default read timeout.
        if "timeout" not in kwargs:
            timeout = os.getenv("COLAB_CLI_REQUEST_TIMEOUT")
            if timeout:
                kwargs["timeout"] = float(timeout)

        self.logger.debug(f"Request: {method} {endpoint}")
        self.logger.debug(f"Params: {params}")

        response = self.session.request(
            method, endpoint, headers=request_headers, params=params, **kwargs
        )

        self.logger.debug(f"Request Headers: {response.request.headers}")
        self.logger.debug(f"Response: {response.status_code} {response.reason}")
        self.logger.debug(f"Response Headers: {response.headers}")
        self.logger.debug(f"Response Body: {response.text}")
        if not response.ok:
            raise ColabRequestError(
                f"Failed to issue request {method} {endpoint}: {response.reason}",
                request=response.request,
                response=response,
                response_body=response.text,
            )

        body = self._strip_xssi_prefix(response.text)
        if not body:
            return {}
        
        return json.loads(body)

    def get_consumption_user_info(self) -> ConsumptionUserInfo:
        """Fetch account-level CCU balance and usage rate from the session backend."""
        url = urljoin(self.colab_domain, f"{TUN_ENDPOINT}/ccu-info")
        ccu = self._issue_request(url)
        return ConsumptionUserInfo(**ccu)

    def list_assignments(self) -> List[ListedAssignment]:
        url = urljoin(self.colab_domain, f"{TUN_ENDPOINT}/assignments")
        assignments = self._issue_request(url)
        return ListedAssignments(**assignments).assignments

if __name__ == '__main__':
    from iantirta.telemetry import netsvc
    netsvc.setup_logger(__name__, default_level=logging.DEBUG)
    from iantirta.media.worker.colab_utils.auth import get_authorized_sessions
    session = get_authorized_sessions()
    client = Client(session)
    from pprint import pprint
    pprint(client.list_assignments())