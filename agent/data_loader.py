"""Load water analytics JSON data for the LangChain Agent."""
import json, os

# Data directory - defaults to mock data in portfolio, override with env var
DATA_DIR = os.environ.get(
    "WATER_DATA_DIR",
    os.path.join(os.path.dirname(__file__), "..", "backend", "data", "output")
)


def load_json(filename):
    path = os.path.join(DATA_DIR, filename)
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def get_anomalies(limit=20):
    data = load_json("anomalies.json")
    return data[:limit]


def get_meter_info(meter_id=None):
    data = load_json("meter_info.json")
    if meter_id:
        return data.get(str(meter_id), {})
    return data


def get_daily_dma():
    return load_json("daily_dma.json")


def get_predictions():
    return load_json("predictions.json")


def summarize_data():
    anomalies = load_json("anomalies.json")
    meters = load_json("meter_info.json")
    return {
        "total_meters": len(meters),
        "total_anomalies": len(anomalies),
        "dma_zones": list(set(m.get("dma", "") for m in meters.values())),
        "anomaly_types": list(set(a.get("type", "") for a in anomalies)),
        "date_range": f"{anomalies[0]['date']} ~ {anomalies[-1]['date']}" if anomalies else "no data",
    }
