from enum import StrEnum
from f.main.atptgrister import ATPTGrister, kf, gf
import requests

def batched(iterable, n=1):
    for ndx in range(0, len(iterable), n):
        yield iterable[ndx:ndx+n]

class af(StrEnum):
    CAKEDAY = "createdAt"
    DISPLAYNAME = "displayName"
    DESCRIPTION = "description"
    FOLLOWERS = "followersCount"
    FOLLOWING = "followsCount"
    POSTS = "postsCount"

batch_size = 25

def main():
    new_profiles = []
    g = ATPTGrister(True)
    for batch in batched(g.list_records("Authors")[1], batch_size):
        raw_resp = requests.get(
            "https://public.api.bsky.app/xrpc/app.bsky.actor.getProfiles?actors="
            + "&actors=".join(a.get(kf.DID) or a.get(kf.HANDLE) for a in batch)
        )
        raw_resp.raise_for_status()
        for profile in raw_resp.json()["profiles"]:
            out: dict[gf, dict[kf | af, str]] = {
                gf.KEY: {kf.DID: profile[kf.DID]},
                gf.FIELDS: {kf.HANDLE: profile[kf.HANDLE]},
            }
            
            if not (labels := profile.get("labels")) or not any(
                label["val"] == "!no-unauthenticated"
                and label["src"] == profile[kf.DID]
                for label in labels
            ):
                out[gf.FIELDS] |= {field: profile[field] for field in list(af) if field in profile}
            else:
                out[gf.FIELDS] |= {field: "-1" for field in [af.FOLLOWING, af.FOLLOWERS, af.POSTS] if field in profile}
            new_profiles.append(out)
    g.add_update_records("Authors", new_profiles)

if __name__ == "__main__":
    main()
