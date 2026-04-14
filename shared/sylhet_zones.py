"""
shared/sylhet_zones.py
=======================
Single source of truth for Sylhet Division geography.

Content:
  - 4 districts (Sylhet, Moulvibazar, Habiganj, Sunamganj)
  - 39 upazilas with exact lat/lng and river assignments
  - 8 river definitions with danger levels and base water levels
  - Helper lookups for agents and dashboard

Sources:
  - Jubair's frontend/utils/data.py (lines 23-113)
  - OpenStreetMap Bangladesh
  - Flood Forecasting & Warning Centre (FFWC) Bangladesh
  - OCHA Bangladesh Flash Flood Situation Reports (June 2022)
"""

from typing import Dict, List, Optional

# ──────────────────────────────────────────────────────────────────────
# SYLHET DIVISION METADATA
# ──────────────────────────────────────────────────────────────────────

SYLHET_DIVISION = {
    "name": "Sylhet Division",
    "center": {"lat": 24.3636, "lon": 91.8337},
    "bbox": {"south": 23.9, "west": 91.0, "north": 25.2, "east": 92.6},
}

# ──────────────────────────────────────────────────────────────────────
# DISTRICTS & UPAZILAS (39 total)
# ──────────────────────────────────────────────────────────────────────

SYLHET_DISTRICTS: Dict[str, Dict] = {
    "sylhet": {
        "name": "Sylhet",
        "bangla": "সিলেট",
        "center": {"lat": 24.8949, "lon": 91.8687},
        "color": "#e74c3c",
        "upazilas": [
            {"name": "Sylhet Sadar",  "lat": 24.8949, "lon": 91.8687, "river": "Surma"},
            {"name": "Beanibazar",    "lat": 24.7611, "lon": 92.0189, "river": "Kushiyara"},
            {"name": "Bishwanath",    "lat": 24.8659, "lon": 91.9819, "river": "Surma"},
            {"name": "Companiganj",   "lat": 25.1167, "lon": 91.9500, "river": "Surma"},
            {"name": "Fenchuganj",    "lat": 24.7667, "lon": 91.9000, "river": "Kushiyara"},
            {"name": "Golapganj",     "lat": 24.7667, "lon": 91.9833, "river": "Surma"},
            {"name": "Gowainghat",    "lat": 25.0167, "lon": 91.9500, "river": "Piyain"},
            {"name": "Jaintiapur",    "lat": 25.0833, "lon": 92.1167, "river": "Saree"},
            {"name": "Kanaighat",     "lat": 25.0000, "lon": 92.2000, "river": "Surma"},
            {"name": "Osmani Nagar",  "lat": 24.8333, "lon": 92.0000, "river": "Kushiyara"},
            {"name": "South Surma",   "lat": 24.8333, "lon": 91.8000, "river": "Surma"},
            {"name": "Zakiganj",      "lat": 24.7667, "lon": 92.1833, "river": "Kushiyara"},
            {"name": "Balaganj",      "lat": 24.7333, "lon": 91.8000, "river": "Surma"},
        ],
    },
    "moulvibazar": {
        "name": "Moulvibazar",
        "bangla": "মৌলভীবাজার",
        "center": {"lat": 24.4827, "lon": 91.7773},
        "color": "#e67e22",
        "upazilas": [
            {"name": "Moulvibazar Sadar", "lat": 24.4827, "lon": 91.7773, "river": "Manu"},
            {"name": "Barlekha",          "lat": 24.6167, "lon": 92.1667, "river": "Juri"},
            {"name": "Juri",              "lat": 24.5500, "lon": 92.0833, "river": "Juri"},
            {"name": "Kamalganj",         "lat": 24.3833, "lon": 91.8500, "river": "Manu"},
            {"name": "Kulaura",           "lat": 24.5333, "lon": 92.0167, "river": "Manu"},
            {"name": "Rajnagar",          "lat": 24.3333, "lon": 91.8833, "river": "Manu"},
            {"name": "Sreemangal",        "lat": 24.3000, "lon": 91.7333, "river": "Balu"},
        ],
    },
    "habiganj": {
        "name": "Habiganj",
        "bangla": "হবিগঞ্জ",
        "center": {"lat": 24.3745, "lon": 91.4153},
        "color": "#27ae60",
        "upazilas": [
            {"name": "Habiganj Sadar", "lat": 24.3745, "lon": 91.4153, "river": "Khowai"},
            {"name": "Ajmiriganj",     "lat": 24.2167, "lon": 91.3167, "river": "Kushiyara"},
            {"name": "Bahubal",        "lat": 24.3667, "lon": 91.5500, "river": "Sutang"},
            {"name": "Baniachong",     "lat": 24.5000, "lon": 91.3667, "river": "Haor"},
            {"name": "Chunarughat",    "lat": 24.2833, "lon": 91.6333, "river": "Khowai"},
            {"name": "Lakhai",         "lat": 24.2167, "lon": 91.4167, "river": "Barak"},
            {"name": "Madhabpur",      "lat": 24.1667, "lon": 91.5833, "river": "Khowai"},
            {"name": "Nabiganj",       "lat": 24.3667, "lon": 91.2167, "river": "Kushiyara"},
            {"name": "Shayestaganj",   "lat": 24.4000, "lon": 91.5000, "river": "Khowai"},
        ],
    },
    "sunamganj": {
        "name": "Sunamganj",
        "bangla": "সুনামগঞ্জ",
        "center": {"lat": 25.0658, "lon": 91.3950},
        "color": "#8e44ad",
        "upazilas": [
            {"name": "Sunamganj Sadar",  "lat": 25.0658, "lon": 91.3950, "river": "Surma"},
            {"name": "Bishwamvarpur",    "lat": 24.9167, "lon": 91.2833, "river": "Surma"},
            {"name": "Chhatak",          "lat": 25.0500, "lon": 91.6667, "river": "Piyain"},
            {"name": "Derai",            "lat": 24.7833, "lon": 91.5000, "river": "Surma"},
            {"name": "Dharampasha",      "lat": 24.9833, "lon": 91.0667, "river": "Kangsha"},
            {"name": "Dowarabazar",      "lat": 25.0000, "lon": 91.5500, "river": "Surma"},
            {"name": "Jagannathpur",     "lat": 24.6833, "lon": 91.5333, "river": "Surma"},
            {"name": "Jamalganj",        "lat": 25.0167, "lon": 91.2500, "river": "Surma"},
            {"name": "Sullah",           "lat": 24.8500, "lon": 91.3667, "river": "Surma"},
            {"name": "Tahirpur",         "lat": 25.1000, "lon": 91.0167, "river": "Surma"},
        ],
    },
}


# ──────────────────────────────────────────────────────────────────────
# RIVERS — Sylhet Division
# Base levels and danger levels from FFWC Bangladesh
# ──────────────────────────────────────────────────────────────────────

SYLHET_RIVERS = [
    {"name": "Surma",     "base_level": 7.2,  "danger_level": 9.0,  "status": "normal"},
    {"name": "Kushiyara", "base_level": 5.8,  "danger_level": 8.5,  "status": "normal"},
    {"name": "Manu",      "base_level": 4.1,  "danger_level": 6.5,  "status": "normal"},
    {"name": "Khowai",    "base_level": 3.9,  "danger_level": 5.8,  "status": "normal"},
    {"name": "Piyain",    "base_level": 6.8,  "danger_level": 7.5,  "status": "warning"},
    {"name": "Juri",      "base_level": 3.2,  "danger_level": 5.0,  "status": "normal"},
    {"name": "Saree",     "base_level": 2.8,  "danger_level": 4.5,  "status": "normal"},
    {"name": "Kangsha",   "base_level": 5.5,  "danger_level": 7.0,  "status": "normal"},
]


# ──────────────────────────────────────────────────────────────────────
# SEVERITY / RISK HELPERS
# ──────────────────────────────────────────────────────────────────────

SEVERITY_COLOR = {
    "critical": "#ff3b3b",
    "high":     "#ff8c00",
    "moderate": "#ffd700",
    "low":      "#4caf50",
    "minimal":  "#2196f3",
}

RISK_LEVEL_ORDER = ["critical", "high", "moderate", "low", "minimal"]


# ──────────────────────────────────────────────────────────────────────
# LOOKUP HELPERS — used by agents and dashboard
# ──────────────────────────────────────────────────────────────────────

def get_all_upazilas() -> List[Dict]:
    """Flat list of all 39 upazilas with district info."""
    result = []
    for dist_id, dist in SYLHET_DISTRICTS.items():
        for uz in dist["upazilas"]:
            result.append({
                "name": uz["name"],
                "lat": uz["lat"],
                "lon": uz["lon"],
                "river": uz.get("river", "Unknown"),
                "district": dist["name"],
                "district_id": dist_id,
                "district_bangla": dist["bangla"],
            })
    return result


def find_upazila(name: str) -> Optional[Dict]:
    """Find an upazila by name (case-insensitive partial match)."""
    name_lower = name.lower().strip()
    for dist_id, dist in SYLHET_DISTRICTS.items():
        for uz in dist["upazilas"]:
            if name_lower in uz["name"].lower():
                return {
                    "name": uz["name"],
                    "lat": uz["lat"],
                    "lon": uz["lon"],
                    "river": uz.get("river", "Unknown"),
                    "district": dist["name"],
                    "district_id": dist_id,
                }
    return None


def get_upazila_coords_map() -> Dict[str, Dict]:
    """
    Returns a lookup dict: lowercase_name → {lat, lon, district, river}
    Used by the dashboard ZONES constant and Agent 2 channel parsers.
    """
    result = {}
    for dist_id, dist in SYLHET_DISTRICTS.items():
        for uz in dist["upazilas"]:
            key = uz["name"].lower().replace(" ", "")
            result[key] = {
                "lat": uz["lat"],
                "lon": uz["lon"],
                "name": uz["name"],
                "district": dist["name"],
                "river": uz.get("river", "Unknown"),
            }
        # Also add district-level keys
        result[dist_id] = {
            "lat": dist["center"]["lat"],
            "lon": dist["center"]["lon"],
            "name": dist["name"],
            "district": dist["name"],
        }
    return result


def get_river_by_name(name: str) -> Optional[Dict]:
    """Find river data by name."""
    for r in SYLHET_RIVERS:
        if r["name"].lower() == name.lower():
            return r
    return None
