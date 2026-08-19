import joblib
import os

MODEL_PATH = os.path.join(
    os.path.dirname(__file__),
    "models",
    "charging_time_model.pkl"
)

model = joblib.load(MODEL_PATH)


def predict_charging_time(
    current_soc,
    target_soc,
    battery_temp,
    charger_power_kw,
    battery_capacity_kwh
):
    features = [[
        current_soc,
        target_soc,
        battery_temp,
        charger_power_kw,
        battery_capacity_kwh
    ]]

    prediction = model.predict(features)[0]

    return float(prediction)
