# boilerplate for basic functinality? in MY python??
from collections import defaultdict
from collections.abc import MutableMapping
import logging
import random
import time
import os
from typing import Any, Iterable, Mapping, TypeVar, TypedDict
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

def dict_filter_falsy[D: dict](d: D) -> D:
    return type(d)({k: v for k, v in d.items() if v})

def recursive_defaultdict():
    return defaultdict(recursive_defaultdict)

class truthy_only_dict[K, V](dict[K, V]):
    def __init__(self, m: Mapping[K, V] | None = None, *args, **kwargs):
        if m:
            filtered = {k: v for k, v in m if v}
            return super().__init__(filtered, *args, **kwargs)
        super().__init__(*args, **kwargs)
        # Filter out falsy values
        self._filter_falsy_values()

    def __setitem__(self, key: K, value: V):
        if value:
            super().__setitem__(key, value)

    def _filter_falsy_values(self):
        # Remove falsy values from the dictionary
        keys_to_remove = [k for k, v in self.items() if not v]
        for k in keys_to_remove:
            del self[k]


def dicts_diff(source: Mapping[Any, Any], dest: Mapping[Any, Any], verbose = False):
    """Returns a dict of elements in dest that are missing or differ from their counterparts in source.\n\nTreats all falsy values as equal"""
    diff = {}

    if verbose and (missing_keys := source.keys() - dest.keys()):
        print(f"keys in source that are missing from dest: {missing_keys}")

    for key, dest_val in dest.items():
        source_val = source.get(key)

        if not source_val and not dest_val:
            continue
        
        if isinstance(dest_val, dict):
            if nested_diff := dicts_diff(source_val or {}, dest_val):
                # print(f"found diff in subdicts at {key}:\n{source_val}\nwith\n{dest_val}")
                diff[key] = nested_diff
        elif source_val != dest_val:
            # print(f"found mismatched vals for {key}:\n{source_val}\n---\n{dest_val}")
            diff[key] = dest_val

    # if diff:
        # print(f"returning {diff}")
    return diff

if __name__ == "__main__":
    import json
    a = json.loads("""{
  "lexicon": 1,
  "id": "app.bsky.feed.like",
  "defs": {
    "main": {
      "type": "record",
      "description": "Record declaring a 'like' of a piece of subject content.",
      "key": "tid",
      "record": {
        "type": "object",
        "required": ["subject", "createdAt"],
        "properties": {
          "subject": { "type": "ref", "ref": "com.atproto.repo.strongRef" },
          "createdAt": { "type": "string", "format": "datetime" },
          "via": { "type": "ref", "ref": "com.atproto.repo.strongRef" }
        }
      }
    }
  }
}""")

    b = json.loads("""{"id":"app.bsky.feed.like","defs":{"main":{"key":"tid","type":"record","record":{"type":"object","required":["subject","createdAt"],"properties":{"subject":{"ref":"com.atproto.repo.strongRef","type":"ref"},"createdAt":{"type":"string","format":"datetime"}}},"description":"Record declaring a 'like' of a piece of subject content."}},"$type":"com.atproto.lexicon.schema","lexicon":1}""")

    # print("final", dicts_diff({"a": {"b": "c"}}, {"a": {"b": "c"}}))
    print("final", dicts_diff(b, a))
