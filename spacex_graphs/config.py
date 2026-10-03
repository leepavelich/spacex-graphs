"""Static configuration: data sources, HTTP settings, paths, and orbit categories."""

import datetime

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

# When Wikipedia can't be reached, cached pages are used only if they were last
# confirmed current within this window. Past it the run fails instead, so a
# blocked or broken fetch can't keep publishing frozen data as if it were new.
STALE_CACHE_LIMIT = datetime.timedelta(days=3)

# SpaceX has launched every year since 2012 (2011 had no launches). A past year
# with no launches means a page is missing from WIKIPEDIA_PAGES, most likely
# because Wikipedia split last year out of the current list into its own page.
FIRST_CONTINUOUS_YEAR = 2012

# A year may have at most this many fewer launches than the last published
# CSV (allowing for the odd Wikipedia correction); more than that means part
# of a page stopped parsing, and the run fails instead of publishing.
MAX_LAUNCH_COUNT_DROP = 2

# The cumulative graph only shows years from this one onwards
MIN_CUMULATIVE_YEAR = 2017

# Years before this are drawn in muted grey as context: their payload mass is
# tiny next to recent years, so they shouldn't compete for attention
HIGHLIGHT_FROM_YEAR = 2020

# The orbit categories the graphs show, in legend order. Every category
# produced by ORBIT_MAPPING or transform's fallbacks must be one of these, and
# plotting must give each a color; the tests check both.
LEO_STARLINK = "LEO (Starlink)"
LEO_OTHER = "LEO (Other)"
OTHER_ORBIT = "Other"
ORBIT_CATEGORIES = (
    LEO_STARLINK,
    LEO_OTHER,
    "SSO (Starlink)",
    "SSO (Other)",
    "MEO",
    "GTO/GEO",
    "BLT",
    "Heliocentric",
    "Transatmospheric",
    OTHER_ORBIT,
)

# Maps raw Wikipedia orbit descriptions to the categories above. Footnote
# markers like "[338]" are removed before lookup, so keys never include them.
ORBIT_MAPPING = {
    "Ballistic lunar transfer (BLT)": "BLT",
    "BLT": "BLT",
    "GEO": "GTO/GEO",
    "GTO": "GTO/GEO",
    "HEO for P/2 orbit": "Other",
    "Heliocentric": "Heliocentric",
    "Heliocentric 0.99–1.67 AU (close to Mars transfer orbit)": "Heliocentric",
    "LEO": "LEO (Other)",
    "LEO (ISS)": "LEO (Other)",
    "LEO (Starlink)": "LEO (Starlink)",
    "LEO / MEO": "Other",
    "MEO": "MEO",
    "Polar LEO": "LEO (Other)",
    "Polar orbit LEO": "LEO (Other)",
    "Polar (Retrograde)": "LEO (Other)",  # Fram2: a crewed polar LEO flight
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
    "Sub-orbital (Starlink)": "Transatmospheric",
    "Transatmospheric (Starlink)": "Transatmospheric",
}
