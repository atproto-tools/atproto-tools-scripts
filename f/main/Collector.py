from enum import StrEnum
from itertools import zip_longest
import re
from typing import Iterable, Any, cast
from pprint import pformat
from f.main.ATPTGrister import ATPTGrister, check_stale, mf, t, gf, kf, make_timestamp, normalize
import feedparser

class ef(StrEnum):  # would have used an enum but it has "name" attr reserved
    """
    entry field names that have special handling, taken as input keys in FieldCollector.add_site()\n
    values- name, desc, tags, rating, url, repo, author.
    first 4 are source-specific and prefixed with source_name in the output
    """
    NAME = "name"
    DESC = "description"
    TAGS = "tags"
    RATING = "rating"
    # the last 3 are source-agnostic
    URL = "url"
    REPO = "repo"
    AUTHOR = "author" # must be an atprotoef = EntryFields() did or handle

class tf(StrEnum):
    """names of table fields"""
    URL = "url" # if urls differ, we override the old one. but we find what to replace by the normalized form
    HOME = "homepageUrl"
    ALT_URLS = "alt_urls"

#TODO implement lexicons as a default field

record = dict[gf, dict[str, Any]]

class cmk(StrEnum):
    source_name = "source_name"
    fields= "fields"

def add_one_missing(dest: list[str], item: str | None):
    # dest = dest.copy()
    if not item:
        return dest
    if item not in dest:
        dest.append(item)
    return dest

def add_missing(dest: list[str], source: Iterable[str] | None):
    # dest = dest.copy()
    if not source:
        return dest
    dest.extend(i for i in source if i not in dest)
    return dest

# TODO add other forges besides github
def check_repo(normal_repo_url: str) -> kf | None:
    # check if a repo link is to a known forge (only github atm)"""
    repo_match = re.search(r"(https://github\.com/[^/]*/[^/]*/?)$", normal_repo_url)
    return repo_match[1] if repo_match else None #type: ignore


class Collector:
    def __init__(self, source_name: str, fields: Iterable[ef | str] = [], tags: Iterable[str] | dict[str, dict[str, Any]] = [], add_repos: bool = False, fetch_authors = False, write_meta = True):
        """
        Args:
            source_name (str): a source_name from the data sources table
            fields (list[str], optional): field name must be valid python variable, no spaces. The fields for name, description, tags, rating are processed/aggregated, use the `Collector.ef` enum for them. Fields starting with _ are hidden in the intermediary output. All fields are prefixed with the source_name when assigned.
            tags (Iterable[str] | dict[str, dict[str, Any]]): a list of tags or a dict of tags with fields (tag descriptions etc)
            add_repo (bool, optional): whether to check for repo link when adding entries. Defaults to False.
            authors (boo, optional): whether to prefetch authors. Defaults to False.
        """
        print("starting collector for " + source_name)
        self.g = ATPTGrister(fetch_authors)
        self._source_name = source_name
        self._prefix = source_name + "_"
        sources = self.g.list_records(t.SOURCES)[1]
        source_record = next(i for i in sources if i["source_name"] == source_name)
        self.last_update_timestamp: int = source_record.get("last_update_timestamp") or 0
        self.current_update_timestamp: int = 0
        if source_feed := source_record.get("feed"):
            #TODO fix type annotations in feedparser upstream
            self.check_update_timestamp(feedparser.parse(source_feed).feed.updated) #type: ignore
            pass
        self._source_id = source_record["id"]
        self._source_label = source_record["label"]
        self._fields: list[str] = [self._prefix + i for i in fields]
        self._df = {i: self._prefix + i for i in [ef.NAME, ef.DESC, ef.TAGS, ef.RATING]}
        self.sites_records: dict[kf, record] = {}
        self.authors_records: dict[kf, record] = {}
        self.repos_records: dict[kf, record] = {}
        #TODO rewrite these to narrower sql queries to only get existing entries from our source and only grab relevant fields. would also need to move this code to after processing all the urls to the source
        #TODO maybe also make the initial fetches concurrent with async
        self.sites = {}
        self._alt_urls: dict[kf, kf] = {}
        for rec in self.g.list_records(t.SITES)[1]:
            normal_url = rec[kf.NORMAL_URL]
            self.sites[normal_url] = rec
            if rec_alt_urls := rec.get(tf.ALT_URLS):
                self._alt_urls |= {alt: normal_url for alt in rec_alt_urls.splitlines()}
        # max allowed size is 1mb. truncated by default, change MAXSAVEDRESP to MAXSAVEDRESP = 1000000 in grister's api.py
        print(f"Sites is {len(self.g.resp_content) / 1000000 } of max request size")
        self.repos = {}
        self._add_repos_opt = add_repos
        for rec in self.g.list_records(t.REPOS)[1]:
            normal_url = rec[kf.NORMAL_URL]
            self.repos[normal_url] = rec
            if rec_alt_urls := rec.get(tf.ALT_URLS):
                self._alt_urls |= {alt: normal_url for alt in rec_alt_urls.splitlines()}
        self.authors = self.g.authors_lookup

        self._tags_set: set[str] = set()
        """all the tags seen during the main pass. for use with self.make_tag_key"""
        self._tags_key: dict[str, str] = {}
        self._og_tag_field = "original tags"  # not a real field name! internal/output purposes only. but idk where else to put it.
        """stores tag references after generating them from grist"""
        if tags or (ef.TAGS in fields):
            self._tags_applied = False
            self._fields[self._fields.index(self._df[ef.TAGS])] = self._og_tag_field #display original tags first
            self._fields.append(self._df[ef.TAGS])
        if tags:
            self.make_tag_key(tags)
        
        self.display_fields: list[str] = [
            i for i in self._fields
            if not i.startswith(self._prefix + "_") or i not in t.__members__.values()
        ] + [ef.URL]
        """
        fields to include in output table (prefixed with source name). passed into self.output() by default .\n
        includes url as the last element (though it is a key and not a field)
        """
        self.write_meta = write_meta
        print("finished setup")

    def check_update_timestamp(self, timestamp: str | int | float):
        self.current_update_timestamp = make_timestamp(timestamp)
        if self.last_update_timestamp == self.current_update_timestamp:
            #TODO there's gotta be a better way to exit out of a windmill script early
            raise StopIteration(f"No updates in {self._source_name} since last run!")

    def make_tag_key(self, tags: Iterable[str] | dict[str, dict[str, Any]]) -> dict[str, str]:
        """
        Converts literal tags into references for nicer presentation.\n
        Should be called before the main pass if tags are listed upfront, or after if not.

        Args:
            tags (Collection[str] | dict[str, dict[str, Any]] | None): the set of tags with their fields. Defaults to self.tags

        Returns:
            dict[str, str]: {original_tag: tag_ref}
        """        
        g = self.g
        assert not isinstance(tags, str) # sometimes i forget to wrap them in a list and strings fall under iterable[str] according to the type checker D:

        if isinstance(tags, dict):
            #flatten the tag fields to get the complete set and put it into columns
            tag_col_ids = {"Tag", *(field for fields in tags.values() for field in fields)}
            tag_cols = [{"id": col, gf.FIELDS: {"label": col}} for col in tag_col_ids]
            tags_records = [{gf.KEY: {"Tag": tag}, gf.FIELDS: fields} for tag, fields in tags.items()]
        else:
            tags_records = [{gf.KEY: {"Tag": tag}} for tag in tags]
            tag_cols = [{"id": "Tag", gf.FIELDS: {"label": "Tag"}}]

        if self._df[ef.TAGS] not in (i["id"] for i in g.list_tables()[1]):
            g.add_tables([{"id": self._df[ef.TAGS], "columns": tag_cols}])
        else:
            g.add_update_cols(self._df[ef.TAGS], tag_cols, noupdate=True)

        g.add_update_records(self._df[ef.TAGS], tags_records)
        new_tags = g.list_records(self._df[ef.TAGS])[1]
        self._tags_key = {x["Tag"]: x["id"] for x in new_tags}
        return self._tags_key
    
    def apply_tags_key(self):
        """returns the original tags for use in further output after writing"""
        og_tags: dict[kf, list[str]] = {}
        tags_field = self._df[ef.TAGS]
        for url, entry in self.sites_records.items():
            if (entry_fields := entry[gf.FIELDS]) and entry_fields.get(self._og_tag_field):
                entry_fields[tags_field] = ["L", *(self._tags_key[tag] for tag in entry_fields[self._og_tag_field])]
                og_tags[url] = entry_fields.pop(self._og_tag_field)
        self._tags_applied = True
        return og_tags

    def _p(self, key: str, new: Any = None, old: Any = None) -> None:
        if old and new:
            print(f"\nDuplicate for {key}:\n{pformat(old)}\n->\n{pformat(new)}")
        else:
            print(f"\nDuplicate for {key}")

    def add_source(self, table: dict[kf, Any], key: kf):
        return add_one_missing(table.get(key, {}).get(t.SOURCES) or ["L"], self._source_id)

    def add_repo_site(self, repo_url: str, normalized_site: kf) -> tuple[str, kf]:
        normal_repo_url = normalize(repo_url)
        normal_repo_url = self._alt_urls.get(normal_repo_url, normal_repo_url)
        site = normalized_site
        if normalized_site == normal_repo_url:
            if (matched_repo := self.repos.get(normal_repo_url, {})).get("normalized_homepage"):
            # if we see a site link to a repo that has a homepage already specified, link to that instead
            # this means we have to manually manage adding and maintaining homepages
            # needed because we may have "instances of a service" pointing back to its repo, and also a separate homepage for the service that also points to the repo

                site, normalized_site = matched_repo[tf.HOME], matched_repo[kf.NORMAL_HOME]
        if repo_record := self.repos_records.get(normal_repo_url):
            add_one_missing(repo_record[gf.FIELDS][t.SITES], normalized_site)
        else:
            self.repos_records[normal_repo_url] = {
                gf.KEY: {kf.NORMAL_URL: normal_repo_url},
                gf.FIELDS: {
                    t.SITES: [normalized_site], #converted to proper ref after writing and re-fetching sites
                    t.SOURCES: self.add_source(self.repos, normal_repo_url),
                    tf.URL: repo_url
                }
            }
            
        return site, normalized_site

    def add_author_site(self, author: str, normal_url: kf) -> kf | None:
        did = self.g.resolve_author(author)
        if not did:
            print(f"^ author of {normal_url}")
            return
        
        if author_record := self.authors_records.get(did):
            add_one_missing(author_record[gf.FIELDS][t.SITES], normal_url)
        else:
            rec = {gf.KEY: {kf.DID: did}, gf.FIELDS: {
                t.SITES: [normal_url],
                t.SOURCES: self.add_source(self.authors, did),
            }}
            if handle := self.authors[did].get(kf.HANDLE):
                rec[gf.FIELDS][kf.HANDLE] = handle
            self.authors_records[did] = rec
        return did

    def add_site(self, entry: dict | str):
        """
        Args:
            entry (str | dict[str, Any]): has a few special keys it can take: `["name", "description", "tags", "rating"]` are handled and aggregated in the main table. `"author"` and `"repo"` also reserved and put into separate tables.
        """
        out: record = {gf.FIELDS: {}, gf.KEY: {}}
        out_fields = out[gf.FIELDS]
        if isinstance(entry, dict):
            og_url: str = entry.pop(ef.URL)
            normalized_site = normalize(og_url)
            if redirect := self._alt_urls.get(normalized_site):
                og_url = normalized_site = redirect
            out_fields[ef.URL] = og_url
            if repo := entry.pop(ef.REPO, None):
                out_fields[ef.URL], normalized_site = self.add_repo_site(repo, normalized_site)
            for field, value in entry.items():
                match field:
                    case ef.TAGS:
                        if self._tags_key:
                            out_fields[self._og_tag_field] = value
                            out_fields[self._df[ef.TAGS]] = ["L", *(self._tags_key[tag] for tag in value)]
                        else:
                            self._tags_set |= set(value)
                            out_fields[self._og_tag_field] = value
                    case ef.AUTHOR:
                        self.add_author_site(value, normalized_site)
                    case _:
                        out_fields[self._prefix + field] = value
        else:
            entry = cast(kf, entry)
            out_fields[ef.URL] = self._alt_urls.get(entry, entry)
            normalized_site = normalize(entry)

        
        if self._add_repos_opt and (repo := check_repo(normalized_site)):
            out_fields[ef.URL], normalized_site = self.add_repo_site(repo, repo)
            
        out[gf.KEY][kf.NORMAL_URL] = normalized_site

        if old_fields := self.sites_records.get(normalized_site, {}).get(gf.FIELDS):
            self._p(normalized_site, out_fields, old_fields)
            if old_fields[ef.URL] != out_fields[ef.URL]:
                print(f"matched urls\n'{old_fields[ef.URL]}'\n'{out_fields[ef.URL]}' in sites")
            if old_tags := old_fields.get(self._og_tag_field):
                out_fields[self._og_tag_field].extend(i for i in old_tags if i not in out_fields[self._og_tag_field])
            if old_rating := old_fields.get(self._df[ef.RATING]):
                out_fields[self._df[ef.RATING]] = max(
                    out_fields.get(self._df[ef.RATING], 0),
                    old_rating
                )
            old_fields |= out_fields
        else:
            out_fields[t.SOURCES] = self.add_source(self.sites, normalized_site)
            self.sites_records[normalized_site] = out
        return normalized_site, out

    def _write_record_table(self, table_id: t):
        dicts = {t.SITES: (self.sites, self.sites_records), t.REPOS: (self.repos, self.repos_records), t.AUTHORS: (self.authors, self.authors_records)}
        entries, records = dicts[table_id]
        if not records:
            return []
        if table_id != t.SITES:
            for key, record in records.items():
                dest = entries.get(key, {}).get(t.SITES) or ["L"]
                source = [self.sites[i]["id"] for i in record[gf.FIELDS][t.SITES]]
                if any(a != b for a, b in zip_longest(source, dest)):
                # if source and source != dest:
                    record[gf.FIELDS][t.SITES] = add_missing(dest, source)
        current_entries = {i for i,v in entries.items() if self._source_id in (v.get(t.SOURCES) or [])}
        if deleted_entries := current_entries - records.keys():
            print(f"{table_id} not present in live {self._source_label}:\n{deleted_entries}")
        out = list(records.values())
        self.g.add_update_records(table_id, out)
        return [rec[gf.KEY] | rec[gf.FIELDS] for rec in out]

    def output(self, display_fields: list[str] = [], dry_run: bool = False) -> dict[str, list[Any]]:
        """write to the grist db and make a pretty json object for output into windmill.
        Args:
            display_fields (list[str], optional): fields to display in output. values can be "url" and the keys of self._field_key. Defaults the order fields were given in the constructor, with tags and url added in last. Fields starting with _ are hidden by default.

        Returns:
            dict[str, list[Any]]: [description of output format](https://www.windmill.dev/docs/core_concepts/rich_display_rendering#render-all)
        """
        self.display_fields = display_fields or self.display_fields
        
        if self._tags_set or self._tags_key:
            og_tags = {}
            if not self._tags_key:
                self.make_tag_key(self._tags_set)
            if not self._tags_applied:
                og_tags = self.apply_tags_key()
            else:
                for url, entry in self.sites_records.items():
                    if entry_og_tags := entry[gf.FIELDS].pop(self._og_tag_field, None):
                        og_tags[url] = entry_og_tags
            sites_output = [
                self.display_fields,
                *(
                    v[gf.FIELDS] | {self._og_tag_field: og_tags[k], ef.URL: k}
                    for k, v in self.sites_records.items()
                ),
            ]
        else:
            sites_output = [
                self.display_fields,
                *(
                    v[gf.FIELDS] | {ef.URL: k}
                    for k, v in self.sites_records.items()
                ),
            ]
        
        if self._fields:
            cols_tables = []
            for col_id in self._fields:
                if not col_id.startswith(self._source_name):
                    continue
                suffix = col_id.split("_")[-1]
                col_record = {
                    "id": col_id,
                    gf.FIELDS: {"label": self._source_label + " " + suffix},
                }
                # TODO add more formatting rules. (column type, width etc)
                entry_fields = col_record[gf.FIELDS]
                if suffix == ef.TAGS:
                    entry_fields |= {
                        "type": f"RefList:{col_id}",
                        "visibleCol": self.g.get_colRef(
                            col_id, "Tag"
                        ),  #TODO visibleCol doesn't work, have to set manually. #blocked
                    }
                elif suffix == ef.RATING:
                    entry_fields |= {
                        "type": "Numeric",
                    }
                cols_tables.append(col_record)
            self.g.add_update_cols(t.SITES, cols_tables, noupdate=True)
            print("wrote cols")
        
        self._write_record_table(t.SITES)
        #TODO SQL filters here too
        self.sites = {i[kf.NORMAL_URL]: i for i in self.g.list_records(t.SITES)[1]}

        if self.write_meta:
            from f.main.get_repos_data import fetch_repo_data
            from f.main.get_authors_data import fetch_authors
            repos_metadata = fetch_repo_data(
                self.g,
                list(url for i in self.repos_records.keys() if (url := check_repo(i)) and check_stale(self.repos.get(i, {}).get(mf.POLLED))),
            )
            for url, fields in repos_metadata.items():
                self.repos_records[url][gf.FIELDS] |= fields
            authors_metadata = fetch_authors(
                did
                for did in self.authors_records.keys()
                if check_stale(self.authors[did].get(mf.POLLED))
            )
            for did, fields in authors_metadata.items():
                self.authors_records[did][gf.FIELDS] |= fields

        repos = self._write_record_table(t.REPOS)
        authors = self._write_record_table(t.AUTHORS)
        if self.current_update_timestamp:
            self.g.add_update_records(
                t.SOURCES,
                [
                    {
                        gf.KEY: {"source_name": self._source_name},
                        gf.FIELDS: {"last_update_timestamp": self.current_update_timestamp},
                    }
                ],
            )

        # TODO writing meta could happen here too. it's an exta round trip to grist but less data from bsky/forges
        # if self.write_meta:
            # from f.main.get_repos_data import main as fetch_stale_repos
            # from f.main.get_authors_data import main as fetch_stale_authors
            # fetch_stale_repos()
            # fetch_stale_authors()


        return { "render_all": [
            {cmk.source_name: self._source_name, cmk.fields: self._fields},
            {"table-row-object": sites_output},
            {"table-row-object": repos},
            {"table-row-object": authors}
        ]}

if __name__ == "__main__":
    c = Collector("Official_showcase")
