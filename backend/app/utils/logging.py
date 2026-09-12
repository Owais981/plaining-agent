import logging
import sys

_SENSITIVE_KEYS = {"anthropic_api_key", "google_maps_api_key", "jwt_secret", "password", "hashed_password"}


def configure_logging():
    logging.basicConfig(
        level=logging.INFO,
        format='{"time":"%(asctime)s","level":"%(levelname)s","logger":"%(name)s","message":%(message)r}',
        stream=sys.stdout,
    )


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)


def scrub(data: dict) -> dict:
    return {k: ("***" if k in _SENSITIVE_KEYS else v) for k, v in data.items()}
