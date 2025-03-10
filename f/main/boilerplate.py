# boilerplate for basic functinality? in MY python??
from typing import Iterable

def add_one_missing(dest: list[str], item: str | None):
    # dest = dest.copy()
    if not item:
        return dest
    if item not in dest:
        dest.append(item)
    return dest

def add_missing(dest: list[str], source: Iterable[str] | None):
    # dest = dest.copy()
    if not source:
        return dest
    dest.extend(i for i in source if i not in dest)
    return dest

def batched(long_list: list, n=1):
    for ndx in range(0, len(long_list), n):
        yield long_list[ndx:ndx+n]

