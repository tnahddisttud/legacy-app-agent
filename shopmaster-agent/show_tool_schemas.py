"""Print exactly what the LLM sees for each tool: name, description and argument schema."""
import json

from tools.shop import ALL_TOOLS, WRITE_TOOL_NAMES

for t in ALL_TOOLS:
    kind = "WRITE (needs human approval)" if t.name in WRITE_TOOL_NAMES else "read-only"
    print(f"\n=== {t.name}   [{kind}]")
    print(t.description)
    print(json.dumps(t.args_schema.model_json_schema()["properties"], indent=2))
