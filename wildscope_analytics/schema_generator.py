"""
WILDSCOPE Decision Intelligence & Analytics Module
JSON Schema Generator - Phase 1 / Phase 2

Exports official JSON Schema definitions from Pydantic v2 models into schemas/ directory.
This ensures the backend (Santosh) and frontend (Laasya) have standard schema files
without maintaining duplicate schemas manually.

Phase 2 additions: DatasetReferenceAnnotation schema exported separately.
"""

from __future__ import annotations
import json
import sys
from pathlib import Path

# Ensure root directory is on pythonpath
REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from wildscope_analytics.contracts.entities import DatasetReferenceAnnotation
from wildscope_analytics.contracts.requests import AnalysisRequest, ReviewRankingRequest
from wildscope_analytics.contracts.responses import AnalysisResponseEnvelope
from wildscope_analytics.contracts.snapshot import Snapshot


def export_schemas(output_dir: Path | str | None = None) -> list[Path]:
    """Generates JSON Schema files from Pydantic contract models."""
    if output_dir is None:
        target_dir = Path(__file__).resolve().parent.parent / "schemas"
    else:
        target_dir = Path(output_dir)

    target_dir.mkdir(parents=True, exist_ok=True)

    models_to_export = [
        ("snapshot.schema.json", Snapshot),
        ("analysis_request.schema.json", AnalysisRequest),
        ("review_ranking_request.schema.json", ReviewRankingRequest),
        ("analysis_response.schema.json", AnalysisResponseEnvelope),
        ("dataset_reference_annotation.schema.json", DatasetReferenceAnnotation),
    ]

    exported_paths = []
    for filename, model in models_to_export:
        schema_path = target_dir / filename
        schema_dict = model.model_json_schema()
        with open(schema_path, "w", encoding="utf-8") as f:
            json.dump(schema_dict, f, indent=2)
        exported_paths.append(schema_path)

    return exported_paths


if __name__ == "__main__":
    paths = export_schemas()
    for p in paths:
        print(f"Generated schema: {p}")
