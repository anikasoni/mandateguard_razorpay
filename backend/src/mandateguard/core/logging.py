"""Logging configuration for the API process."""

import logging


def configure_logging(level: str) -> None:
    """Configure a concise process-wide log format."""

    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        force=True,
    )
