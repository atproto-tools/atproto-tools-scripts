import os
import wmill
from f.main.Collector import Collector, t, gf, kf, ef, normalize, ATPTGrister
from f.main.lex_enum import lex
from f.main.boilerplate import get_timed_logger
log = get_timed_logger(__file__)

#longterm other sanitization? idk what the risks are
def clean_url(url: str) -> kf:
    return normalize(url.strip())

def filter_falsy(d: dict):
    return {k: v for k,v in d.items() if v} # gotta 'cast to null' to keep blank/empty values uniform in all tables

submitter = os.environ["WM_USERNAME"]
if submitter:
    submitter = submitter.capitalize() #not strictly necessary but sources are capitalized thems the rules
sg = ATPTGrister(False)

# not sure if this is the best approach (blindly sending a post request). but it seems like the most efficient unless we want to add all new authors manually to Data_Sources
sg.add_update_records(t.SOURCES, [{gf.KEY: {"source_name": submitter}, gf.FIELDS: {"label": submitter + " form"}}])

out_template = """
[view your entry here](https://atproto-tools.getgrist.com/p2SiVPSGqbi8/main-list/p/9#a1.s27.r{rec_id}).
"""
#longterm for now, only one URL per submission, and it must be a new url. if we can figure out how to set a cookie from the web form, we can allow edits (since it allows ownership)
#blocked once tags are unified, add a tag selector (via cached net request in wmill)
def main(url: str | None, name: str | None = None, desc: str | None = None, repo: str | None = None, author: str | None = None, lexicon: int | None = None):
    c = Collector(submitter, fields = [ef.NAME, ef.DESC], add_repos=True, write_meta=True, fetch_authors=True)
    c.g.update_config({'GRIST_API_KEY': wmill.get_variable(path="u/autumn/grist_form_key")})
    url, repo = url and clean_url(url), repo and clean_url(repo)
    if url:
        new_record = filter_falsy({
            ef.URL: url,
            ef.NAME: name,
            ef.DESC: desc,
            ef.REPO: repo,
            ef.AUTHOR: author,
            ef.LEXICON: lexicon and int(lexicon) #longterm add multiple lexicons in the ui. for now submitting twice with different ones can work.
        })
        c.add_site(new_record)
        c.output()
        log.info("wrote output")
        out = out_template.format(rec_id = c.sites[url]['id'])
    else:
        out = "no url provided"
    return {"markdown": out}

if __name__ == "__main__":
    main(
            url="https://bookhive.buzz",
            repo="https://github.com/nperez0111/bookhive/",
            author="https://bsky.app/profile/bookhive.buzz",
            # name="atproto tools",
            # desc="open database of the atproto ecosystem",
            # lexicon=lex.UNIVERSAL
        )
    main(
            url="https://atproto-tools.getgrist.com/p2SiVPSGqbi8/",
            repo="https://github.com/atproto-tools/atproto-tools-scripts/",
            author="aeshna-cyanea.bsky.social",
            # name="atproto tools",
            # desc="open database of the atproto ecosystem",
            lexicon=lex.BLUESKY
        )
