import re
import requests
import datetime
import os
from bs4 import BeautifulSoup
import pandas as pd
import matplotlib.pyplot as plt
from matplotlib.ticker import FuncFormatter

# Define the output directory
output_dir = "outputs"

# Check if the directory exists, and create it if it does not
if not os.path.exists(output_dir):
    os.makedirs(output_dir)

# URLs of the Wikipedia pages
urls = [
    "https://en.wikipedia.org/wiki/List_of_Falcon_9_and_Falcon_Heavy_launches_(2010%E2%80%932019)",
    "https://en.wikipedia.org/wiki/List_of_Falcon_9_and_Falcon_Heavy_launches",
]


def month_to_int(month_name):
    datetime_object = datetime.datetime.strptime(month_name, "%b")
    return datetime_object.month


def fetch_and_parse(url):
    # Fetch the HTML content
    response = requests.get(url)
    soup = BeautifulSoup(response.content, "html.parser")

    # Find the tables containing launch data
    tables = soup.findAll("table", {"class": "wikitable plainrowheaders collapsible"})

    # Parse the tables and extract relevant data
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
    # Remove any square brackets and the contents inside
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
    if "Starlink" in payload:
        return f"{orbit} (Starlink)"
    return orbit


# # Fetch and parse data from both Wikipedia pages
all_data = []
for url in urls:
    all_data.extend(fetch_and_parse(url))

# Convert data into a DataFrame
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
fig1, ax1 = plt.subplots(figsize=(10, 7))
pivot_df.plot(
    kind="bar", stacked=True, color=[color_map[col] for col in ordered_columns], ax=ax1
)
ax1.set_title("Payload Mass to Type of Orbit by Year")
ax1.set_xlabel("Year")
ax1.set_ylabel("Payload Mass (kg)")
ax1.legend(title="Orbit Type")
ax1.tick_params(axis="x", rotation=45)
ax1.ticklabel_format(style="plain", axis="y")
ax1.yaxis.set_major_formatter(FuncFormatter(lambda x, _: f"{int(x):,}"))
fig1.savefig(
    os.path.join(output_dir, "payload_mass_to_orbit_by_year.svg"), format="svg"
)

# Plotting Cumulative Line Chart

df["DateTime"] = pd.to_datetime(df["DateTime"])
df["DayOfYear"] = df["DateTime"].dt.dayofyear
df_filtered = df[df["Year"] >= 2017]


fig2, ax2 = plt.subplots(figsize=(10, 7))
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

ax2.set_title("Cumulative Payload Mass to Orbit By Year")
ax2.set_xlabel("Day of the Year")
ax2.set_ylabel("Cumulative Payload Mass (kg)")
ax2.legend(title="Year")
ax2.grid(True)
ax2.yaxis.set_major_formatter(FuncFormatter(lambda x, _: f"{int(x):,}"))
fig2.savefig(
    os.path.join(output_dir, "cumulative_payload_mass_to_orbit.svg"), format="svg"
)

# Show all figures at once.
plt.show()
