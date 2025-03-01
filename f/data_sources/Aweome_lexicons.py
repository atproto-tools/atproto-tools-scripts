from typing import Any
import requests
from f.main.Collector import Collector, ef, t
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


# the lexicons table now only be manually updated (and kept in sync with the lex enum in f.main.Collector). this file kept around mostly to crawl the reference app metadata
def main():
    c = Collector("Awesome_lexicons", [ef.TAGS], fetch_authors=True, add_repos=True)
    lexicons = {entry["label"]: entry for entry  in c.g.list_records("Awesome_lexicons")[1]}
    md = get_tree(
        requests.get(
            "https://raw.githubusercontent.com/lexicon-community/awesome-lexicons/refs/heads/main/README.md"
        ).text,
    )
    list_start = next(i for i, node in enumerate(md) if node["type"] == "heading" and node["children"][0]["raw"] == "Lexicons") # type: ignore
    lexicons_entries = {}
    lex_name = ""
    for node in md[list_start + 1:]:
        normal_app_url = ""
        assert isinstance(node, dict)
        if node["type"] == "heading" and node["attrs"]["level"] == 2:
            lex_name = node["children"][0]["raw"]
        if node["type"] == "list":
            fields = node["children"]
            lex_fields: dict[str, Any] = {
                "awesome_list_link": f"[{lex_name}](https://github.com/lexicon-community/awesome-lexicons?tab=readme-ov-file#{lex_name.replace(" ", "-").lower()})"
            }
            lexicons_entries[lex_name] = lex_fields
            for field in fields:
                block = field['children'][0]['children']
                if block[0]["raw"].startswith('Devs'):
                    lex_fields["authors"] = []
                    for elem in block[1:]:
                        if elem["type"] == "link":
                            lex_fields["authors"].append(c.g.resolve_author(elem["attrs"]["url"]))
                            
                elif (cur_field := block[0]["raw"]).lower().startswith('github') or cur_field.lower().startswith("lexicon"):
                    lex_fields["source"] = cur_field[cur_field.find("https://"):]
                    
                elif block[0]["raw"].startswith('Namespace'):
                    lex_fields["namespace"] = block[1]["raw"]
                    
                elif (cur_field := block[0]["raw"]).startswith('App') or cur_field.startswith("https://bsky.app"): # cmon guys
                    app_url = cur_field[cur_field.find("https://"):]
                    if len(app_url) == 1 and lex_name.startswith("Statusphere"):
                        app_url = "https://github.com/bluesky-social/statusphere-example-app" # yeah..
                    normal_app_url, _ = c.add_site({
                        ef.URL: app_url,
                        ef.TAGS: [lex_name],
                        ef.LEXICONS: lexicons[lex_name]["id"]
                    })

                elif block[0]["raw"].lower().startswith('bluesky account'):
                    site_author = block[1]['attrs']['url']
                    if normal_app_url:
                        c.add_author_site(site_author, normal_app_url) #type: ignore - app always listed before bluesky account
                    lex_fields["bluesky_account"] = site_author
    c.g.write_authors()
    for lexicons in lexicons_entries.values():
        if "authors" in lexicons:
            lexicons["authors"] = ["L", *(c.g.authors_lookup[author]["id"] for author in lexicons["authors"])]
    c.g.add_update_records(t.LEXICONS)
    c.output()

if __name__ == "__main__":
    main()
