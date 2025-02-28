from enum import StrEnum
from time import time
from typing import Any, Iterable
from urllib.parse import urlparse, urlunparse
import requests
import wmill
import pprint
import re
from f.main.ATPTGrister import ATPTGrister, CustomGrister, make_timestamp, t, kf, gf, mf, check_stale

class rt(StrEnum):
    LICENSES = "Licenses"
    LANGUAGES = "Languages"
    TOPICS = "Github_topics"

keyfields = {
    t.AUTHORS: "did",
    rt.LICENSES: "name",
    rt.LANGUAGES: "name",
    rt.TOPICS: "name",
}

ref_field_names = {
    t.AUTHORS: "Authors",
    rt.TOPICS: "topics",
    rt.LICENSES: "license",
    rt.LANGUAGES: "language"
}


# boilerplate for basic functinality? in MY python??
def batched(long_list: list, n=1):
    for ndx in range(0, len(long_list), n):
        yield long_list[ndx:ndx+n]


gitea_field_key = { #thank u claude
    "website": "homepageUrl",
    "description": "description",
    "updated_at": "updatedAt",
    "archived": "isArchived",
    "created_at": "createdAt",
    "forks_count": "forkCount",
    "stars_count": "stargazerCount",
    "open_issues_count": "issues",  # GitHub has this nested under issues with state OPEN
    "open_pr_counter": "pullRequests",  # GitHub has this nested under pullRequests with state OPEN
    "language": ref_field_names[rt.LANGUAGES]
    # for now we just make a gross assumption that github language names map neatly to gitea names

    # Topics
    # "topics": "topics",  # GitHub has this nested under nodes
    
    # License #TODO idk how to merge gitea and github licenses
    # "licenses": "license",  # GitHub has this as a single license under licenseInfo
    
    # Release info (partial match)
    # "release_counter": "latestRelease",  # a simple counter doesn't seem useful
}

fragment = """
fragment repoProperties on Repository {
  homepageUrl
  description
  isArchived
  latestRelease {
    updatedAt
    name
  }
  defaultBranchRef {
      target {
        ... on Commit {
          committedDate
        }
      }
    }
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

def fetch_repo_data(g: CustomGrister, repo_urls: Iterable[str]) -> dict[kf, dict[str, Any]]:
    """
    fills in repo metadata to the Repos table. Quite slow - it reads/writes 3 additional tables (listed in the rt enum)

    Args:
        g (CustomGrister): an initialized CustomGrister, preferably with fetch_authors=True in constructor
        repos (list[list[str]]): a list of repos in the form [[owner, repo], [owner, repo], ...]
    Returns:
        dict[str, dict[str, Any]]: records indexed by url
    """
    if not repo_urls:
        return {}
    records = {}
    ref_trackers = {}
    #TODO make these list requests async
    for table, keyfield in keyfields.items():
        if table == t.AUTHORS:
            source_table = {k:v for k,v in g.authors_lookup.items() if k.startswith("did:")}
        else:
            source_table = {rec[keyfield]: rec for rec in g.list_records(table)[1]}
        ref_trackers[table] = {
            "old": source_table,
            "new": set(), # set of new values to be written to the table
            "entries": [], # the list of fields dicts that will be replaced with references
        }

    def add_refs(fields: dict, dest: t | rt, val: str | list[str]):
        tracker = ref_trackers[dest]
        if isinstance(val, list):
            tracker["new"] |= set(val) - tracker["old"].keys()
        else:
            if not tracker["old"].get(val):
                tracker["new"].add(val)
        tracker["entries"].append(fields)
        fields[ref_field_names[dest]] = val

    #TODO support other forges. forgejo? inquire about other popular ones. Gitlab doesn't seem to have a public api at all?
    gitea_domains = ["gitea.com", "git.syui.ai"]  # TODO store this in a wmill variable or smth
    gitea_urls = [
        parsed_url
        for url in repo_urls
        if (parsed_url := urlparse(url)).netloc in gitea_domains
        and len(parsed_url.path.strip("/").split("/")) == 2
    ]
    for i in gitea_urls:
        url = urlunparse(i)
        new_path = "/api/v1/repos" + i.path
        endpoint = urlunparse(i._replace(path=new_path))
        resp = requests.get(endpoint)
        resp.raise_for_status()
        r_json = resp.json()
        # records[url] = {
        #     gitea_field_key[field]: value for field, value in r_json
        # }
        out = {mf.POLLED: int(time())}
        for gitea_field, grist_field in gitea_field_key.items():
            if (val := r_json.get(gitea_field)) is not None:
                out[grist_field] = val
        records[url] = out
    
    github_urls: list[tuple[str, str]] = [
        (rmatch[1], rmatch[2])
        for url in repo_urls
        if (rmatch := re.search(r"https://github\.com/([^/]*)/([^/]*)/?$", url))
    ]
    github_responses: dict[str, dict[str, Any]] = {}
    batch_size = 64 # 100 is the stated limit, but it still timed out server-side a fair bit. this seems to work better
    for num_req, batch in enumerate(batched(github_urls, batch_size)): 
        repos_query_batch = "\n".join(
            template.format(id="r" + str(num_req * batch_size + i), owner=owner, repo=repo)
            for i, (owner, repo) in enumerate(batch)
        )
        query = f"{fragment} {{{repos_query_batch} {rate_limit_info}}}"
        response = requests.post(
            "https://api.github.com/graphql", json={"query": query}, headers=headers
        )
        data = response.json()["data"]
        pprint.pp(data.pop("rateLimit"))
        if errors := data.pop("errors", None):
            pprint.pp(errors)
        github_responses |= data

    for (owner, repo), resp in zip(github_urls, github_responses.values()):
        url = f"https://github.com/{owner}/{repo}"
        out: dict[str, Any] = {
            mf.POLLED: int(time())
        }
        if resp:
            for field, v in resp.items():
                if v:
                    match field:
                        #TODO iirc there was a lib to automate structural type hinting for graphql fields
                        case "homepageUrl":
                            out[field] = v
                        case "description":
                            out[field] = v
                        case "isArchived":
                            out[field] = v
                        case "defaultBranchRef":
                            out["updatedAt"] = make_timestamp(v["target"]["committedDate"])
                        case "latestRelease":
                            out |= {"last_release_date": v["updatedAt"], "latest_version": v["name"]}
                        case "owner": #TODO replace this with top X contributors. mb calculate X by whatever number is repsonsile for >80% of commits/prs
                            if accounts := v.get("socialAccounts", {}).get("nodes"):
                                for acc in accounts:
                                    if acc["provider"] == "BLUESKY" and (did := g.resolve_author(acc["url"])):
                                        add_refs(out, t.AUTHORS, did)
                                        break #TODO some people have multiple bsky handles listed. handle this somehow idk
                            if sponsor := v.get("sponsorsListing"):
                                out["sponsor_url"] = sponsor["url"]
                        case "createdAt":
                            out[field] = make_timestamp(v)
                        case "repositoryTopics":
                            add_refs(
                                out,
                                rt.TOPICS,
                                [node["topic"]["name"] for node in v["nodes"]],
                            )
                        case "forkCount":
                            out[field] = v
                        case "stargazerCount":
                            out[field] = v
                        case "issues":
                            out[field] = v["totalCount"]
                        case "pullRequests":
                            out[field] = v["totalCount"]
                        case "primaryLanguage":
                            add_refs(out, rt.LANGUAGES, v["name"])
                        case "licenseInfo":
                            #TODO more fields for licenses
                            add_refs(out, rt.LICENSES, v["name"])
        else:
            out[mf.INACTIVE] = "true"
        records[url] = out

    g.write_authors()
    ref_trackers[t.AUTHORS]["old"] = g.authors_lookup
    ref_trackers[t.AUTHORS]["new"].clear()

    for table, tracker in ref_trackers.items():
        ref_field = ref_field_names[table]
        old = tracker["old"]
        if new_items := tracker["new"]:
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
    return records


def update_all_repos(g: CustomGrister | None = None):
    g = g or ATPTGrister(fetch_authors=True)
    #TODO convert to sql query
    all_repos = [
        i[kf.NORMAL_URL]
        for i in g.list_records("Repos")[1]
        if ( True
            # i.get("github_path")
            # and not i.get(mf.INACTIVE)
            # and not i.get("isArchived")
            and check_stale(i.get(mf.POLLED))
        )
    ]
    records = fetch_repo_data(g, all_repos)
    assert records
    print(len(str(records)))
    g.add_update_records(t.REPOS, list(
        {
            gf.KEY: {kf.NORMAL_URL: url},
            gf.FIELDS: v
        }
        for url, v in records.items()
    ))

def main():
    update_all_repos()

if __name__ == "__main__":
    main()
