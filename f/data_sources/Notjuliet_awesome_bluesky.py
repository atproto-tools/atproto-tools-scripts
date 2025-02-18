import requests
from typing import Any
from f.main.Collector import Collector, ef
import mistune

def render_nodes(nodes) -> str:
    out = ""
    for node in nodes:
        if node["type"] == "link":
            out += f'[{node["children"][0]["raw"]}]({node["attrs"]["url"]})'
        elif node["type"] == "text":
            out += node["raw"]
        elif node["type"] == "codespan":
            out += "`" + node["raw"] + "`"
        else:
            raise RuntimeError("unknown node type")
    return out

get_tree = mistune.create_markdown(renderer=None)

def main():
    c = Collector(
        "Notjuliet_awesome_bluesky", ["name", "description", "tags"], add_repos=True
    )
    get_tree = mistune.create_markdown(renderer=None)

    md: Any = get_tree(
        requests.get(
            "https://raw.githubusercontent.com/notjuliet/awesome-bluesky/refs/heads/main/README.md"
        ).text
    )

    # https://codebeautify.org/python-formatter-beautifier on md is helpful
    current_h2: list = []
    current_h3: list = []
    for node in md:
        if node["type"] == "heading" and node["attrs"]["level"] == 2:
            current_h2 = [node["children"][0]["raw"]]
            current_h3 = []
        if node["type"] == "heading" and node["attrs"]["level"] == 3:
            current_h3 = [node["children"][0]["raw"]]
        if node["type"] == "list":  # sublist
            list_items = node["children"]
            for item in list_items:  # list entries
                # item always has a single child block_text which has two children, link and description
                link = item["children"][0]["children"][0]

                c.add_site({
                    ef.URL: link["attrs"]["url"],
                    ef.NAME: link["children"][0]["raw"], # raw text of the link
                    ef.DESC: render_nodes(item["children"][0]["children"][1:]).strip(". -"),
                    ef.TAGS: current_h2 + current_h3,
                    # ef.TAGS: ["/".join(current_h2 + current_h3)]
                })

    return c.output()
