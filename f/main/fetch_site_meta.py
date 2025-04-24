import requests
from bs4 import BeautifulSoup, Tag
import re
from enum import StrEnum
from f.main.boilerplate import get_timed_logger
log = get_timed_logger(__name__)

class sm_fields(StrEnum):
    TITLE = "website_title"
    DESC = "website_desc"

def clean_title(title: str, url: str):
    if url.startswith("https://github.com"):
        title = re.sub(r"GitHub - [^/]+/[^:]+: ", "", title)
    return title

spammy_descriptions = [
    re.compile(r"development by creating an account on GitHub\.$")
]

#TODO add rel-alternate atproto links
#TODO add fetching the H1 of the README when we detect a git repo
def fetch_site_meta(url: str) -> tuple[str | None, str | None]: # thank u claude
    try:
        response = requests.get(url)
        response.raise_for_status() 
        # some of the sites i tested returned improperly decoded chars by default, for example https://publer.com
        # apparently this is intentional https://github.com/psf/requests/issues/1604
        # therefore, by executive fiat
        response.encoding = 'utf-8'
        # response.encoding = response.apparent_encoding # https://stackoverflow.com/a/58578323/592606
        soup = BeautifulSoup(response.text, 'html.parser')

        # why do people do this (name attrinstead of property as in the spec) :|
        og_title = soup.find('meta', attrs={'property': 'og:title'}) or soup.find('meta', attrs={'name': 'og:title'})
        og_description = soup.find('meta', attrs={'property': 'og:description'}) or soup.find('meta', attrs={'name': 'og:description'})

        if isinstance(og_title, Tag):
            title = str(og_title['content'])
        else:
            title_tag = soup.find('title')
            title = title_tag.string if isinstance(title_tag, Tag) else None
        title = title and clean_title(title, url)
        
        if isinstance(og_description, Tag):
            description = str(og_description['content'])
        else:
            name_desc = soup.find('meta', attrs={'name': 'description'})
            if isinstance(name_desc, Tag):
                description = str(name_desc['content'])
            else:
                description = None

        if description:
            for i in spammy_descriptions:
                if i.search(description):
                    description = None
                    break

        log.debug(f'fetched site {url}\ntitle: {title}' + (f'\ndesc:  {description}' if description else ''))

        return (title, description)

    except requests.RequestException as e:
        log.error(f"An error occurred fetching {url}:\n{e}")
        return (None, None)

def main():
    from f.main.Collector import gf, kf, ATPTGrister
    g = ATPTGrister(False)
    sites = [rec for rec in g.list_records("Sites")[1] if not rec["Computed_Name"] or not rec["Computed_Description"]]
    out_recs = []
    for site_rec in sites:
        out = {
            gf.KEY: {kf.NORMAL_URL: site_rec[kf.NORMAL_URL]},
            gf.FIELDS: {}
        }
        out_fields = out[gf.FIELDS]
        fetched_name, fetched_desc = fetch_site_meta(site_rec['url'])
        if fetched_name:
            out_fields[sm_fields.TITLE] = fetched_name
        if fetched_desc:
            out_fields[sm_fields.DESC] = fetched_desc
        if out_fields:
            out_recs.append(out)
    g.add_update_records("Sites", out_recs)
    return {"table-row-object": [rec[gf.FIELDS] | rec[gf.KEY] for rec in out_recs]}

if __name__ == "__main__":
    print(fetch_site_meta("https://verify.aviary.domains/"))
    # main()
