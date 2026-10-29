from __future__ import annotations

import json
import logging
import os
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import Enum
from urllib.parse import urljoin, urlparse

import requests

from iantirta.media.worker.colab_utils.utils import get_status_code

XSSI_PREFIX = ")]}'\n"
TUN_ENDPOINT = "/tun/m"



@dataclass(slots=True, frozen=True)
class FreeCcuQuotaInfo:
    nextRefillTimestampSec: datetime
    remainingTokens: int


@dataclass(slots=True, frozen=True)
class ConsumptionUserInfo:
    currentBalance: float
    consumptionRateHourly: float
    assignmentsCount: float
    eligibleGpus: list[str]
    ineligibleGpus: list[str]
    eligibleTpus: list[str]
    ineligibleTpus: list[str]
    freeCcuQuotaInfo: FreeCcuQuotaInfo | None = None

    @classmethod
    def from_dict(cls, **data):
        # Create a copy to avoid mutating the original dictionary
        parsed_data = data.copy()
        
        if parsed_data.get('freeCcuQuotaInfo'):
            fq_data = parsed_data['freeCcuQuotaInfo']
            parsed_data['freeCcuQuotaInfo'] = FreeCcuQuotaInfo(
                nextRefillTimestampSec=datetime.fromtimestamp(fq_data['nextRefillTimestampSec']),
                remainingTokens=int(fq_data['remainingTokens'])
            )
            
        return cls(**parsed_data)


class Accelerator(str, Enum):
    NONE = "NONE"
    G4 = "G4"
    T4 = "T4"
    L4 = "L4"
    A100 = "A100"
    H100 = "H100"
    V5E1 = "V5E1"
    V6E1 = "V6E1"


class Variant(str, Enum):
    DEFAULT = "DEFAULT"
    GPU = "GPU"
    TPU = "TPU"


class AssignmentVariant(int, Enum):
    DEFAULT = 0
    GPU = 1
    TPU = 2


class Shape(int, Enum):
    STANDARD = 0
    HIGH_RAM = 1


@dataclass(slots=True, frozen=True)
class RuntimeProxyInfo:
    token: str
    tokenExpiresInSeconds: int
    url: str

    def expires_at(self) -> datetime:
        """Absolute expiry; call right after receiving the response."""
        return datetime.now(timezone.utc) + timedelta(
            seconds=self.tokenExpiresInSeconds
        )


@dataclass(slots=True, frozen=True)
class ListedAssignment:
    accelerator: Accelerator
    endpoint: str
    variant: AssignmentVariant
    machine_shape: Shape
    runtime_proxy_info: RuntimeProxyInfo

    @classmethod
    def from_dict(cls, data: dict):
        proxy_data = data.get('runtimeProxyInfo', {})
        proxy_info = RuntimeProxyInfo(**proxy_data) if proxy_data else None

        return cls(
            accelerator=Accelerator(data['accelerator']),
            endpoint=data['endpoint'],
            variant=AssignmentVariant(data['variant']),
            machine_shape=Shape(data['machineShape']),
            runtime_proxy_info=proxy_info
        )


@dataclass(slots=True, frozen=True)
class ListedAssignments:
    assignments: list[ListedAssignment]

    @classmethod
    def from_dict(cls, **data):
        raw_assignments = data.get('assignments', [])
        parsed_assignments = [ListedAssignment.from_dict(a) for a in raw_assignments]
        
        return cls(assignments=parsed_assignments)


@dataclass(slots=True, frozen=True)
class PostAssignmentResponse:
    accelerator: Accelerator
    endpoint: str
    runtime_proxy_info: RuntimeProxyInfo
    variant: AssignmentVariant
    machine_shape: Shape
    extras: dict

    @classmethod
    def from_dict(cls, **data):
        proxy_data = data.pop('runtimeProxyInfo', {})
        proxy_info = RuntimeProxyInfo(**proxy_data) if proxy_data else None

        return cls(
            accelerator=Accelerator(data.pop('accelerator')),
            endpoint=data.pop('endpoint'),
            variant=AssignmentVariant(data.pop('variant')),
            machine_shape=Shape(data.pop('machineShape')),
            runtime_proxy_info=proxy_info,
            extras=data
        )


@dataclass(slots=True, frozen=True)
class GetAssignmentResponse:
    acc: str
    nbh: str
    token: str
    variant: Variant
    p: bool

    @classmethod
    def from_dict(cls, **data):
        variant = data.pop("variant")
        return cls(
            **data,
            variant=Variant(variant)
        )


@dataclass(slots=True, frozen=True)
class GetUnassignRequest:
    token: str


@dataclass(slots=True, frozen=True)
class Assignment:
    endpoint: str
    runtime_proxy_info: RuntimeProxyInfo


# Accelerators that only exist in a single (high-memory) shape; the assign
# endpoint ignores shape=hm for these (colab-vscode forces STANDARD).
HIGH_MEM_ONLY_ACCELERATORS = frozenset(
    {Accelerator.L4, Accelerator.V5E1, Accelerator.V6E1}
)


def uuid_to_web_safe_base64(uuid_val: uuid.UUID) -> str:
    uuid_str = str(uuid_val)
    transformed = uuid_str.replace("-", "_")
    padding = "." * (44 - len(uuid_str))
    return transformed + padding


class ColabRequestError(Exception):
    def __init__(self, message, request, response, response_body=None):
        super().__init__(message)
        self.request = request
        self.response = response
        self.response_body = response_body


class TooManyAssignmentsError(Exception):
    pass


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
        headers: dict[str, str] | None = None,
        params: dict[str, str] | None = None,
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
        return ConsumptionUserInfo.from_dict(**ccu)

    def list_assignments(self) -> list[ListedAssignment]:
        url = urljoin(self.colab_domain, f"{TUN_ENDPOINT}/assignments")
        assignments = self._issue_request(url)
        return ListedAssignments.from_dict(**assignments).assignments

    # assign
    def unassign(self, endpoint: str):
        url = urljoin(self.colab_domain, f"{TUN_ENDPOINT}/unassign/{endpoint}")
        resp = self._issue_request(url)
        resp = GetUnassignRequest(**resp)
        return self._issue_request(
            url, method="POST", headers={'X-Goog-Colab-Token': resp.token}
        )

    def assign(
        self,
        notebook_hash: uuid.UUID,
        variant: Variant | None = None,
        accelerator: Accelerator | None = None,
        shape: Shape | None = None,
    ) -> PostAssignmentResponse | Assignment:
        assignment = self._get_assignment(notebook_hash, variant, accelerator, shape)
        if isinstance(assignment, Assignment):
            return assignment

        retries = max(0, int(os.getenv("COLAB_CLI_ASSIGN_RETRIES", "3")))
        backoff = max(0.0, float(os.getenv("COLAB_CLI_RETRY_BACKOFF", "10")))
        for attempt in range(retries + 1):
            try:
                res = self._post_assignment(
                    notebook_hash, assignment.token, variant, accelerator, shape
                )
                break
            except (ColabRequestError, requests.exceptions.ReadTimeout) as e:
                status = (
                    get_status_code(e) if isinstance(e, ColabRequestError) else None
                )
                if status == 412:
                    raise TooManyAssignmentsError(str(e))
                retryable = isinstance(
                    e, requests.exceptions.ReadTimeout
                ) or status in (502, 503, 504)
                if not retryable or attempt >= retries:
                    raise
                delay = backoff * (2**attempt)
                self.logger.warning(
                    "Assignment request failed; retrying in %.0fs", delay
                )
                time.sleep(delay)
                # Reconcile an uncertain POST before submitting the same request again.
                assignment = self._get_assignment(
                    notebook_hash, variant, accelerator, shape
                )
                if isinstance(assignment, Assignment):
                    return assignment

        return res

    def _build_assign_url(
        self,
        notebook_hash: uuid.UUID,
        variant: Variant | None = None,
        accelerator: Accelerator | None = None,
        shape: Shape | None = None,
    ) -> str:
        url = urljoin(self.colab_domain, f"{TUN_ENDPOINT}/assign")
        params = {"nbh": uuid_to_web_safe_base64(notebook_hash)}
        if variant:
            params["variant"] = variant.value
        if accelerator:
            params["accelerator"] = accelerator.value
        if shape == Shape.HIGH_RAM:
            params["shape"] = "hm"

        req = requests.Request("GET", url, params=params)
        prep = req.prepare()
        return prep.url

    def _get_assignment(
        self,
        notebook_hash: uuid.UUID,
        variant: Variant | None = None,
        accelerator: Accelerator | None = None,
        shape: Shape | None = None,
    ) -> Assignment | GetAssignmentResponse:
        url = self._build_assign_url(notebook_hash, variant, accelerator, shape)
        data = self._issue_request(url)
        try:
            assignment = Assignment(**data)
        except TypeError:
            assignment = GetAssignmentResponse(**data)
        return assignment

    def _post_assignment(
        self,
        notebook_hash: uuid.UUID,
        xsrf_token: str,
        variant: Variant | None = None,
        accelerator: Accelerator | None = None,
        shape: Shape | None = None,
    ) -> PostAssignmentResponse:
        url = self._build_assign_url(notebook_hash, variant, accelerator, shape)
        data = self._issue_request(
            url, method="POST", headers={'X-Goog-Colab-Token': xsrf_token}
        )
        return PostAssignmentResponse.from_dict(**data)


if __name__ == '__main__':
    from rich import inspect as i
    from iantirta.telemetry import netsvc
    netsvc.setup_logger(__name__, default_level=logging.DEBUG)
    from iantirta.media.worker.colab_utils.auth import get_authorized_sessions
    session = get_authorized_sessions()
    client = Client(session)
    from pprint import pprint
    # pprint(client.assign(uuid.uuid4()))

    pprint(client.unassign('m-s-ass1a1-1e3c4c8mwdja1'))
