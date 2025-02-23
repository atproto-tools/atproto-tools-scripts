import requests
import wmill
from f.main.Collector import Collector, ef

query = """
query getList($after: String) {
  node(id: "UL_kwDOCyNr884ATJdC") {
    ... on UserList {
      updatedAt
      items(first: 100, after: $after) {
        totalCount
        nodes {
          ... on RepositoryInfo {
            url
            homepageUrl
            description
            owner {
              ... on User {
                socialAccounts(first: 20) {
                  nodes {
                    url
                    provider
                  }
                }
              }
            }
          }
        }
        pageInfo {
          hasNextPage
          endCursor
        }
      }
    }
  }
  rateLimit {
    cost
    remaining
    limit
    resetAt
  }
}
"""


def main():
    c = Collector("Aeshna_cyanea_starred", fields=[ef.DESC], fetch_authors=True)

    headers = {
        "Authorization": f"Bearer {wmill.get_variable('u/autumn/github_key')}",
        "X-GitHub-Api-Version": "2022-11-28",
    }

    after_cursor = None
    while True:
        r = requests.post(
            "https://api.github.com/graphql", json={"query": query, "variables": {"after": after_cursor}}, headers=headers
        ).json()
        node = r["data"]["node"]
        # c.check_update_timestamp(node["updatedAt"])
        items = node["items"]
        if items["pageInfo"]["hasNextPage"]:
            after_cursor = items["pageInfo"]["endCursor"]
        else:
            after_cursor = None

        for node in items["nodes"]:
            repo_url = node["url"]
            homepage = node.get("homepageUrl") or repo_url
            entry = {
                ef.URL: homepage,
                ef.REPO: repo_url
            }
            if desc := node["description"]:
                entry[ef.DESC] = desc
            if accounts := node.get("socialAccounts", {}).get("nodes"):
                bluesky_account = next((acc["url"] for acc in accounts if acc["provider"] == "BLUESKY"), None)
                if bluesky_account: #TODO some people have multiple bsky handles listed. handle this somehow idk
                    entry[ef.AUTHOR] = bluesky_account
            c.add_site(entry)
            if not after_cursor:
                break
    return c.output()

if __name__ == "__main__":
    main()
