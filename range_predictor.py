import joblib
import pandas as pd


# Load the trained model once when the backend starts
model = joblib.load("models/range_model.pkl")


def predict_range(
    soc: float,
    battery_temp: float,
    speed: float,
    ac_on: int,
    distance_travelled: float,
    energy_consumed: float
) -> float:

    vehicle_data = pd.DataFrame([{
        "soc": soc,
        "battery_temp": battery_temp,
        "speed": speed,
        "ac_on": ac_on,
        "distance_travelled": distance_travelled,
        "energy_consumed": energy_consumed
    }])

    prediction = model.predict(vehicle_data)[0]

    return round(float(prediction), 2)
