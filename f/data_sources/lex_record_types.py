# ruff: noqa: E402 
import asyncio
from typing import Any, Literal, Optional, TypedDict, cast
from atproto_client.exceptions import AtProtocolError
from pydantic import ValidationError
from f.main.boilerplate import get_timed_logger, dicts_diff
log = get_timed_logger(__name__)
import re
import json
from f.main.ATPTGrister import ATPTGrister
from f.main.github_client import gh_client, get_repo_files
from atproto_lexicon.parser import lexicon_parse
import dns.resolver
from atproto_client import Client as atproto_client
from atproto_client.models.base import ModelBase as atp_model
from at_url_converter import at_url, url_obj
import at_url_converter.atproto_utils as atproto_utils
from httpx import Client as httpx_client
http_client = httpx_client()
at_client = atproto_client()

def resolve_nsid(nsid: str) -> Optional[at_url]:
    '''
    resolves nsid to its repo

    Args:
        nsid (str): the nsid to look up

    Returns:
        at_url: `at://{did}/com.atproto.lexicon.schema/{nsid}`
    '''    
    split = nsid.split(".")[::-1]
    split[0] = "_lexicon"
    try:
        if (r := dns.resolver.resolve( ".".join(split), "TXT")) and (rrset := r.rrset):
            if len(rrset) > 1:
                log.error(f"rrset is too long, should be length 1:\n{rrset}")
        else:
            return None
        did = str(rrset[0]).strip("\"").removeprefix("did=")
        return at_url(did, "com.atproto.lexicon.schema", nsid)
    except Exception as e:
        log.error(f"error when resolving nsid {nsid}:\n{e}")

nsid_regex = re.compile(r"^(?P<domain_authority>[a-zA-Z](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?(?:\.[a-zA-Z](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?)+)\.(?P<name>(?:[a-zA-Z](?:[a-zA-Z0-9]{0,62})?)+)$")

github_url_regex = re.compile( #TIL about implicit string concatenation
    r'github\.com/'
    r'(?P<owner>[^/]+)/'
    r'(?P<repo>[^/]+)/'
    r'(?:tree|blob)/'
    r'(?P<branch>[^/]+)/?'
    r'(?P<path>.*)?/?'
)


github_template = "https://github.com/{0}/{1}/tree/{2}/{3}"

log.debug('finished imports')

unwanted_domains = [
    'chat.bsky'
]

class lex_check_result(TypedDict):
    nsid: str
    error: Optional[str]
    at_url: Optional[str]
    matched: Optional[Literal["yes", "no"]]
    self_centered: bool

class lex_record(lex_check_result, total=False):
    web_url: str
    Lexicons: str
    name: str

def rec_value(rec: atp_model) -> dict[str, Any]:
    """gets the record value. strips extra keys inserted into the lexicon rec by the pds or pydantic"""
    return {k: v for k, v in rec.model_dump()["value"].items() if k not in ("$type", "py_type")}

def check_lex(input: str | dict)-> lex_check_result | None:
    if isinstance(input, str):
        input = cast(dict, json.loads(input))
    try:
        parse_error = None
        lexicon_parse(input)
    except ValidationError as e:
        parse_error = json.dumps(e.errors())
        log.error(e)

    # the validation code isn't completely correct so for now we just save the error and do our own more lenient check afterward
    if (main_def := input['defs'].get('main', {})).get('type') == 'record':
        if nsid_match := nsid_regex.match(input['id']):
            nsid: str = input["id"]
            domain, name = nsid_match.groups()
            log.debug(f'got record for lex {name} of {domain}')
            if (nsid_url := resolve_nsid(input['id'])):
                if input['id'] != nsid_url.rkey:
                    log.warning(f"record's rkey {input['id']} did not match canonical rkey {nsid_url.rkey}")
                try:
                    resolved_record = rec_value(at_client.com.atproto.repo.get_record({
                        "repo": nsid_url.repo,
                        "collection": "com.atproto.lexicon.schema",
                        "rkey": input['id']
                    }))
                    if diff := dicts_diff(resolved_record, input):
                        log.info(f"diff of repo's and resolved {nsid} lexicon:\n{diff}")
                        matched = "no"
                    else:
                        matched = "yes"
                except AtProtocolError as e:
                    log.info(f"could not fetch record for {nsid}:\n{e}")
                    matched = None
            else:
                matched = None
            return {
                "nsid": nsid,
                "error": parse_error,
                "at_url": str(nsid_url) if nsid_url else None,
                "matched": matched,
                "self_centered": main_def.get("key") == "literal:self"
            }
        else:
            log.error(f"found lex {input['id']} but it's not valid!")
            return None
    return None


type forge = Literal["github", "gitea", "tangled", "pds"]

async def find_lexicons(url: str, forge_type: forge) -> dict[str, lex_record]:
    out: dict[str, lex_record] = {}
    log.debug(f"searching for lexicons in {url}, forge type {forge_type}")
    if forge_type == "github":
        lex_search_template = 'https://api.github.com/search/code?q=repo:{owner}/{repo} "\\"type\\": \\"record\\"" {search_path} extension:json&per_page=100'
        if not (repo_info := github_url_regex.search(url)):
                raise ValueError(f"url {url} does not match regex {github_url_regex}")
        owner, repo_name, branch, search_path = repo_info.groups()
        
        if search_path:
            search_path = 'path:' + search_path
            if not search_path.endswith('/'): # apparently github accepts missing trailing / and then just gives different results
                search_path += '/'
        paths = []
        query = lex_search_template.format(owner=owner, repo=repo_name, search_path=search_path)
        while query:
            log.debug(f'requesting url\n{query}')
            r = gh_client.get(query)
            data = r.json()
            paths += [item['path'] for item in data ['items']]
            query = r.links.get('next', {}).get('url')
        for path, file in get_repo_files(url, paths).items():
            if (lex_entry := check_lex(file)):
                out[lex_entry["nsid"]] = {
                    "web_url": github_template.format(owner, repo_name, branch, path),
                    **lex_entry
                }
    elif forge_type == "gitea": #TODO gitea (if we see a gitea lex repo) https://gitea.com/api/swagger#/repository/repoGetContents
        raise NotImplementedError(f"{forge_type} repos not implemented")
    elif forge_type == "tangled":
        u = url_obj(url)
        match u:
            case url_obj(path=[handle, repo_name]):
                base_path = ""
                branch = None
            case url_obj(path=[handle, repo_name, "tree", branch, *path]):
                base_path = "/".join(path)
            case _:
                raise ValueError("unrecognized tangled url structure")
        metadata_repo = at_url(handle, "sh.tangled.repo")
        did = await metadata_repo.get_did()
        if not (matched_rec := await atproto_utils.find_record(metadata_repo, {"name": repo_name})):
            raise StopIteration(f"repo with name {repo_name} not found in {metadata_repo}")
        knot = matched_rec["value"]["knot"]
        if not branch:
            q = f"https://{knot}/{did}/{repo_name}"
            log.debug(f"querying getting default branch name from repo metadata at {q}")
            r = http_client.get(q)
            data = r.json()
            branch = data["ref"]
            url = url.rstrip("/") + "/tree/" + branch

        query_template = "https://{knot}/{did}/{repo_name}/tree/{branch}"
        api_query = query_template.format(knot=knot, did=did, repo_name=repo_name, branch=branch)
        def get_tangled_dir(base_query: str, path: str = ""):
            api_query = base_query + "/" + path
            log.debug(f"querying {api_query}")
            dir_r = http_client.get(api_query)
            data = dir_r.json()
            for entry in data["files"]:
                if entry["is_file"]:
                    file_query = "/".join((base_query.replace("/tree/", "/blob/", 1), path, entry["name"]))
                    log.debug(f"getting file {file_query}")
                    file_r = http_client.get(file_query)
                    file_data = file_r.json()
                    contents = file_data["contents"]
                    if '"type": "record"' in contents:
                        if check_result := check_lex(contents):
                            nsid: str = check_result["nsid"]
                            if nsid not in out:
                                out[nsid] = {
                                    "web_url": url.replace("/tree/", "/blob/", 1).removesuffix(base_path) + file_data["path"],
                                    **check_result
                                }
                            else:
                                raise ValueError(f"found duplicate entry at path {base_query + file_data['path']} for nsid {nsid}")
                else:
                    get_tangled_dir(base_query, path + "/" + entry["name"])
        get_tangled_dir(api_query, base_path)

    elif forge_type == "pds":
        async for rec in atproto_utils.list_records(at_url(url, "com.atproto.lexicon.schema")):
            if lex_entry := check_lex(rec_value(rec)):
                out[lex_entry["nsid"]] = {
                    "web_url": "https://pdsls.dev/" + rec.uri,
                    **lex_entry
                }

    return out

async def _main():
    g = ATPTGrister(False)
    #blocked this is a dirty hack because we have no way atm to tell current from outdated lexicons so we put the more 'authoritative' (bsky.app) repo first
    seen = {}
    diffs = {}
    lex_domains: dict[str, dict[str, Any]] = {rec['domain']: rec for rec in g.list_records("Lexicons", sort='manualSort')[1]}
    log.debug('fetched records')
    nsids: dict[str, dict[str, Any]] = {
        rec["nsid"]: rec
        for rec in g.list_records("Tags_lexicon_record_types", sort="manualSort")[1]
    }
    
    for domain, domain_rec in lex_domains.items():
        forge_type = domain_rec.get("forge_type")
        url = domain_rec.get("source")
        if not forge_type or not url:
            continue

        for found_nsid, entry in (await find_lexicons(url, forge_type)).items():
            # sometimes people put other people's lexicons in their domains. we want to make sure they get filed properly (by domain ownership)
            split_found_nsid = found_nsid.split(".")
            split_found_domain = split_found_nsid[:2]


            # need to search like this bc some domains in lex_domains are three segments long, e.g. fyi.unravel.frontpage
            found_domain = ".".join(split_found_domain)
            for i in split_found_nsid[2:]:
                if match := lex_domains.get(found_domain):
                    canon_source = match.get("source")
                    if url == canon_source:
                        entry["Lexicons"] = match["id"]
                    elif canon_source:
                        log.info(f"found non-canonical entry for {found_nsid} in {url}")
                        entry = None
                    break
                else:
                    found_domain += "." + i
            else:
                found_domain = ".".join(split_found_domain)
            if not entry:
                continue
            
            old_entry = nsids.get(found_nsid) or {}
            if old_entry.get("name_override"):
                entry["name"] = old_entry["name"]
            if diff := dicts_diff(old_entry, entry):
                diffs[found_nsid] = diff
            seen[found_nsid] = entry

    if unseen := nsids.keys() - seen.keys():
        log.warning(f"did not see lexicons (deprecated?):\n{unseen}")

    if diffs:
        out = g.format_records(diffs, "nsid")
        g.add_update_records("Tags_lexicon_record_types", out)
        return diffs

def main():
    return asyncio.run(_main())

if __name__ == "__main__":
    import pprint
    pprint.pp(main())
