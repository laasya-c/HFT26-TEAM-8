"""
WILDSCOPE Decision Intelligence & Analytics Module
Localhost Web Inspector - Phase 1 Developer Tool

A lightweight local web interface allowing developers to inspect data contracts,
visually test snapshot validation, view entity counts, explore error reports,
and inspect generated JSON schemas on localhost:8000.
"""

from __future__ import annotations
import json
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
import uvicorn

from wildscope_analytics import (
    AnalysisMetric,
    AnalysisRequest,
    CURRENT_SCHEMA_VERSION,
    ReviewRankingRequest,
    analyze,
    load_and_validate_snapshot,
    rank_review,
)

app = FastAPI(
    title="WILDSCOPE Phase 1 - Contract & Validation Inspector",
    description="Developer Localhost Inspector for Phase 1 Shared Contracts, Referential Validation & Schemas",
    version=CURRENT_SCHEMA_VERSION,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

REPO_ROOT = Path(__file__).resolve().parent.parent
EXAMPLES_DIR = REPO_ROOT / "examples"
SCHEMAS_DIR = REPO_ROOT / "schemas"


@app.get("/api/fixtures/{name}")
def get_fixture(name: str):
    """Fetch one of the synthetic example fixtures."""
    file_path = EXAMPLES_DIR / f"{name}.json"
    if not file_path.exists():
        return JSONResponse(status_code=404, content={"error": f"Fixture '{name}' not found"})
    with open(file_path, "r", encoding="utf-8") as f:
        return json.load(f)


@app.get("/api/schemas/{name}")
def get_schema(name: str):
    """Fetch one of the exported JSON schemas."""
    file_path = SCHEMAS_DIR / f"{name}.schema.json"
    if not file_path.exists():
        return JSONResponse(status_code=404, content={"error": f"Schema '{name}' not found"})
    with open(file_path, "r", encoding="utf-8") as f:
        return json.load(f)


@app.post("/api/validate")
async def validate_endpoint(request: Request):
    """Validate any submitted snapshot payload."""
    try:
        body = await request.json()
    except Exception as e:
        return JSONResponse(status_code=400, content={"error": f"Malformed JSON: {str(e)}"})

    snapshot, report = load_and_validate_snapshot(body)
    return {
        "is_valid": report.is_valid,
        "schema_version": report.schema_version,
        "dataset_revision": report.dataset_revision,
        "counts": report.counts,
        "errors": [e.model_dump() for e in report.errors],
        "warnings": report.warnings,
    }


@app.post("/api/test-analyze")
async def test_analyze_endpoint(request: Request):
    """Test the analyze() entry point against a snapshot."""
    body = await request.json()
    snapshot_payload = body.get("snapshot", {})
    metric_str = body.get("metric", AnalysisMetric.SPECIES_ENCOUNTER_COUNTS.value)

    snapshot, report = load_and_validate_snapshot(snapshot_payload)
    if snapshot is None:
        return JSONResponse(
            status_code=400,
            content={"status": "invalid_request", "errors": [e.model_dump() for e in report.errors]},
        )

    req = AnalysisRequest(
        metric=AnalysisMetric(metric_str),
        expected_revision=snapshot.metadata.dataset_revision,
    )
    result = analyze(snapshot, req)
    return result.model_dump(mode="json")


@app.get("/", response_class=HTMLResponse)
def index():
    """Interactive visual dashboard on localhost."""
    return HTMLResponse(
        """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>WILDSCOPE — Contract & Validation Inspector (Localhost)</title>
  <style>
    :root {
      --bg: #0f172a;
      --card: #1e293b;
      --border: #334155;
      --text: #f8fafc;
      --muted: #94a3b8;
      --accent: #10b981;
      --accent-hover: #059669;
      --danger: #ef4444;
      --warning: #f59e0b;
      --info: #3b82f6;
    }
    * { box-sizing: border-box; margin: 0; padding: 0; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; }
    body { background-color: var(--bg); color: var(--text); padding: 24px; }
    .header { display: flex; justify-content: space-between; align-items: center; border-bottom: 1px solid var(--border); padding-bottom: 16px; margin-bottom: 24px; }
    .badge { display: inline-block; padding: 4px 10px; border-radius: 9999px; font-size: 12px; font-weight: 600; }
    .badge-branch { background: #312e81; color: #a5b4fc; }
    .badge-role { background: #064e3b; color: #6ee7b7; }
    .grid { display: grid; grid-template-columns: 1fr 1fr; gap: 24px; }
    @media (max-width: 900px) { .grid { grid-template-columns: 1fr; } }
    .card { background: var(--card); border: 1px solid var(--border); border-radius: 12px; padding: 20px; }
    .card-title { font-size: 18px; font-weight: 600; margin-bottom: 14px; display: flex; align-items: center; justify-content: space-between; }
    .btn-group { display: flex; gap: 8px; margin-bottom: 14px; flex-wrap: wrap; }
    button { background: var(--border); color: var(--text); border: none; padding: 8px 14px; border-radius: 6px; font-weight: 500; cursor: pointer; transition: 0.2s; }
    button:hover { background: #475569; }
    button.primary { background: var(--accent); color: #042f2e; }
    button.primary:hover { background: var(--accent-hover); }
    textarea { width: 100%; height: 380px; background: #0b1120; border: 1px solid var(--border); border-radius: 8px; color: #38bdf8; font-family: monospace; font-size: 13px; padding: 12px; resize: vertical; }
    .status-box { padding: 16px; border-radius: 8px; margin-bottom: 16px; font-weight: 500; }
    .status-valid { background: #064e3b; border: 1px solid var(--accent); color: #a7f3d0; }
    .status-invalid { background: #450a0a; border: 1px solid var(--danger); color: #fecaca; }
    .stat-row { display: grid; grid-template-columns: repeat(4, 1fr); gap: 10px; margin-bottom: 16px; }
    .stat-card { background: #0b1120; padding: 12px; border-radius: 8px; border: 1px solid var(--border); text-align: center; }
    .stat-number { font-size: 22px; font-weight: 700; color: #38bdf8; }
    .stat-label { font-size: 11px; color: var(--muted); text-transform: uppercase; margin-top: 4px; }
    .err-list { margin-top: 12px; }
    .err-item { background: #2a1215; border-left: 4px solid var(--danger); padding: 10px 14px; margin-bottom: 8px; border-radius: 0 6px 6px 0; font-size: 13px; }
    .err-code { font-weight: 700; color: #f87171; font-family: monospace; }
    .err-path { color: #fdba74; font-family: monospace; }
    .warn-item { background: #271f11; border-left: 4px solid var(--warning); padding: 10px 14px; margin-bottom: 8px; border-radius: 0 6px 6px 0; font-size: 13px; color: #fde68a; }
    pre { background: #0b1120; padding: 14px; border-radius: 8px; border: 1px solid var(--border); overflow-x: auto; font-size: 12px; color: #cbd5e1; max-height: 280px; }
    .nav-links a { color: #38bdf8; text-decoration: none; margin-left: 12px; font-size: 14px; }
    .nav-links a:hover { text-decoration: underline; }
  </style>
</head>
<body>

  <div class="header">
    <div>
      <h2>WILDSCOPE &bull; Localhost Contract &amp; Validation Inspector</h2>
      <p style="color: var(--muted); font-size: 13px; margin-top: 4px;">
        AI-Powered Wildlife Monitoring &bull; Phase 1 Shared Contracts &bull; Branch: <span class="badge badge-branch">shravan</span>
        &bull; Role: <span class="badge badge-role">Shravan &mdash; Analytics &amp; Integrity</span>
      </p>
    </div>
    <div class="nav-links">
      <a href="/docs" target="_blank">&rarr; Interactive API Docs (/docs)</a>
    </div>
  </div>

  <div class="grid">
    <!-- Left Column: Input and Fixtures -->
    <div class="card">
      <div class="card-title">
        <span>Snapshot Input Payload</span>
        <span style="font-size: 12px; color: var(--muted);" id="charCount">Ready</span>
      </div>

      <div class="btn-group">
        <button onclick="loadFixture('valid_snapshot')">Load Valid Snapshot</button>
        <button onclick="loadFixture('minimal_snapshot')">Load Minimal Snapshot</button>
        <button onclick="loadFixture('invalid_snapshot')">Load Invalid Snapshot</button>
        <button class="primary" onclick="runValidation()">&#9658; Validate Snapshot</button>
      </div>

      <textarea id="jsonInput" placeholder="Paste snapshot JSON here..."></textarea>

      <div style="margin-top: 14px; display: flex; gap: 8px;">
        <button onclick="testAnalyze('species_encounter_counts')">Test analyze(snapshot)</button>
        <button onclick="testAnalyze('activity_time_distribution')">Test diurnal analyze()</button>
      </div>
    </div>

    <!-- Right Column: Validation Report & Details -->
    <div class="card">
      <div class="card-title">
        <span>Validation Results &amp; Diagnostics</span>
        <span id="timestamp" style="font-size: 12px; color: var(--muted);"></span>
      </div>

      <div id="statusBox" class="status-box status-valid">
        Click "Validate Snapshot" to run deep relational and schema verification.
      </div>

      <div class="stat-row" id="statsRow" style="display: none;">
        <div class="stat-card">
          <div class="stat-number" id="statCameras">0</div>
          <div class="stat-label">Cameras</div>
        </div>
        <div class="stat-card">
          <div class="stat-number" id="statObservations">0</div>
          <div class="stat-label">Observations</div>
        </div>
        <div class="stat-card">
          <div class="stat-number" id="statDetections">0</div>
          <div class="stat-label">Detections</div>
        </div>
        <div class="stat-card">
          <div class="stat-number" id="statEncounters">0</div>
          <div class="stat-label">Encounters</div>
        </div>
      </div>

      <div id="diagnosticsSection"></div>

      <div style="margin-top: 16px;">
        <div class="card-title" style="font-size: 14px;">Response Envelope / Raw Diagnostics</div>
        <pre id="rawOutput">Select a fixture or click Validate to inspect details.</pre>
      </div>
    </div>
  </div>

  <script>
    async function loadFixture(name) {
      try {
        const res = await fetch(`/api/fixtures/${name}`);
        const data = await res.json();
        document.getElementById('jsonInput').value = JSON.stringify(data, null, 2);
        document.getElementById('charCount').innerText = `${name}.json loaded`;
        runValidation();
      } catch (e) {
        alert("Error loading fixture: " + e);
      }
    }

    async function runValidation() {
      const input = document.getElementById('jsonInput').value;
      if (!input.trim()) {
        alert("Please paste or load a snapshot JSON first.");
        return;
      }

      let payload;
      try {
        payload = JSON.parse(input);
      } catch (e) {
        showError("Invalid JSON syntax: " + e.message);
        return;
      }

      try {
        const res = await fetch('/api/validate', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload)
        });
        const rep = await res.json();
        renderReport(rep);
      } catch (e) {
        showError("Validation network error: " + e);
      }
    }

    function renderReport(rep) {
      const statusBox = document.getElementById('statusBox');
      const statsRow = document.getElementById('statsRow');
      const diagSection = document.getElementById('diagnosticsSection');
      const rawOutput = document.getElementById('rawOutput');

      document.getElementById('timestamp').innerText = new Date().toLocaleTimeString();
      rawOutput.innerText = JSON.stringify(rep, null, 2);

      if (rep.is_valid) {
        statusBox.className = "status-box status-valid";
        statusBox.innerHTML = `&#10003; <strong>Snapshot Valid!</strong> Revision: <code>${rep.dataset_revision ?? 'N/A'}</code> &bull; Schema: <code>${rep.schema_version ?? '1.0.0'}</code>`;
      } else {
        statusBox.className = "status-box status-invalid";
        statusBox.innerHTML = `&#10007; <strong>Validation Failed:</strong> ${rep.errors ? rep.errors.length : 0} structured error(s) detected.`;
      }

      if (rep.counts) {
        statsRow.style.display = 'grid';
        document.getElementById('statCameras').innerText = rep.counts.cameras || 0;
        document.getElementById('statObservations').innerText = rep.counts.observations || 0;
        document.getElementById('statDetections').innerText = rep.counts.detections || 0;
        document.getElementById('statEncounters').innerText = rep.counts.encounters || 0;
      }

      let html = '';
      if (rep.errors && rep.errors.length > 0) {
        html += '<div class="err-list"><strong style="color: var(--danger)">Errors:</strong>';
        rep.errors.forEach(err => {
          html += `<div class="err-item">
            <span class="err-code">[${err.code}]</span> <span class="err-path">${err.field_path}</span><br>
            <span>${err.message}</span>
          </div>`;
        });
        html += '</div>';
      }

      if (rep.warnings && rep.warnings.length > 0) {
        html += '<div style="margin-top: 10px;"><strong style="color: var(--warning)">Advisory Warnings (Missing Optional Data):</strong>';
        rep.warnings.forEach(warn => {
          html += `<div class="warn-item">&bull; ${warn}</div>`;
        });
        html += '</div>';
      }

      diagSection.innerHTML = html;
    }

    async function testAnalyze(metricName) {
      const input = document.getElementById('jsonInput').value;
      if (!input.trim()) { alert("Load a snapshot first."); return; }
      const payload = JSON.parse(input);

      const res = await fetch('/api/test-analyze', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ snapshot: payload, metric: metricName })
      });
      const data = await res.json();
      document.getElementById('rawOutput').innerText = JSON.stringify(data, null, 2);

      const statusBox = document.getElementById('statusBox');
      statusBox.className = "status-box status-valid";
      statusBox.innerHTML = `Entry Point Executed &bull; Status: <strong>${data.status}</strong> &bull; Limitations: ${data.limitations?.join(' ')}`;
    }

    function showError(msg) {
      const statusBox = document.getElementById('statusBox');
      statusBox.className = "status-box status-invalid";
      statusBox.innerHTML = `<strong>Error:</strong> ${msg}`;
      document.getElementById('diagnosticsSection').innerHTML = '';
    }

    // Auto-load valid snapshot on start
    window.onload = () => loadFixture('valid_snapshot');
  </script>
</body>
</html>
"""
    )


def run():
    """Starts the inspector server on localhost:8000."""
    print("\n" + "=" * 60)
    print("WILDSCOPE Phase 1 Localhost Inspector Starting")
    print("Open your browser and navigate to: http://localhost:8000")
    print("Interactive Swagger API docs at:  http://localhost:8000/docs")
    print("=" * 60 + "\n")
    uvicorn.run(app, host="127.0.0.1", port=8000, log_level="info")


if __name__ == "__main__":
    run()
