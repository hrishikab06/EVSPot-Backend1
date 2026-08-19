from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import Optional
from datetime import datetime, timedelta, timezone
from ocpi_mock import router as ocpi_router
import bcrypt

from database import get_connection
from range_predictor import predict_range
from charging_time_predictor import predict_charging_time
from route_service import get_route

app = FastAPI(title="EVSpot API")
app.include_router(ocpi_router)

# =========================================================
# REQUEST MODELS
# =========================================================

class ChargerAvailabilityRequest(BaseModel):
    start_time: datetime
    end_time: datetime

class RegisterRequest(BaseModel):
    email: str
    password: str
    full_name: str
    phone: Optional[str] = None


class LoginRequest(BaseModel):
    email: str
    password: str


class BookingRequest(BaseModel):
    user_id: int
    charger_id: int
    start_time: datetime
    end_time: datetime
    estimated_cost_inr: Optional[float] = None

class RangePredictionRequest(BaseModel):
    soc: float
    battery_temp: float
    speed: float
    ac_on: int
    distance_travelled: float
    energy_consumed: float

class ChargingTimePredictionRequest(BaseModel):
    current_soc: float
    target_soc: float
    battery_temp: float
    charger_power_kw: float
    battery_capacity_kwh: float

class CandidateStation(BaseModel):
    id: str
    name: str
    address: str
    latitude: float
    longitude: float


class PlanTripRequest(BaseModel):
    current_lat: float
    current_lng: float

    destination_lat: float
    destination_lng: float

    current_soc: float
    battery_temp: float
    battery_capacity_kwh: float

    candidate_stations: list[CandidateStation]

# =========================================================
# BOOKING HELPERS
# =========================================================

def expire_old_bookings(cursor):
    """
    Mark BOOKED reservations as EXPIRED when
    the 10-minute arrival window has passed.
    """

    cursor.execute(
        """
        UPDATE bookings
        SET status = 'EXPIRED'
        WHERE status = 'BOOKED'
          AND CURRENT_TIMESTAMP > start_time + INTERVAL '10 minutes'
        """
    )


# =========================================================
# BASIC ROUTES
# =========================================================

@app.get("/")
def root():
    return {
        "message": "EVSpot backend is running!"
    }


@app.get("/db-test")
def db_test():

    conn = get_connection()
    cursor = conn.cursor()

    try:
        cursor.execute("SELECT COUNT(*) FROM users")
        user_count = cursor.fetchone()[0]

        return {
            "database": "connected",
            "users": user_count
        }

    finally:
        cursor.close()
        conn.close()

@app.post("/predict-range")
def predict_vehicle_range(data: RangePredictionRequest):

    try:
        predicted_range = predict_range(
            soc=data.soc,
            battery_temp=data.battery_temp,
            speed=data.speed,
            ac_on=data.ac_on,
            distance_travelled=data.distance_travelled,
            energy_consumed=data.energy_consumed
        )

        return {
            "predicted_range_km": predicted_range
        }

    except Exception as e:
        print("Range prediction error:", e)

        raise HTTPException(
            status_code=500,
            detail="Range prediction failed"
        )

@app.post("/predict-charging-time")
def predict_vehicle_charging_time(data: ChargingTimePredictionRequest):

    try:
        predicted_time = predict_charging_time(
            current_soc=data.current_soc,
            target_soc=data.target_soc,
            battery_temp=data.battery_temp,
            charger_power_kw=data.charger_power_kw,
            battery_capacity_kwh=data.battery_capacity_kwh
        )

        return {
            "predicted_charging_time_minutes": round(predicted_time, 2)
        }

    except Exception as e:
        print("Charging time prediction error:", e)

        raise HTTPException(
            status_code=500,
            detail="Charging time prediction failed"
        )

@app.post("/plan-trip")
def plan_trip(data: PlanTripRequest):

    if not data.candidate_stations:
        raise HTTPException(
            status_code=400,
            detail="No candidate charging stations provided"
        )

    # ---------------------------------------------------------
    # Prototype assumptions
    # ---------------------------------------------------------
    energy_consumption_kwh_per_km = 0.18
    charger_power_kw = 50.0
    target_soc = 62.0

    current_energy_kwh = (
        data.current_soc / 100
    ) * data.battery_capacity_kwh

    evaluated_stations = []

    # ---------------------------------------------------------
    # Evaluate every candidate station
    # ---------------------------------------------------------
    for station in data.candidate_stations:

        # Current location -> charging station
        route_to_station = get_route(
            data.current_lat,
            data.current_lng,
            station.latitude,
            station.longitude
        )

        if route_to_station is None:
            continue

        # Can the EV physically reach this station?
        energy_used_to_station = (
            route_to_station["distance_km"]
            * energy_consumption_kwh_per_km
        )

        if energy_used_to_station > current_energy_kwh:
            continue

        # Estimate SOC at arrival
        arrival_energy_kwh = (
            current_energy_kwh
            - energy_used_to_station
        )

        arrival_soc = (
            arrival_energy_kwh
            / data.battery_capacity_kwh
        ) * 100

        arrival_soc = max(
            0.0,
            min(arrival_soc, 100.0)
        )

        # Predict charging time
        charging_time = predict_charging_time(
            current_soc=arrival_soc,
            target_soc=target_soc,
            battery_temp=data.battery_temp,
            charger_power_kw=charger_power_kw,
            battery_capacity_kwh=data.battery_capacity_kwh
        )

        # Energy/range available after charging
        energy_after_charging_kwh = (
            target_soc / 100
        ) * data.battery_capacity_kwh

        max_range_after_charging_km = (
            energy_after_charging_kwh
            / energy_consumption_kwh_per_km
        )

        # -----------------------------------------------------
        # Station -> destination
        # -----------------------------------------------------

        route_from_station = get_route(
            station.latitude,
            station.longitude,
            data.destination_lat,
            data.destination_lng
        )

        if route_from_station is None:
            continue

        # IMPORTANT:
        # For the one-stop planner, the destination must be
        # reachable after the single charging stop.
        if (
            route_from_station["distance_km"]
            > max_range_after_charging_km
        ):
            continue

        total_drive_distance = (
            route_to_station["distance_km"]
            + route_from_station["distance_km"]
        )

        total_drive_time = (
            route_to_station["duration_minutes"]
            + route_from_station["duration_minutes"]
        )

        total_trip_time = (
            total_drive_time
            + charging_time
        )

        evaluated_stations.append({
            "station": station,
            "route_to_station": route_to_station,
            "route_from_station": route_from_station,
            "arrival_soc": arrival_soc,
            "charging_time": charging_time,
            "total_drive_distance": total_drive_distance,
            "total_drive_time": total_drive_time,
            "total_trip_time": total_trip_time
        })

    # ---------------------------------------------------------
    # No valid one-stop solution
    # ---------------------------------------------------------

        if not evaluated_stations:
          return {
            "one_stop_possible": False,
            "message": (
                "No single charging station can complete "
                "this trip with one charging stop."
            ),

            "total_distance_km": round(
                direct_route["distance_km"],
                2
            ),

            "drive_time_minutes": round(
                direct_route["duration_minutes"],
                2
            ),

            "recommended_station": None,

            "arrival_soc_percent": None,

            "target_soc_percent": target_soc,

            "charging_time_minutes": None,

            "charging_cost_inr": 0.0,

            "total_trip_time_minutes": round(
                direct_route["duration_minutes"],
                2
            ),

            "route_plan": [
                {
                    "type": "start",
                    "name": "Your Location",
                    "distance_km": round(
                        direct_route["distance_km"],
                        2
                    ),
                    "drive_time_minutes": round(
                        direct_route["duration_minutes"],
                        2
                    )
                },
                {
                    "type": "destination",
                    "name": "Destination",
                    "distance_km": round(
                        direct_route["distance_km"],
                        2
                    ),
                    "drive_time_minutes": round(
                        direct_route["duration_minutes"],
                        2
                    )
                }
            ]
        }

    # ---------------------------------------------------------
    # Choose fastest valid one-stop station
    # ---------------------------------------------------------

    best = min(
        evaluated_stations,
        key=lambda item: item["total_trip_time"]
    )

    station = best["station"]
    route_to_station = best["route_to_station"]
    route_from_station = best["route_from_station"]
    arrival_soc = best["arrival_soc"]
    charging_time = best["charging_time"]
    total_drive_distance = best["total_drive_distance"]
    total_drive_time = best["total_drive_time"]
    total_trip_time = best["total_trip_time"]

    return {
        "one_stop_possible": True,

        "message": "One-stop charging plan found.",

        "total_distance_km": round(
            total_drive_distance,
            2
        ),

        "drive_time_minutes": round(
            total_drive_time,
            2
        ),

        "recommended_station": {
            "id": station.id,
            "name": station.name,
            "address": station.address,
            "latitude": station.latitude,
            "longitude": station.longitude
        },

        "arrival_soc_percent": round(
            arrival_soc,
            2
        ),

        "target_soc_percent": target_soc,

        "charging_time_minutes": round(
            charging_time,
            2
        ),

        "charging_cost_inr": 0.0,

        "total_trip_time_minutes": round(
            total_trip_time,
            2
        ),

        "route_plan": [
            {
                "type": "start",
                "name": "Your Location",
                "distance_km": round(
                    route_to_station["distance_km"],
                    2
                ),
                "drive_time_minutes": round(
                    route_to_station["duration_minutes"],
                    2
                )
            },
            {
                "type": "charging",
                "name": station.name,
                "charging_time_minutes": round(
                    charging_time,
                    2
                )
            },
            {
                "type": "destination",
                "name": "Destination",
                "distance_km": round(
                    route_from_station["distance_km"],
                    2
                ),
                "drive_time_minutes": round(
                    route_from_station["duration_minutes"],
                    2
                )
            }
        ]
    }

# =========================================================
# AUTHENTICATION
# =========================================================

@app.post("/register")
def register(user: RegisterRequest):

    # bcrypt has a 72-byte password limit
    if len(user.password.encode("utf-8")) > 72:
        raise HTTPException(
            status_code=400,
            detail="Password must be 72 bytes or less"
        )

    if len(user.password) < 6:
        raise HTTPException(
            status_code=400,
            detail="Password must be at least 6 characters"
        )

    password_hash = bcrypt.hashpw(
        user.password.encode("utf-8"),
        bcrypt.gensalt()
    ).decode("utf-8")

    conn = get_connection()
    cursor = conn.cursor()

    try:

        cursor.execute(
            """
            INSERT INTO users (
                email,
                password_hash,
                full_name,
                phone
            )
            VALUES (%s, %s, %s, %s)
            RETURNING id
            """,
            (
                user.email,
                password_hash,
                user.full_name,
                user.phone
            )
        )

        user_id = cursor.fetchone()[0]

        conn.commit()

        return {
            "message": "Registration successful",
            "user_id": user_id
        }

    except Exception as e:

        conn.rollback()

        if "duplicate key" in str(e).lower():
            raise HTTPException(
                status_code=409,
                detail="Email already registered"
            )

        print("Registration error:", e)

        raise HTTPException(
            status_code=500,
            detail="Registration failed"
        )

    finally:

        cursor.close()
        conn.close()


@app.post("/login")
def login(user: LoginRequest):

    conn = get_connection()
    cursor = conn.cursor()

    try:

        cursor.execute(
            """
            SELECT
                id,
                email,
                password_hash,
                full_name
            FROM users
            WHERE email = %s
            """,
            (user.email,)
        )

        db_user = cursor.fetchone()

        if db_user is None:
            raise HTTPException(
                status_code=401,
                detail="Invalid email or password"
            )

        user_id, email, password_hash, full_name = db_user

        password_valid = bcrypt.checkpw(
            user.password.encode("utf-8"),
            password_hash.encode("utf-8")
        )

        if not password_valid:
            raise HTTPException(
                status_code=401,
                detail="Invalid email or password"
            )

        return {
            "message": "Login successful",
            "user_id": user_id,
            "email": email,
            "full_name": full_name
        }

    finally:

        cursor.close()
        conn.close()


# =========================================================
# CREATE BOOKING
# =========================================================

@app.post("/bookings")
def create_booking(booking: BookingRequest):

    # -----------------------------------------------------
    # Validate booking time
    # -----------------------------------------------------

    if booking.end_time <= booking.start_time:
        raise HTTPException(
            status_code=400,
            detail="End time must be after start time"
        )

    conn = get_connection()
    cursor = conn.cursor()

    try:

        # -------------------------------------------------
        # Check user
        # -------------------------------------------------

        cursor.execute(
            """
            SELECT id
            FROM users
            WHERE id = %s
            """,
            (booking.user_id,)
        )

        if cursor.fetchone() is None:
            raise HTTPException(
                status_code=404,
                detail="User not found"
            )

        # -------------------------------------------------
        # Check charger
        # -------------------------------------------------

        cursor.execute(
            """
            SELECT id
            FROM chargers
            WHERE id = %s
            """,
            (booking.charger_id,)
        )

        if cursor.fetchone() is None:
            raise HTTPException(
                status_code=404,
                detail="Charger not found"
            )

        # -------------------------------------------------
        # Expire old bookings
        # -------------------------------------------------

        expire_old_bookings(cursor)

        # -------------------------------------------------
        # Check overlapping bookings
        # -------------------------------------------------

        cursor.execute(
            """
            SELECT id
            FROM bookings
            WHERE charger_id = %s
              AND status IN ('BOOKED','ACTIVE')
              AND start_time < %s
              AND end_time > %s
            """,
            (
                booking.charger_id,
                booking.end_time,
                booking.start_time
            )
        )

        if cursor.fetchone() is not None:
            raise HTTPException(
                status_code=409,
                detail="Charger is already booked for this time"
            )

        # -------------------------------------------------
        # Calculate arrival deadline
        # -------------------------------------------------

        arrival_deadline = (
            booking.start_time + timedelta(minutes=10)
        )

        # -------------------------------------------------
        # Create booking
        # -------------------------------------------------

        cursor.execute(
            """
            INSERT INTO bookings (
                user_id,
                charger_id,
                start_time,
                end_time,
                status,
                estimated_cost_inr
            )
            VALUES (
                %s,
                %s,
                %s,
                %s,
                'BOOKED',
                %s
            )
            RETURNING id, status, created_at
            """,
            (
                booking.user_id,
                booking.charger_id,
                booking.start_time,
                booking.end_time,
                booking.estimated_cost_inr
            )
        )

        booking_id, status, created_at = cursor.fetchone()

        conn.commit()

        return {
            "message": "Booking created successfully",
            "booking_id": booking_id,
            "status": status,
            "start_time": booking.start_time,
            "end_time": booking.end_time,
            "arrival_deadline": arrival_deadline,
            "created_at": created_at
        }

    except HTTPException:

        conn.rollback()
        raise

    except Exception as e:

        conn.rollback()

        print("Booking error:", e)

        raise HTTPException(
            status_code=500,
            detail="Failed to create booking"
        )

    finally:

        cursor.close()
        conn.close()


# =========================================================
# ARRIVE AT BOOKING
# =========================================================

@app.post("/bookings/{booking_id}/arrive")
def arrive_at_booking(booking_id: int):

    conn = get_connection()
    cursor = conn.cursor()

    try:

        # -------------------------------------------------
        # Find booking
        # -------------------------------------------------

        cursor.execute(
            """
            SELECT
                id,
                start_time,
                status
            FROM bookings
            WHERE id = %s
            """,
            (booking_id,)
        )

        booking = cursor.fetchone()

        if booking is None:
            raise HTTPException(
                status_code=404,
                detail="Booking not found"
            )

        booking_id, start_time, status = booking

        # -------------------------------------------------
        # Booking must still be BOOKED
        # -------------------------------------------------

        if status != "BOOKED":
            raise HTTPException(
                status_code=400,
                detail=f"Booking is already {status}"
            )

        # -------------------------------------------------
        # Current UTC time
        # -------------------------------------------------

        now = datetime.now(timezone.utc)

        if start_time.tzinfo is None:
            start_time = start_time.replace(
                tzinfo=timezone.utc
            )

        # -------------------------------------------------
        # 10-minute arrival window
        # -------------------------------------------------

        arrival_deadline = (
            start_time + timedelta(minutes=10)
        )

        # -------------------------------------------------
        # User arrived too late
        # -------------------------------------------------

        if now > arrival_deadline:

            cursor.execute(
                """
                UPDATE bookings
                SET status = 'EXPIRED'
                WHERE id = %s
                """,
                (booking_id,)
            )

            conn.commit()

            raise HTTPException(
                status_code=410,
                detail="Booking expired. Arrival window was 10 minutes."
            )

        # -------------------------------------------------
        # User arrived successfully
        # -------------------------------------------------

        cursor.execute(
            """
            UPDATE bookings
            SET
                status = 'ACTIVE',
                arrived_at = %s
            WHERE id = %s
            RETURNING
                id,
                status,
                arrived_at
            """,
            (
                now,
                booking_id
            )
        )

        updated_booking = cursor.fetchone()

        conn.commit()

        return {
            "message": "Arrival confirmed",
            "booking_id": updated_booking[0],
            "status": updated_booking[1],
            "arrived_at": updated_booking[2]
        }

    except HTTPException:

        conn.rollback()
        raise

    except Exception as e:

        conn.rollback()

        print("Arrival error:", e)

        raise HTTPException(
            status_code=500,
            detail="Failed to confirm arrival"
        )

    finally:

        cursor.close()
        conn.close()
# =========================================================
# CHARGING STATIONS
# =========================================================

@app.get("/stations")
def get_stations():

    conn = get_connection()
    cursor = conn.cursor()

    try:
        cursor.execute(
            """
            SELECT
                id,
                name,
                address,
                city,
                state,
                postal_code,
                latitude,
                longitude,
                operator_name,
                access_type,
                open_24_7,
                opening_hours,
                amenities
            FROM charging_stations
            ORDER BY id
            """
        )

        rows = cursor.fetchall()

        stations = []

        for row in rows:
            stations.append({
                "id": row[0],
                "name": row[1],
                "address": row[2],
                "city": row[3],
                "state": row[4],
                "postal_code": row[5],
                "latitude": float(row[6]),
                "longitude": float(row[7]),
                "operator_name": row[8],
                "access_type": row[9],
                "open_24_7": row[10],
                "opening_hours": row[11],
                "amenities": row[12]
            })

        return {
            "count": len(stations),
            "stations": stations
        }

    finally:
        cursor.close()
        conn.close()
@app.get("/stations/{station_id}")
def get_station(station_id: int):

    conn = get_connection()
    cursor = conn.cursor()

    try:
        cursor.execute(
            """
            SELECT
                id,
                name,
                address,
                city,
                state,
                postal_code,
                latitude,
                longitude,
                operator_name,
                access_type,
                open_24_7,
                opening_hours,
                amenities
            FROM charging_stations
            WHERE id = %s
            """,
            (station_id,)
        )

        row = cursor.fetchone()

        if row is None:
            raise HTTPException(
                status_code=404,
                detail="Station not found"
            )

        return {
            "id": row[0],
            "name": row[1],
            "address": row[2],
            "city": row[3],
            "state": row[4],
            "postal_code": row[5],
            "latitude": float(row[6]),
            "longitude": float(row[7]),
            "operator_name": row[8],
            "access_type": row[9],
            "open_24_7": row[10],
            "opening_hours": row[11],
            "amenities": row[12]
        }

    finally:
        cursor.close()
        conn.close()
@app.get("/stations/{station_id}/chargers")
def get_station_chargers(station_id: int):

    conn = get_connection()
    cursor = conn.cursor()

    try:
        cursor.execute(
            """
            SELECT
                c.id,
                c.station_id,
                c.connector_type,
                c.power_kw,
                c.status,

                CASE
                    WHEN EXISTS (
                        SELECT 1
                        FROM bookings b
                        WHERE b.charger_id = c.id
                          AND b.status IN ('BOOKED', 'ACTIVE')
                          AND b.start_time <= CURRENT_TIMESTAMP
                          AND b.end_time > CURRENT_TIMESTAMP
                    )
                    THEN false

                    WHEN c.status <> 'available'
                    THEN false

                    ELSE true
                END AS is_available

            FROM chargers c
            WHERE c.station_id = %s
            ORDER BY c.id
            """,
            (station_id,)
        )

        rows = cursor.fetchall()

        return {
            "station_id": station_id,
            "count": len(rows),
            "chargers": [
                {
                    "id": row[0],
                    "station_id": row[1],
                    "connector_type": row[2],
                    "power_kw": float(row[3]),
                    "status": row[4],
                    "is_available": row[5]
                }
                for row in rows
            ]
        }

    finally:
        cursor.close()
        conn.close()
# =========================================================
# CHECK CHARGER AVAILABILITY FOR A TIME SLOT
# =========================================================

@app.post("/chargers/{charger_id}/availability")
def check_charger_availability(
    charger_id: int,
    request: ChargerAvailabilityRequest
):

    if request.end_time <= request.start_time:
        raise HTTPException(
            status_code=400,
            detail="End time must be after start time"
        )

    conn = get_connection()
    cursor = conn.cursor()

    try:

        # -------------------------------------------------
        # Check charger exists
        # -------------------------------------------------

        cursor.execute(
            """
            SELECT id, status
            FROM chargers
            WHERE id = %s
            """,
            (charger_id,)
        )

        charger = cursor.fetchone()

        if charger is None:
            raise HTTPException(
                status_code=404,
                detail="Charger not found"
            )

        charger_id_db, charger_status = charger

        # -------------------------------------------------
        # Check physical charger status
        # -------------------------------------------------

        if charger_status != "available":
            return {
                "charger_id": charger_id,
                "available": False,
                "reason": "Charger is not operational"
            }

        # -------------------------------------------------
        # Check overlapping bookings
        # -------------------------------------------------

        cursor.execute(
            """
            SELECT
                id,
                start_time,
                end_time,
                status
            FROM bookings
            WHERE charger_id = %s
              AND status IN ('BOOKED', 'ACTIVE')
              AND start_time < %s
              AND end_time > %s
            LIMIT 1
            """,
            (
                charger_id,
                request.end_time,
                request.start_time
            )
        )

        existing_booking = cursor.fetchone()

        if existing_booking is not None:
            return {
                "charger_id": charger_id,
                "available": False,
                "reason": "Charger is already booked for this time"
            }

        # -------------------------------------------------
        # Available
        # -------------------------------------------------

        return {
            "charger_id": charger_id,
            "available": True,
            "reason": "Charger is available for this time"
        }

    finally:

        cursor.close()
        conn.close()
