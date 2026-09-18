"""Generate the contract without opening any database or reading credentials."""

import json
from pathlib import Path

from class_copilot.dto import PublicTypes
from class_copilot.main import app

from class_copilot.domain import Settings

schema = app.openapi()
models = PublicTypes.model_json_schema(ref_template="#/components/schemas/{model}")
schema["components"]["schemas"].update(models["$defs"])
settings = Settings.model_json_schema(ref_template="#/components/schemas/{model}")
schema["components"]["schemas"].update(settings.pop("$defs", {}))
schema["components"]["schemas"]["Settings"] = settings
path = Path(__file__).resolve().parents[1] / "web/openapi.json"
path.write_text(json.dumps(schema, indent=2, ensure_ascii=False) + "\n")
print(
    f"Exported {sum(len([k for k in p if k in ('get', 'post', 'put', 'patch', 'delete')]) for p in schema['paths'].values())} operations"
)
