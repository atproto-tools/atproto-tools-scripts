from enum import StrEnum
from time import time
from typing import Any, Iterable
from f.main.ATPTGrister import ATPTGrister, check_stale, t, kf, gf, mf
import requests

def batched(long_list: list, n=1):
    for ndx in range(0, len(long_list), n):
        yield long_list[ndx:ndx+n]

class af(StrEnum):
    CAKEDAY = "createdAt"
    DISPLAYNAME = "displayName"
    DESCRIPTION = "description"
    FOLLOWERS = "followersCount"
    FOLLOWING = "followsCount"
    POSTS = "postsCount"

batch_size = 25

def fetch_authors(authors: Iterable[str]) -> dict[kf, dict[str, Any]]:
    '''
    returns profile metadata of authors from bluesky

    Args:
        authors_fields (list[dict[str, str  |  int]]): A list of dicts each containing one of kf.HANDLE or kf.DID and optionally mf.POLLED
    '''    
    if not authors:
        return {}
    new_profiles = {}
    for batch in batched(list(set(authors)), batch_size):
        raw_resp = requests.get(
            "https://public.api.bsky.app/xrpc/app.bsky.actor.getProfiles?actors="
            + "&actors=".join(batch)
        )
        raw_resp.raise_for_status()
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
            new_profiles[profile[kf.DID]] = out
    return new_profiles

def main():
    g = ATPTGrister(fetch_authors=False)
    stale_authors = [
        fields[kf.DID] for fields in
        g.list_records(t.AUTHORS)[1]
        if check_stale(fields.get(mf.POLLED))
    ]
    
    fetched = [
        {
            gf.KEY: {kf.DID: did},
            gf.FIELDS: fields
        }
        for did, fields in fetch_authors(stale_authors).items()
    ]
    if fetched:        
        g.add_update_records(t.AUTHORS, fetched)
        return fetched

if __name__ == "__main__":
    main()
