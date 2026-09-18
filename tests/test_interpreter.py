from types import SimpleNamespace

import httpx
import pytest
from openai import APITimeoutError

from app.config import LLMSettings
from app.errors import LLMConfigurationError, LLMInvalidOutputError, LLMTimeoutError
from app.llm_interpreter import DirectiveBatch, OpenAIInterpreter
from app.schemas import Battery


def _battery() -> Battery:
    return Battery(
        capacity_kwh=200,
        initial_energy_kwh=80,
        minimum_energy_kwh=30,
        max_charge_kwh_per_hour=50,
        max_discharge_kwh_per_hour=50,
    )


def _settings() -> LLMSettings:
    return LLMSettings(
        provider="openai",
        model="test-model",
        api_key="test-key",
        base_url=None,
        timeout_seconds=5,
        max_retries=0,
    )


class FakeResponses:
    def __init__(self, parsed=None, error=None) -> None:
        self.parsed = parsed
        self.error = error
        self.kwargs = None

    def parse(self, **kwargs):
        self.kwargs = kwargs
        if self.error:
            raise self.error
        return SimpleNamespace(output_parsed=self.parsed)


class FakeClient:
    def __init__(self, parsed=None, error=None) -> None:
        self.responses = FakeResponses(parsed=parsed, error=error)


@pytest.mark.parametrize(
    ("note", "candidate", "directive_type"),
    [
        (
            "Solar drops to 25% from noon to 2 PM.",
            {
                "note_index": 0,
                "applies": True,
                "directive_type": "solar_reduction",
                "structured_adjustment": {"hours": [12, 13], "factor": 0.25},
                "explanation": "Only 25% of forecast solar remains.",
            },
            "solar_reduction",
        ),
        (
            "Keep half of capacity from 6 PM to 9 PM.",
            {
                "note_index": 0,
                "applies": True,
                "directive_type": "minimum_battery_reserve",
                "structured_adjustment": {
                    "hours": [18, 19, 20],
                    "minimum_energy_kwh": 100,
                },
                "explanation": "A 100 kWh reserve is required.",
            },
            "minimum_battery_reserve",
        ),
        (
            "Do not charge from 2 AM to 5 AM.",
            {
                "note_index": 0,
                "applies": True,
                "directive_type": "no_charge_window",
                "structured_adjustment": {"hours": [2, 3, 4]},
                "explanation": "Charging is unavailable.",
            },
            "no_charge_window",
        ),
        (
            "Do not discharge from 6 PM to 8 PM.",
            {
                "note_index": 0,
                "applies": True,
                "directive_type": "no_discharge_window",
                "structured_adjustment": {"hours": [18, 19]},
                "explanation": "Discharging is unavailable.",
            },
            "no_discharge_window",
        ),
        (
            "Grid import cannot exceed 155 kWh from 6 PM to 9 PM.",
            {
                "note_index": 0,
                "applies": True,
                "directive_type": "max_grid_window",
                "structured_adjustment": {
                    "hours": [18, 19, 20],
                    "max_grid_kwh": 155,
                },
                "explanation": "Grid import is capped.",
            },
            "max_grid_window",
        ),
        (
            "The sports registration deadline moved.",
            {
                "note_index": 0,
                "applies": False,
                "directive_type": "no_op",
                "structured_adjustment": None,
                "explanation": "The note is unrelated to energy scheduling.",
            },
            "no_op",
        ),
    ],
)
def test_interprets_every_supported_directive(note, candidate, directive_type) -> None:
    batch = DirectiveBatch.model_validate({"interpretations": [candidate]})
    client = FakeClient(parsed=batch)
    interpreter = OpenAIInterpreter(_settings(), client=client)

    result = interpreter.interpret_notes([note], _battery())

    assert result[0].directive_type == directive_type
    assert result[0].note_index == 0


def test_sends_schema_constrained_prompt_with_battery_context() -> None:
    batch = DirectiveBatch.model_validate(
        {
            "interpretations": [
                {
                    "note_index": 0,
                    "applies": False,
                    "directive_type": "no_op",
                    "structured_adjustment": None,
                    "explanation": "Unrelated note.",
                }
            ]
        }
    )
    client = FakeClient(parsed=batch)
    interpreter = OpenAIInterpreter(_settings(), client=client)

    interpreter.interpret_notes(["A non-energy note."], _battery())

    request = client.responses.kwargs
    assert request["model"] == "test-model"
    assert request["text_format"] is DirectiveBatch
    assert request["temperature"] == 0
    assert request["store"] is False
    assert '"capacity_kwh":200.0' in request["input"][1]["content"]
    # Window convention must be documented (end-inclusive on the last hour).
    assert "start-inclusive and end-INCLUSIVE" in request["input"][0]["content"]
    # Percentage-to-factor mapping must be explicit so paraphrases map correctly.
    assert "'80% reduction' -> 0.20" in request["input"][0]["content"]
    # Paraphrase robustness markers should be present.
    assert "Recognize paraphrases by meaning" in request["input"][0]["content"]
    assert "usable solar falls to 1/4" in request["input"][0]["content"]


def test_rejects_missing_or_malformed_parsed_output() -> None:
    interpreter = OpenAIInterpreter(_settings(), client=FakeClient(parsed=None))

    with pytest.raises(LLMInvalidOutputError):
        interpreter.interpret_notes(["Do not charge from 2 to 3 PM."], _battery())


def test_rejects_wrong_note_mapping() -> None:
    batch = DirectiveBatch.model_validate(
        {
            "interpretations": [
                {
                    "note_index": 1,
                    "applies": False,
                    "directive_type": "no_op",
                    "structured_adjustment": None,
                    "explanation": "Unrelated note.",
                }
            ]
        }
    )
    interpreter = OpenAIInterpreter(_settings(), client=FakeClient(parsed=batch))

    with pytest.raises(LLMInvalidOutputError):
        interpreter.interpret_notes(["A non-energy note."], _battery())


def test_converts_provider_timeout_to_controlled_error() -> None:
    timeout = APITimeoutError(request=httpx.Request("POST", "https://api.openai.com/v1/responses"))
    interpreter = OpenAIInterpreter(_settings(), client=FakeClient(error=timeout))

    with pytest.raises(LLMTimeoutError):
        interpreter.interpret_notes(["A non-energy note."], _battery())


def test_configuration_requires_api_key(monkeypatch) -> None:
    monkeypatch.setattr("app.config.load_dotenv", lambda: False)
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    with pytest.raises(LLMConfigurationError):
        LLMSettings.from_env()
