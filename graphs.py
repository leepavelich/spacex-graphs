"""Module that generates graphs from Wikipedia of SpaceX mass-to-orbit launches"""
import os
import datetime
import re
import requests
from bs4 import BeautifulSoup
import pandas as pd
import matplotlib.pyplot as plt
from matplotlib.ticker import FuncFormatter

OUTPUT_DIR = "outputs"
os.makedirs(OUTPUT_DIR, exist_ok=True)

# URLs of the Wikipedia pages
urls = [
    "https://en.wikipedia.org/wiki/List_of_Falcon_9_and_Falcon_Heavy_launches_(2010%E2%80%932019)",
    "https://en.wikipedia.org/wiki/List_of_Falcon_9_and_Falcon_Heavy_launches",
]


def month_to_int(month_name):
    """Converts a month name to its corresponding integer"""
    datetime_object = datetime.datetime.strptime(month_name, "%b")
    return datetime_object.month


def fetch_and_parse(url):
    """Fetches and parses the Wikipedia page at the given URL"""
    response = requests.get(url, timeout=10)
    soup = BeautifulSoup(response.content, "html.parser")
    tables = soup.findAll("table", {"class": "wikitable plainrowheaders collapsible"})

    data = []
    for table in tables:
        rows = table.find_all("tr")
        for row in rows:
            cols = row.find_all("td")
            if len(cols) > 6:
                date_col = cols[0].get_text(separator=" ", strip=True)
                date_match = re.search(r"(\d{1,2})\s+(\w+)\s*(\d{4})", date_col)
                time_match = re.search(r"(\d{2}):(\d{2})", date_col)

                day, month_name, year = date_match.groups()
                month = month_to_int(month_name[:3])
                day, year = int(day), int(year)
                date = datetime.date(year, month, day)

                hour, minute = time_match.groups()
                hour, minute = int(hour), int(minute)
                time = datetime.time(hour, minute)

                datetime_launch = datetime.datetime.combine(date, time)

                payload = cols[3].text.strip()
                payload_mass = (
                    cols[4].text.strip().split()[0]
                )  # Take the first number before any space
                orbit = cols[5].text.strip()

                # Clean the payload mass data (remove non-numeric characters)
                payload_mass = "".join(filter(str.isdigit, payload_mass))
                payload_mass = int(payload_mass) if payload_mass.isdigit() else 0

                data.append((year, orbit, payload, payload_mass, datetime_launch))
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
    }

    return orbit_mapping.get(orbit_cleaned, "Other")


def categorize_starlink(payload, orbit):
    """Categorizes the orbit as Starlink if the payload contains 'Starlink'"""
    if "Starlink" in payload:
        return f"{orbit} (Starlink)"
    return orbit


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
all_data = []
for url in urls:
    all_data.extend(fetch_and_parse(url))

df = pd.DataFrame(
    all_data, columns=["Year", "Orbit", "Payload", "PayloadMass", "DateTime"]
)

df["Orbit"] = df.apply(lambda x: categorize_starlink(x["Payload"], x["Orbit"]), axis=1)
df["Orbit"] = df["Orbit"].apply(clean_orbit_category)

# Dirty hacks
df.iloc[92, 3] = 5500  # Halfway between 5000 and 6000

# Define a color map that corresponds to the categories in the example graph
color_map = {
    "LEO (Starlink)": "chocolate",
    "LEO (Other)": "coral",
    "MEO": "orchid",
    "GTO/GEO": "yellowgreen",
    "BLT": "gold",
    "Heliocentric": "wheat",
    "Other": "lightgray",
}

# Reorder the columns based on the example graph's legend order
ordered_columns = [
    "LEO (Starlink)",
    "LEO (Other)",
    "MEO",
    "GTO/GEO",
    "BLT",
    "Heliocentric",
    "Other",
]

payload_mass_by_year_orbit = (
    df.drop(columns="DateTime").groupby(["Year", "Orbit"]).sum().reset_index()
)

# Normalize the 'DateTime' to start from the first day of the year
df["NormalizedDateTime"] = df["DateTime"].apply(lambda dt: dt.replace(year=1900))
df.sort_values(by="DateTime", inplace=True)
df["CumulativePayloadMass"] = df.groupby("Year")["PayloadMass"].transform(
    pd.Series.cumsum
)

pivot_df = payload_mass_by_year_orbit.pivot(
    index="Year", columns="Orbit", values="PayloadMass"
).fillna(0)[ordered_columns]


# Plotting Stacked Bar Chart
fig1, ax1 = create_figure(
    "Payload Mass to Type of Orbit by Year", "Year", "Payload Mass (kg)"
)
pivot_df.plot(
    kind="bar", stacked=True, color=[color_map[col] for col in ordered_columns], ax=ax1
)
ax1.legend(title="Orbit Type")
fig1.savefig(
    os.path.join(OUTPUT_DIR, "payload_mass_to_orbit_by_year.svg"), format="svg"
)

# Plotting Cumulative Line Chart

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


fig2, ax2 = create_figure(
    "Cumulative Payload Mass to Orbit By Year",
    "Day of the Year",
    "Cumulative Payload Mass (kg)",
)
for year, group_data in df_filtered.groupby("Year"):
    # Convert 'NormalizedDateTime' to a number of days since the start of the year
    group_data["DayOfYear"] = group_data["NormalizedDateTime"].apply(
        lambda dt: (dt - datetime.datetime(1900, 1, 1)).days + 1
    )
    ax2.plot(
        group_data["DayOfYear"],
        group_data["CumulativePayloadMass"],
        label=year,
        drawstyle="steps-post",
    )

ax2.legend(title="Year")
fig2.savefig(
    os.path.join(OUTPUT_DIR, "cumulative_payload_mass_to_orbit.svg"), format="svg"
)

plt.show()
