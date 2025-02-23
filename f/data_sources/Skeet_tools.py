from requests import get
from bs4 import BeautifulSoup
from typing import Any
from f.main.Collector import Collector, ef

def main() -> dict[str, list[Any]]:

    c = Collector(
        "Skeet_tools", [ef.NAME, ef.DESC, ef.TAGS, ef.RATING], add_repos=True
    )

    page_content: Any = BeautifulSoup(
        get("https://dame.blog/skeet-tools/").text, "html.parser"
    )

    sections = page_content.css.select(".post-body > section")
    for section in sections:
        category = section.h2.string
        featured_entry = category.find("Featured") != -1

        for list in section.css.select("ul"):
            current_h3 = list.previous_sibling.previous_sibling
            if current_h3 and current_h3.name == "h3":
                current_h3 = current_h3.string
            else:
                current_h3 = None

            for item in list.css.select("li > a"):
                
                name: str = item.string
                parts = name.split(":", 1)  #hope nobody has a colon in their project name
                tool = {
                    ef.NAME: parts[0].strip(),
                    ef.URL: item["href"]
                }

                if len(parts) == 2:
                    tool[ef.DESC] = parts[1].strip()

                if featured_entry:
                    tool[ef.RATING] = 1
                else:
                    tool[ef.TAGS] = [category]

                if current_h3:
                    tool[ef.TAGS].append(current_h3)

                c.add_site(tool)

    return c.output()

if __name__ == "__main__":
    main()
