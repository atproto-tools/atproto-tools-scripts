import asyncio
from enum import StrEnum
from time import time
from typing import Any, Iterable, Sequence
from f.main.ATPTGrister import ATPTGrister, check_stale, t, kf, gf, mf
from itertools import batched
import httpx

from f.main.boilerplate import dicts_diff

c = httpx.AsyncClient()

class af(StrEnum):
    CAKEDAY = "createdAt"
    DISPLAYNAME = "displayName"
    DESCRIPTION = "description"
    FOLLOWERS = "followersCount"
    FOLLOWING = "followsCount"
    POSTS = "postsCount"


# BSKY_API_CONCURRENT_CONNECTIONS = int(os.environ.get("BSKY_API_CONCURRENT_CONNECTIONS", 5))
# sem = asyncio.Semaphore(BSKY_API_CONCURRENT_CONNECTIONS)

batch_size = 25 # getProfiles api limit
async def _fetch_authors(authors: Sequence[str]) -> dict[kf, dict[str, Any]]:
    assert len(authors) <= batch_size
    raw_resp = await c.get(
        "https://public.api.bsky.app/xrpc/app.bsky.actor.getProfiles?actors="
        + "&actors=".join(authors)
    )
    raw_resp.raise_for_status()
    fetched_profiles = {}
    for profile in raw_resp.json()["profiles"]:
        out: dict[str, Any] = {
            kf.HANDLE: profile[kf.HANDLE],
            mf.POLLED: int(time()),
        }
        
        if not (labels := profile.get("labels")) or not any(
            label["val"] == "!no-unauthenticated"
            and label["src"] == profile[kf.DID]
            for label in labels
        ):
            out |= {field: profile[field] for field in list(af) if field in profile}
        else:
            out |= {field: "-1" for field in [af.FOLLOWING, af.FOLLOWERS, af.POSTS] if field in profile}
        fetched_profiles[profile[kf.DID]] = out

    return fetched_profiles

async def fetch_authors(authors: Iterable[str]) -> dict[kf, dict[str, Any]]:
    '''
    returns profile metadata of authors from bluesky

    Args:
        authors_fields (list[dict[str, str  |  int]]): A list of dicts each containing one of kf.HANDLE or kf.DID and optionally mf.POLLED
    '''    
    if not authors:
        return {}
    out = {}
    profiles = asyncio.as_completed(_fetch_authors(i) for i in batched(set(authors), batch_size))
    for p in profiles:
        out |= await p
    
    return out

async def _main():
    g = ATPTGrister(fetch_authors=False)
    stale_authors = {
        fields[kf.DID]: fields for fields in
        g.list_records(t.AUTHORS)[1]
        if check_stale(fields.get(mf.POLLED), 0)
    }
    if not stale_authors:
        return None
    new_authors_diffs = {
        did: dicts_diff(stale_authors[did], fields)
        for did, fields in (await fetch_authors(stale_authors.keys())).items()
    }
    recs = [
        {
            gf.KEY: {kf.DID: did},
            gf.FIELDS: diff
        }
        for did, diff in new_authors_diffs.items()
    ]
    g.add_update_records(t.AUTHORS, recs)
    return new_authors_diffs

def main():
    return asyncio.run(_main())

if __name__ == "__main__":
    import pprint
    pprint.pp(main())
