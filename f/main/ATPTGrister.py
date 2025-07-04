from collections import defaultdict
from enum import StrEnum
from pprint import pp
from typing import Any, Iterable, cast
from atproto import IdResolver
from pygrister.api import GristApi
from wmill import get_variable as wmill_var
import json
import re
from urllib.parse import urlparse, urlunparse, parse_qsl, urlencode
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from f.main.boilerplate import add_missing, get_timed_logger
utc = ZoneInfo("UTC")
resolver = IdResolver()
log = get_timed_logger(__name__, 'debug')

class t(StrEnum):
    """atproto-tools table names"""
    SOURCES = "Data_Sources"
    LEXICONS = "Lexicons"
    SITES = "Sites"
    REPOS = "Repos"
    AUTHORS = "Authors"

class gf(StrEnum):
    KEY = "require" # field
    """require"""
    FIELDS = "fields"
    """fields"""

class kf(StrEnum):
    """key fields"""
    DID = "did"
    HANDLE = "handle"
    NORMAL_URL = "normalized_url"
    NORMAL_HOME = "normalized_homepage"
    ID = "id"

class mf(StrEnum):
    """metadata fields"""
    POLLED = "last_polled"
    STATUS = "status"

def normalize_url(url: str) -> kf:
    if url.find("://") == -1:
        url = "https://" + url
    parsed = urlparse(url)
    #longterm catch more tracking params, maybe look for a library?
    query = urlencode([
        i for i in parse_qsl(parsed.query)
        if not re.match('(?:utm_|fbclid|gclid|ref$).*', i[0])
    ])
    netloc = parsed.netloc.lower()
    netloc = netloc[4:] if netloc.startswith("www.") else netloc
    path = re.match(r"(.*?)(/about)?/?$",parsed.path)[1] #type: ignore (preference)
    scheme = "https" if parsed.scheme == "http" else parsed.scheme
    return urlunparse(parsed._replace(netloc=netloc, path=path, scheme=scheme, query=query)) #type: ignore (preference)

#TODO maybe set up converter functions instead
def make_timestamp(timestamp: str | int | float):
    """convert a ISO8601 datetime string to a grist-friendly timestamp"""
    if isinstance(timestamp, str):
        return int(datetime.fromisoformat(timestamp).timestamp())
    else:
        return int(timestamp)

def check_stale(timestamp: str | int | float| None, stale_threshold: float = 2) -> bool:
    """
    returns whether a given UTC timestamp is stale and the current UTC timestamp

    Args:
        timestamp (str | int | float): the target timestamp
        stale_threshold (int, optional): minimum threshold of staleness, in days. Defaults to 2.
    """
    if not timestamp:
        return True
    timestamp = make_timestamp(timestamp)
    delta = datetime.now(utc) - datetime.fromtimestamp(timestamp, utc)
    log.debug(f"got timestamp {timestamp} with threshold {stale_threshold}. delta is {delta}")
    return delta >= timedelta(days=stale_threshold)

strict_did_regex= r"^did:(?P<method>[a-z0-9]+):(?P<identifier>(?:(?:[a-zA-Z0-9._\-]|%[a-fA-F0-9]{2})*:)*(?:[a-zA-Z0-9._-]+|%[a-fA-F0-9]{2})+)$"
did_regex = r"(?P<did>did:(?P<method>[a-z0-9]+):(?P<identifier>(?:(?:[a-zA-Z0-9._\-]|%[a-fA-F0-9]{2})*:)*(?:[a-zA-Z0-9._-]+|%[a-fA-F0-9]{2})+))(?:[^a-zA-Z0-9._-]|$)"
#TODO support other clients besides bsky.app such as ouranos. maybe use code from pdsls redirector extension
handle_regexes = {
    r"^((?:[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?\.)?(?P<second_level>(?:[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?\.)[a-zA-Z](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?))$",
    r"bsky\.app/profile/([^/]*)",
}
def match_handle(author) -> kf | None:
    for pattern in handle_regexes:
        if author_match := re.search(pattern, author):
            return author_match[1] #type: ignore    

class CustomGrister(GristApi):
    def __init__(self, config: dict[str, str] | None = None, in_converter: dict | None = None, out_converter: dict | None = None, request_options: dict | None = None, fetch_authors = False):
        super().__init__(config, in_converter, out_converter, request_options)
        self.authors_lookup: dict[kf, dict[str, Any]] = {}
        self._new_authors_records: dict[kf, dict[str, Any]] = {}
        if not fetch_authors:
            return
        authors_by_did: dict[kf, dict[str, dict[str, Any]]] = defaultdict(dict)
        invalid_dids: dict[kf, dict[str, Any]] = {}
        old_records: list[dict[str, Any]] = self.list_records(t.AUTHORS)[1]
        for row in old_records:
            handle: kf | None = row.get(kf.HANDLE)
            did: kf | None = row.get(kf.DID)
            if did and not handle:
                if handle := self.get_handle(did):
                    row[kf.HANDLE] = handle
                    row['no_handle'] = True
                    log.info(f'fetched handle {handle} for {did}')
                else:
                    log.warning(f"record id {row['id']} has no handle for did {did}")
            elif handle and not did:
                if did := self.resolve_author(handle):
                    row[kf.DID] = did
                    row['no_did'] = True
                    log.info(f'fetched {did} for handle {handle}')
                else:
                    log.warning(f'no did for handle {handle}')
                    invalid_dids[row['id']] = {"unreachable_did": True}
                    continue
            elif not did: # and no handle, logically. but the type checker didn't get the logic
                log.error(f"record id {row['id']} has no valid handle or did")
                continue

            if handle:
                self.authors_lookup[handle] = row
            self.authors_lookup[did] = row
            authors_by_did[did][row['id']] = row
        
        to_delete = set()
        merged_authors = []
        for did, record_list in authors_by_did.items():
            if len(record_list) == 1:
                if (primary_rec := record_list.popitem()[1]).get('no_did', None):
                    merged_authors.append({kf.HANDLE: primary_rec[kf.HANDLE], kf.DID: did, 'no_did': True})
                elif primary_rec.pop('no_handle', None):
                    merged_authors.append({kf.HANDLE: primary_rec[kf.HANDLE], kf.DID: did})
                continue

            primary_id, primary_rec = next( # get the record with existing did, otherwise get the latest one
                ((id, rec) for id, rec in record_list.items() if rec.get(kf.DID)),
                next(((rec['id'], rec) for rec in sorted(
                    list(record_list.values()),
                    key=lambda x: x.get('record_updatedAt', 0)
                )))
            )
            record_list.pop(primary_id)
            out: dict[str, Any] = {kf.HANDLE: primary_rec[kf.HANDLE], kf.DID: did, "contacted": primary_rec['contacted']} 
            for id, rec in record_list.items():
                for k,v in rec.items():
                    if isinstance(v, list) and v[0] == 'L':
                        if not primary_rec.get(k):
                            out[k] = ['L']
                        out[k] = add_missing(primary_rec[k], v)
                out['handle'] = out['handle'] or rec['handle']
                out['contacted'] = out['contacted'] or rec['contacted']
                to_delete.add(id)
            merged_authors.append(out)
        if to_delete:
            self.delete_rows(t.AUTHORS, list(to_delete))
        if merged_authors or invalid_dids:
            merged_authors = [
                {
                    gf.KEY: {kf.HANDLE: rec[kf.HANDLE]}
                    if rec.pop("no_did", None)
                    else {kf.DID: rec[kf.DID]},
                    gf.FIELDS: rec,
                }
                for rec in merged_authors
            ]
            merged_authors += self.make_records(invalid_dids, kf.ID)
            pp(merged_authors)
            # for i in merged_authors:
            #     log.debug(f'POSTing {i[gf.KEY]}')
            #     pp(i[gf.FIELDS])
            #     self.add_update_records(t.AUTHORS, [i])
            self.add_update_records(t.AUTHORS, merged_authors)

    def make_records(self, entries: dict[kf, dict[str, Any]], rec_key: str):
        return [
            {
                gf.KEY: {rec_key: entry.get(rec_key) or key},
                gf.FIELDS: entry,
            }
            for key, entry in entries.items()
        ]

    """raises IOError with the request response on http error"""
    def apicall(self, url: str, method: str = 'GET', headers: dict | None = None, params: dict | None = None, json: dict | None = None, filename: str = '') -> tuple[int, Any]:
        resp =  super().apicall(url, method, headers, params, json, filename)
        if self.resp_code != 200:
            raise IOError(
                self.resp_code, f"{self.resp_reason}: {self.resp_content}"
            )
        return resp

    # don't like doing this but the put columns enpdoint has really weird behaviour, sometimes it invents a new id for you and makes a new column with it
    # also changed the noadd and noupdate default params, kinda weird to have both of those true by default.
    def add_update_cols(self, table_id: str, cols: list[dict], noadd: bool = False, noupdate: bool = False, replaceall: bool = False, doc_id: str = '', team_id: str = ''):
        if replaceall:
            return super().add_update_cols(
                table_id, cols, noadd, noupdate, replaceall, doc_id, team_id
            )

        target_col_ids = {col["id"] for col in cols}
        col_ids: set[str] = {x["id"] for x in self.list_cols(table_id)[1]}
        if (new_col_ids := target_col_ids - col_ids) and not noadd:
            col_ids |= set(self.add_cols(table_id, [col for col in cols if col["id"] in new_col_ids])[1])
        elif (update_col_ids := col_ids & target_col_ids) and not noupdate:
            super().add_update_cols(table_id, [col for col in cols if col["id"] in update_col_ids], noadd=True)
        return int(self.resp_code), col_ids

    def get_colRef(self, table_id: str, col_id: str) -> int | None:
        return next((col["fields"]["colRef"] for col in self.list_cols(table_id)[1] if col["id"] == col_id), None)

    def get_colRefs(self, table_id: str, col_ids: Iterable[str], format: bool = True):
        """
        finds colRefs for a set of columns, returned formatted as a json array string

        Args:
            table_id (str): the grist table id
            col_ids (set[str]): a list of column ids
            format (bool, optional): whether to return a list instead of a key. Defaults to True.

        Returns:
            str | dict[str,int]: either the {id:colref, ...} dict, or a string with a list of colRefs
        """
        ref_key: dict[str, int] = {col["id"]: col["fields"]["colRef"] for col in self.list_cols(table_id)[1] if col["id"] in col_ids}
        if format:
            return str(list(ref_key.values()))
        return ref_key

    def get_handle(self, did: str) -> kf | None:
        if handle := self.authors_lookup.get(cast(kf, did), {}).get(kf.HANDLE):
            log.debug(f'cache hit for {handle} handle lookup')
            return handle
        if (resp := resolver.did.resolve(did)) and (handle := resp.get_handle()):
            return cast(kf, handle)

    def _fetch_did(self, handle: str) -> kf | None:
        """usually better to use self.resolve_author since it has a cache"""
        if out := resolver.handle.resolve(handle):
            return cast(kf, out)

    def resolve_author(self, author: str) -> None | kf:
        """converts handle or profile link to did. if not found, resolves it."""
        if did_match := re.search(did_regex, author):
            did: kf | None = cast(kf, did_match[0])
            assert did
            if did not in self.authors_lookup and did not in self._new_authors_records:
                self.authors_lookup[did] = {kf.DID: did}
                self._new_authors_records[did] =  {gf.KEY: {kf.DID: did}}
        elif author_handle := match_handle(author):
            if did := self.authors_lookup.get(author_handle, {}).get(kf.DID):
                pass
            elif resp := self._fetch_did(author_handle):
                did = cast(kf, resp)
                if did not in self.authors_lookup:
                    self.authors_lookup[author_handle] = self.authors_lookup[did] = {kf.DID: did, kf.HANDLE: author_handle}
                else:
                    self.authors_lookup[author_handle] = self.authors_lookup[did]
                    self.authors_lookup[author_handle][kf.HANDLE] = author_handle

                self._new_authors_records[did] = {gf.KEY: {kf.DID: did}, gf.FIELDS: {kf.HANDLE: author_handle}}
        else:
            log.error(f"{author} is not a valid did or bsky.app profile")
            return
        return did

    def write_authors(self):
        if not self._new_authors_records:
            return
        self.add_update_records(t.AUTHORS, list(self._new_authors_records.values()))
        for entry in self.list_records(t.AUTHORS)[1]:
            self.authors_lookup.setdefault(entry[kf.DID], {}).update(
                id = entry["id"],
                did = entry[kf.DID],
                handle = entry[kf.HANDLE]
            )
        self._new_authors_records.clear()

names_col = "names"
site_source_name = "site"
"""used in the names_col record as a dummy source name where we store the ogl data"""

out_converters = {
    t.SITES: {
        names_col: lambda x: json.loads(x) if x else {site_source_name: {}},
    }
}

in_converters = {
    t.SITES: {
        names_col: json.dumps,
    }
}

def ATPTGrister(fetch_authors = False) -> CustomGrister:
    """Get configured GristApi client"""
    grist_config = json.loads(wmill_var("f/main/grist_config"))
    grist_config["GRIST_API_KEY"] = wmill_var("u/autumn/GRIST_API_KEY")
    return CustomGrister(grist_config, fetch_authors=fetch_authors, in_converter=in_converters, out_converter=out_converters)

if __name__ == "__main__":
    g = ATPTGrister(True)
