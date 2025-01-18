"""Module that generates graphs from Wikipedia of SpaceX mass-to-orbit launches"""

import os
import datetime
import calendar
import re
import argparse
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
    "https://en.wikipedia.org/wiki/List_of_Falcon_9_and_Falcon_Heavy_launches_(2020%E2%80%932022)",
    "https://en.wikipedia.org/wiki/List_of_Falcon_9_and_Falcon_Heavy_launches",
    "https://en.wikipedia.org/wiki/List_of_Starship_launches",
]


def month_to_int(month_name):
    """Converts a month name to its corresponding integer"""
    datetime_object = datetime.datetime.strptime(month_name, "%b")
    return datetime_object.month


def fetch_and_parse(url):
    """Fetches and parses the Wikipedia page at the given URL"""
    response = requests.get(url, timeout=10)
    soup = BeautifulSoup(response.content, "html.parser")
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

            day, month_name, year = date_match.groups()
            month = month_to_int(month_name[:3])
            day, year = int(day), int(year)
            date = datetime.date(year, month, day)

            hour, minute = time_match.groups()
            hour, minute = int(hour), int(minute)
            time = datetime.time(hour, minute)

            datetime_launch = datetime.datetime.combine(date, time)

            payload = cols[3].text.strip()
            payload_mass = cols[4].text.strip().split()[0]  # Take the first number before any space
            orbit = cols[5].text.strip()
            launch_outcome = cols[7].text.strip().lower()

            if "success" not in launch_outcome:
                payload_mass = "0"

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
    fig1 = plot_payload_mass_to_orbit_by_year()
    fig2 = plot_cumulative_payload_mass_to_orbit(df_filtered)
    if output:
        save_plots(fig1, fig2)
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
