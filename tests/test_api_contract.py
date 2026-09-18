import json

from fastapi.testclient import TestClient

from app.main import app


client = TestClient(app)


def _sample_payload() -> dict:
    return {
        "scenario_id": "UNIT-001",
        "operator_notes": ["The cafeteria menu changes tomorrow."],
        "hours": [
            {
                "hour": hour,
                "demand_kwh": 100,
                "solar_kwh": 20 if 8 <= hour <= 16 else 0,
                "tariff_bdt_per_kwh": 10,
            }
            for hour in range(24)
        ],
        "battery": {
            "capacity_kwh": 200,
            "initial_energy_kwh": 80,
            "minimum_energy_kwh": 30,
            "max_charge_kwh_per_hour": 50,
            "max_discharge_kwh_per_hour": 50,
        },
    }


def test_health_endpoint() -> None:
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_optimize_energy_returns_required_shape() -> None:
    response = client.post("/optimize-energy", json=_sample_payload())

    assert response.status_code == 200
    body = response.json()
    assert body["scenario_id"] == "UNIT-001"
    assert len(body["directive_interpretation"]) == 1
    assert len(body["hourly_plan"]) == 24
    assert body["directive_interpretation"][0]["directive_type"] == "no_op"
    assert body["hourly_plan"][0]["battery_action"] == "idle"
    assert body["total_grid_kwh"] == sum(item["grid_kwh"] for item in body["hourly_plan"])


def test_rejects_incomplete_hour_set() -> None:
    payload = _sample_payload()
    payload["hours"] = payload["hours"][:-1]

    response = client.post("/optimize-energy", json=payload)

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "request_validation_error"


def test_accepts_out_of_order_hours_and_returns_ordered_plan() -> None:
    payload = _sample_payload()
    payload["hours"] = list(reversed(payload["hours"]))

    response = client.post("/optimize-energy", json=payload)

    assert response.status_code == 200
    assert [entry["hour"] for entry in response.json()["hourly_plan"]] == list(range(24))


def test_rejects_duplicate_hour() -> None:
    payload = _sample_payload()
    payload["hours"][23]["hour"] = 22

    response = client.post("/optimize-energy", json=payload)

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "request_validation_error"


def test_rejects_blank_scenario_id() -> None:
    payload = _sample_payload()
    payload["scenario_id"] = "   "

    response = client.post("/optimize-energy", json=payload)

    assert response.status_code == 422


def test_rejects_non_finite_numeric_values() -> None:
    payload = _sample_payload()
    payload["hours"][0]["demand_kwh"] = float("inf")

    response = client.post(
        "/optimize-energy",
        content=json.dumps(payload),
        headers={"content-type": "application/json"},
    )

    assert response.status_code == 422


def test_rejects_malformed_json_with_safe_error() -> None:
    response = client.post(
        "/optimize-energy",
        content=b'{"scenario_id":',
        headers={"content-type": "application/json"},
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "request_validation_error"


def test_unexpected_failure_returns_controlled_error(monkeypatch) -> None:
    def fail(_payload):
        raise RuntimeError("provider secret must not be exposed")

    monkeypatch.setattr("app.main.build_contract_response", fail)
    with TestClient(app, raise_server_exceptions=False) as safe_client:
        response = safe_client.post("/optimize-energy", json=_sample_payload())

    assert response.status_code == 500
    assert response.json() == {
        "error": {
            "code": "internal_error",
            "message": "The request could not be completed due to an internal error.",
        }
    }
    assert "provider secret" not in response.text
