import pandas as pd
import numpy as np

np.random.seed(42)

rows = 2000

data = []

for _ in range(rows):

    soc = np.random.uniform(15, 100)
    battery_temp = np.random.uniform(20, 45)
    speed = np.random.uniform(30, 110)
    ac_on = np.random.randint(0, 2)

    distance_travelled = np.random.uniform(5, 100)

    # Simulated energy consumption
    base_consumption = 0.12 * speed

    temperature_factor = 1 + abs(battery_temp - 25) * 0.01
    ac_factor = 1.08 if ac_on else 1.0

    energy_consumed = (
        distance_travelled
        * base_consumption
        / 100
        * temperature_factor
        * ac_factor
        * np.random.uniform(0.9, 1.1)
    )

    # Simulated remaining range
    efficiency = (
        18
        * temperature_factor
        * ac_factor
        * (1 + speed / 150)
    )

    remaining_range = (
        soc / 100
        * 350
        / (efficiency / 18)
    )

    remaining_range += np.random.normal(0, 5)

    remaining_range = max(remaining_range, 5)

    data.append([
        soc,
        battery_temp,
        speed,
        ac_on,
        distance_travelled,
        energy_consumed,
        remaining_range
    ])


df = pd.DataFrame(
    data,
    columns=[
        "soc",
        "battery_temp",
        "speed",
        "ac_on",
        "distance_travelled",
        "energy_consumed",
        "remaining_range"
    ]
)

df.to_csv("data/range_data.csv", index=False)

print("Generated dataset successfully.")
print(f"Rows: {len(df)}")
print("Saved to data/range_data.csv")