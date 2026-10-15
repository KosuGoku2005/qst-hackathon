#!/usr/bin/env python3
"""
inspect_data.py
---------------
Inspects the Zurich VBZ transit datasets in:
  - Data/Passengerdata/ (gefaessgroesse, haltestellen, linie, reisende, tagtyp)
  - Data/Traveltimes/   (fahrzeiten_soll_ist_*, haltepunkt, haltestelle)

Loads the CSV files using pandas, displays their columns, data types, sample rows,
and explains the Zurich transit corridor structure and cross-table linkages.
"""

from pathlib import Path
import pandas as pd

# Set display options for clean terminal output
pd.set_option("display.max_columns", 15)
pd.set_option("display.width", 120)
pd.set_option("display.unicode.east_asian_width", False)


def inspect_csv(file_path: Path, sep: str, encoding: str = "utf-8", nrows: int = 5):
    """Load a sample of a CSV and print schema and sample rows."""
    print("=" * 80)
    print(f"FILE: {file_path.name}")
    print(f"Path: {file_path}")
    print(f"Format: sep='{sep}', encoding='{encoding}'")

    try:
        df = pd.read_csv(file_path, sep=sep, encoding=encoding, nrows=nrows)
        print(f"Columns ({len(df.columns)}): {list(df.columns)}")
        print("\nData Types:")
        for col, dtype in df.dtypes.items():
            print(f"  - {col}: {dtype}")
        print(f"\nSample Rows (first {nrows}):")
        print(df.to_string(index=False))
        return df
    except Exception as e:
        print(f"Error loading {file_path}: {e}")
        return None


def inspect_corridor_structure(base_dir: Path):
    """
    Demonstrate how tables link together to form transit corridors
    with stops, passenger load, vehicle capacity, and scheduled/actual travel times.
    """
    print("\n" + "#" * 80)
    print("ZURICH TRANSIT CORRIDOR STRUCTURE ANALYSIS")
    print("#" * 80)

    p_dir = base_dir / "Data" / "Passengerdata"
    t_dir = base_dir / "Data" / "Traveltimes"

    # 1. Load small lookup tables fully
    df_stops = pd.read_csv(p_dir / "haltestellen.csv", sep=";")
    df_lines = pd.read_csv(p_dir / "linie.csv", sep=";")
    df_cap = pd.read_csv(p_dir / "gefaessgroesse.csv", sep=";")
    df_travel_stops = pd.read_csv(t_dir / "haltestelle.csv", sep=",", encoding="utf-8-sig")
    df_stop_points = pd.read_csv(t_dir / "haltepunkt.csv", sep=",", encoding="utf-8-sig")

    # 2. Load samples of large operational tables
    df_reisende = pd.read_csv(p_dir / "reisende.csv", sep=";", nrows=5000)
    traveltime_file = next(t_dir.glob("fahrzeiten_soll_ist_*.csv"))
    df_travel = pd.read_csv(traveltime_file, sep=",", encoding="utf-8-sig", nrows=5000)

    print("\n1. NETWORK SUMMARY:")
    print(f"  - Passenger stops (haltestellen.csv): {len(df_stops):,} stops")
    print(f"  - Transit lines (linie.csv): {len(df_lines):,} lines (e.g. T=Tram, B=Bus)")
    print(f"  - Physical stops (haltestelle.csv): {len(df_travel_stops):,} stops")
    print(f"  - Boarding platforms/points with GPS (haltepunkt.csv): {len(df_stop_points):,} stop points")

    # 3. Corridor Segment demonstration in Passenger data
    print("\n2. PASSENGER CORRIDOR SEGMENTS (reisende.csv):")
    print("  Corridor segments represent directional edges between consecutive stops:")
    print("  Columns: Haltestellen_Id -> Nach_Hst_Id, ID_Abschnitt, Sequenz, Distanz, Besetzung (occupancy)")
    
    # Pick a sample line trip
    sample_trip_id = df_reisende["Plan_Fahrt_Id"].iloc[0]
    sample_corridor = df_reisende[df_reisende["Plan_Fahrt_Id"] == sample_trip_id].sort_values("Sequenz")
    
    # Merge stop names
    sample_corridor = sample_corridor.merge(
        df_stops[["Haltestellen_Id", "Haltestellenkurzname", "Haltestellenlangname"]],
        on="Haltestellen_Id",
        how="left"
    )
    cols_to_show = ["Linienname", "Richtung", "Sequenz", "Haltestellenkurzname", "Haltestellenlangname", 
                    "FZ_AB", "Einsteiger", "Aussteiger", "Besetzung", "Distanz", "ID_Abschnitt"]
    print(f"\n  Sample Trip Corridor (Plan_Fahrt_Id = {sample_trip_id}):")
    print(sample_corridor[cols_to_show].head(6).to_string(index=False))

    # Check vehicle capacity for this trip
    cap_info = df_cap[df_cap["Plan_Fahrt_Id"] == sample_trip_id]
    if not cap_info.empty:
        c = cap_info.iloc[0]
        print(f"\n  Vehicle Capacity for Trip {sample_trip_id}:")
        print(f"    Seats: {c['SITZPLAETZE']}, Max Cap (4m²): {c['KAP_4m2']}")

    # 4. Corridor Segments in Travel Times data
    print("\n3. TRAVEL TIME & DELAY SEGMENTS (fahrzeiten_soll_ist_*.csv):")
    print("  Segments contain scheduled ('soll') and actual ('ist') times in seconds past midnight.")
    sample_fahrt = df_travel["fahrt_id"].iloc[0]
    sample_travel_corridor = df_travel[df_travel["fahrt_id"] == sample_fahrt].sort_values("seq_von")
    
    # Calculate delays
    sample_travel_corridor = sample_travel_corridor.copy()
    sample_travel_corridor["dep_delay_sec"] = sample_travel_corridor["ist_ab_von"] - sample_travel_corridor["soll_ab_von"]
    sample_travel_corridor["arr_delay_sec"] = sample_travel_corridor["ist_an_nach1"] - sample_travel_corridor["soll_an_nach"]
    
    t_cols = ["linie", "richtung", "seq_von", "halt_kurz_von1", "seq_nach", "halt_kurz_nach1", 
              "soll_ab_von", "ist_ab_von", "dep_delay_sec", "arr_delay_sec", "fw_lang"]
    print(f"\n  Sample Travel Run (fahrt_id = {sample_fahrt}):")
    print(sample_travel_corridor[t_cols].head(6).to_string(index=False))

    # 5. Cross-dataset link
    print("\n4. CROSS-DATASET LINKAGE KEY:")
    print("  - Passenger Haltestellen.csv ['Haltestellennummer'] <===> Traveltimes Haltestelle.csv ['halt_diva']")
    print("  - Stop names: Haltestellenkurzname <===> halt_kurz, Haltestellenlangname <===> halt_lang")
    print("  - Line IDs: Linienname in linie.csv <===> linie in fahrzeiten_soll_ist_*.csv")
    print("  - GPS Coordinates: Found in haltepunkt.csv ('GPS_Latitude', 'GPS_Longitude') via halt_id / halt_diva")


def main():
    base_dir = Path(__file__).resolve().parent

    print("=" * 80)
    print("ZURICH TRANSIT DATASET INSPECTION (VBZ OPEN GOVERNMENT DATA)")
    print("=" * 80)

    # 1. Inspect Passenger Data
    p_dir = base_dir / "Data" / "Passengerdata"
    print("\nPART 1: PASSENGER DATASETS (Data/Passengerdata/)")
    passenger_files = [
        "haltestellen.csv",
        "linie.csv",
        "tagtyp.csv",
        "gefaessgroesse.csv",
        "reisende.csv",
    ]
    for fname in passenger_files:
        fpath = p_dir / fname
        if fpath.exists():
            inspect_csv(fpath, sep=";", encoding="utf-8", nrows=3)
        else:
            print(f"File not found: {fpath}")

    # 2. Inspect Travel Times Data
    t_dir = base_dir / "Data" / "Traveltimes"
    print("\nPART 2: TRAVEL TIME DATASETS (Data/Traveltimes/)")
    travel_files = [
        "haltestelle.csv",
        "haltepunkt.csv",
    ]
    # Add fahrzeiten file dynamically
    travel_files.extend([f.name for f in t_dir.glob("fahrzeiten_soll_ist_*.csv")])
    for fname in travel_files:
        fpath = t_dir / fname
        if fpath.exists():
            inspect_csv(fpath, sep=",", encoding="utf-8-sig", nrows=3)
        else:
            print(f"File not found: {fpath}")

    # 3. Inspect Transit Corridor Linkages
    inspect_corridor_structure(base_dir)


if __name__ == "__main__":
    main()
