"""
WILDSCOPE Decision Intelligence & Analytics Module
Phase 6: Spatial Intelligence Engine

Implements deterministic geospatial analysis for camera trap networks:
- Feature F08: Possible monitoring blind spots (gap analysis).
- Feature F09: Candidate camera placement ranking.
- Feature F14: Geofencing and proximity indicators.
- Feature F16: Wildlife-infrastructure scenarios.

CRITICAL SCIENTIFIC & INTERPRETIVE GUARDRAILS:
1. Spatial calculations are deterministic geometric operations based on declared
   or assumed sensor models, boundaries, and scenarios.
2. Gap polygons indicate areas outside declared camera coverage assumptions,
   NOT field-validated wildlife absence or animal avoidance.
3. Candidate placement ranks reflect single-site marginal coverage gain over baseline.
   Marginal gains are NOT additive; placing multiple candidates requires joint evaluation.
   Zero-gain feasible sites are redundant, not physically infeasible. Excluded sites
   are separated from eligible rankings.
4. Camera coordinates reflect physical device mounting locations, NOT animal locations.
   Camera proximity indicators must never be described as "animal geofence crossing".
5. Scenario analysis is geometric modeling; it does NOT predict ecological impact,
   displacement routes, or population viability.
6. Mathematical Model, Numerical Precision & Spatial Accuracy:
   a. Coordinate Conversion & Roundtrip Error:
      Uses spherical Lambert Azimuthal Equal-Area (LAEA) projection on an authalic reference
      sphere (R = 6,371,008.8 m). In IEEE 754 float64, forward and inverse projection achieve
      numerical roundtrip precision within ~1e-14 degrees (asserted < 1e-6 degrees in tests).
      NOTE ON UNITS: In geographic coordinates, 1e-6 degrees latitude is approximately 0.111 meters
      (111 mm), and longitude distance varies with latitude as ~0.111 * cos(lat) meters (e.g. ~0.092 m
      at 34 deg lat). It must NEVER be confused with 0.1 millimetres.
   b. Spherical-Model Approximation:
      The authalic sphere approximation introduces up to ~0.5% scale and area discrepancy relative
      to the WGS84 reference ellipsoid at mid-latitudes.
   c. Projection Distortion:
      LAEA is equal-area on the reference sphere (preserving relative planar area), but introduces
      angular/directional shear away from the projection center.
   d. Input-Location Uncertainty:
      Target and camera coordinates carry field GPS uncertainty (typically 3 to 15 meters) and
      sensor detection zone assumptions.
   e. Real-World Measurement Accuracy:
      Physical accuracy is governed by GPS field uncertainty, sensor detection ranges, and ellipsoidal
      approximation—not the sub-meter numerical precision of the floating-point projection equations.
"""

from __future__ import annotations

import math
from datetime import datetime
from typing import Any

import numpy as np
import shapely
from shapely.geometry import (
    LineString,
    MultiLineString,
    MultiPolygon,
    Point,
    Polygon,
    mapping,
)
from shapely.ops import unary_union

from wildscope_analytics.contracts.entities import (
    Camera,
    CameraCoverage,
    CandidateSite,
    SpatialZone,
    TargetLocation,
)
from wildscope_analytics.contracts.enums import (
    AnalysisMetric,
    CandidatePlacementStatus,
    DataSourceMode,
    PositionType,
    ProximityRelation,
    ResponseStatus,
    SpatialSourceType,
    ValidationErrorCode,
)
from wildscope_analytics.contracts.requests import (
    AnalysisRequest,
    BlindSpotAnalysisRequest,
    CandidatePlacementRequest,
    InfrastructureScenarioRequest,
    ProximityAnalysisRequest,
)
from wildscope_analytics.contracts.responses import (
    AnalysisResponseEnvelope,
    BlindSpotResult,
    CandidatePlacementItem,
    CandidatePlacementResult,
    InfrastructureScenarioResult,
    ProximityResult,
    TargetProximityItem,
    ValidationErrorDetail,
)
from wildscope_analytics.contracts.snapshot import Snapshot

# Earth radius in meters (WGS84 authalic / mean radius)
EARTH_RADIUS_METERS = 6371008.8

# Geographic extent limits for local LAEA planar projection
MAX_SPAN_DEGREES = 10.0
MIN_LATITUDE = -85.0
MAX_LATITUDE = 85.0
MAX_SEGMENT_DEGREES = 0.05

# Supported Coordinate Reference Systems
SUPPORTED_CRS = {
    "EPSG:4326",
    "WGS84",
    "URN:OGC:DEF:CRS:OGC:1.3:CRS84",
    "CRS84",
    "OGC:CRS84",
    "4326",
}


# ---------------------------------------------------------------------------
# CRS & Geometry Validation Helpers
# ---------------------------------------------------------------------------

def validate_crs(crs: str | None) -> None:
    """
    Validates that the supplied CRS is supported (WGS84 / EPSG:4326).
    Rejects unsupported coordinate reference systems.
    """
    if crs is None:
        return
    cleaned = str(crs).strip().upper()
    if cleaned not in SUPPORTED_CRS:
        raise ValueError(
            f"Unsupported Coordinate Reference System '{crs}'. "
            f"WildScope spatial analytics strictly support WGS84 (EPSG:4326)."
        )


def validate_geojson_coordinates(coords: Any, expected_depth: int) -> None:
    """
    Recursively validates GeoJSON coordinate arrays:
    - Finite floats (no NaN, inf).
    - Longitude in [-180.0, 180.0], Latitude in [-90.0, 90.0].
    - Depth matches expected geometry type.
    - Antimeridian crossing check: rejects consecutive longitude jumps > 180 deg.
    """
    if expected_depth == 1:
        # [longitude, latitude]
        if not isinstance(coords, (list, tuple)) or len(coords) < 2:
            raise ValueError(f"GeoJSON coordinate point must be [lon, lat], got {coords}")
        lon, lat = coords[0], coords[1]
        if not (isinstance(lon, (int, float)) and isinstance(lat, (int, float))):
            raise ValueError(f"Coordinates must be numbers, got {coords}")
        if not (math.isfinite(lon) and math.isfinite(lat)):
            raise ValueError(f"Coordinates must be finite numbers, got [{lon}, {lat}]")
        if not (-180.0 <= lon <= 180.0):
            raise ValueError(f"Longitude {lon} out of bounds [-180.0, 180.0]")
        if not (-90.0 <= lat <= 90.0):
            raise ValueError(f"Latitude {lat} out of bounds [-90.0, 90.0]")
        return

    if not isinstance(coords, (list, tuple)) or len(coords) == 0:
        raise ValueError(f"Expected nested coordinate list at depth {expected_depth}, got {coords}")

    # Check for antimeridian crossing along line or ring
    if expected_depth == 2 and len(coords) >= 2:
        for idx in range(len(coords) - 1):
            p1 = coords[idx]
            p2 = coords[idx + 1]
            if isinstance(p1, (list, tuple)) and isinstance(p2, (list, tuple)) and len(p1) >= 2 and len(p2) >= 2:
                lon1, lon2 = p1[0], p2[0]
                if isinstance(lon1, (int, float)) and isinstance(lon2, (int, float)):
                    if abs(lon2 - lon1) > 180.0:
                        raise ValueError(
                            f"Antimeridian crossing detected between longitude {lon1} and {lon2} "
                            f"(|lon2 - lon1| > 180 deg). Geometry must be pre-split at -180/180 longitude."
                        )

    for sub_coords in coords:
        validate_geojson_coordinates(sub_coords, expected_depth - 1)


def parse_and_validate_geometry(geom_dict: dict[str, Any]) -> shapely.geometry.base.BaseGeometry:
    """
    Parses a GeoJSON geometry dictionary into a validated Shapely geometry.
    Rejects malformed geometries, self-intersections, non-closed rings,
    antimeridian crossings, and invalid coordinate bounds without silent repairs.
    """
    if not isinstance(geom_dict, dict):
        raise ValueError(f"Geometry must be a dictionary, got {type(geom_dict).__name__}")
    if "type" not in geom_dict or "coordinates" not in geom_dict:
        raise ValueError("GeoJSON geometry dictionary must contain 'type' and 'coordinates' keys")

    geom_type = geom_dict["type"]
    coords = geom_dict["coordinates"]

    if geom_type == "Point":
        validate_geojson_coordinates(coords, 1)
        geom = Point(coords[0], coords[1])
    elif geom_type == "LineString":
        validate_geojson_coordinates(coords, 2)
        if len(coords) < 2:
            raise ValueError(f"LineString must contain at least 2 coordinate points, got {len(coords)}")
        geom = LineString(coords)
    elif geom_type == "MultiLineString":
        validate_geojson_coordinates(coords, 3)
        geom = MultiLineString(coords)
    elif geom_type == "Polygon":
        validate_geojson_coordinates(coords, 3)
        if len(coords) == 0:
            raise ValueError("Polygon must contain at least one ring (exterior ring)")
        # Check exterior ring closure and minimum length
        exterior = coords[0]
        if len(exterior) < 4:
            raise ValueError(f"Polygon exterior ring must have at least 4 coordinates, got {len(exterior)}")
        if exterior[0] != exterior[-1]:
            raise ValueError("Polygon ring must be closed (first coordinate must match last coordinate)")
        for hole in coords[1:]:
            if len(hole) < 4:
                raise ValueError(f"Polygon interior ring must have at least 4 coordinates, got {len(hole)}")
            if hole[0] != hole[-1]:
                raise ValueError("Polygon interior ring must be closed")
        geom = Polygon(exterior, coords[1:])
    elif geom_type == "MultiPolygon":
        validate_geojson_coordinates(coords, 4)
        polys = []
        for poly_coords in coords:
            exterior = poly_coords[0]
            if len(exterior) < 4 or exterior[0] != exterior[-1]:
                raise ValueError("MultiPolygon rings must be closed with at least 4 coordinates")
            polys.append(Polygon(exterior, poly_coords[1:]))
        geom = MultiPolygon(polys)
    else:
        raise ValueError(f"Unsupported GeoJSON geometry type: '{geom_type}'")

    if not geom.is_valid:
        explanation = shapely.is_valid_reason(geom)
        raise ValueError(f"Invalid geometry topology ({geom_type}): {explanation}")

    # Validate geographic extents (polar limit and maximum span)
    validate_geographic_extent(geom)

    return geom


def validate_geographic_extent(geom: shapely.geometry.base.BaseGeometry) -> None:
    """
    Enforces supported geographic extents for local planar LAEA projection:
    - Latitude within [-85.0, 85.0] (rejects polar singularities).
    - Longitude and latitude span <= 10.0 degrees (rejects overly large regional/global extents).
    """
    min_lon, min_lat, max_lon, max_lat = geom.bounds
    if min_lat < MIN_LATITUDE or max_lat > MAX_LATITUDE:
        raise ValueError(
            f"Coordinates exceed supported latitude bounds [{MIN_LATITUDE}, {MAX_LATITUDE}] "
            f"(got latitudes from {min_lat:.2f} to {max_lat:.2f}). Polar regions near +/-90 deg "
            f"are unsupported due to extreme azimuthal distortion."
        )
    d_lon = max_lon - min_lon
    d_lat = max_lat - min_lat
    if d_lon > MAX_SPAN_DEGREES or d_lat > MAX_SPAN_DEGREES:
        raise ValueError(
            f"Geometry extent span ({max(d_lon, d_lat):.2f} deg) exceeds maximum supported geographic "
            f"extent of {MAX_SPAN_DEGREES} degrees for local planar LAEA projection."
        )


# ---------------------------------------------------------------------------
# Coordinate Projection & Edge Densification (LAEA)
# ---------------------------------------------------------------------------

def densify_coords(coords: list[tuple[float, float]], max_step_deg: float = MAX_SEGMENT_DEGREES) -> list[tuple[float, float]]:
    """
    Inserts intermediate points along coordinate segments exceeding max_step_deg
    via linear interpolation in longitude/latitude coordinate space (degree space).
    """
    out: list[tuple[float, float]] = []
    for i in range(len(coords) - 1):
        p1 = coords[i]
        p2 = coords[i + 1]
        dist = math.hypot(p2[0] - p1[0], p2[1] - p1[1])
        steps = max(1, int(math.ceil(dist / max_step_deg)))
        for s in range(steps):
            t = s / steps
            out.append((p1[0] + t * (p2[0] - p1[0]), p1[1] + t * (p2[1] - p1[1])))
    out.append(coords[-1])
    return out


def densify_geometry(geom: shapely.geometry.base.BaseGeometry, max_step_deg: float = MAX_SEGMENT_DEGREES) -> shapely.geometry.base.BaseGeometry:
    """
    Densifies long polygon or linestring edges in longitude/latitude coordinate space before
    projection. Linear interpolation in degree space samples along coordinate lines (parallels
    and meridians). Because parallels (lines of constant latitude other than the equator) are
    small circles that project as curved arcs in LAEA, inserting intermediate points along
    coordinate lines prevents straight-chord clipping in planar metric space.
    Note: Interpolation is in coordinate (degree) space, not along great-circle geodesics.
    """
    if geom.geom_type == "Polygon":
        ext = densify_coords(list(geom.exterior.coords), max_step_deg)
        holes = [densify_coords(list(h.coords), max_step_deg) for h in geom.interiors]
        return Polygon(ext, holes)
    elif geom.geom_type == "MultiPolygon":
        return MultiPolygon([densify_geometry(p, max_step_deg) for p in geom.geoms])
    elif geom.geom_type == "LineString":
        return LineString(densify_coords(list(geom.coords), max_step_deg))
    elif geom.geom_type == "MultiLineString":
        return MultiLineString([LineString(densify_coords(list(line.coords), max_step_deg)) for line in geom.geoms])
    return geom


def _project_laea_coords(coords: np.ndarray, center_lon: float, center_lat: float) -> np.ndarray:
    """Vectorized projection from WGS84 [lon, lat] in degrees to planar [x, y] in meters."""
    lon_rad = np.radians(coords[:, 0])
    lat_rad = np.radians(coords[:, 1])
    center_lon_rad = math.radians(center_lon)
    center_lat_rad = math.radians(center_lat)

    d_lon = lon_rad - center_lon_rad
    sin_center = math.sin(center_lat_rad)
    cos_center = math.cos(center_lat_rad)
    sin_lat = np.sin(lat_rad)
    cos_lat = np.cos(lat_rad)

    denom = 1.0 + sin_center * sin_lat + cos_center * cos_lat * np.cos(d_lon)
    if np.any(denom <= 1e-6):
        raise ValueError("Geometry contains a point antipodal to projection center; projection singularity.")

    k = np.sqrt(2.0 / denom)
    x = EARTH_RADIUS_METERS * k * cos_lat * np.sin(d_lon)
    y = EARTH_RADIUS_METERS * k * (cos_center * sin_lat - sin_center * cos_lat * np.cos(d_lon))
    return np.column_stack((x, y))


def _unproject_laea_coords(coords: np.ndarray, center_lon: float, center_lat: float) -> np.ndarray:
    """Vectorized inverse projection from planar [x, y] in meters back to WGS84 [lon, lat] in degrees."""
    x = coords[:, 0]
    y = coords[:, 1]
    center_lon_rad = math.radians(center_lon)
    center_lat_rad = math.radians(center_lat)
    sin_center = math.sin(center_lat_rad)
    cos_center = math.cos(center_lat_rad)

    rho = np.hypot(x, y)
    safe_rho = np.where(rho < 1e-12, 1e-12, rho)
    c = 2.0 * np.arcsin(np.clip(safe_rho / (2.0 * EARTH_RADIUS_METERS), -1.0, 1.0))
    sin_c = np.sin(c)
    cos_c = np.cos(c)

    lat_rad = np.arcsin(cos_c * sin_center + (y * sin_c * cos_center / safe_rho))
    lon_rad = center_lon_rad + np.arctan2(x * sin_c, safe_rho * cos_center * cos_c - y * sin_center * sin_c)

    res_lon = np.where(rho < 1e-12, center_lon, np.degrees(lon_rad))
    res_lat = np.where(rho < 1e-12, center_lat, np.degrees(lat_rad))
    return np.column_stack((res_lon, res_lat))


def project_geometry(geom: shapely.geometry.base.BaseGeometry, center_lon: float, center_lat: float, densify: bool = True) -> shapely.geometry.base.BaseGeometry:
    """Projects a Shapely geometry from WGS84 (degrees) to local planar coordinates (meters)."""
    target = densify_geometry(geom) if densify else geom
    return shapely.transform(target, lambda c: _project_laea_coords(c, center_lon, center_lat))


def unproject_geometry(geom: shapely.geometry.base.BaseGeometry, center_lon: float, center_lat: float) -> shapely.geometry.base.BaseGeometry:
    """Unprojects a planar Shapely geometry (meters) back to WGS84 (degrees)."""
    return shapely.transform(geom, lambda c: _unproject_laea_coords(c, center_lon, center_lat))


def _is_temporally_applicable(
    valid_from: datetime | None,
    valid_to: datetime | None,
    win_start: datetime | None,
    win_end: datetime | None,
) -> bool:
    """Checks if geometry validity interval overlaps requested evaluation window."""
    if valid_from is not None and win_end is not None and valid_from >= win_end:
        return False
    if valid_to is not None and win_start is not None and valid_to <= win_start:
        return False
    return True


# ---------------------------------------------------------------------------
# Feature F08: Possible Monitoring Blind Spots
# ---------------------------------------------------------------------------

def compute_monitoring_blind_spots(
    snapshot: Snapshot,
    request: BlindSpotAnalysisRequest | AnalysisRequest,
) -> AnalysisResponseEnvelope[BlindSpotResult]:
    """
    Computes monitoring coverage and uncovered gap polygons within a study area (Feature F08).

    Outputs:
    - Total study area, covered area, uncovered gap area (m^2 and km^2).
    - Coverage fraction in [0.0, 1.0].
    - GeoJSON polygons representing unmonitored gap areas.
    - Explicit coverage completeness status (complete_active, complete_zero, partial, unassessed).
    """
    # 1. Revision guard
    expected_rev = request.expected_revision if hasattr(request, "expected_revision") else None
    if expected_rev is not None and expected_rev != snapshot.metadata.dataset_revision:
        return AnalysisResponseEnvelope(
            status=ResponseStatus.INVALID_REQUEST,
            dataset_revision=snapshot.metadata.dataset_revision,
            metric=AnalysisMetric.MONITORING_BLIND_SPOTS,
            warnings=[
                f"Dataset revision mismatch: request expected {expected_rev}, "
                f"snapshot is at {snapshot.metadata.dataset_revision}."
            ],
            limitations=["Analysis halted due to concurrent modification."],
        )

    # 2. CRS validation
    req_crs = getattr(request, "crs", None)
    if req_crs is None and hasattr(request, "parameters"):
        req_crs = request.parameters.get("crs")
    try:
        validate_crs(req_crs)
    except ValueError as exc:
        return AnalysisResponseEnvelope(
            status=ResponseStatus.INVALID_REQUEST,
            dataset_revision=snapshot.metadata.dataset_revision,
            metric=AnalysisMetric.MONITORING_BLIND_SPOTS,
            warnings=[str(exc)],
            limitations=["Unsupported CRS specified."],
        )

    # 3. Extract parameters
    params = request.parameters if hasattr(request, "parameters") else {}
    study_area_raw = getattr(request, "study_area_polygon", None) or params.get("study_area_polygon")
    default_radius = getattr(request, "default_coverage_radius_meters", None) or params.get("default_coverage_radius_meters", 50.0)
    scoped_cam_ids = getattr(request, "camera_ids", None) or params.get("camera_ids")
    win_start = getattr(request, "start_time", None) or params.get("start_time")
    win_end = getattr(request, "end_time", None) or params.get("end_time")
    inv_complete_flag = getattr(request, "coverage_inventory_complete", False) or params.get("coverage_inventory_complete", False)

    # Look for study area in snapshot if not in request
    if study_area_raw is None and snapshot.spatial_context and snapshot.spatial_context.zones:
        for zone in snapshot.spatial_context.zones:
            if not _is_temporally_applicable(zone.valid_from, zone.valid_to, win_start, win_end):
                continue
            if zone.zone_type in ("study_area", "reserve_boundary", "boundary", "core_reserve"):
                study_area_raw = zone.geometry
                break
        if study_area_raw is None and snapshot.spatial_context.zones:
            study_area_raw = snapshot.spatial_context.zones[0].geometry

    # Missing prerequisite check
    if study_area_raw is None:
        if snapshot.metadata.data_source_mode == DataSourceMode.DATASET_REFERENCE:
            return AnalysisResponseEnvelope(
                status=ResponseStatus.UNAVAILABLE,
                dataset_revision=snapshot.metadata.dataset_revision,
                metric=AnalysisMetric.MONITORING_BLIND_SPOTS,
                exclusion_reasons=["Missing spatial study area boundary prerequisites."],
                warnings=[
                    "Raw reference datasets (e.g. Caltech Camera Traps) do not provide study area polygons "
                    "or camera coverage geometry. Blind spot gap analysis cannot be evaluated without a designated boundary."
                ],
                limitations=["No synthetic or assumed study boundary was invented."],
            )
        return AnalysisResponseEnvelope(
            status=ResponseStatus.INVALID_REQUEST,
            dataset_revision=snapshot.metadata.dataset_revision,
            metric=AnalysisMetric.MONITORING_BLIND_SPOTS,
            warnings=["study_area_polygon is required for blind spot gap analysis."],
            limitations=["Evaluation halted."],
        )

    # Parse and validate study area
    try:
        study_area_geom = parse_and_validate_geometry(study_area_raw)
        if study_area_geom.geom_type not in ("Polygon", "MultiPolygon"):
            raise ValueError(f"Study area must be Polygon or MultiPolygon, got {study_area_geom.geom_type}")
    except Exception as exc:
        return AnalysisResponseEnvelope(
            status=ResponseStatus.INVALID_REQUEST,
            dataset_revision=snapshot.metadata.dataset_revision,
            metric=AnalysisMetric.MONITORING_BLIND_SPOTS,
            warnings=[f"Invalid study area geometry: {exc}"],
            limitations=["Geometry validation failed."],
        )

    # Center projection at study area centroid
    center_lon = float(study_area_geom.centroid.x)
    center_lat = float(study_area_geom.centroid.y)
    proj_method = (
        f"Lambert Azimuthal Equal-Area (LAEA) centered at ({center_lon:.5f}, {center_lat:.5f}) "
        f"[spherical R={EARTH_RADIUS_METERS:.1f}m]"
    )

    study_area_proj = project_geometry(study_area_geom, center_lon, center_lat)
    study_area_sq_m = float(study_area_proj.area)
    if study_area_sq_m <= 0.0:
        return AnalysisResponseEnvelope(
            status=ResponseStatus.INVALID_REQUEST,
            dataset_revision=snapshot.metadata.dataset_revision,
            metric=AnalysisMetric.MONITORING_BLIND_SPOTS,
            warnings=["Study area polygon has zero planar area."],
            limitations=["Evaluation halted."],
        )

    # 4. Collect camera coverages
    coverage_inputs = getattr(request, "camera_coverages", None) or params.get("camera_coverages", [])
    cam_coverages: list[shapely.geometry.base.BaseGeometry] = []
    active_cams_evaluated = 0
    exclusion_reasons: list[str] = []
    warnings: list[str] = []
    source_class = SpatialSourceType.ASSUMED

    snap_cams = {c.id: c for c in snapshot.cameras}
    target_cam_ids = set(scoped_cam_ids) if scoped_cam_ids is not None else set(snap_cams.keys())

    # Check temporal applicability and geometry of explicit coverages
    for cov in coverage_inputs:
        cov_obj = CameraCoverage(**cov) if isinstance(cov, dict) else cov
        if scoped_cam_ids is not None and cov_obj.camera_id not in target_cam_ids:
            continue
        if not _is_temporally_applicable(cov_obj.valid_from, cov_obj.valid_to, win_start, win_end):
            exclusion_reasons.append(
                f"Camera coverage for '{cov_obj.camera_id}' validity window [{cov_obj.valid_from}, {cov_obj.valid_to}] "
                f"does not overlap requested evaluation window."
            )
            continue
        if cov_obj.source_type:
            source_class = cov_obj.source_type
        if cov_obj.geometry:
            try:
                g = parse_and_validate_geometry(cov_obj.geometry)
                g_proj = project_geometry(g, center_lon, center_lat)
                cam_coverages.append(g_proj)
                active_cams_evaluated += 1
            except Exception as exc:
                warnings.append(f"Invalid geometry for camera {cov_obj.camera_id}: {exc}")
        elif cov_obj.camera_id in snap_cams:
            cam = snap_cams[cov_obj.camera_id]
            if cam.latitude is not None and cam.longitude is not None:
                rad = cov_obj.detection_radius_meters or default_radius
                pt_proj = project_geometry(Point(cam.longitude, cam.latitude), center_lon, center_lat)
                cam_coverages.append(pt_proj.buffer(rad))
                active_cams_evaluated += 1

    # Cameras in snapshot without explicit coverage entry
    handled_cam_ids = {cov.camera_id for cov in coverage_inputs if hasattr(cov, "camera_id")}
    for cam_id in sorted(target_cam_ids):
        if cam_id in handled_cam_ids:
            continue
        cam = snap_cams.get(cam_id)
        if cam is None:
            continue
        if cam.latitude is not None and cam.longitude is not None:
            pt_proj = project_geometry(Point(cam.longitude, cam.latitude), center_lon, center_lat)
            cam_coverages.append(pt_proj.buffer(default_radius))
            active_cams_evaluated += 1
        else:
            exclusion_reasons.append(f"Camera '{cam_id}' has no geographical coordinates; excluded from coverage.")

    # 5. Evaluate coverage completeness: absent vs complete-zero vs partial vs complete-active
    # If no camera coverages were generated:
    if not cam_coverages:
        # Check if complete-zero inventory was explicitly established
        if inv_complete_flag:
            gap_geojson = [mapping(study_area_geom)]
            result = BlindSpotResult(
                data_source_mode=snapshot.metadata.data_source_mode,
                metric=AnalysisMetric.MONITORING_BLIND_SPOTS,
                projection_method=proj_method,
                study_area_sq_meters=round(study_area_sq_m, 2),
                study_area_sq_km=round(study_area_sq_m / 1_000_000.0, 6),
                covered_area_sq_meters=0.0,
                covered_area_sq_km=0.0,
                uncovered_area_sq_meters=round(study_area_sq_m, 2),
                uncovered_area_sq_km=round(study_area_sq_m / 1_000_000.0, 6),
                coverage_fraction=0.0,
                gap_polygons_count=1,
                gap_polygons=gap_geojson,
                active_cameras_evaluated_count=0,
                is_coverage_complete=True,
                coverage_inventory_status="complete_zero",
                source_classification=source_class,
            )
            return AnalysisResponseEnvelope(
                status=ResponseStatus.OK,
                dataset_revision=snapshot.metadata.dataset_revision,
                metric=AnalysisMetric.MONITORING_BLIND_SPOTS,
                result=result,
                metric_units="square meters",
                exclusion_reasons=exclusion_reasons,
                warnings=["Complete inventory explicitly confirms zero active monitoring coverage in study area."],
                limitations=[
                    "Calculated from declared camera coverage geometry. Represents area outside declared coverage, "
                    "NOT field-validated wildlife absence or proven lack of animal occurrence."
                ],
            )
        else:
            # Absent coverage records -> INSUFFICIENT_DATA
            return AnalysisResponseEnvelope(
                status=ResponseStatus.INSUFFICIENT_DATA,
                dataset_revision=snapshot.metadata.dataset_revision,
                metric=AnalysisMetric.MONITORING_BLIND_SPOTS,
                exclusion_reasons=exclusion_reasons or ["Camera coverage records are absent or unconfigured."],
                warnings=[
                    "Camera coverage records are absent or unconfigured. Cannot perform blind spot analysis "
                    "without declared camera coverage geometry or an explicit assertion of a complete zero-coverage inventory "
                    "(coverage_inventory_complete=True)."
                ],
                limitations=["Evaluation halted due to absent coverage inventory."],
            )

    # If some cameras were excluded due to missing coordinates/coverage -> PARTIAL status
    is_partial = len(exclusion_reasons) > 0
    response_status = ResponseStatus.PARTIAL if is_partial else ResponseStatus.OK
    inv_status = "partial" if is_partial else "complete_active"

    # Union all coverage polygons and clip to study area
    coverage_union_proj = unary_union(cam_coverages)
    clipped_coverage_proj = coverage_union_proj.intersection(study_area_proj)
    covered_area_sq_m = float(clipped_coverage_proj.area)

    # Calculate gap
    gap_proj = study_area_proj.difference(clipped_coverage_proj)
    uncovered_area_sq_m = float(gap_proj.area)

    # Extract 2D polygons from gap geometry
    gap_polygons_proj: list[Polygon] = []
    if gap_proj.is_empty:
        gap_polygons_proj = []
    elif gap_proj.geom_type == "Polygon":
        gap_polygons_proj = [gap_proj]
    elif gap_proj.geom_type == "MultiPolygon":
        gap_polygons_proj = list(gap_proj.geoms)
    elif gap_proj.geom_type == "GeometryCollection":
        for g in gap_proj.geoms:
            if g.geom_type == "Polygon":
                gap_polygons_proj.append(g)
            elif g.geom_type == "MultiPolygon":
                gap_polygons_proj.extend(g.geoms)

    # Unproject gap polygons back to WGS84 GeoJSON
    gap_polygons_wgs84: list[dict[str, Any]] = []
    for gp in gap_polygons_proj:
        if gp.area > 0.01:  # Filter microscopic numerical artifacts (< 0.01 m^2)
            gp_wgs84 = unproject_geometry(gp, center_lon, center_lat)
            gap_polygons_wgs84.append(mapping(gp_wgs84))

    cov_fraction = min(1.0, max(0.0, covered_area_sq_m / study_area_sq_m))

    result = BlindSpotResult(
        data_source_mode=snapshot.metadata.data_source_mode,
        metric=AnalysisMetric.MONITORING_BLIND_SPOTS,
        projection_method=proj_method,
        study_area_sq_meters=round(study_area_sq_m, 2),
        study_area_sq_km=round(study_area_sq_m / 1_000_000.0, 6),
        covered_area_sq_meters=round(covered_area_sq_m, 2),
        covered_area_sq_km=round(covered_area_sq_m / 1_000_000.0, 6),
        uncovered_area_sq_meters=round(uncovered_area_sq_m, 2),
        uncovered_area_sq_km=round(uncovered_area_sq_m / 1_000_000.0, 6),
        coverage_fraction=round(cov_fraction, 4),
        gap_polygons_count=len(gap_polygons_wgs84),
        gap_polygons=gap_polygons_wgs84,
        active_cameras_evaluated_count=active_cams_evaluated,
        is_coverage_complete=(not is_partial),
        coverage_inventory_status=inv_status,
        source_classification=source_class,
    )

    return AnalysisResponseEnvelope(
        status=response_status,
        dataset_revision=snapshot.metadata.dataset_revision,
        metric=AnalysisMetric.MONITORING_BLIND_SPOTS,
        result=result,
        metric_units="square meters",
        exclusion_reasons=exclusion_reasons,
        warnings=warnings,
        limitations=[
            "Calculated from declared camera coverage geometry. Represents area outside declared coverage, "
            "NOT field-validated wildlife absence or proven lack of animal occurrence."
        ],
    )


# ---------------------------------------------------------------------------
# Feature F09: Candidate Camera Placement Ranking
# ---------------------------------------------------------------------------

def rank_candidate_placements(
    snapshot: Snapshot,
    request: CandidatePlacementRequest | AnalysisRequest,
) -> AnalysisResponseEnvelope[CandidatePlacementResult]:
    """
    Ranks candidate camera placement sites based on single-site marginal coverage gain (Feature F09).

    Separates eligible candidates from excluded candidates. Zero-gain feasible sites are
    classified as REDUNDANT, not physically infeasible.
    """
    # 1. Revision guard
    expected_rev = request.expected_revision if hasattr(request, "expected_revision") else None
    if expected_rev is not None and expected_rev != snapshot.metadata.dataset_revision:
        return AnalysisResponseEnvelope(
            status=ResponseStatus.INVALID_REQUEST,
            dataset_revision=snapshot.metadata.dataset_revision,
            metric=AnalysisMetric.CANDIDATE_PLACEMENT,
            warnings=[f"Dataset revision mismatch: expected {expected_rev}, got {snapshot.metadata.dataset_revision}."],
            limitations=["Analysis halted."],
        )

    # 2. CRS validation
    req_crs = getattr(request, "crs", None)
    if req_crs is None and hasattr(request, "parameters"):
        req_crs = request.parameters.get("crs")
    try:
        validate_crs(req_crs)
    except ValueError as exc:
        return AnalysisResponseEnvelope(
            status=ResponseStatus.INVALID_REQUEST,
            dataset_revision=snapshot.metadata.dataset_revision,
            metric=AnalysisMetric.CANDIDATE_PLACEMENT,
            warnings=[str(exc)],
            limitations=["Unsupported CRS specified."],
        )

    # 3. Extract parameters
    params = request.parameters if hasattr(request, "parameters") else {}
    study_area_raw = getattr(request, "study_area_polygon", None) or params.get("study_area_polygon")
    candidates_raw = getattr(request, "candidate_sites", None) or params.get("candidate_sites", [])
    exclusions_raw = getattr(request, "exclusion_zones", None) or params.get("exclusion_zones", [])
    existing_covs_raw = getattr(request, "existing_camera_coverages", None) or params.get("existing_camera_coverages", [])
    default_radius = getattr(request, "default_coverage_radius_meters", None) or params.get("default_coverage_radius_meters", 50.0)
    cost_weight = getattr(request, "cost_weight", None) if hasattr(request, "cost_weight") else params.get("cost_weight", 1.0)
    if cost_weight is None:
        cost_weight = 1.0

    if not math.isfinite(cost_weight) or cost_weight < 0.0:
        return AnalysisResponseEnvelope(
            status=ResponseStatus.INVALID_REQUEST,
            dataset_revision=snapshot.metadata.dataset_revision,
            metric=AnalysisMetric.CANDIDATE_PLACEMENT,
            warnings=[f"cost_weight must be a finite non-negative number, got {cost_weight}"],
            limitations=["Evaluation halted."],
        )

    # Look for study area in snapshot if not in request
    if study_area_raw is None and snapshot.spatial_context and snapshot.spatial_context.zones:
        for zone in snapshot.spatial_context.zones:
            if zone.zone_type in ("study_area", "reserve_boundary", "boundary", "core_reserve"):
                study_area_raw = zone.geometry
                break
        if study_area_raw is None and snapshot.spatial_context.zones:
            study_area_raw = snapshot.spatial_context.zones[0].geometry

    if study_area_raw is None:
        if snapshot.metadata.data_source_mode == DataSourceMode.DATASET_REFERENCE:
            return AnalysisResponseEnvelope(
                status=ResponseStatus.UNAVAILABLE,
                dataset_revision=snapshot.metadata.dataset_revision,
                metric=AnalysisMetric.CANDIDATE_PLACEMENT,
                exclusion_reasons=["Missing study area boundary and candidate sites in reference dataset."],
                warnings=["Candidate placement ranking requires a defined study area and candidate site geometries."],
                limitations=["No synthetic candidates were invented."],
            )
        return AnalysisResponseEnvelope(
            status=ResponseStatus.INVALID_REQUEST,
            dataset_revision=snapshot.metadata.dataset_revision,
            metric=AnalysisMetric.CANDIDATE_PLACEMENT,
            warnings=["study_area_polygon is required for candidate placement ranking."],
            limitations=["Evaluation halted."],
        )

    try:
        study_area_geom = parse_and_validate_geometry(study_area_raw)
    except Exception as exc:
        return AnalysisResponseEnvelope(
            status=ResponseStatus.INVALID_REQUEST,
            dataset_revision=snapshot.metadata.dataset_revision,
            metric=AnalysisMetric.CANDIDATE_PLACEMENT,
            warnings=[f"Invalid study area geometry: {exc}"],
            limitations=["Geometry validation failed."],
        )

    center_lon = float(study_area_geom.centroid.x)
    center_lat = float(study_area_geom.centroid.y)
    proj_method = (
        f"Lambert Azimuthal Equal-Area (LAEA) centered at ({center_lon:.5f}, {center_lat:.5f}) "
        f"[spherical R={EARTH_RADIUS_METERS:.1f}m]"
    )
    study_area_proj = project_geometry(study_area_geom, center_lon, center_lat)
    study_area_sq_m = float(study_area_proj.area)

    # 4. Parse existing baseline coverage
    baseline_coverages_proj: list[shapely.geometry.base.BaseGeometry] = []
    snap_cams = {c.id: c for c in snapshot.cameras}
    for cov in existing_covs_raw:
        cov_obj = CameraCoverage(**cov) if isinstance(cov, dict) else cov
        if cov_obj.geometry:
            g = parse_and_validate_geometry(cov_obj.geometry)
            baseline_coverages_proj.append(project_geometry(g, center_lon, center_lat))
        elif cov_obj.camera_id in snap_cams:
            cam = snap_cams[cov_obj.camera_id]
            if cam.latitude is not None and cam.longitude is not None:
                rad = cov_obj.detection_radius_meters or default_radius
                pt_proj = project_geometry(Point(cam.longitude, cam.latitude), center_lon, center_lat)
                baseline_coverages_proj.append(pt_proj.buffer(rad))

    if not existing_covs_raw and snapshot.cameras:
        for cam in snapshot.cameras:
            if cam.latitude is not None and cam.longitude is not None:
                pt_proj = project_geometry(Point(cam.longitude, cam.latitude), center_lon, center_lat)
                baseline_coverages_proj.append(pt_proj.buffer(default_radius))

    baseline_covered_proj = (
        unary_union(baseline_coverages_proj).intersection(study_area_proj)
        if baseline_coverages_proj
        else Polygon()
    )
    baseline_covered_sq_m = float(baseline_covered_proj.area)
    baseline_cov_fraction = min(1.0, max(0.0, baseline_covered_sq_m / study_area_sq_m)) if study_area_sq_m > 0 else 0.0

    # 5. Parse exclusion zones
    exclusion_geoms_proj: list[shapely.geometry.base.BaseGeometry] = []
    for ex in exclusions_raw:
        ex_geom_dict = ex.geometry if hasattr(ex, "geometry") else (ex.get("geometry") if isinstance(ex, dict) else ex)
        if ex_geom_dict:
            g = parse_and_validate_geometry(ex_geom_dict)
            exclusion_geoms_proj.append(project_geometry(g, center_lon, center_lat))

    if snapshot.spatial_context and snapshot.spatial_context.zones:
        for z in snapshot.spatial_context.zones:
            if "exclusion" in z.zone_type.lower() or "inaccessible" in z.zone_type.lower():
                g = parse_and_validate_geometry(z.geometry)
                exclusion_geoms_proj.append(project_geometry(g, center_lon, center_lat))

    exclusions_union_proj = unary_union(exclusion_geoms_proj) if exclusion_geoms_proj else Polygon()

    # 6. Evaluate candidate sites
    if not candidates_raw and snapshot.spatial_context and snapshot.spatial_context.candidate_sites:
        candidates_raw = snapshot.spatial_context.candidate_sites

    if not candidates_raw:
        return AnalysisResponseEnvelope(
            status=ResponseStatus.INSUFFICIENT_DATA,
            dataset_revision=snapshot.metadata.dataset_revision,
            metric=AnalysisMetric.CANDIDATE_PLACEMENT,
            warnings=["No candidate placement sites provided or found in snapshot."],
            limitations=["Zero candidates evaluated."],
        )

    eligible_items: list[CandidatePlacementItem] = []
    excluded_items: list[CandidatePlacementItem] = []
    feasible_count = 0
    excluded_count = 0

    for cand_raw in candidates_raw:
        try:
            cand = CandidateSite(**cand_raw) if isinstance(cand_raw, dict) else cand_raw
        except Exception as exc:
            return AnalysisResponseEnvelope(
                status=ResponseStatus.INVALID_REQUEST,
                dataset_revision=snapshot.metadata.dataset_revision,
                metric=AnalysisMetric.CANDIDATE_PLACEMENT,
                warnings=[f"Invalid candidate site input: {exc}"],
                limitations=["Evaluation halted."],
            )

        c_id = cand.candidate_id
        c_cost = cand.cost
        c_rad = cand.coverage_radius_meters or default_radius

        cand_geom_proj: shapely.geometry.base.BaseGeometry | None = None
        cand_pt_proj: Point | None = None

        if cand.geometry:
            g = parse_and_validate_geometry(cand.geometry)
            cand_geom_proj = project_geometry(g, center_lon, center_lat)
            cand_pt_proj = cand_geom_proj.centroid
        elif cand.latitude is not None and cand.longitude is not None:
            cand_pt_proj = project_geometry(Point(cand.longitude, cand.latitude), center_lon, center_lat)
            cand_geom_proj = cand_pt_proj.buffer(c_rad)
        else:
            continue

        # Check exclusion zone intersection with candidate deployment location
        is_excluded = False
        ex_reasons: list[str] = []
        if not exclusions_union_proj.is_empty and cand_pt_proj is not None:
            if exclusions_union_proj.intersects(cand_pt_proj):
                is_excluded = True
                ex_reasons.append("Candidate site location falls within a designated exclusion zone.")

        if is_excluded:
            excluded_count += 1
            excluded_items.append(
                CandidatePlacementItem(
                    candidate_id=c_id,
                    rank=None,  # Excluded sites are not assigned eligible ranks
                    status=CandidatePlacementStatus.EXCLUDED,
                    marginal_coverage_gain_sq_meters=0.0,
                    marginal_coverage_gain_sq_km=0.0,
                    score=0.0,
                    cost=round(c_cost, 2),
                    overlap_with_baseline_sq_meters=0.0,
                    is_in_exclusion_zone=True,
                    exclusion_reasons=ex_reasons,
                    notes="Excluded from placement consideration due to terrain, legal, or accessibility constraints.",
                )
            )
            continue

        # Effective candidate coverage clipped to study area and minus exclusions
        cand_effective = cand_geom_proj.intersection(study_area_proj)
        if not exclusions_union_proj.is_empty:
            cand_effective = cand_effective.difference(exclusions_union_proj)

        # Marginal gain
        marginal_geom = cand_effective.difference(baseline_covered_proj)
        marginal_gain_sq_m = float(marginal_geom.area)

        # Overlap with baseline
        overlap_geom = cand_effective.intersection(baseline_covered_proj)
        overlap_sq_m = float(overlap_geom.area)

        status = (
            CandidatePlacementStatus.FEASIBLE
            if marginal_gain_sq_m > 0.1
            else CandidatePlacementStatus.REDUNDANT
        )
        if status == CandidatePlacementStatus.FEASIBLE:
            feasible_count += 1

        # Efficiency score: marginal_gain / (cost ^ cost_weight)
        score = marginal_gain_sq_m / (c_cost ** cost_weight) if marginal_gain_sq_m > 0 else 0.0

        notes = (
            f"Provides {marginal_gain_sq_m:.1f} m^2 marginal coverage gain."
            if status == CandidatePlacementStatus.FEASIBLE
            else "Candidate site is physically feasible, but provides 0.0 m^2 marginal coverage gain over existing baseline deployment."
        )

        eligible_items.append(
            CandidatePlacementItem(
                candidate_id=c_id,
                rank=None,
                status=status,
                marginal_coverage_gain_sq_meters=round(marginal_gain_sq_m, 2),
                marginal_coverage_gain_sq_km=round(marginal_gain_sq_m / 1_000_000.0, 6),
                score=round(score, 4),
                cost=round(c_cost, 2),
                overlap_with_baseline_sq_meters=round(overlap_sq_m, 2),
                is_in_exclusion_zone=False,
                notes=notes,
            )
        )

    # 7. Rank eligible candidates separately from excluded
    # Priority: FEASIBLE before REDUNDANT
    status_order = {
        CandidatePlacementStatus.FEASIBLE: 0,
        CandidatePlacementStatus.REDUNDANT: 1,
    }

    eligible_items.sort(
        key=lambda item: (
            status_order.get(item.status, 9),
            -item.score,
            -item.marginal_coverage_gain_sq_meters,
            item.cost,
            item.candidate_id,
        )
    )

    # Assign final sequential ranks to eligible candidates only
    for rank_idx, item in enumerate(eligible_items, 1):
        item.rank = rank_idx

    result = CandidatePlacementResult(
        data_source_mode=snapshot.metadata.data_source_mode,
        metric=AnalysisMetric.CANDIDATE_PLACEMENT,
        projection_method=proj_method,
        study_area_sq_meters=round(study_area_sq_m, 2),
        baseline_covered_area_sq_meters=round(baseline_covered_sq_m, 2),
        baseline_coverage_fraction=round(baseline_cov_fraction, 4),
        ranked_candidates=eligible_items,
        excluded_candidates=excluded_items,
        total_candidates=len(eligible_items) + len(excluded_items),
        feasible_candidates_count=feasible_count,
        excluded_candidates_count=excluded_count,
    )

    return AnalysisResponseEnvelope(
        status=ResponseStatus.OK,
        dataset_revision=snapshot.metadata.dataset_revision,
        metric=AnalysisMetric.CANDIDATE_PLACEMENT,
        result=result,
        metric_units="square meters",
        limitations=[
            "Candidate ranks reflect single-site marginal coverage gain over the baseline. "
            "Marginal gains are NOT additive; placing multiple candidates simultaneously requires joint "
            "combinatorial evaluation as candidate viewsheds may overlap. Excluded candidates are evaluated separately."
        ],
    )


# ---------------------------------------------------------------------------
# Feature F14: Geofencing & Proximity Indicators
# ---------------------------------------------------------------------------

def compute_proximity_indicators(
    snapshot: Snapshot,
    request: ProximityAnalysisRequest | AnalysisRequest,
) -> AnalysisResponseEnvelope[ProximityResult]:
    """
    Computes geometric proximity and topological relations between target locations
    and spatial zones or infrastructure (Feature F14).

    Distinguishes:
    - Fixed camera sites from modeled animal positions.
    - Region interior distance (0.0 if inside) from boundary distance.
    - Boundary intersection from positional uncertainty overlap (indeterminate).
    - Threshold uncertainty: when positional uncertainty straddles the threshold.
    - Polygon holes: points inside holes are correctly treated as outside the region.
    """
    # 1. Revision guard
    expected_rev = request.expected_revision if hasattr(request, "expected_revision") else None
    if expected_rev is not None and expected_rev != snapshot.metadata.dataset_revision:
        return AnalysisResponseEnvelope(
            status=ResponseStatus.INVALID_REQUEST,
            dataset_revision=snapshot.metadata.dataset_revision,
            metric=AnalysisMetric.PROXIMITY_INDICATORS,
            warnings=[f"Dataset revision mismatch: expected {expected_rev}, got {snapshot.metadata.dataset_revision}."],
            limitations=["Analysis halted."],
        )

    # 2. CRS validation
    req_crs = getattr(request, "crs", None)
    if req_crs is None and hasattr(request, "parameters"):
        req_crs = request.parameters.get("crs")
    try:
        validate_crs(req_crs)
    except ValueError as exc:
        return AnalysisResponseEnvelope(
            status=ResponseStatus.INVALID_REQUEST,
            dataset_revision=snapshot.metadata.dataset_revision,
            metric=AnalysisMetric.PROXIMITY_INDICATORS,
            warnings=[str(exc)],
            limitations=["Unsupported CRS specified."],
        )

    # 3. Extract targets
    params = request.parameters if hasattr(request, "parameters") else {}
    targets_raw = getattr(request, "target_locations", None) or params.get("target_locations", [])
    zones_raw = getattr(request, "zones", None) or params.get("zones", [])
    threshold_m = getattr(request, "proximity_threshold_meters", None) if hasattr(request, "proximity_threshold_meters") else params.get("proximity_threshold_meters", 100.0)
    if threshold_m is None:
        threshold_m = 100.0

    if not math.isfinite(threshold_m) or threshold_m < 0.0:
        return AnalysisResponseEnvelope(
            status=ResponseStatus.INVALID_REQUEST,
            dataset_revision=snapshot.metadata.dataset_revision,
            metric=AnalysisMetric.PROXIMITY_INDICATORS,
            warnings=[f"proximity_threshold_meters must be a finite non-negative number, got {threshold_m}"],
            limitations=["Evaluation halted."],
        )

    targets: list[TargetLocation] = []
    if targets_raw:
        for t in targets_raw:
            targets.append(TargetLocation(**t) if isinstance(t, dict) else t)
    elif snapshot.cameras:
        for cam in snapshot.cameras:
            if cam.latitude is not None and cam.longitude is not None:
                targets.append(
                    TargetLocation(
                        target_id=cam.id,
                        position_type=PositionType.CAMERA_SITE,
                        latitude=cam.latitude,
                        longitude=cam.longitude,
                        associated_camera_id=cam.id,
                    )
                )

    if not targets:
        if snapshot.metadata.data_source_mode == DataSourceMode.DATASET_REFERENCE:
            return AnalysisResponseEnvelope(
                status=ResponseStatus.UNAVAILABLE,
                dataset_revision=snapshot.metadata.dataset_revision,
                metric=AnalysisMetric.PROXIMITY_INDICATORS,
                exclusion_reasons=["Missing target coordinates in reference dataset."],
                warnings=["Caltech reference dataset does not provide camera GPS coordinates for proximity evaluation."],
                limitations=["No synthetic coordinates were invented."],
            )
        return AnalysisResponseEnvelope(
            status=ResponseStatus.UNAVAILABLE,
            dataset_revision=snapshot.metadata.dataset_revision,
            metric=AnalysisMetric.PROXIMITY_INDICATORS,
            warnings=["No target locations with valid coordinates found or provided for proximity analysis."],
            limitations=["Evaluation halted."],
        )

    zones: list[SpatialZone] = []
    if zones_raw:
        for z in zones_raw:
            zones.append(SpatialZone(**z) if isinstance(z, dict) else z)
    elif snapshot.spatial_context and snapshot.spatial_context.zones:
        zones.extend(snapshot.spatial_context.zones)

    if not zones:
        return AnalysisResponseEnvelope(
            status=ResponseStatus.UNAVAILABLE,
            dataset_revision=snapshot.metadata.dataset_revision,
            metric=AnalysisMetric.PROXIMITY_INDICATORS,
            warnings=["No spatial zones or infrastructure features provided or found in snapshot."],
            limitations=["Evaluation halted."],
        )

    # 4. Projection center from targets and zones
    all_lons = [t.longitude for t in targets]
    all_lats = [t.latitude for t in targets]
    center_lon = float(np.mean(all_lons))
    center_lat = float(np.mean(all_lats))
    proj_method = (
        f"Lambert Azimuthal Equal-Area (LAEA) centered at ({center_lon:.5f}, {center_lat:.5f}) "
        f"[spherical R={EARTH_RADIUS_METERS:.1f}m]"
    )

    evaluations: list[TargetProximityItem] = []

    for t in targets:
        t_pt_proj = project_geometry(Point(t.longitude, t.latitude), center_lon, center_lat, densify=False)
        u_raw = t.uncertainty_radius_meters
        u_assessed = u_raw is not None
        u_rad = float(u_raw) if u_assessed else 0.0
        u_status = "assessed" if u_assessed else "unassessed"

        for z in zones:
            try:
                z_geom = parse_and_validate_geometry(z.geometry)
                z_proj = project_geometry(z_geom, center_lon, center_lat, densify=True)
            except Exception as exc:
                continue

            warning_msg = None
            if z_proj.geom_type in ("Polygon", "MultiPolygon"):
                # Region interior check
                is_inside = z_proj.contains(t_pt_proj) or z_proj.intersects(t_pt_proj)
                boundary_dist = float(z_proj.boundary.distance(t_pt_proj))

                if is_inside:
                    region_dist = 0.0
                    # Zero uncertainty on boundary remains BOUNDARY
                    if boundary_dist <= 1e-3 and u_rad == 0.0:
                        rel = ProximityRelation.BOUNDARY
                    elif u_rad > 0.0 and u_rad >= boundary_dist:
                        rel = ProximityRelation.INDETERMINATE
                        warning_msg = (
                            f"Positional uncertainty radius ({u_rad:.1f}m) overlaps zone boundary "
                            f"(distance to boundary: {boundary_dist:.1f}m)."
                        )
                    else:
                        rel = ProximityRelation.INSIDE
                else:
                    region_dist = float(z_proj.distance(t_pt_proj))
                    boundary_dist = region_dist
                    if boundary_dist <= 1e-3 and u_rad == 0.0:
                        rel = ProximityRelation.BOUNDARY
                    elif u_rad > 0.0 and u_rad >= region_dist:
                        rel = ProximityRelation.INDETERMINATE
                        warning_msg = (
                            f"Positional uncertainty radius ({u_rad:.1f}m) overlaps zone boundary "
                            f"(distance to boundary: {boundary_dist:.1f}m)."
                        )
                    else:
                        rel = ProximityRelation.OUTSIDE
            else:
                # Linear or point infrastructure
                dist_to_feature = float(z_proj.distance(t_pt_proj))
                region_dist = dist_to_feature
                boundary_dist = dist_to_feature

                if dist_to_feature <= 1e-3 and u_rad == 0.0:
                    rel = ProximityRelation.BOUNDARY
                elif u_rad > 0.0 and u_rad >= dist_to_feature:
                    rel = ProximityRelation.INDETERMINATE
                    warning_msg = (
                        f"Positional uncertainty radius ({u_rad:.1f}m) overlaps infrastructure feature "
                        f"(distance: {dist_to_feature:.1f}m)."
                    )
                else:
                    rel = ProximityRelation.OUTSIDE

            # Proximity threshold evaluation with uncertainty propagation
            within_thresh = region_dist <= threshold_m
            min_possible_dist = max(0.0, region_dist - u_rad)
            max_possible_dist = region_dist + u_rad

            if u_rad == 0.0:
                thresh_status = "definitely_within" if within_thresh else "definitely_outside"
            else:
                if max_possible_dist <= threshold_m:
                    thresh_status = "definitely_within"
                elif min_possible_dist > threshold_m:
                    thresh_status = "definitely_outside"
                else:
                    thresh_status = "uncertain"
                    thresh_note = (
                        f"Positional uncertainty radius ({u_rad:.1f}m) straddles proximity threshold "
                        f"({threshold_m:.1f}m): possible range [{min_possible_dist:.1f}m, {max_possible_dist:.1f}m]."
                    )
                    warning_msg = (warning_msg + " " + thresh_note) if warning_msg else thresh_note

            # Clear descriptive labeling
            if t.position_type == PositionType.CAMERA_SITE:
                pos_desc = (
                    f"Camera/site proximity indicator: Camera '{t.target_id}' is {rel.value} "
                    f"'{z.name}' (region distance: {region_dist:.1f}m, boundary distance: {boundary_dist:.1f}m). "
                    "Reflects physical device placement; not an animal geofence crossing."
                )
            elif t.position_type == PositionType.ESTIMATED_ANIMAL_POSITION:
                pos_desc = (
                    f"Estimated animal proximity indicator: Target '{t.target_id}' is {rel.value} "
                    f"'{z.name}' (region distance: {region_dist:.1f}m, boundary distance: {boundary_dist:.1f}m)."
                )
            else:
                pos_desc = (
                    f"Observation proximity indicator: Target '{t.target_id}' is {rel.value} "
                    f"'{z.name}' (distance: {region_dist:.1f}m)."
                )

            evaluations.append(
                TargetProximityItem(
                    target_id=t.target_id,
                    position_type=t.position_type,
                    zone_id=z.id,
                    zone_name=z.name,
                    zone_type=z.zone_type,
                    relation=rel,
                    region_distance_meters=round(region_dist, 2),
                    boundary_distance_meters=round(boundary_dist, 2),
                    within_threshold=within_thresh,
                    threshold_status=thresh_status,
                    proximity_threshold_meters=round(threshold_m, 2),
                    uncertainty_radius_meters=round(u_rad, 2),
                    uncertainty_status=u_status,
                    position_description=pos_desc,
                    warning=warning_msg,
                )
            )

    result = ProximityResult(
        data_source_mode=snapshot.metadata.data_source_mode,
        metric=AnalysisMetric.PROXIMITY_INDICATORS,
        projection_method=proj_method,
        targets_evaluated_count=len(targets),
        zones_evaluated_count=len(zones),
        evaluations=evaluations,
    )

    return AnalysisResponseEnvelope(
        status=ResponseStatus.OK,
        dataset_revision=snapshot.metadata.dataset_revision,
        metric=AnalysisMetric.PROXIMITY_INDICATORS,
        result=result,
        metric_units="meters",
        limitations=[
            "Proximity indicators reflect geometric distance between supplied coordinates and zone boundaries. "
            "For camera sites, this indicates physical device placement proximity, NOT animal geofence crossing. "
            "Positional uncertainty can cause indeterminate boundary and threshold relations. Descriptive indicator only; "
            "no threat or danger score is assigned."
        ],
    )


# ---------------------------------------------------------------------------
# Feature F16: Wildlife-Infrastructure Scenarios
# ---------------------------------------------------------------------------

def evaluate_infrastructure_scenario(
    snapshot: Snapshot,
    request: InfrastructureScenarioRequest | AnalysisRequest,
) -> AnalysisResponseEnvelope[InfrastructureScenarioResult]:
    """
    Evaluates what-if spatial scenarios (e.g. proposed roads, buffers, hypothetical cameras)
    against baseline camera trap coverage in an isolated, non-mutating manner (Feature F16).
    """
    # 1. Revision guard
    expected_rev = request.expected_revision if hasattr(request, "expected_revision") else None
    if expected_rev is not None and expected_rev != snapshot.metadata.dataset_revision:
        return AnalysisResponseEnvelope(
            status=ResponseStatus.INVALID_REQUEST,
            dataset_revision=snapshot.metadata.dataset_revision,
            metric=AnalysisMetric.INFRASTRUCTURE_SCENARIO,
            warnings=[f"Dataset revision mismatch: expected {expected_rev}, got {snapshot.metadata.dataset_revision}."],
            limitations=["Analysis halted."],
        )

    # 2. CRS validation
    req_crs = getattr(request, "crs", None)
    if req_crs is None and hasattr(request, "parameters"):
        req_crs = request.parameters.get("crs")
    try:
        validate_crs(req_crs)
    except ValueError as exc:
        return AnalysisResponseEnvelope(
            status=ResponseStatus.INVALID_REQUEST,
            dataset_revision=snapshot.metadata.dataset_revision,
            metric=AnalysisMetric.INFRASTRUCTURE_SCENARIO,
            warnings=[str(exc)],
            limitations=["Unsupported CRS specified."],
        )

    # 3. Extract parameters
    params = request.parameters if hasattr(request, "parameters") else {}
    scen_id = getattr(request, "scenario_id", None) or params.get("scenario_id", "scenario_01")
    scen_name = getattr(request, "scenario_name", None) or params.get("scenario_name", "Hypothetical Scenario")
    study_area_raw = getattr(request, "study_area_polygon", None) or params.get("study_area_polygon")
    hypo_features = getattr(request, "hypothetical_features", None) or params.get("hypothetical_features", [])
    assumptions = list(getattr(request, "assumptions", None) or params.get("assumptions", []))
    default_radius = getattr(request, "default_coverage_radius_meters", None) or params.get("default_coverage_radius_meters", 50.0)

    # Find study area in snapshot if not in request
    if study_area_raw is None and snapshot.spatial_context and snapshot.spatial_context.zones:
        for zone in snapshot.spatial_context.zones:
            if zone.zone_type in ("study_area", "reserve_boundary", "boundary", "core_reserve"):
                study_area_raw = zone.geometry
                break
        if study_area_raw is None and snapshot.spatial_context.zones:
            study_area_raw = snapshot.spatial_context.zones[0].geometry

    if study_area_raw is None:
        if snapshot.metadata.data_source_mode == DataSourceMode.DATASET_REFERENCE:
            return AnalysisResponseEnvelope(
                status=ResponseStatus.UNAVAILABLE,
                dataset_revision=snapshot.metadata.dataset_revision,
                metric=AnalysisMetric.INFRASTRUCTURE_SCENARIO,
                exclusion_reasons=["Missing study area boundary in reference dataset."],
                warnings=["Scenario analysis requires a defined study area polygon."],
                limitations=["No synthetic scenario boundary was invented."],
            )
        return AnalysisResponseEnvelope(
            status=ResponseStatus.INVALID_REQUEST,
            dataset_revision=snapshot.metadata.dataset_revision,
            metric=AnalysisMetric.INFRASTRUCTURE_SCENARIO,
            warnings=["study_area_polygon is required for infrastructure scenario evaluation."],
            limitations=["Evaluation halted."],
        )

    # Validate study area
    try:
        study_area_geom = parse_and_validate_geometry(study_area_raw)
    except Exception as exc:
        return AnalysisResponseEnvelope(
            status=ResponseStatus.INVALID_REQUEST,
            dataset_revision=snapshot.metadata.dataset_revision,
            metric=AnalysisMetric.INFRASTRUCTURE_SCENARIO,
            warnings=[f"Invalid study area geometry: {exc}"],
            limitations=["Geometry validation failed."],
        )

    center_lon = float(study_area_geom.centroid.x)
    center_lat = float(study_area_geom.centroid.y)
    proj_method = (
        f"Lambert Azimuthal Equal-Area (LAEA) centered at ({center_lon:.5f}, {center_lat:.5f}) "
        f"[spherical R={EARTH_RADIUS_METERS:.1f}m]"
    )
    study_area_proj = project_geometry(study_area_geom, center_lon, center_lat)
    study_area_sq_m = float(study_area_proj.area)

    # 4. Compute baseline coverage
    baseline_coverages_proj: list[shapely.geometry.base.BaseGeometry] = []
    base_cov_raw = getattr(request, "baseline_camera_coverages", None) or params.get("baseline_camera_coverages", [])

    snap_cams = {c.id: c for c in snapshot.cameras}
    for cov in base_cov_raw:
        cov_obj = CameraCoverage(**cov) if isinstance(cov, dict) else cov
        if cov_obj.geometry:
            g = parse_and_validate_geometry(cov_obj.geometry)
            baseline_coverages_proj.append(project_geometry(g, center_lon, center_lat))
        elif cov_obj.camera_id in snap_cams:
            cam = snap_cams[cov_obj.camera_id]
            if cam.latitude is not None and cam.longitude is not None:
                rad = cov_obj.detection_radius_meters or default_radius
                pt_proj = project_geometry(Point(cam.longitude, cam.latitude), center_lon, center_lat)
                baseline_coverages_proj.append(pt_proj.buffer(rad))

    if not base_cov_raw and snapshot.cameras:
        for cam in snapshot.cameras:
            if cam.latitude is not None and cam.longitude is not None:
                pt_proj = project_geometry(Point(cam.longitude, cam.latitude), center_lon, center_lat)
                baseline_coverages_proj.append(pt_proj.buffer(default_radius))

    baseline_covered_proj = (
        unary_union(baseline_coverages_proj).intersection(study_area_proj)
        if baseline_coverages_proj
        else Polygon()
    )
    base_covered_sq_m = float(baseline_covered_proj.area)
    base_fraction = min(1.0, max(0.0, base_covered_sq_m / study_area_sq_m)) if study_area_sq_m > 0 else 0.0

    # 5. Apply hypothetical features to create scenario geometry
    scenario_coverages_proj = list(baseline_coverages_proj)
    hypo_applied_summary: list[dict[str, Any]] = []
    hypo_subtractions_proj: list[shapely.geometry.base.BaseGeometry] = []

    for f_idx, feat in enumerate(hypo_features):
        feat_type = feat.get("type", "unknown")
        feat_name = feat.get("name", f"hypothetical_feature_{f_idx+1}")
        feat_geom_dict = feat.get("geometry")
        feat_buffer = feat.get("buffer_meters", 0.0)

        if not feat_geom_dict:
            continue

        try:
            g = parse_and_validate_geometry(feat_geom_dict)
            g_proj = project_geometry(g, center_lon, center_lat)

            if feat_buffer > 0.0:
                g_proj = g_proj.buffer(feat_buffer)

            # Classify role of feature
            if feat_type in ("proposed_camera", "coverage_addition"):
                scenario_coverages_proj.append(g_proj)
                hypo_applied_summary.append({
                    "name": feat_name,
                    "type": feat_type,
                    "action": "added_coverage",
                    "buffer_meters": feat_buffer,
                })
            elif feat_type in ("road", "road_corridor", "exclusion_zone", "infrastructure_development"):
                hypo_subtractions_proj.append(g_proj)
                hypo_applied_summary.append({
                    "name": feat_name,
                    "type": feat_type,
                    "action": "excluded_from_monitoring",
                    "buffer_meters": feat_buffer,
                })
            else:
                scenario_coverages_proj.append(g_proj)
                hypo_applied_summary.append({
                    "name": feat_name,
                    "type": feat_type,
                    "action": "added_coverage",
                })
        except Exception as exc:
            hypo_applied_summary.append({
                "name": feat_name,
                "error": str(exc),
            })

    # Scenario coverage
    scenario_cov_union = (
        unary_union(scenario_coverages_proj).intersection(study_area_proj)
        if scenario_coverages_proj
        else Polygon()
    )

    if hypo_subtractions_proj:
        sub_union = unary_union(hypo_subtractions_proj)
        scenario_cov_union = scenario_cov_union.difference(sub_union)

    scen_covered_sq_m = float(scenario_cov_union.area)
    scen_fraction = min(1.0, max(0.0, scen_covered_sq_m / study_area_sq_m)) if study_area_sq_m > 0 else 0.0

    abs_change_sq_m = scen_covered_sq_m - base_covered_sq_m
    rel_change_frac = (
        (scen_fraction - base_fraction) / base_fraction
        if base_fraction > 0.0
        else None
    )

    if not assumptions:
        assumptions = [
            "All hypothetical features are strictly exploratory planning scenarios.",
            "Baseline camera positions and operational coverage remain unchanged unless explicitly modified.",
            "No behavioral displacement, barrier avoidance, or demographic changes are simulated.",
        ]

    result = InfrastructureScenarioResult(
        scenario_id=scen_id,
        scenario_name=scen_name,
        projection_method=proj_method,
        source_classification=SpatialSourceType.HYPOTHETICAL,
        study_area_sq_meters=round(study_area_sq_m, 2),
        baseline_covered_sq_meters=round(base_covered_sq_m, 2),
        baseline_coverage_fraction=round(base_fraction, 4),
        scenario_covered_sq_meters=round(scen_covered_sq_m, 2),
        scenario_coverage_fraction=round(scen_fraction, 4),
        absolute_change_sq_meters=round(abs_change_sq_m, 2),
        relative_change_fraction=round(rel_change_frac, 4) if rel_change_frac is not None else None,
        hypothetical_features_applied=hypo_applied_summary,
        assumptions=assumptions,
    )

    return AnalysisResponseEnvelope(
        status=ResponseStatus.OK,
        dataset_revision=snapshot.metadata.dataset_revision,
        metric=AnalysisMetric.INFRASTRUCTURE_SCENARIO,
        result=result,
        metric_units="square meters",
        limitations=[
            "Hypothetical scenario analysis only. Evaluates geometric coverage and proximity changes "
            "under explicit assumptions. Does not predict ecological impacts, animal movement route displacement, "
            "or population viability changes."
        ],
    )
