# 🚀 CBIT Hacktoberfest '26 — Project Repository

> **Official Public Repository for CBIT Hacktoberfest '26**  
> *Chaitanya Bharathi Institute of Technology (CBIT), Hyderabad*

---

## 📋 Team Information

| Attribute | Details |
| :--- | :--- |
| **Team Name** | **ByteStrom** |
| **Team Number** | `TEAM-8` (`HFT26-TEAM-8`) |
| **Registration ID** | `HFEST26-475WHN3H` |
| **Problem Track** | **WILDSCOPE — AI-Powered Wildlife Intelligence & Camera-Trap Monitoring System** |
| **Domain** | `General Track / Environmental AI & Analytics` |
| **Team Leader** | Harsh Rao (dharshrao27@gmail.com) |
| **Institution** | Keshav Memorial Institute of Technology |

### 👥 Team Members & Responsibilities

| # | Name | Email | Role & Module Responsibilities |
| :--- | :--- | :--- | :--- |
| 1 | **Harsh Rao** (Lead) | dharshrao27@gmail.com | Vision models, animal detection, taxonomic classification, encounter grouping |
| 2 | **Kolachalama Sri Shravan** | srishravank@gmail.com | Integration architecture, shared data contracts, validation, decision intelligence (`analyze`, `rank_review`) |
| 3 | **Santosh Yuvaraj** | santoshyuvarajeshwaroju@gmail.com | Backend API gateway, persistent database, job queues, revision management, review audit trail |
| 4 | **Laasya Priya** | c.laasya27@gmail.com | Interactive React frontend, map visualization, human review interface, transparent reporting |

---

## 🎯 Problem Statement: WILDSCOPE

WILDSCOPE converts raw camera-trap imagery and videos into traceable, reviewable wildlife evidence. It supports researchers and conservation management teams by automating animal detection, taxonomic classification, encounter aggregation, spatio-temporal activity patterns, and conclusion-sensitive review prioritization.

---

## 📦 Phase 1: Shared Data Contracts & Validation Engine

**Branch:** `shravan`  
**Implemented by:** Kolachalama Sri Shravan

Phase 1 establishes the strongly-typed contracts, validation engine, JSON schemas, and response envelopes that guarantee data integrity across all four team modules before analytical algorithms run.

### 🌟 Key Capabilities Implemented
1. **Pydantic v2 Contracts:** Models for `Camera`, `MediaAsset`, `Observation`, `Detection`, `NormalizedBBox`, `Encounter`, `ReviewEvent`, `MonitoringEffort`, and `SpatialContext`.
2. **Deep Relational Validation (`validation.py`):**
   - Unique entity IDs across all collections.
   - Foreign-key referential integrity (cameras, media, observations, detections, encounters, reviews, efforts).
   - Strict encounter membership: all member observations and detections must belong to the encounter's camera.
   - Non-overlapping monitoring effort intervals per camera trap.
   - Coordinate range validation (`[-90, 90]`, `[-180, 180]`) and mandatory paired presence.
   - Timezone-aware timestamps for known times.
   - Separation of detection confidence from classification confidence.
   - Review consistency rules (corrected species requires replacement taxon, rejected detection forbids taxon).
3. **Transparent Response Envelopes (`AnalysisResponseEnvelope`):**
   - 5 distinct operational statuses: `ok`, `partial`, `insufficient_data`, `unavailable`, `invalid_request`.
   - Never fabricates fake operational metrics or returns fake zeroes for missing data.
   - Citations to supporting evidence IDs (`evidence_references`).
4. **JSON Schema Automation (`schema_generator.py`):**
   - Generates machine-readable JSON Schema files for backend (FastAPI) and frontend (TypeScript) synchronization.

---

## 🚀 Quick Start & Installation

```bash
# 1. Clone repository and switch to Shravan's branch
git clone https://github.com/<your-username>/HFT26-TEAM-8.git
cd HFT26-TEAM-8
git checkout shravan

# 2. Install package in editable mode
pip install -e .

# 3. Run validation test suite
pytest -v
```

### 🔬 Generating JSON Schemas

```bash
python wildscope_analytics/schema_generator.py
```
Exports schemas to `schemas/`:
- `schemas/snapshot.schema.json`
- `schemas/analysis_request.schema.json`
- `schemas/review_ranking_request.schema.json`
- `schemas/analysis_response.schema.json`

### 💻 Python Usage Example

```python
from wildscope_analytics import (
    load_and_validate_snapshot,
    AnalysisRequest,
    AnalysisMetric,
    analyze,
)

# 1. Load and validate point-in-time snapshot
snapshot, report = load_and_validate_snapshot("examples/valid_snapshot.json")

if report.is_valid:
    print(f"Snapshot valid! Revision: {report.dataset_revision}")
    for warning in report.warnings:
        print(f"Advisory: {warning}")

    # 2. Construct analytical request
    request = AnalysisRequest(
        metric=AnalysisMetric.SPECIES_ENCOUNTER_COUNTS,
        species_ids=["panthera_tigris"],
        expected_revision=report.dataset_revision,
    )

    # 3. Execute entry point
    response = analyze(snapshot, request)
    print(f"Response status: {response.status}")
    print(f"Limitations: {response.limitations}")
else:
    print("Snapshot validation failed:")
    for err in report.errors:
        print(f"[{err.code}] {err.field_path}: {err.message}")
```

---

## 📁 Repository Structure

```
HFT26-TEAM-8/
├── wildscope_analytics/          # Core analytics & contract package
│   ├── __init__.py               # Entry points (analyze, rank_review, load_and_validate_snapshot)
│   ├── contracts/
│   │   ├── __init__.py           # Contract exports
│   │   ├── enums.py              # TriageState, ScoreType, ReviewDecision, ResponseStatus, AnalysisMetric
│   │   ├── entities.py           # Camera, Detection, NormalizedBBox, Encounter, ReviewEvent, etc.
│   │   ├── snapshot.py           # Snapshot and SnapshotMetadata contracts
│   │   ├── requests.py           # AnalysisRequest, ReviewRankingRequest
│   │   └── responses.py          # AnalysisResponseEnvelope, ValidationErrorDetail
│   ├── validation.py             # Validation engine, uniqueness, referential integrity
│   └── schema_generator.py       # Pydantic JSON Schema export script
├── schemas/                      # Generated JSON Schemas for team synchronization
│   ├── snapshot.schema.json
│   ├── analysis_request.schema.json
│   ├── review_ranking_request.schema.json
│   └── analysis_response.schema.json
├── examples/                     # Synthetic test fixtures
│   ├── valid_snapshot.json       # Complete valid synthetic fixture
│   ├── minimal_snapshot.json     # Minimal valid fixture
│   └── invalid_snapshot.json     # Intentionally invalid fixture for error demonstration
├── tests/                        # Comprehensive test suites (38 passing tests)
│   ├── test_contracts.py         # Entity constraints, bounds, round-trip serialization
│   └── test_validation.py        # Relational integrity, uniqueness, entry points
├── docs/                         # Technical specifications & team handoff
│   ├── phase1_contract.md        # Complete contract definitions and field matrix
│   └── team_handoff.md           # Handoff guide for Harsh, Santosh, and Laasya
├── pyproject.toml                # Project packaging configuration
└── README.md                     # Project overview and setup guide
```
