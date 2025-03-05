import os
import wmill
from f.main.Collector import Collector, lex, t, gf, kf, ef, normalize, ATPTGrister

from datetime import datetime
start = datetime.now()
def simple_log(msg: str):
    # print(datetime.now() - start, msg)
    return

#TODO other sanitization? idk what the risks are
def clean_url(url: str) -> kf:
    return normalize(url.strip())

def filter_falsy(d: dict):
    return {k: v for k,v in d.items() if v} # gotta 'cast to null' to keep blank/empty values uniform in all tables

submitter = os.environ.get("WM_USERNAME") or ""
if submitter:
    submitter = submitter.capitalize() #not strictly necessary but sources are capitalized thems the rules
sg = ATPTGrister(False)
#TODO #ask not sure if this is the best approach (blindly sending a post request). but it seems like the most efficient unless we want to add all new authors manually to Data_Sources
sg.add_update_records(t.SOURCES, [{gf.KEY: {"source_name": submitter}, gf.FIELDS: {"label": submitter + " form"}}])

out_template = """
[view your entry here](https://atproto-tools.getgrist.com/p2SiVPSGqbi8/main-list/p/9#a1.s27.r{rec_id}).
"""
#TODO for now, only one URL per submission, and it must be a new url. if we can figure out how to set a cookie from the web form, we can allow edits (since it allows ownership)
#TODO #blocked once tags are unified, add a tag selector (via cached net request in wmill)
def main(url: str | None, name: str | None = None, desc: str | None = None, repo: str | None = None, author: str | None = None, lexicon: str | None = None):
    c = Collector(submitter, fields = [ef.NAME, ef.DESC], add_repos=True, write_meta=True, fetch_authors=True)
    simple_log("collector init")
    c.g.update_config({'GRIST_API_KEY': wmill.get_variable(path="u/autumn/grist_form_key")})
    simple_log("updated config")
    url, repo = url and clean_url(url), repo and clean_url(repo)
    if url:
        new_record = filter_falsy({
            ef.URL: url,
            ef.NAME: name,
            ef.DESC: desc,
            ef.REPO: repo,
            ef.AUTHOR: author,
            ef.LEXICON: lexicon and int(lexicon) # TODO add multiple lexicons in the ui. for now submitting twice with different ones should work.
        })
        c.add_site(new_record)
        simple_log("added")
        c.output()
        simple_log("wrote")
        out = out_template.format(rec_id = c.sites[url]['id'])
    else:
        out = "no url provided"
    return {"markdown": out}

if __name__ == "__main__":
    main(
            url="https://atproto-tools.getgrist.com/p2SiVPSGqbi8/",
            repo="https://github.com/atproto-tools/atproto-tools-scripts/",
            author="aeshna-cyanea.bsky.social",
            # name="atproto tools",
            # desc="open database of the atproto ecosystem",
            lexicon=lex.UNIVERSAL
        )
    main(
            url="https://atproto-tools.getgrist.com/p2SiVPSGqbi8/",
            repo="https://github.com/atproto-tools/atproto-tools-scripts/",
            author="aeshna-cyanea.bsky.social",
            # name="atproto tools",
            # desc="open database of the atproto ecosystem",
            lexicon=lex.BLUESKY
        )
