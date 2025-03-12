# boilerplate for basic functinality? in MY python??
import logging
import random
import time
import os
from typing import Iterable

class TimedLoggerAdapter(logging.LoggerAdapter):
    """Adapter that adds timing information to log records."""
    
    # Static dictionary to store timing information per logger name
    
    def __init__(self, logger: logging.Logger, extra=None):
        super().__init__(logger, extra)
        current_time = time.time()
        self.timings = {
            'start': current_time,
            'last': current_time
        }
    
    def process(self, msg, kwargs):
        current_time = time.time()
        timings = self.timings
        
        # Calculate elapsed times
        elapsed = current_time - timings['last']
        total_elapsed = current_time - timings['start']
        
        # Update last time
        timings['last'] = current_time
        
        # Add timing info to the extra dict
        extra = kwargs.get('extra', {})
        extra.update({
            'delta_time': elapsed,
            'total_time': total_elapsed
        })
        kwargs['extra'] = extra
        
        return msg, kwargs

class TimedFormatter(logging.Formatter):
    """Formatter that includes timing information from the record."""
    def format(self, record):
        # Check if timing info exists in the record
        if not hasattr(record, 'delta_time'):
            record.delta_time = "+0.000s"
        if not hasattr(record, 'total_time'):
            record.total_time = "0.000s"
        return super().format(record)

def get_timed_logger(name: str = "", level: str | int = "INFO") -> TimedLoggerAdapter:
    """Get a logger with timing capabilities."""
    if name.endswith('.py'):
        name = os.path.split(name)[1].removesuffix('.py')
        
    name = name or f"unknown_timer_{random.choice(range(10000))}"
    logger = logging.getLogger(name)
    level = os.environ.get("ATPROTO_LOG_LEVEL") or level
    if isinstance(level, str):
        level = getattr(logging, level.upper())
    logger.setLevel(level)

    handler = logging.StreamHandler()
    handler.setLevel(logger.level)
    handler.setFormatter(TimedFormatter('{total_time:.3f} | {delta_time:.3f} {filename}/{levelname}: {message}', style='{'))
    logger.addHandler(handler)
    return TimedLoggerAdapter(logger)

def add_one_missing(dest: list[str], item: str | None):
    if not item:
        return dest
    if item not in dest:
        dest.append(item)
    return dest

def add_missing(dest: list[str], source: Iterable[str] | None):
    if not source:
        return dest
    dest.extend(i for i in source if i not in dest)
    return dest

def batched(long_list: list, n=1):
    for ndx in range(0, len(long_list), n):
        yield long_list[ndx:ndx+n]

if __name__ == "__main__":
    a = get_timed_logger()
    b = get_timed_logger()
    a.info("test")
    time.sleep(1)
    a.info("after 1s")
    a.info("instant")
    b.info("after 1 s")
