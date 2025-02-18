import requests
from typing import Any
from f.main.Collector import Collector, ef
import mistune

def render_nodes(nodes):
    out = ""
    for node in nodes:
        if node["type"] == "link":
            out += f'[{node["children"][0]["raw"]}]({node["attrs"]["url"]})'
        elif node["type"] == "text":
            out += node["raw"]
        else:
            raise RuntimeError("unknown node type")
    return out

get_tree = mistune.create_markdown(renderer=None)

def main():
    
    c = Collector(
        "Fishttp_awesome_bluesky",
        ["name", "description", "tags"],
        add_repos=True
    )

    md = get_tree(
        requests.get(
            "https://raw.githubusercontent.com/fishttp/awesome-bluesky/refs/heads/main/readme.md"
        ).text,
    )

    # https://codebeautify.org/python-formatter-beautifier on md is helpful
    current_h2: list = []
    for node in md:
        assert not isinstance(node, str)
        if node["type"] == "heading" and node["attrs"]["level"] == 2:
            current_h2 = [node["children"][0]["raw"]]
        if node["type"] == "list":  # sublist
            for item in node["children"]:  # list entries
                # item always has a single child block_text which has two children, link and description
                link = item["children"][0]["children"][0]
                entry: dict[str, Any] = {
                    ef.URL: link["attrs"]["url"],
                    ef.NAME: link["children"][0]["raw"],
                    ef.DESC: render_nodes(item["children"][0]["children"][1:]).strip(". -"),
                    ef.TAGS: current_h2,
                }
                if entry[ef.URL]:
                    c.add_site(entry)

    return c.output()

if __name__ == "__main__":
    main()
