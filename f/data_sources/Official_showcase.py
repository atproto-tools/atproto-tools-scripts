import re
import requests
import pyjson5
from f.main.Collector import Collector, ef
from typing import Any

excluded_repos = [
    "https://github.com/myConsciousness/atproto.dart/tree/main/packages" # is a data source, not a site
]

def main() -> dict[str, list]:
    raw_file = requests.get("https://raw.githubusercontent.com/bluesky-social/bsky-docs/refs/heads/main/src/data/users.tsx").text
    
    tags_string = re.search("export const Tags.*= ({.*?^})", raw_file, re.M + re.S).group(1) #type: ignore
    assert isinstance(tags_string, str)
    raw_tags = pyjson5.decode(tags_string)
    del raw_tags["favorite"]
    del raw_tags["opensource"] # we keep track of these separately, don't need them in the key
    tags: dict[str, dict[str, Any]] = {}
    og_tags_key: dict[str, str] = {} # maps the og lowercase names to their labels
    for og_tag, og_fields in raw_tags.items():
        tags[og_fields["label"]] = og_fields
        og_tags_key[og_tag] = og_fields.pop("label")

    c = Collector("Official_showcase", [ef.NAME, ef.DESC, ef.TAGS, ef.RATING], tags, True, fetch_authors=True)
    raw_entries = re.search(r"const Users: User\[\] = (\[\n.*?\n\])", raw_file, re.S).group(1) # type: ignore
    assert isinstance(raw_entries, str)
    
    # sample entry for reference-
    # title: 'atproto (C++/Qt)',
    # description: 'AT Protocol implementation in C++/Qt',
    # preview: require('./showcase/example-1.png'),
    # website: 'https://github.com/mefboer/atproto',
    # source: 'https://github.com/mefboer/atproto',
    # author: 'https://bsky.app/profile/did:plc:qxaugrh7755sxvmxndcvcsgn',
    # tags: ['protocol', 'opensource'],
    
    raw_entries = "".join([x for x in raw_entries.splitlines() if x.find("require(") == -1]) # strip lines with "require("
    entries = pyjson5.decode(raw_entries)
    field_key = {
            ef.URL: "website",
            ef.NAME: "title",
            ef.DESC: "description",
            ef.AUTHOR: "author",
            ef.REPO: "source",
    }
    for entry in entries:
        if "website" not in entry: # fix your data guys! https://github.com/bluesky-social/bsky-docs/blob/main/src/data/users.tsx#L846
            entry["website"] = entry["source"] 

        if entry.get("source") in excluded_repos:
            continue

        # additional check if entry[v] is truthy because for some reason there is an explicit null at https://github.com/bluesky-social/bsky-docs/blob/main/src/data/users.tsx#L808
        fields = {k: entry[v] for k,v in field_key.items() if v in entry and entry[v]}

        for og_tag in entry.get("tags", []):
            if og_tag == "favorite":
                fields[ef.RATING] = 1
            elif og_tag == "opensource":
                if source := entry.get("source"):
                    if not fields[ef.REPO]:
                        print(f"{entry['title']} marked opensource, but no repo field")
                    fields[ef.REPO] = source
            else:
                if ef.TAGS in fields:
                    fields[ef.TAGS].append(og_tags_key[og_tag])
                else:
                    fields[ef.TAGS] = [og_tags_key[og_tag]]
        c.add_site(fields)

    return c.output()

if __name__ == "__main__":

    main()
