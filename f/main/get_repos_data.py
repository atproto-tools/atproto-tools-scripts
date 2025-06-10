from datetime import datetime
from enum import StrEnum
from typing import Any, Iterable
from urllib.parse import urlparse, urlunparse
import requests
import wmill
import pprint
import re
from f.main.ATPTGrister import ATPTGrister, CustomGrister, make_timestamp, t, kf, gf, mf, check_stale
from f.main.boilerplate import batched, dicts_diff
from operator import itemgetter as getter

forge_type_col = "forge_type"
class forges(StrEnum):
    GITHUB = "github"
    GITLAB = "gitlab"
    GITEA = "gitea"
    TANGLED = "tangled"


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
  README: object(expression: "HEAD:README.md") {
    ... on Blob {
      text
    }
  }
  readme: object(expression: "HEAD:readme.md") {
    ... on Blob {
      text
    }
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

poll_timestamp = datetime.today().timestamp()

def fetch_repo_data(g: CustomGrister, repo_urls: Iterable[kf], old_records: dict[kf, dict[str, Any]] = {}) -> dict[kf, dict[str, Any]]:
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
    if not old_records:
        old_records  = {rec[kf.NORMAL_URL]: rec for rec in g.list_records(t.REPOS)[1]}
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

    gitea_field_key = { #thank u claude
        "homepageUrl": getter("website"),
        "description": getter("description"),
        "updatedAt": getter("updated_at"),
        mf.STATUS: lambda x: "archived" if x.get("archived") else None,
        "createdAt": getter("created_at"),
        "forkCount": getter("forks_count"),
        "stargazerCount": getter("stars_count"),
        "issues": getter("open_issues_count"),  # GitHub has this nested under issues with state OPEN
        "pullRequests": getter("open_pr_counter"),  # GitHub has this nested under pullRequests with state OPEN
        #TODO for now we just make a gross assumption that github language names map neatly to gitea names, but we should really verify
        ref_field_names[rt.LANGUAGES]: lambda x: add_refs(x, rt.LANGUAGES, x.get("languages")),

        # Topics
        # "topics": "topics",  # GitHub has this nested under nodes. #TODO idk how to handle mapping them onto github topics
        
        #TODO same problem, not sure how to map them to github equivalents
        # "licenses": "license",  # GitHub has this as a single license under licenseInfo
    }

    #TODO also add readme.md parsing
    gitea_urls = [
        urlparse(url)
        for url in repo_urls
        if old_records.get(url, {}).get(forge_type_col) == forges.GITEA
    ]
    for i in gitea_urls:
        endpoint = urlunparse(i._replace(path="/api/v1/repos" + i.path))
        resp = requests.get(endpoint)
        resp.raise_for_status()
        r_json = resp.json()
        out = {mf.POLLED: int(poll_timestamp)}
        for grist_field, field_getter in gitea_field_key.items():
            if (val := field_getter(r_json)) is not None: # 0 is a valid value
                out[grist_field] = val 
        records[urlunparse(i)] = out

    github_urls: list[tuple[str, str]] = [
        (rmatch[1], rmatch[2])
        for url in repo_urls
        if (rmatch := re.search(r"https://github\.com/([^/]*)/([^/]*)/?$", url))
    ]
    github_responses: dict[str, dict[str, Any]] = {}
    batch_size = 32
    # 100 is the stated limit, but it still timed out server-side a fair bit. experimentally 64 seems to work better.
    # 32 when fetching readmes
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
            mf.POLLED: int(poll_timestamp)
        }
        if resp:
            for field, v in resp.items():
                if not v:
                    continue
                #TODO redo this to a dict of lambdas maybe? but some of these are multiline and lambdas can't be. ask
                match field:
                    #TODO iirc there was a lib to automate structural type hinting for graphql fields
                    case "homepageUrl":
                        out[field] = v
                    case "description":
                        out[field] = v
                    case "isArchived":
                        out[mf.STATUS] = "archived"
                    case "defaultBranchRef":
                        out["updatedAt"] = make_timestamp(v["target"]["committedDate"])
                    case "latestRelease":
                        out |= {"last_release_date": v["updatedAt"], "latest_version": v["name"]}
                    case "owner":
                        if accounts := v.get("socialAccounts", {}).get("nodes"):
                            for acc in accounts:
                                if acc["provider"] == "BLUESKY" and (did := g.resolve_author(acc["url"])):
                                    add_refs(out, t.AUTHORS, did)
                                    break #TODO some people have multiple bsky handles listed. handle this somehow instead of just using the first one
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
                    case "readme":
                        if v and (text := v["text"]):
                            # judgement call, sometimes people put meta stuff in the first few lines before the header
                            lines: list[str] = text.splitlines()[:5]
                            for line in lines:
                                if readme_heading := re.match(r"^##? (.*)", line):
                                    out["readme_header"] = readme_heading[1]
                                    break
                    case "README":
                        if v and (text := v["text"]):
                            lines: list[str] = text.splitlines()[:5]
                            for line in lines:
                                if readme_heading := re.match(r"^##? (.*)", line):
                                    out["readme_header"] = readme_heading[1]
                                    break
            contribs_count = 0
            contribs_query = f"https://api.github.com/repos/{owner}/{repo}/contributors?per_page=100"
            while True:
                contribs_resp = requests.get(contribs_query, headers=headers)
                contribs_data = contribs_resp.json() # for debugging
                contribs_count += len(contribs_data)
                if (link := contribs_resp.headers.get("link")) and (last_link_match := re.search(r'<(.*?)>; rel="last"', link)):
                    contribs_query = last_link_match[1]
                else:
                    break
            out["contributors"] = contribs_count or None
        else:
            out[mf.STATUS] = "not found"
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


def update_all_repos(g: CustomGrister | None = None, include_inactive: bool = True):
    g = g or ATPTGrister(fetch_authors=True)
    #TODO convert to sql query
    old_records_dict = {rec[kf.NORMAL_URL]: rec for rec in g.list_records("Repos")[1]}
    urls = [
        i[kf.NORMAL_URL]
        for i in old_records_dict.values()
        if (
            # TODO if we start to get a large fraction of archived/deleted repos, move checking those to a separate (less frequent) job
            (include_inactive or not i.get(mf.STATUS)) and
            check_stale(i.get(mf.POLLED))
        )
    ]
    if repo_data := fetch_repo_data(g, urls, old_records_dict):
        diffs  = {
            url: diff
            for url, rec in repo_data.items()
            if (diff := dicts_diff(old_records_dict[url], rec))
        }
        records = [
            {gf.KEY: {kf.NORMAL_URL: url}, gf.FIELDS: diff}
            for url, diff in diffs.items()
        ]
        if records:
            g.add_update_records(t.REPOS, records)

def main():
    update_all_repos()

if __name__ == "__main__":
    main()
