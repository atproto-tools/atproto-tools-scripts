import requests
from bs4 import BeautifulSoup, Tag
import re

def clean_title(title: str, url: str):
    if url.startswith("https://github.com"):
        title = re.sub(r"GitHub - [^/]+/[^:]+: ", "", title)
    return title

#TODO add fetching the H1 of the README when we detect a git repo
def fetch_site_meta(url: str) -> tuple[str | None, str | None]: # thank u claude
    try:
        response = requests.get(url)
        response.raise_for_status() 
        # some of the sites i tested returned improperlydecoded chars by default, for example https://publer.com
        # apparently this is intentional https://github.com/psf/requests/issues/1604
        response.encoding = 'utf-8'
        # response.encoding = response.apparent_encoding # https://stackoverflow.com/a/58578323/592606
        soup = BeautifulSoup(response.text, 'html.parser')

        # Extract Open Graph title and description
        og_title = soup.find('meta', attrs={'property': 'og:title'})
        og_description = soup.find('meta', attrs={'property': 'og:description'})

        if isinstance(og_title, Tag) and isinstance(og_description, Tag):
            title = str(og_title['content'])
            description = str(og_description['content'])
            title = clean_title(title, url)
            return (title, description)
        else:
            title_tag = soup.find('title')
            title = title_tag.string if isinstance(title_tag, Tag) else None                
            return (title, None)

    except requests.RequestException as e:
        print(f"An error occurred: {e}")
        return (None, None)

def main():
    from f.main.Collector import gf, ef, kf, ATPTGrister
    g = ATPTGrister(False)
    sites = g.list_records("Sites", {"Computed_Name": [None, ""]})[1]
    out_recs = []
    for site_rec in sites:
        out = {
            gf.KEY: {kf.NORMAL_URL: site_rec[kf.NORMAL_URL]},
            gf.FIELDS: {}
        }
        out_fields = out[gf.FIELDS]
        fetched_name, fetched_desc = fetch_site_meta(site_rec['url'])
        if fetched_name and not site_rec["Computed_Name"]:
            out_fields["website_title"] = fetched_name
        if fetched_desc and not site_rec["Computed_Description"]:
            out_fields["website_desc"] = fetched_desc
        if out_fields:
            out_recs.append(out)
    g.add_update_records("Sites", out_recs)
    return {"table-row-object": [rec[gf.FIELDS] | rec[gf.KEY] for rec in out_recs]}

if __name__ == "__main__":
    main()
