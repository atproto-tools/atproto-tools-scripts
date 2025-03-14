# boilerplate for basic functinality? in MY python??
import logging
import random
import time
import os
from typing import Iterable
# TODO consider switching to a different parsing lib https://sethmlarson.dev/why-urls-are-hard-path-params-urlparse
from urllib.parse import urlparse, parse_qsl, unquote, urlunparse

env_log_level = os.environ.get("ATPT_LOG_LEVEL")

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
    level = env_log_level or level
    if isinstance(level, str):
        level = getattr(logging, level.upper())
    logger.setLevel(level)

    handler = logging.StreamHandler()
    handler.setLevel(logger.level)
    handler.setFormatter(TimedFormatter('{total_time:07.3f} | {delta_time:06.3f} {filename}/{levelname}: {message}', style='{'))
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

class url_obj:
    @staticmethod
    def split_path(path_str: str) -> list[str]:
        return [unquote(i) for i in path_str.split("/") if i]

    @staticmethod
    def parse_query(query_str: str) -> list[tuple[str, str]]:
        return [(unquote(k), unquote(v)) for k, v in parse_qsl(query_str)]

    def find_query_param(self, param: str, query_string: str = '') -> str | None:
        '''
        attempts to find the value of first matching param in url query

        Args:
            param (str): target key
            query_string (str, optional): provide your own query string. defaults to self.query

        Returns:
            str | None: the first matching target value, if any
        '''        
        source = url_obj.parse_query(query_string) if query_string else self.query
        return next((p[1] for p in source if p[0] == param), None)
    
    def unparse(self, scheme: str = '', netloc: str = '', path: str = '', params: str = '', query: str = '', fragment: str = '', ):
        ps = "/".join(self.path) if self.path else ""
        qs = ("&".join(["=".join((i[0], i[1])) for i in self.query])) if self.query else ""
        return urlunparse((scheme or self.scheme, netloc or self.netloc, path or ps, params or self.params, query or qs, fragment or self.fragment))

    def __init__(self, url: str):
        parsed = urlparse(url)
        self.og_parsed = parsed
        self.og = url
        
        self.scheme = parsed.scheme
        self.netloc = parsed.netloc
        self.path = url_obj.split_path(parsed.path)
        self.params = parsed.params # the red headed step child of urlparse :(
        self.query = url_obj.parse_query(parsed.query)
        self.fragment = unquote(parsed.fragment)

        self.dict = {
            k: self.__getattribute__(k)
            for k in ["scheme", "netloc", "path", "query", "fragment"]
        }

if __name__ == "__main__":
    # a = get_timed_logger(__file__)
    # b = get_timed_logger()
    # a.info("test")
    # time.sleep(1)
    # a.info("after 1s")
    # a.info("instant")
    # b.info("after 1 s")
    u = url_obj('http://google.com/path?q=query')
    print(u.dict)
    print(u.unparse())
