"""Static configuration: data sources, HTTP settings, paths, and orbit categories."""

OUTPUT_DIR = "outputs"
CACHE_DIR = ".cache"

REQUEST_TIMEOUT = 10
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
}

# Wikipedia pages listing SpaceX launches, mapped to short display names
WIKIPEDIA_PAGES = {
    "https://en.wikipedia.org/wiki/List_of_Falcon_9_and_Falcon_Heavy_launches_(2010%E2%80%932019)": "Falcon 2010-2019",
    "https://en.wikipedia.org/wiki/List_of_Falcon_9_and_Falcon_Heavy_launches_(2020%E2%80%932022)": "Falcon 2020-2022",
    "https://en.wikipedia.org/wiki/List_of_Falcon_9_and_Falcon_Heavy_launches_(2023)": "Falcon 2023",
    "https://en.wikipedia.org/wiki/List_of_Falcon_9_and_Falcon_Heavy_launches_(2024)": "Falcon 2024",
    "https://en.wikipedia.org/wiki/List_of_Falcon_9_and_Falcon_Heavy_launches": "Falcon current",
    "https://en.wikipedia.org/wiki/List_of_Starship_launches": "Starship launches",
}

# The cumulative graph only shows years from this one onwards
MIN_CUMULATIVE_YEAR = 2017

# Maps raw Wikipedia orbit descriptions to standardized categories
ORBIT_MAPPING = {
    "Ballistic lunar transfer (BLT)": "BLT",
    "GEO": "GTO/GEO",
    "GTO": "GTO/GEO",
    "GTO[338]": "GTO/GEO",
    "GTO[356]": "GTO/GEO",
    "GTO[399]": "GTO/GEO",
    "HEO for P/2 orbit": "Other",
    "Heliocentric": "Heliocentric",
    "Heliocentric0.99-1.67 AU[251](close to Mars transfer orbit)": "Heliocentric",
    "LEO": "LEO (Other)",
    "LEO (ISS)": "LEO (Other)",
    "LEO (Starlink)": "LEO (Starlink)",
    "LEO / MEO": "Other",
    "LEO[172]": "LEO (Other)",
    "MEO": "MEO",
    "Polar LEO": "LEO (Other)",
    "Polar orbit LEO": "LEO (Other)",
    "Retrograde LEO": "LEO (Other)",
    "SSO": "SSO (Other)",
    "SSO (Starlink)": "SSO (Starlink)",
    "Sun-Earth L1 insertion": "Other",
    "Sun-Earth L2 injection": "Other",
    "Transatmospheric": "Transatmospheric",
    "—": "Transatmospheric",  # Starship test flights often have — for orbit
}
