# Part of Iantirta.com
# See LICENSE file for full copyright and licensing details.

from enum import Enum

__all__ = [
    "ErrorType"
]


class ErrorType(Enum):
    """YT DLP Error wrapper"""

    RATE_LIMIT = (
        "http error 429",
        "too many requests",
        "rate limit",
    )

    UNKNOWN = ()
    
    @classmethod
    def _missing_(cls, exc: Exception):
        msg = str(exc).lower()
        for member in cls:
            if member == cls.UNKNOWN: continue
            if any(needle in msg for needle in member.value):
                return member
        return cls.UNKNOWN
