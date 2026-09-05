import os
import yaml

def generate_default_config(output_path="download_config.yaml"):
    config = {
        "usgs_username": "YOUR_USGS_USERNAME",
        "usgs_password": "YOUR_USGS_PASSWORD",
        "dataset": "landsat_ot_c2_l2",
        "year": 2025,
        "cloud_cover": 10,
        "raw_landsat_dir": "G:/My Drive/Raw_Landsat",
        "temp_download_dir": "temp_download",
        "bands": ["SR_B2", "SR_B3", "SR_B4", "SR_B5", "ST_B10", "QA_PIXEL"],
        "locations": [
            # 1. Urban
            {
                "name": "Mumbai", "latitude": 19.0760, "longitude": 72.8777,
                "seasons": [
                    {"name": "Summer", "start_date": "2025-03-01", "end_date": "2025-05-31"}
                ]
            },
            {
                "name": "NewYorkCity", "latitude": 40.7128, "longitude": -74.0060,
                "seasons": [
                    {"name": "Winter", "start_date": "2025-12-01", "end_date": "2026-02-28"}
                ]
            },
            # 2. Agriculture
            {
                "name": "Punjab", "latitude": 30.9010, "longitude": 75.8573,
                "seasons": [
                    {"name": "Growing", "start_date": "2025-07-01", "end_date": "2025-09-30"}
                ]
            },
            {
                "name": "Iowa", "latitude": 41.8780, "longitude": -93.0977,
                "seasons": [
                    {"name": "Harvest", "start_date": "2025-09-01", "end_date": "2025-11-30"}
                ]
            },
            # 3. Forest
            {
                "name": "WesternGhats", "latitude": 10.1632, "longitude": 77.0600,
                "seasons": [
                    {"name": "Summer", "start_date": "2025-03-01", "end_date": "2025-05-31"}
                ]
            },
            {
                "name": "BlackForest", "latitude": 48.0500, "longitude": 8.1500,
                "seasons": [
                    {"name": "Autumn", "start_date": "2025-09-01", "end_date": "2025-11-30"}
                ]
            },
            # 4. Desert
            {
                "name": "Thar", "latitude": 26.9157, "longitude": 70.9083,
                "seasons": [
                    {"name": "Summer", "start_date": "2025-03-01", "end_date": "2025-05-31"}
                ]
            },
            {
                "name": "Atacama", "latitude": -23.8634, "longitude": -69.1328,
                "seasons": [
                    {"name": "Winter", "start_date": "2025-06-01", "end_date": "2025-08-31"}
                ]
            },
            # 5. Mountains
            {
                "name": "Ladakh", "latitude": 34.1526, "longitude": 77.5771,
                "seasons": [
                    {"name": "Summer", "start_date": "2025-06-01", "end_date": "2025-08-31"}
                ]
            },
            {
                "name": "SwissAlps", "latitude": 46.5613, "longitude": 8.3585, "cloud_cover": 20,
                "seasons": [
                    {"name": "Winter", "start_date": "2025-12-01", "end_date": "2026-02-28"}
                ]
            },
            # 6. Coast
            {
                "name": "Chennai", "latitude": 13.0827, "longitude": 80.2707,
                "seasons": [
                    {"name": "Summer", "start_date": "2025-03-01", "end_date": "2025-05-31"}
                ]
            },
            {
                "name": "Sydney", "latitude": -33.8688, "longitude": 151.2093,
                "seasons": [
                    {"name": "Winter", "start_date": "2025-06-01", "end_date": "2025-08-31"}
                ]
            },
            # 7. Wetlands
            {
                "name": "Sundarbans", "latitude": 21.9497, "longitude": 89.1833,
                "seasons": [
                    {"name": "Summer", "start_date": "2025-03-01", "end_date": "2025-05-31"}
                ]
            },
            {
                "name": "Everglades", "latitude": 25.2866, "longitude": -80.8987,
                "seasons": [
                    {"name": "Winter", "start_date": "2025-12-01", "end_date": "2026-02-28"}
                ]
            }
        ]
    }

    with open(output_path, "w") as f:
        yaml.dump(config, f, sort_keys=False, default_flow_style=False)

    print(f"Generated configuration file at: {output_path}")

if __name__ == "__main__":
    generate_default_config()
