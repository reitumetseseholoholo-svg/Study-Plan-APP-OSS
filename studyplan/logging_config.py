import logging
import sys

# configure a basic structured logger
_logger = logging.getLogger("studyplan")
_logger.setLevel(logging.DEBUG)
_handler = logging.StreamHandler(sys.stdout)
_formatter = logging.Formatter(
    fmt="%(asctime)s %(levelname)s %(name)s %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
)
_handler.setFormatter(_formatter)
_logger.addHandler(_handler)


def get_logger(name: str | None = None) -> logging.Logger:
    if name:
        return logging.getLogger(f"studyplan.{name}")
    return _logger
