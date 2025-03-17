import json
from pprint import pformat
from string import Template
from typing import Callable, Any, Optional
import wmill
from f.main.boilerplate import get_timed_logger, batched, url_obj
import time
import httpx

log = get_timed_logger()

# https://docs.github.com/en/rest/using-the-rest-api/rate-limits-for-the-rest-api?apiVersion=2022-11-28#about-secondary-rate-limits
class GitHubRateLimitRetryTransport(httpx.BaseTransport): # thank u claude
    def __init__(self, cooldown: float = 0):
        self.main_transport = httpx.HTTPTransport()
        self.cooldown = cooldown  # hopefully the cooldown lets us avoid hitting rate limit?
        self.last_request_time = 0

    def handle_request(self, request):
        while True:
            if self.cooldown:
                elapsed = time.time() - self.last_request_time
                if elapsed < self.cooldown:
                    to_sleep = self.cooldown - elapsed
                    log.debug(f"cooldown: waiting {to_sleep:.2f}s")
                    time.sleep(to_sleep)
            
            response = self.main_transport.handle_request(request)
            response.read()
            self.last_request_time = time.time()

            headers = response.headers

            if int(headers.get("x-ratelimit-remaining", 0)) == 0:
                reset_time = int(headers.get("x-ratelimit-reset", 0))
                # Calculate wait time
                wait_time = reset_time - time.time()
                if wait_time > 0:
                    log.warning(f"Primary github rate limit hit. Waiting {wait_time:.2f} seconds. response body:\n{response.json()}")
                    time.sleep(wait_time + 1)  # Add 1 second buffer
                    continue

            if (retry_after := int(headers.get("retry-after", 0))) > 0:
                log.warning(f"Secondary github rate limit hit. Waiting {retry_after} seconds. response body:\n{response.json()}")
                time.sleep(retry_after)
                continue

            # If we get here, either we're not rate limited or we've waited and should return the response
            return response

gh = httpx.Client(
    headers={
        "Authorization": f"Bearer {wmill.get_variable('u/autumn/github_key')}",
        "Content-Type": "application/json",
    },
    transport=GitHubRateLimitRetryTransport()
)

rate_limit_info = "rateLimit {cost remaining resetAt}"

outer_template = Template('''
query {
  repository(owner: "$owner", name: "$repo") {
    $lines
  }
  $rate_limit_info
}
''')

line_template = Template('$id: object(expression: "$branch:$path") { ... on Blob { text } }')

def get_repo_files(url: str, paths: list[str], batch_size = 32) -> dict[str, str]:
    
    u = url_obj(url)
    owner, repo, _, branch, *_ = u.path
    if not all((owner, repo, branch)):
        raise ValueError('improperly formatted url')
    
    out: dict[str, str] = {}

    for num_req, batch in enumerate(batched(paths, batch_size)): 
        lines = "    \n".join(
            line_template.substitute(id="r" + str(num_req * batch_size + i), branch=branch, path=path)
            for i, path in enumerate(batch)
        )
        query = outer_template.substitute(owner=owner, repo=repo, lines=lines, rate_limit_info=rate_limit_info)

        log.debug(f'sending {query}')
        response = gh.post(
            "https://api.github.com/graphql", json={"query": query}
        )

        data: dict[str, Any] = response.json()['data']
        log.info("rate limit: " + str(data.pop("rateLimit", None)))
        if errors := data.pop("errors", None):
            log.error(f"error fetching github files:\n{pformat(errors)}")
        batch_results = {
            paths[int(id.strip("r"))]: entry["text"]
            for id, entry in data["repository"].items()
        }

        out |= batch_results

    return out


if __name__ == "__main__": 
    get_repo_files("https://github.com/bluesky-social/atproto/tree/main/", ['lexicons/app/bsky/feed/like.json','lexicons/app/bsky/graph/list.json'], lambda x: json.loads(x))
