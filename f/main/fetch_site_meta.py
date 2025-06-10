from copy import deepcopy
from datetime import UTC, datetime
from typing import Any, Literal, TypedDict, cast
import requests
from bs4 import BeautifulSoup, Tag, NavigableString
import re
from f.main.boilerplate import dicts_diff, dict_filter_falsy, truthy_only_dict
from f.main.ATPTGrister import ATPTGrister, check_stale, gf, kf, names_col, site_source_name
from f.main.boilerplate import get_timed_logger
log = get_timed_logger(__name__)

def clean_title(title: str | None, url: str):
    if not title:
        return ""
    if url.startswith("https://github.com"):
        title = re.sub(r"GitHub - [^/]+/[^:]+: ", "", title)
    return title

def clean_description(desc: str | None, url: str):
    if not desc:
        return ""
    if re.search(r"development by creating an account on GitHub\.$", desc):
        return ""
    return desc

class site_info(TypedDict, total=False):
    title: str
    desc: str
    error: str

#TODO add rel-alternate atproto links
#TODO add fetching the H1 of the README when we detect a git repo
def fetch_site_meta(url: str) -> site_info:
    try:
        out: site_info = {}
        response = requests.get(url)
        if not response.ok:
            out["error"] = response.reason
            return out
        response.raise_for_status() 
        # some of the sites i tested returned improperly decoded chars by default, for example https://publer.com
        # apparently this is intentional https://github.com/psf/requests/issues/1604
        # therefore, by executive fiat:
        response.encoding = 'utf-8'
        # response.encoding = response.apparent_encoding # https://stackoverflow.com/a/58578323/592606
        soup = BeautifulSoup(response.text, 'html.parser')

        og_title_tag = (
            soup.find('meta', attrs={'property': 'og:title'}) or
            soup.find('meta', attrs={'name': 'og:title'})
        )

        if og_title_tag:
            assert not isinstance(og_title_tag, NavigableString)
            out["title"] = clean_title(str(og_title_tag['content']), url)
        elif title_tag := soup.find('title'):
            assert not isinstance(title_tag, NavigableString)
            out["title"] = clean_title(title_tag.string, url)

        og_description = (
            soup.find("meta", attrs={"property": "og:description"}) or
            soup.find("meta", attrs={"name": "og:description"}) or
            soup.find("meta", attrs={"name": "description"})
        )

        if og_description:
            assert not isinstance(og_description, NavigableString)
            out["desc"] = clean_description(og_description.attrs.get("content"), url)
        elif og_description:
            log.warning(f"description was not a tag: {og_description}")

        out = cast(site_info, dict_filter_falsy(cast(dict, out)))
        log.debug(f"fetched site {url} : {out}")
        return out

    except requests.RequestException as e:
        log.error(f"error fetching {url}:\n{e}")
        return {"error": str(e.strerror)}

def check_and_fetch(rec: dict[str, Any], threshold: float = 3.2) -> dict[str, site_info] | None:
    names = rec[names_col]
    if check_stale(names[site_source_name].get("last_polled"), threshold):
        return deepcopy(names) | {
            site_source_name: {
                "last_polled": datetime.now(UTC).isoformat(timespec="minutes"),
                **fetch_site_meta(rec["url"]),
            }
        }


def main():
    g = ATPTGrister(False)
    new_names = [
        {
            gf.KEY: {kf.NORMAL_URL: site_rec[kf.NORMAL_URL]},
            gf.FIELDS: {names_col: new_meta},
        }
        for site_rec in g.list_records("Sites")[1]
        if (new_meta := check_and_fetch(site_rec))
    ]
    if new_names:
        g.add_update_records("Sites", deepcopy(new_names))
        return {"table-row-object": [rec[gf.FIELDS][names_col][site_source_name] | rec[gf.KEY] for rec in new_names]}


if __name__ == "__main__":
    # fetch_site_meta("https://bsky.app")
    print(main())
