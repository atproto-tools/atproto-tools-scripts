from f.main.Collector import lex
def main():
    return {
        "type": "object",
        "order": [
            "url",
            "name",
            "desc",
            "repo",
            "author",
            "lexicon"
        ],
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "required": [
            "url"
        ],
        "properties": {
            "url": {
                "type": "string",
                "title": "URL",
                "format": "uri",
                "default": "",
                "Noneable": False,
                "description": "main URL of the app",
                "originalType": "string",
                "disableVariablePicker": True
            },
            "name": {
                "type": "string",
                "title": "Name",
                "default": None,
                "description": "",
                "originalType": "string",
                "disableVariablePicker": True
            },
            "desc": {
                "type": "string",
                "title": "Description",
                "default": None,
                "description": "",
                "originalType": "string",
                "disableVariablePicker": True
            },
            "repo": {
                "type": "string",
                "title": "Source Code URL",
                "format": "uri",
                "default": None,
                "description": "if distinct from main URL",
                "originalType": "string",
                "disableVariablePicker": True
            },
            "author": {
                "type": "string",
                "title": "Author",
                "default": None,
                "description": "DID, handle, or bsky.app profile",
                "originalType": "string",
                "disableVariablePicker": True
            },
            "lexicon": {
                "type": "string",
                "title": "Lexicon",
                "default": None,
                "Noneable": True,
                "enumLabels": {lex_num: lex_name for lex_name, lex_num in lex._member_map_.items()},
                "enum": list(lex._member_map_.values()),
                "description": ""
            }
        }
    }