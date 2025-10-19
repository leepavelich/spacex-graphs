"""Module that generates graphs from Wikipedia of SpaceX mass-to-orbit launches"""

import os
import datetime
import calendar
import re
import argparse
import json
import hashlib
from concurrent.futures import ThreadPoolExecutor
import requests
from bs4 import BeautifulSoup
import pandas as pd
import matplotlib.pyplot as plt
from matplotlib.ticker import FuncFormatter

OUTPUT_DIR = "outputs"
CACHE_DIR = ".cache"
os.makedirs(OUTPUT_DIR, exist_ok=True)
os.makedirs(CACHE_DIR, exist_ok=True)

# URLs of the Wikipedia pages
urls = [
    "https://en.wikipedia.org/wiki/List_of_Falcon_9_and_Falcon_Heavy_launches_(2010%E2%80%932019)",
    "https://en.wikipedia.org/wiki/List_of_Falcon_9_and_Falcon_Heavy_launches_(2020%E2%80%932022)",
    "https://en.wikipedia.org/wiki/List_of_Falcon_9_and_Falcon_Heavy_launches_(2023)",
    "https://en.wikipedia.org/wiki/List_of_Falcon_9_and_Falcon_Heavy_launches",
    "https://en.wikipedia.org/wiki/List_of_Starship_launches",
]


def get_cache_key(url):
    """Generate a cache key from URL"""
    return hashlib.md5(url.encode()).hexdigest()


def fetch_with_cache(url, headers):
    """Fetch URL with ETag/Last-Modified caching support"""
    cache_key = get_cache_key(url)
    cache_meta_path = os.path.join(CACHE_DIR, f"{cache_key}.json")
    cache_content_path = os.path.join(CACHE_DIR, f"{cache_key}.html")

    # Load cached metadata if exists
    cached_meta = {}
    if os.path.exists(cache_meta_path):
        with open(cache_meta_path, "r", encoding="utf-8") as f:
            cached_meta = json.load(f)

    # Add conditional request headers if we have cached data
    request_headers = headers.copy()
    if "etag" in cached_meta:
        request_headers["If-None-Match"] = cached_meta["etag"]
    if "last-modified" in cached_meta:
        request_headers["If-Modified-Since"] = cached_meta["last-modified"]

    # Make the request
    response = requests.get(url, headers=request_headers, timeout=10)

    # If 304 Not Modified, use cached content
    if response.status_code == 304 and os.path.exists(cache_content_path):
        with open(cache_content_path, "rb") as f:
            return f.read()

    # Otherwise, save new content and metadata
    if response.status_code == 200:
        # Save content
        with open(cache_content_path, "wb") as f:
            f.write(response.content)

        # Save metadata
        meta = {"url": url}
        if "ETag" in response.headers:
            meta["etag"] = response.headers["ETag"]
        if "Last-Modified" in response.headers:
            meta["last-modified"] = response.headers["Last-Modified"]

        with open(cache_meta_path, "w", encoding="utf-8") as f:
            json.dump(meta, f)

        return response.content

    # Fallback to cached content if request failed but cache exists
    if os.path.exists(cache_content_path):
        with open(cache_content_path, "rb") as f:
            return f.read()

    # No cache and request failed
    response.raise_for_status()
    return response.content


def month_to_int(month_name):
    """Converts a month name to its corresponding integer"""
    datetime_object = datetime.datetime.strptime(month_name, "%b")
    return datetime_object.month


def fetch_and_parse_starship(url):
    """Fetches and parses Starship launches from Wikipedia"""
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
    }
    content = fetch_with_cache(url, headers)
    soup = BeautifulSoup(content, "html.parser")
    tables = soup.findAll("table", {"class": "wikitable"})

    data = []
    for table in tables:
        rows = table.find_all("tr")
        for row in rows:
            cols = row.find_all("td")
            if len(cols) != 11:
                continue

            date_col = cols[0].get_text(separator=" ", strip=True)
            date_match = re.search(r"(\d{1,2})\s+(\w+)\s*(\d{4})", date_col)
            time_match = re.search(r"(\d{2}):(\d{2})", date_col)

            if not date_match:
                alt_match = re.search(r"(\w+)\s+(\d{1,2}),?\s*(\d{4})", date_col)
                if alt_match:
                    month_name, day, year = alt_match.groups()
                    day = int(day)
                else:
                    continue
            else:
                day, month_name, year = date_match.groups()
                day = int(day)
            month = month_to_int(month_name[:3])
            year = int(year)
            date = datetime.date(year, month, day)

            if time_match:
                hour, minute = time_match.groups()
                hour, minute = int(hour), int(minute)
            else:
                hour = minute = 0
            time = datetime.time(hour, minute)

            datetime_launch = datetime.datetime.combine(date, time)

            # For Starship, columns are different:
            # Col 2: Ship version, Col 4: Payload, Col 5: Payload mass, Col 6: Orbit, Col 8: Launch outcome
            ship_version = cols[2].text.strip()
            payload = cols[4].text.strip()
            payload_mass_text = cols[5].text.strip()
            orbit = cols[6].text.strip()
            launch_outcome = cols[8].text.strip().lower()

            # Extract block version from ship (e.g., "Block 1S24" -> "Block 1")
            block_match = re.search(r"Block\s+(\d+)", ship_version)
            if block_match:
                vehicle = f"Block {block_match.group(1)} Starship"
            else:
                vehicle = "Starship"

            # Only the August 26, 2025 launch was successful so far
            if "success" in launch_outcome:
                # Extract mass from text like "~16,000 kg (35,000 lb)[54]"
                mass_match = re.search(r"~?([\d,]+)\s*kg", payload_mass_text)
                if mass_match:
                    payload_mass = mass_match.group(1).replace(",", "")
                    payload_mass = int(payload_mass)
                else:
                    payload_mass = 0
            else:
                payload_mass = 0

            # Use "Starship Test" as payload name if no payload
            if payload == "—" or not payload:
                payload = "Starship Test"

            data.append((year, orbit, payload, payload_mass, datetime_launch, vehicle))
    return data


def parse_payload_mass_text(text):
    """Parse payload mass text from Wikipedia cell.

    Handles values like:
    - "5,000 kg"
    - "5,000–6,000 kg" (returns the average 5,500)
    - "5000-6000 kg" (same as above)
    - "~16,000 kg" (returns 16000)
    - Any footnotes or extra text are ignored
    Returns an integer mass in kg, or 0 if not parseable.
    """
    if not text:
        return 0

    # Normalize dashes and strip
    s = str(text).strip()
    s = s.replace("\u2013", "-").replace("\u2014", "-")  # en/em dash -> hyphen

    # If there's an explicit numeric range, average the bounds (hyphen/en dash or 'to')
    range_match = re.search(r"(\d[\d,]*)\s*(?:-|to)\s*(\d[\d,]*)", s, flags=re.IGNORECASE)
    if range_match:
        a, b = range_match.groups()
        a = int(a.replace(",", ""))
        b = int(b.replace(",", ""))
        return int(round((a + b) / 2))

    # Otherwise take the first integer in the string
    single_match = re.search(r"(\d[\d,]*)", s)
    if single_match:
        return int(single_match.group(1).replace(",", ""))

    return 0


def fetch_and_parse(url):
    """Fetches and parses the Wikipedia page at the given URL"""
    # Check if this is the Starship page
    if "Starship" in url:
        return fetch_and_parse_starship(url)

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
    }
    content = fetch_with_cache(url, headers)
    soup = BeautifulSoup(content, "html.parser")
    tables = soup.findAll("table", {"class": "wikitable"})

    data = []
    for table in tables:
        rows = table.find_all("tr")
        for row in rows:
            cols = row.find_all("td")
            if len(cols) not in [9, 11]:
                continue

            date_col = cols[0].get_text(separator=" ", strip=True)
            date_match = re.search(r"(\d{1,2})\s+(\w+)\s*(\d{4})", date_col)
            time_match = re.search(r"(\d{2}):(\d{2})", date_col)

            if not date_match:
                alt_match = re.search(r"(\w+)\s+(\d{1,2}),?\s*(\d{4})", date_col)
                if alt_match:
                    month_name, day, year = alt_match.groups()
                    day = int(day)
                else:
                    continue
            else:
                day, month_name, year = date_match.groups()
                day = int(day)
            month = month_to_int(month_name[:3])
            year = int(year)
            date = datetime.date(year, month, day)

            if time_match:
                hour, minute = time_match.groups()
                hour, minute = int(hour), int(minute)
            else:
                hour = minute = 0
            time = datetime.time(hour, minute)

            datetime_launch = datetime.datetime.combine(date, time)

            # For Falcon launches: Col 1: Booster, Col 3: Payload, Col 4: Mass, Col 5: Orbit, Col 7: Outcome
            booster = cols[1].text.strip() if len(cols) > 1 else ""
            payload = cols[3].text.strip()
            payload_mass_text = cols[4].text.strip()
            payload_mass = parse_payload_mass_text(payload_mass_text)
            orbit = cols[5].text.strip()
            launch_outcome = cols[7].text.strip().lower()

            if "success" not in launch_outcome:
                payload_mass = 0

            # Determine vehicle type from booster column
            if "Heavy" in booster or "FH" in booster:
                vehicle = "Falcon Heavy"
            else:
                vehicle = "Falcon 9"

            data.append((year, orbit, payload, payload_mass, datetime_launch, vehicle))
    return data


def clean_orbit_category(orbit):
    """Cleans the orbit category by removing square brackets and mapping to a category"""
    orbit_cleaned = re.sub(r"\[.*?\]", "", orbit)
    orbit_cleaned = orbit_cleaned.strip()

    # Mapping dict to map the orbit from DataFrame to the desired categories
    orbit_mapping = {
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

    return orbit_mapping.get(orbit_cleaned, "Other")


def categorize_starlink(payload, orbit):
    """Categorizes the orbit as Starlink if the payload contains 'Starlink'"""
    if "Starlink" in payload:
        return f"{orbit} (Starlink)"
    return orbit


def add_end_of_period_entries(df):
    """
    For each year in the DataFrame, this function adds an entry at the end of the period
    (end of the year or current day if it's the current year) with the last known cumulative payload mass.
    """
    current_year = datetime.datetime.now().year
    current_day_of_year = datetime.datetime.now().timetuple().tm_yday
    end_of_period_entries = []

    for year in df["Year"].unique():
        last_entry_for_year = df[df["Year"] == year].iloc[-1]
        last_cumulative_mass = last_entry_for_year["CumulativePayloadMass"]

        # If it's the current year, use the current day of the year
        if year == current_year:
            period_end_date = datetime.datetime(year, 1, 1) + datetime.timedelta(
                days=current_day_of_year - 1
            )
        else:  # Otherwise, use the last day of the year
            period_end_date = datetime.datetime(year, 12, 31)

        end_of_period_entries.append(
            {
                "Year": year,
                "PayloadMass": 0,  # No additional payload, so mass is 0
                "DateTime": period_end_date,
                "NormalizedDateTime": period_end_date.replace(year=1900),
                "CumulativePayloadMass": last_cumulative_mass,
                "DayOfYear": period_end_date.timetuple().tm_yday,
            }
        )

    # Append the end-of-period entries to the original DataFrame
    return pd.concat(
        [df, pd.DataFrame(end_of_period_entries)], ignore_index=True
    ).sort_values(by="DateTime")


def create_figure(title, xlabel, ylabel, size=(10, 7)):
    """Creates a figure with the given title, x label, and y label"""
    fig, ax = plt.subplots(figsize=size)
    ax.set_title(title)
    ax.set_xlabel(xlabel)
    ax.set_ylabel(ylabel)
    ax.grid(True)
    ax.tick_params(axis="x", rotation=45)
    ax.ticklabel_format(style="plain", axis="y")
    ax.yaxis.set_major_formatter(FuncFormatter(lambda x, _: f"{int(x):,}"))
    return fig, ax


# # Fetch and parse data from both Wikipedia pages
# Use ThreadPoolExecutor to fetch all URLs concurrently
all_data = []
with ThreadPoolExecutor(max_workers=5) as executor:
    results = executor.map(fetch_and_parse, urls)
    for result in results:
        all_data.extend(result)

df = pd.DataFrame(
    all_data, columns=["Year", "Orbit", "Payload", "PayloadMass", "DateTime", "Vehicle"]
)

df["Orbit"] = df.apply(lambda x: categorize_starlink(x["Payload"], x["Orbit"]), axis=1)
df["Orbit"] = df["Orbit"].apply(clean_orbit_category)

# Define a color map that corresponds to the categories in the example graph
color_map = {
    "LEO (Starlink)": "chocolate",
    "LEO (Other)": "coral",
    "SSO (Starlink)": "darkgoldenrod",
    "SSO (Other)": "orange",
    "MEO": "orchid",
    "GTO/GEO": "yellowgreen",
    "BLT": "gold",
    "Heliocentric": "wheat",
    "Transatmospheric": "lightblue",
    "Other": "lightgray",
}

# Reorder the columns based on the example graph's legend order
ordered_columns = [
    "LEO (Starlink)",
    "LEO (Other)",
    "SSO (Starlink)",
    "SSO (Other)",
    "MEO",
    "GTO/GEO",
    "BLT",
    "Heliocentric",
    "Transatmospheric",
    "Other",
]

payload_mass_by_year_orbit = (
    df.drop(columns="DateTime").groupby(["Year", "Orbit"]).sum().reset_index()
)


def plot_payload_mass_to_orbit_by_year():
    """Plots the payload mass to orbit by year"""
    fig, ax = create_figure(
        "Payload Mass to Type of Orbit by Year", "Year", "Payload Mass (kg)"
    )
    pivot_df = payload_mass_by_year_orbit.pivot(
        index="Year", columns="Orbit", values="PayloadMass"
    ).fillna(0)[ordered_columns]

    pivot_df.plot(
        kind="bar",
        stacked=True,
        color=[color_map[col] for col in ordered_columns],
        ax=ax,
    )

    # A fixed amount of padding above the bars for the annotations
    fixed_padding = 10000

    # Annotate each bar with the total payload mass for the year
    for i, total in enumerate(pivot_df.sum(axis=1)):
        ax.text(
            i,
            total + fixed_padding,
            f"{int(total):,}",
            ha="center",
            va="bottom",
            color="grey",
            fontsize=8,
        )

    ax.legend(title="Orbit Type")
    ax.set_xlabel("")
    plt.tight_layout()
    return fig


def plot_cumulative_payload_mass_to_orbit(_df_filtered):
    """Plots the cumulative payload mass to orbit by year"""
    fig, ax = create_figure(
        "Cumulative Payload Mass to Orbit By Year",
        "",
        "Cumulative Payload Mass (kg)",
    )
    df_extended = add_end_of_period_entries(_df_filtered)

    colors = [
        "red",
        "green",
        "blue",
        "orange",
        "purple",
        "pink",
        "lightblue",
        "lightgreen",
    ]

    sorted_years = sorted(df_extended["Year"].unique(), reverse=True)
    year_color_map = {year: color for year, color in zip(sorted_years, colors)}

    for year, group_data in df_extended.groupby("Year"):
        group_data = group_data.sort_values("DateTime")
        group_data["DayOfYear"] = group_data["DateTime"].dt.dayofyear
        cumulative_mass = group_data["PayloadMass"].cumsum()

        # Get the color for the year
        color = year_color_map.get(year, "grey")  # Default to grey if no color assigned

        ax.plot(
            group_data["DayOfYear"],
            cumulative_mass,
            label=str(year),
            color=color,  # Use the color from the map
            drawstyle="steps-post",
        )

    ax.legend(title="Year", loc="upper left")

    # Set the x-axis ticks to the first of each month
    months_to_label = [datetime.datetime(2020, month, 1) for month in range(1, 13, 2)]
    ax.set_xticks([date.timetuple().tm_yday for date in months_to_label])
    ax.set_xticklabels([date.strftime("%b 1") for date in months_to_label], rotation=0)

    # Set the x-axis limit to the maximum day of the year
    current_year = datetime.datetime.now().year
    if calendar.isleap(current_year):
        ax.set_xlim(-14, 366 + 7)
    else:
        ax.set_xlim(-14, 365 + 7)

    plt.tight_layout()
    return fig


def save_plots(fig1, fig2):
    """Saves the plots as SVG files"""
    fig1.savefig(
        os.path.join(OUTPUT_DIR, "payload_mass_to_orbit_by_year.svg"), format="svg"
    )
    fig2.savefig(
        os.path.join(OUTPUT_DIR, "cumulative_payload_mass_to_orbit.svg"), format="svg"
    )


def compute_data_hash(data):
    """Compute a hash of the launch data for change detection"""
    # Convert data to a sorted, stable string representation
    data_str = json.dumps(sorted(data), sort_keys=True, default=str)
    return hashlib.sha256(data_str.encode()).hexdigest()


def has_data_changed(data):
    """Check if data has changed since last run"""
    hash_file = os.path.join(CACHE_DIR, "data_hash.txt")
    new_hash = compute_data_hash(data)

    # If hash file doesn't exist, data has "changed"
    if not os.path.exists(hash_file):
        with open(hash_file, "w", encoding="utf-8") as f:
            f.write(new_hash)
        return True

    # Compare with stored hash
    with open(hash_file, "r", encoding="utf-8") as f:
        old_hash = f.read().strip()

    if old_hash != new_hash:
        # Update hash file
        with open(hash_file, "w", encoding="utf-8") as f:
            f.write(new_hash)
        return True

    return False


def save_launches_csv(all_data):
    """Saves all launch data to a CSV file for debugging"""
    # Create a list of dictionaries for easier CSV writing
    csv_data = []
    for item in all_data:
        # Handle both old format (5 elements) and new format (6 elements with vehicle)
        if len(item) == 6:
            year, orbit, payload, payload_mass, datetime_launch, vehicle = item
        else:
            year, orbit, payload, payload_mass, datetime_launch = item
            vehicle = "Unknown"

        orbit_with_starlink = categorize_starlink(payload, orbit)
        orbit_category = clean_orbit_category(orbit_with_starlink)

        csv_data.append(
            {
                "Date": datetime_launch.strftime("%Y-%m-%d"),
                "Time (UTC)": datetime_launch.strftime("%H:%M:%S"),
                "Year": year,
                "Vehicle": vehicle,
                "Payload": payload,
                "Payload Mass (kg)": payload_mass,
                "Orbit": orbit,
                "Orbit Category": orbit_category,
            }
        )

    # Convert to DataFrame and sort by date
    csv_df = pd.DataFrame(csv_data)
    csv_df["DateTime"] = pd.to_datetime(csv_df["Date"] + " " + csv_df["Time (UTC)"])
    csv_df = csv_df.sort_values("DateTime")
    csv_df = csv_df.drop(columns=["DateTime"])

    # Save to CSV
    csv_path = os.path.join(OUTPUT_DIR, "spacex_launches.csv")
    csv_df.to_csv(csv_path, index=False)
    print(f"Launch data saved to {csv_path}")


# Normalize the 'DateTime' to start from the first day of the year
# df["NormalizedDateTime"] = df["DateTime"].apply(lambda dt: dt.replace(year=1900))
df.sort_values(by="DateTime", inplace=True)
df["CumulativePayloadMass"] = df.groupby("Year")["PayloadMass"].transform(
    pd.Series.cumsum
)


# Add an initial entry for each year
initial_entries = []
unique_years = df["Year"].unique()
for year in unique_years:
    if year >= 2017:  # Condition to only add rows for years 2017 and onwards
        initial_entries.append(
            {
                "Year": year,
                "Orbit": "",
                "Payload": "",
                "PayloadMass": 0,
                "DateTime": datetime.datetime(year, 1, 1),
                "Vehicle": "",  # Add Vehicle column for initial entries
                "NormalizedDateTime": datetime.datetime(
                    1900, 1, 1
                ),  # Normalized to year 1900
                "CumulativePayloadMass": 0,  # Explicitly state cumulative mass as 0
            }
        )

# Convert initial_entries to a DataFrame and concatenate with the main DataFrame
initial_df = pd.DataFrame(initial_entries)
df = pd.concat([initial_df, df], ignore_index=True)
df["DateTime"] = pd.to_datetime(df["DateTime"])
df["DayOfYear"] = df["DateTime"].dt.dayofyear
df_filtered = df[df["Year"] >= 2017]


def main(output):
    """Main function that generates and optionally outputs the plots"""
    # Check if data has changed - if not, skip regeneration when outputting
    if output and not has_data_changed(all_data):
        print("No changes detected in launch data - skipping graph regeneration")
        return

    fig1 = plot_payload_mass_to_orbit_by_year()
    fig2 = plot_cumulative_payload_mass_to_orbit(df_filtered)
    if output:
        save_plots(fig1, fig2)
        save_launches_csv(all_data)
        print("Graphs updated successfully")
    else:
        plt.show()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Generate and optionally output plots as SVG."
    )
    parser.add_argument(
        "--output", action="store_true", help="Output the plots as SVG files"
    )
    args = parser.parse_args()
    main(args.output)
