import pandas as pd
import joblib

from sklearn.model_selection import train_test_split
from sklearn.ensemble import RandomForestRegressor
from sklearn.metrics import mean_absolute_error, r2_score


# Load dataset
data = pd.read_csv("range_data.csv")

# Input features
X = data[
    [
        "soc",
        "battery_temp",
        "speed",
        "ac_on",
        "distance_travelled",
        "energy_consumed"
    ]
]

# Target
y = data["remaining_range"]


# Split dataset
X_train, X_test, y_train, y_test = train_test_split(
    X,
    y,
    test_size=0.2,
    random_state=42
)


# Create model
model = RandomForestRegressor(
    n_estimators=200,
    random_state=42
)


# Train
model.fit(X_train, y_train)


# Test
predictions = model.predict(X_test)

mae = mean_absolute_error(y_test, predictions)
r2 = r2_score(y_test, predictions)

print("Model trained successfully")
print(f"MAE: {mae:.2f} km")
print(f"R² Score: {r2:.2f}")


# Save model
joblib.dump(model, "models/range_model.pkl")

print("Model saved to models/range_model.pkl")
r2 = r2_score(y_test, predictions)

print("Model trained successfully")
print(f"MAE: {mae:.2f} km")
print(f"R² Score: {r2:.2f}")


# Save model
joblib.dump(model, "models/range_model.pkl")

print("Model saved to models/range_model.pkl")

