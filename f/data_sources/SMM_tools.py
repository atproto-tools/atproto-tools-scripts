from f.main.Collector import Collector
import requests
from bs4 import BeautifulSoup


def main():

    c = Collector("SMM_tools")
    # Send a GET request to the URL
    response = requests.get(
        "https://www.hilarybaumann.com/social-media-manager-tools-for-bluesky/"
    )

    # Check if the request was successful
    if response.status_code == 200:
        # Parse the HTML content
        soup = BeautifulSoup(response.content, 'html.parser')

        exclude = ["https://bsky.app/profile/hilarybaumann.com", "https://docs.bsky.app/showcase?tags=client&ref=testingitwith.com"]
        links = {a["href"] for a in soup.select('.post-content a[href]')
                 if a["href"] not in exclude and not a["href"].startswith("https://bsky.app/profile/testingitwith.com/")} #type: ignore
        for a in links:
            c.add_site(a) # type: ignore

        return c.output()

if __name__=="__main__":
    main()
