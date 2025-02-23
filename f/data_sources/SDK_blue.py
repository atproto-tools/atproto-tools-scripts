import requests
import yaml
import wmill
from f.main.Collector import Collector

query = """
query {
  repository(owner: "mackuba", name: "sdk.blue") {
    object(expression: "master:_data/projects") {
      ... on Tree {
        entries {
          object {
            ... on Blob {
              text
            }
          }
        }
      }
    }
  }
}
"""


def main():
    c = Collector("SDK_blue", add_repos=True)

    headers = {
        "Authorization": f"Bearer {wmill.get_variable('u/autumn/github_key')}",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    r = requests.post(
        "https://api.github.com/graphql", json={"query": query}, headers=headers
    )

    dir = r.json()["data"]["repository"]["object"]["entries"]
    for lang in dir:
        sublist = yaml.safe_load(lang["object"]["text"])
        for entry in sublist["repos"]:
            if url := entry.get("url"):
              c.add_site(url)

    return c.output()

if __name__ == "__main__":
    main()
