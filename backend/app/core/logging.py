import logging

from .config import get_settings


def configure_logging() -> None:
    logging.basicConfig(
        level=getattr(logging, get_settings().log_level, logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
