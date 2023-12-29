import re
import requests
from bs4 import BeautifulSoup
import pandas as pd
import matplotlib.pyplot as plt
from matplotlib.ticker import FuncFormatter

# URLs of the Wikipedia pages
urls = [
    "https://en.wikipedia.org/wiki/List_of_Falcon_9_and_Falcon_Heavy_launches_(2010%E2%80%932019)",
    "https://en.wikipedia.org/wiki/List_of_Falcon_9_and_Falcon_Heavy_launches",
]


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
            if len(cols) > 6:  # Check if the row has sufficient data
                # Extract year, orbit, and payload mass
                date = cols[0].text.strip()
                day = date.split()[0]
                month = date.split()[1]
                year = date.split()[-1][:4]
                payload = cols[3].text.strip()
                payload_mass = (
                    cols[4].text.strip().split()[0]
                )  # Take the first number before any space
                orbit = cols[5].text.strip()

                # Clean the payload mass data (remove non-numeric characters)
                payload_mass = "".join(filter(str.isdigit, payload_mass))
                payload_mass = int(payload_mass) if payload_mass.isdigit() else 0

                data.append((year, orbit, payload, payload_mass))
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
df = pd.DataFrame(all_data, columns=["Year", "Orbit", "Payload", "PayloadMass"])

df["Orbit"] = df.apply(lambda x: categorize_starlink(x["Payload"], x["Orbit"]), axis=1)
df["Orbit"] = df["Orbit"].apply(clean_orbit_category)

# Dirty hacks
df.iloc[92, 3] = 5500  # Halway between 5000 and 6000

# Plotting
grouped_data = df.groupby(["Year", "Orbit"]).sum().reset_index()

pivot_df = grouped_data.pivot(
    index="Year", columns="Orbit", values="PayloadMass"
).fillna(0)

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
pivot_df = pivot_df[ordered_columns]

pivot_df.plot(
    kind="bar",
    stacked=True,
    color=[color_map[col] for col in ordered_columns],
    figsize=(10, 7),
)
plt.title("Payload Mass to Type of Orbit")
plt.xlabel("Year")
plt.ylabel("Payload Mass (kg)")
plt.legend(title="Orbit Type")
plt.ticklabel_format(style="plain", axis="y")
plt.gca().yaxis.set_major_formatter(FuncFormatter(lambda x, _: f"{int(x):,}"))
plt.show()
