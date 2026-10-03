"""Static configuration: data sources, HTTP settings, paths, and orbit categories."""

OUTPUT_DIR = "outputs"
CACHE_DIR = ".cache"

REQUEST_TIMEOUT = 10
# Wikimedia's User-Agent policy asks automated clients to identify themselves
# with a way to get in touch, and may block generic or spoofed browser UAs:
# https://foundation.wikimedia.org/wiki/Policy:Wikimedia_Foundation_User-Agent_Policy
HEADERS = {
    "User-Agent": "spacex-graphs/1.0 (https://github.com/leepavelich/spacex-graphs)"
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
    "Heliocentric0.99–1.67 AU(close to Mars transfer orbit)": "Heliocentric",
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
    "Sub-orbital": "Transatmospheric",
    "Suborbital": "Transatmospheric",
    "Sun–Earth L1 insertion": "Other",
    "Sun–Earth L2 injection": "Other",
    "Transatmospheric": "Transatmospheric",
    "—": "Transatmospheric",  # Starship test flights often have — for orbit
    # Starship flights that carried Starlink satellites (or simulators) on a
    # suborbital trajectory: the payload never reached orbit, so it counts as
    # Transatmospheric rather than as a Starlink orbit
    "Suborbital (Starlink)": "Transatmospheric",
    "Transatmospheric (Starlink)": "Transatmospheric",
}
