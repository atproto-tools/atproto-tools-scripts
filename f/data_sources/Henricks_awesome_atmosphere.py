import requests
from typing import Any
from f.main.Collector import Collector, ef
import mistune

get_tree = mistune.create_markdown(renderer=None)

c = Collector(
    "Henricks_awesome_atmosphere", ["description", "tags"], add_repos=True
)

excludes = ["https://blog.hugeblank.dev/3ldjqge6zuc2w", "https://recipies.blue"]


def main():
    md: Any = get_tree(
        requests.get(
            "https://raw.githubusercontent.com/HenrickTheBull/Henricks-Awesome-ATmosphere/refs/heads/main/readme.md"
        ).text,
    )

    # https://codebeautify.org/python-formatter-beautifier on md is helpful
    current_h3: list = []
    for node in md:
        if node["type"] == "heading" and node["attrs"]["level"] == 3:
            current_h3 = [node["children"][0]["raw"]]
        if node["type"] == "list":  # sublist
            list_items = node["children"]   
            for item in list_items:  # list entries
                # item always has a single child block_text which has two children, link and description
                link: str = item["children"][0]["children"][0]["raw"]
                entry = {
                    ef.URL: link[:link.find(" ")],  # will be stripped so it's fine
                    ef.DESC: link[link.find(" ") + 2:].strip("- ."),
                    ef.TAGS: current_h3,
                }
                if entry[ef.URL] not in excludes:
                    c.add_site(entry)

    return c.output()

if __name__ == "__main__":
    main()
