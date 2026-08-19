import os
import requests

GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")

if not GOOGLE_API_KEY:
    raise RuntimeError("GOOGLE_API_KEY is not set")


ROUTES_URL = "https://routes.googleapis.com/directions/v2:computeRoutes"


def get_route(
    start_lat: float,
    start_lng: float,
    end_lat: float,
    end_lng: float
):
    headers = {
        "Content-Type": "application/json",
        "X-Goog-Api-Key": GOOGLE_API_KEY,
        "X-Goog-FieldMask": (
            "routes.duration,"
            "routes.distanceMeters,"
            "routes.polyline.encodedPolyline"
        ),
    }

    payload = {
        "origin": {
            "location": {
                "latLng": {
                    "latitude": start_lat,
                    "longitude": start_lng
                }
            }
        },
        "destination": {
            "location": {
                "latLng": {
                    "latitude": end_lat,
                    "longitude": end_lng
                }
            }
        },
        "travelMode": "DRIVE"
    }

    response = requests.post(
        ROUTES_URL,
        headers=headers,
        json=payload,
        timeout=30
    )

    response.raise_for_status()

    routes = response.json().get("routes", [])

    if not routes:
        return None

    route = routes[0]

    distance_km = route.get("distanceMeters", 0) / 1000

    duration_string = route.get("duration", "0s")
    duration_seconds = float(duration_string.rstrip("s"))
    duration_minutes = duration_seconds / 60

    return {
        "distance_km": distance_km,
        "duration_minutes": duration_minutes,
        "polyline": route.get("polyline", {}).get(
            "encodedPolyline"
        )
    }
