import pandas as pd
import joblib

from sklearn.model_selection import train_test_split
from sklearn.ensemble import RandomForestRegressor
from sklearn.metrics import mean_absolute_error, r2_score


# Load data
data = pd.read_csv("data/charging_data.csv")


# Features
X = data[
    [
        "current_soc",
        "target_soc",
        "battery_temp",
        "charger_power_kw",
        "battery_capacity_kwh"
    ]
]


# Target
y = data["charging_time_minutes"]


# Train/test split
X_train, X_test, y_train, y_test = train_test_split(
    X,
    y,
    test_size=0.2,
    random_state=42
)


# Model
model = RandomForestRegressor(
    n_estimators=200,
    random_state=42
)


# Train
model.fit(X_train, y_train)


# Evaluate
predictions = model.predict(X_test)

mae = mean_absolute_error(
    y_test,
    predictions
)

r2 = r2_score(
    y_test,
    predictions
)


print("Charging model trained successfully")
print(f"MAE: {mae:.2f} minutes")
print(f"R² Score: {r2:.2f}")


# Save model
joblib.dump(
    model,
    "models/charging_time_model.pkl"
)

print(
    "Model saved to models/charging_time_model.pkl"
)