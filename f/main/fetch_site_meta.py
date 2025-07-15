import asyncio
from copy import deepcopy
from datetime import UTC, datetime
import os
from typing import Any, Literal, TypedDict, cast
import httpx
from bs4 import BeautifulSoup, Tag, NavigableString
import re
from f.main.boilerplate import batched, dicts_diff, dict_filter_falsy, truthy_only_dict
from f.main.ATPTGrister import ATPTGrister, check_stale, gf, kf, names_col, site_source_name
from f.main.boilerplate import get_timed_logger
log = get_timed_logger(__name__)


FETCH_SITE_TIMEOUT = int(os.environ.get("FETCH_SITE_TIMEOUT", 20))
CONCURRENT_FETCH_SITE_LIMIT = int(os.environ.get("CONCURRENT_CONNECTION_LIMIT", 8))
c = httpx.AsyncClient(follow_redirects=True, timeout=FETCH_SITE_TIMEOUT, trust_env=True)

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
    last_polled: str
    normalized_url: str


sem = asyncio.Semaphore(CONCURRENT_FETCH_SITE_LIMIT)
#TODO add rel-alternate atproto links
async def fetch_site_meta(url: str) -> site_info:
    async with sem:
        try:
            out: site_info = {}
            response = await c.get(url)
            response.raise_for_status()
            # some of the sites i tested returned improperly decoded chars by default, for example https://publer.com
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

        except httpx.HTTPStatusError as e:
            base_msg = f"{e.response.status_code} {e.response.reason_phrase}"
            msg = f"error fetching {url}:\n{base_msg}"
            # if e.response.text:
            #     msg += "\n" + e.response.text
            log.error(msg)
            return {"error": base_msg}
        except httpx.HTTPError as e:
            e_with_type = ": ".join(i for i in [e.__class__.__name__, str(e)] if i)
            msg = f"error fetching {url}:\n{e_with_type}"
            log.error(msg)
            return {"error": e_with_type}

async def check_and_fetch(rec: dict[str, Any], threshold: float = 0) -> dict[str, site_info] | None:
    names: dict[str, site_info] = rec[names_col]
    if check_stale(names.get(site_source_name, {}).get("last_polled"), threshold):
        new_meta = await fetch_site_meta(rec["url"])
        new_meta["last_polled"] = datetime.now(UTC).isoformat(timespec="minutes")
        new_meta["normalized_url"] = rec[kf.NORMAL_URL]
        return deepcopy(names) | {site_source_name: new_meta}

excluded_regexes = {
    re.compile(r"https://github\.com/[^/]+/[^/]+/?$")
}

def url_not_exluded(rec):
    url = rec[kf.NORMAL_URL]
    if not any(i.search(url) for i in excluded_regexes):
        return url

async def _main():
    g = ATPTGrister(False)
    recs = {url: rec for rec in g.list_records("Sites")[1] if (url := url_not_exluded(rec))}
    raw_metas = {
        url: nm
        for meta in asyncio.as_completed([
            (check_and_fetch(rec)) for rec in recs.values()
        ])
        if (nm := await meta)
        and (diff :=
            dicts_diff(
                recs[(url := nm[site_source_name].pop(kf.NORMAL_URL))][names_col][site_source_name], # yeag..
                nm[site_source_name],
                "last_polled",
            )
        )
    }
    new_names = [{
            gf.KEY: {kf.NORMAL_URL: url},
            gf.FIELDS: {names_col: nm},
        } for url, nm in raw_metas.items()]
    if new_names:
        for batch in batched(deepcopy(new_names), 100):
            g.add_update_records("Sites", batch)
        return {"table-row-object": [rec[gf.FIELDS][names_col][site_source_name] | rec[gf.KEY] for rec in new_names]}

def main():
    return asyncio.run(_main())

if __name__ == "__main__":
    print(asyncio.run(_main()))
