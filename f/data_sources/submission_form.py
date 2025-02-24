from typing import Any, cast
import wmill
from f.main.ATPTGrister import normalize
from f.main.Collector import Collector, kf, ef

#TODO other sanitization? idk what the risks are
def clean_url(url: str ) -> kf:
    url = url.strip()
    if not url:
        return cast(kf, url)
    return cast(kf, normalize(url))

out_template = """
[view your entry here](https://atproto-tools.getgrist.com/p2SiVPSGqbi8/main-list/p/9#a1.s27.r{rec_id}).
this link includes a unique identifier- you (or anyone you share it with) can use the it to edit any entries you've created.
"""

#TODO for now, only one URL per submission, and it must be a new url. adding a url to an existing author/repo is not allowed. if we can figure out how to set a cookie from the web form, we can allow adding multiple thin (since it allows ownership)
#TODO #blocked once tags are unified, add a tag selector (via cached net request in wmill)
def main(url: str, name: str = "", desc: str = "", repo: str = "", author: str = ""): #, lexicon: DynSelect_lexicon_select = ''):
    url, repo = clean_url(url), clean_url(repo)
    author = cast(kf, author)
    c = Collector("Submission_form", fields = [ef.NAME, ef.DESC], add_repos=True, write_meta=True)
    c.g.update_config({'GRIST_API_KEY': wmill.get_variable(path="u/autumn/grist_form_key")})
    if url:
        if not c.sites.get(url):
            entry: dict[str, Any] = {ef.URL: url}
            if name := name.strip():
                entry[ef.NAME] = name
            if desc := desc.strip():
                entry[ef.DESC] = desc
            url, _ = c.add_site(entry)
            if repo:
                c.add_repo_site(repo, url)
            if author:
                c.add_author_site(author, url)
            c.output()
            out = out_template.format(rec_id = c.sites[url]['id'])
        else:
            out = f"[entry already exists](https://atproto-tools.getgrist.com/p2SiVPSGqbi8/main-list/p/9#a1.s27.r{c.sites[url]['id']})"
    else:
        out = "no url provided"
    
    return {"markdown": out}

if __name__ == "__main__":
    print(
        main(
            "https://atproto-tools.getgrist.com/p2SiVPSGqbi8/",
            repo="https://github.com/atproto-tools/atproto-tools-scripts/",
            author="aeshna-cyanea.bsky.social",
            name="atproto tools",
            desc="open database of the atproto ecosystem"
        )
    )
