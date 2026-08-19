import os
import requests
from database import get_connection


GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")

if not GOOGLE_API_KEY:
    raise RuntimeError("GOOGLE_API_KEY is not set")


# Mumbai search points
# Multiple points are necessary because Google returns
# a limited number of results per se
  
   # =========================================================
# MUMBAI GRID SEARCH
# =========================================================

SEARCH_POINTS = []

# Approximate Mumbai coverage
MIN_LAT = 18.88
MAX_LAT = 19.30

MIN_LNG = 72.77
MAX_LNG = 73.05

# Grid spacing
LAT_STEP = 0.02
LNG_STEP = 0.02

lat = MIN_LAT

while lat <= MAX_LAT:
    lng = MIN_LNG

    while lng <= MAX_LNG:
        SEARCH_POINTS.append((lat, lng))
        lng += LNG_STEP

    lat += LAT_STEP

print(f"Generated {len(SEARCH_POINTS)} search points")

URL = "https://places.googleapis.com/v1/places:searchNearby"

HEADERS = {
    "Content-Type": "application/json",
    "X-Goog-Api-Key": GOOGLE_API_KEY,
    "X-Goog-FieldMask": (
        "places.id,"
        "places.displayName,"
        "places.formattedAddress,"
        "places.location,"
        "places.businessStatus"
    ),
}


def search_google(latitude, longitude):

    payload = {
        "includedTypes": [
            "electric_vehicle_charging_station"
        ],
        "maxResultCount": 20,
        "locationRestriction": {
            "circle": {
                "center": {
                    "latitude": latitude,
                    "longitude": longitude
                },
                "radius": 10000
            }
        }
    }

    response = requests.post(
        URL,
        headers=HEADERS,
        json=payload,
        timeout=30
    )

    response.raise_for_status()

    return response.json().get("places", [])


def import_station(cursor, place):

    # Ignore temporarily closed stations
    if place.get("businessStatus") == "CLOSED_TEMPORARILY":
        return False

    place_id = place.get("id")
    name = place.get("displayName", {}).get(
        "text",
        "EV Charging Station"
    )

    address = place.get(
        "formattedAddress",
        "Mumbai"
    )

    location = place.get("location", {})

    latitude = location.get("latitude")
    longitude = location.get("longitude")

    if not place_id or latitude is None or longitude is None:
        return False

    # Check if we already imported this location.
    # We use the coordinates + name combination because
    # the current database does not have a Google Place ID column.
    cursor.execute(
        """
        SELECT id
        FROM charging_stations
        WHERE name = %s
          AND ABS(latitude - %s) < 0.0001
          AND ABS(longitude - %s) < 0.0001
        LIMIT 1
        """,
        (name, latitude, longitude)
    )

    if cursor.fetchone():
        return False

    # Insert station
    cursor.execute(
        """
        INSERT INTO charging_stations (
            name,
            address,
            city,
            state,
            postal_code,
            latitude,
            longitude,
            operator_name,
            access_type,
            open_24_7
        )
        VALUES (
            %s,
            %s,
            'Mumbai',
            'Maharashtra',
            NULL,
            %s,
            %s,
            %s,
            'public',
            TRUE
        )
        RETURNING id
        """,
        (
            name,
            address,
            latitude,
            longitude,
            name
        )
    )

    station_id = cursor.fetchone()[0]

    # Create a basic charger.
    #
    # Google Places does not reliably provide connector,
    # power or live availability information through this
    # request, so we deliberately mark these as estimates.
    cursor.execute(
        """
        INSERT INTO chargers (
            station_id,
            connector_type,
            power_kw,
            status
        )
        VALUES (
            %s,
            'UNKNOWN',
            0,
            'available'
        )
        """,
        (station_id,)
    )

    print(f"ADDED: {name} ({latitude}, {longitude})")

    return True


def main():

    print("Starting Mumbai EV station import...")

    all_places = {}

    # Search every point
    for latitude, longitude in SEARCH_POINTS:

        print(
            f"Searching: {latitude}, {longitude}"
        )

        places = search_google(
            latitude,
            longitude
        )

        print(
            f"  Found {len(places)} places"
        )

        # Deduplicate using Google's Place ID
        for place in places:

            place_id = place.get("id")

            if place_id:
                all_places[place_id] = place

    print()
    print(
        f"Unique Google places found: {len(all_places)}"
    )

    conn = get_connection()
    cursor = conn.cursor()

    added = 0
    skipped = 0

    try:

        for place in all_places.values():

            if import_station(cursor, place):
                added += 1
            else:
                skipped += 1

        conn.commit()

        print()
        print("IMPORT COMPLETE")
        print(f"Added:   {added}")
        print(f"Skipped: {skipped}")

    except Exception:

        conn.rollback()
        raise

    finally:

        cursor.close()
        conn.close()


if __name__ == "__main__":
    main()
