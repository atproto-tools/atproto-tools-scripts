import wmill
from f.main.Collector import Collector, t, kf, ef, normalize

from datetime import datetime
start = datetime.now()
def simple_log(msg: str):
    print(datetime.now() - start, msg)

#TODO other sanitization? idk what the risks are
def clean_url(url: str) -> kf:
    return normalize(url.strip())

def filter_falsy(d: dict):
    return {k: v for k,v in d.items() if v} # gotta 'cast to null' to keep blank/empty values uniform in all tables

out_template = """
[view your entry here](https://atproto-tools.getgrist.com/p2SiVPSGqbi8/main-list/p/9#a1.s27.r{rec_id}).
this link includes a unique identifier- you (or anyone you share it with) can use the it to edit any entries you've created.
"""
submissions_field = "submissions"
#TODO for now, only one URL per submission, and it must be a new url. if we can figure out how to set a cookie from the web form, we can allow edits (since it allows ownership)
#TODO #blocked once tags are unified, add a tag selector (via cached net request in wmill)
def main(url: str | None, name: str | None = None, desc: str | None = None, repo: str | None = None, author: str | None = None):
    c = Collector("Submission_form", fields = [ef.NAME, ef.DESC, submissions_field], add_repos=True, write_meta=True, fetch_authors=True)
    simple_log("collector init")
    c.g.update_config({'GRIST_API_KEY': wmill.get_variable(path="u/autumn/grist_form_key")})
    simple_log("updated config")
    url, repo = url and clean_url(url), repo and clean_url(repo)
    author = author and c.g.resolve_author(author)
    submissions = 0
    if url:
        if not c.sites.get(url):
            new_record = filter_falsy({
                ef.URL: url,
                submissions_field: 1,
                ef.NAME: name,
                ef.DESC: desc,
                ef.REPO: repo,
                ef.AUTHOR: author,
            })
        else:
            old_record: dict = c.sites[url]
            submissions = (old_s := old_record.get(c._prefix + submissions_field)) and old_s + 1 or 1
            new_record = {
                ef.URL: url,
                #TODO add in column info as a possible field in the collector constructor fields dict param
                submissions_field: submissions,
                ef.NAME: old_record.get("Computed_Name") or name,
                ef.DESC: old_record.get("Computed_Description") or desc,
            }
            if repo and not old_record.get(t.REPOS):
                new_record[ef.REPO] = repo
            if author and not old_record.get(t.AUTHORS):
                new_record[ef.AUTHOR] = author
        c.add_site(new_record)
        simple_log("added")
        c.output()
        simple_log("wrote")
        out = out_template.format(rec_id = c.sites[url]['id'])
        if submissions:
            out += f"\nthis url has already been submitted {submissions} times"
    else:
        out = "no url provided"
    return {"markdown": out}

if __name__ == "__main__":
    print(
        main(
            url="https://atproto-tools.getgrist.com/p2SiVPSGqbi8/",
            repo="https://github.com/atproto-tools/atproto-tools-scripts/",
            author="aeshna-cyanea.bsky.social",
            # name="atproto tools",
            # desc="open database of the atproto ecosystem"
        ),
        main(
            url="https://atproto-tools.getgrist.com/p2SiVPSGqbi8/",
            repo="https://github.com/atproto-tools/atproto-tools-scripts/",
            author="aeshna-cyanea.bsky.social",
            name="atproto tools",
            desc="custom description - overly verbose and longer than the one from the github repo"
        ),
        main(
            url="https://atproto-tools.getgrist.com/p2SiVPSGqbi8/",
            desc="even more custom description - overly verbose and longer than the one from the github repo"
        ),
    )
