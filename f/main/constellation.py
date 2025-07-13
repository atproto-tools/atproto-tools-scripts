import json
import os
from typing import Annotated, AsyncIterable, TypedDict
from pydantic import BaseModel, Field, BeforeValidator
from httpx import Client, Request
from at_url_converter import at_url
from atproto_core.nsid import validate_nsid as _validate_nsid
from atproto_client.models.string_formats import Did, Nsid, RecordKey

CONSTELLATION_URL = os.environ.get("CONSTELLATION_URL", "https://constellation.microcosm.blue")
c = Client(headers={"Accept": "application/json"}, base_url=CONSTELLATION_URL)

def validate_nsid(value: str):
    _validate_nsid(value)
    return value

def parse_at_url(value):
    if isinstance(value, at_url):
        return value
    if isinstance(value, str):
        return at_url.from_str(value)
    raise ValueError("Value must be a string or at_url instance")

StringOrATURL = Annotated[at_url, BeforeValidator(parse_at_url)]
path_str = Annotated[str, Field(pattern=r"\..*")]
"""A string that starts with a dot, used for paths in constellation queries"""

class constellation_query(BaseModel):
    """
    A query for constellation links
    Attributes:
        target: The target of the links, can be a string or an at_url instance
        collection: The collection to query, must be a valid NSID
        path: The path to query, must start with a dot
    """
    target: StringOrATURL
    collection: Nsid
    path: path_str

    def __init__(self, target: str | at_url, collection: Nsid, path: str):
        self.__pydantic_validator__.validate_python(
            {"target": target, "collection": collection, "path": path},
            self_instance=self,
            context={"strict_string_formats": True},
        )

class PaginatedLinks:
    """A generator for paginated links from a constellation query"""
    def __init__(self, request: Request, item_limit=0, req_limit=0):
        self.item_limit = item_limit
        self.req_limit = req_limit
        r = c.send(request).json() # fetch eagerly to get a total count right away
        self.req_count = 1
        self.url = request.url
        self.total_count = r.pop("total")
        self.cursor = r.pop("cursor", True) # set to True to have at least one iteration
        if len(r) != 1:
            raise ValueError("Unexpected response format", r)
        self.data = r.popitem()[1]
        self.link_count = len(self.data)

    async def __aiter__(self):
        while True:
            if self.item_limit:
                self.data = self.data[:self.item_limit - self.link_count]
            for i in self.data:
                yield i
            if not self.data or not self.cursor or self.req_count == self.req_limit:
                return
            r = c.get(self.url, params={"cursor": self.cursor}).json()
            self.req_count += 1
            r.pop("total")
            self.cursor = r.pop("cursor", None)
            if len(r ) != 1:
                raise ValueError("Unexpected response format", r)
            self.data = r.popitem()[1]
            self.link_count += len(self.data)

class LinksResponse(TypedDict):
    did: Did
    collection: Nsid
    rkey: RecordKey

async def links(query: constellation_query, item_limit=0, req_limit=0) -> AsyncIterable[LinksResponse]:
    """links to a target from a specific collection and path"""
    return PaginatedLinks(c.build_request("get", "links", params=query.model_dump()), item_limit=item_limit, req_limit=req_limit)

async def distinct_dids(query: constellation_query, item_limit=0, req_limit=0) -> AsyncIterable[Did]:
    """distinct DIDs (identities) with links to a target"""
    return PaginatedLinks(c.build_request("get", "links/distinct-dids", params=query.model_dump()), item_limit=item_limit, req_limit=req_limit)

async def count(query: constellation_query) -> int:
    """total number of links pointing at a given target."""
    return c.get("links/count", params=query.model_dump()).json()["total"]

async def distinct_did_count(query: constellation_query) -> int:
    """distinct DIDs (identities) with links to a target"""
    return c.get("links/count/distinct-dids", params=query.model_dump()).json()["total"]

class path_info(TypedDict):
    """
    Attributes:
        records (int): Number of records linking to the path
        distinct_dids (int): Number of distinct DIDs linking to the path
    """
    records: int
    distinct_dids: int

async def all_links(url: str | at_url, item_limit=0, req_limit=0) -> dict[Nsid, dict[path_str, path_info]]:
    """All links to a target, including linking record counts and distinct linking DIDs"""
    r = c.get("links/all", params={"target": str(url)})
    j =r.json()
    return j["links"]
