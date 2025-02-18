from enum import StrEnum
from typing import Any
import requests
import wmill
import pprint
from f.main.atptgrister import ATPTGrister, make_timestamp, kf, gf, t

class rt(StrEnum):
    AUTHORS = "Authors"
    LICENSES = "Licenses"
    LANGUAGES = "Languages"
    TOPICS = "Github_topics"

keyfields = {
    rt.AUTHORS: "did",
    rt.LICENSES: "name",
    rt.LANGUAGES: "name",
    rt.TOPICS: "name",
}

# boilerplate for basic functinality? in MY python??
def batched(iterable, n=1):
    for ndx in range(0, len(iterable), n):
        yield iterable[ndx:ndx+n]

class SetDict(dict):
    def __missing__(self, key):
        self[key] = set()
        return self[key]

refs_fields = ["topics", "licenseInfo", "authors"]
class EntryDict(dict):
    def __missing__(self, key):
        if key in refs_fields:
            self[key] = []
            return self[key]
        raise KeyError(key)

def add_one_missing(dest: list[str], item: str | None):
    # dest = dest.copy()
    if not item:
        return dest
    if item not in dest:
        dest.append(item)
    return dest

fragment = """
fragment repoProperties on Repository {
  homepageUrl
  description
  updatedAt
  latestRelease {
    updatedAt
    name
  }
  # defaultBranchRef {
  #     target {
  #       ... on Commit {
  #         committedDate
  #       }
  #     }
  #   }
  owner {
    ... on User {
      sponsorsListing {
        url
      }
      socialAccounts(first: 20) {
        nodes {
          url
          provider
        }
      }
    }
    ... on Organization {
      sponsorsListing {
        url
      }
    }
  }
  createdAt
  repositoryTopics(first: 20) {
    nodes {
      topic {
        name
      }
    }
  }
  forkCount
  stargazerCount
  issues(states: OPEN) {
    totalCount
  }
  pullRequests(states: OPEN) {
    totalCount
  }
  primaryLanguage {
    name
  }
  licenseInfo {
    name
  }
}
"""
template = (
    """{id}: repository(owner: "{owner}", name: "{repo}") {{...repoProperties}}"""
)
rate_limit_info = "rateLimit {cost remaining resetAt}"
headers = {
    "Authorization": f"Bearer {wmill.get_variable('u/autumn/github_key')}",
    "Content-Type": "application/json",
}

batch_size = 64 # 100 is the stated limit, but it still timed out server-side a fair bit. this seems to work better

def main():
    g = ATPTGrister(fetch_authors=True)
    all_repos = [
        path.split("/")
        for i in g.list_records("Repos")[1]
        if ((path := i.get("github_path")) and not i.get("not_found"))
    ]
    all_responses: dict[str, dict[str, Any]] = {}
    for num_req, batch in enumerate(batched(all_repos, batch_size)): 
        repos = "\n".join(
            template.format(id="r" + str(num_req * batch_size + i), owner=owner, repo=repo)
            for i, (owner, repo) in enumerate(batch)
        )
        query = f"{fragment} {{{repos} {rate_limit_info}}}"
        response = requests.post(
            "https://api.github.com/graphql", json={"query": query}, headers=headers
        )
        data = response.json()["data"]
        pprint.pp(data.pop("rateLimit"))
        if errors := data.pop("errors", None):
            pprint.pp(errors)
        all_responses |= data

    ref_trackers = {}

    def make_ref_trackers():    
        for table in rt:
            keyfield = "name" if table != rt.AUTHORS else "did"
            ref_trackers[table] = {
                "old": {rec[keyfield]: rec for rec in g.list_records(table)[1]},
                "new": set(),
                "entries": [],
            }
    make_ref_trackers()

    ref_field_names = {
        rt.TOPICS: "topics",
        rt.LICENSES: "licenseInfo",
        rt.AUTHORS: "Authors",
        rt.LANGUAGES: "primaryLanguage"
    }

    def add_refs(fields: dict, dest: rt, val: str | list[str]):
        tracker = ref_trackers[dest]
        if isinstance(val, list):
            tracker["new"] |= set(val) - tracker["old"].keys()
        else:
            if not tracker["old"].get(val):
                tracker["new"].add(val)
        tracker["entries"].append(fields)
        fields[ref_field_names[dest]] = val
        
    records = []
    for (owner, repo), resp in zip(all_repos, all_responses.values()):
        out = {gf.KEY: {kf.NORMAL_URL: f"https://github.com/{owner}/{repo}"}, gf.FIELDS: {}}
        fields: dict[str, Any] = out[gf.FIELDS]
        for field, v in resp.items():
            if v:
                match field:
                    #TODO iirc there was a lib to automate structural type hinting for graphql fields
                    case "homepageUrl":
                        fields[field] = v
                    case "description":
                        fields[field] = v
                    case "updatedAt":
                        fields[field] = make_timestamp(v)
                    case "latestRelease":
                        fields |= {"last_release_date": v["updatedAt"], "latest_version": v["name"]}
                    case "owner": #TODO replace this with top X contributors. mb calculate X by whatever number is repsonsile for >80% of commits/prs
                        if accounts := v.get("socialAccounts", {}).get("nodes"):
                            for acc in accounts: 
                                if acc["provider"] == "BLUESKY" and (did := g.resolve_author(acc["url"])):
                                    add_refs(fields, rt.AUTHORS, did)
                                    break #TODO some people have multiple bsky handles listed. handle this somehow idk
                        if sponsor := v.get("sponsorsListing"):
                            fields["sponsor_url"] = sponsor["url"]
                    case "createdAt":
                        fields[field] = make_timestamp(v)
                    case "repositoryTopics":
                        add_refs(
                            fields,
                            rt.TOPICS,
                            [node["topic"]["name"] for node in v["nodes"]],
                        )
                    case "forkCount":
                        fields[field] = v
                    case "stargazerCount":
                        fields[field] = v
                    case "issues":
                        fields[field] = v["totalCount"]
                    case "pullRequests":
                        fields[field] = v["totalCount"]
                    case "primaryLanguage":
                        add_refs(fields, rt.LANGUAGES, v["name"])
                    case "licenseInfo":
                        #TODO fields for licenses
                        add_refs(fields, rt.LICENSES, v["name"])
        records.append(out)

    g.write_authors()
    ref_trackers[t.AUTHORS]["old"] = g.authors_lookup
    ref_trackers[t.AUTHORS]["new"].clear()

    for table, tracker in ref_trackers.items():
        ref_field = ref_field_names[table]
        old = tracker["old"]
        if new_items := tracker.get("new"):
            table_keyfield = keyfields[table]
            items_list = list(new_items)
            new_ids = g.add_records(table, [{table_keyfield: rec} for rec in items_list])[1]
            for id, item in zip(new_ids, items_list):
                old[item] = {"id": id}
        if table != rt.TOPICS:
            for entry in tracker["entries"]:
                entry[ref_field] = old[entry[ref_field]]["id"]
        else:
            for entry in tracker["entries"]:
                entry[ref_field] = ["L", *(old[i]["id"] for i in entry[ref_field])]

    g.add_update_records(t.REPOS, records)

if __name__ == "__main__":
    main()
