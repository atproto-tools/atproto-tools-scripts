from wmill import Windmill
from f.main.ATPTGrister import ATPTGrister, t
import pprint
path = "f/data_sources/"

def main():
    w = Windmill()
    # actual_scripts = [
    #     script for script
    #     in w.get("w/atproto-tools-scripts/scripts/list_paths").json()
    #     if script.startswith(path)
    # ]
    g = ATPTGrister()
    sorted_sources = sorted(g.list_records(t.SOURCES, hidden=True)[1], key = lambda x: x["manualSort"])
    scripts = [path + s["source_name"]
               for s in sorted_sources
               if not s["status"]]
    for script in scripts:
        # reliant on the source name column matching up with script names in windmill
        try:
            w.run_script(script, assert_result_is_not_none=False)
        except Exception as e:
            pprint.pprint(e)
            pass
if __name__ == "__main__":
    main()
