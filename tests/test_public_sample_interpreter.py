import json
import os
from pathlib import Path

import pytest

from app.config import LLMSettings
from app.llm_interpreter import DirectiveBatch, OpenAIInterpreter
from app.schemas import Battery


RUN_LLM_TESTS = os.getenv("RUN_LLM_INTEGRATION_TESTS") == "1"
SAMPLE_FILE = Path(__file__).parents[1] / "BUP_CSE_FEST_2026_Preli_Public_Sample_Cases.json"

if not SAMPLE_FILE.exists():
    pytest.skip(
        f"Public sample cases file not present ({SAMPLE_FILE.name}).",
        allow_module_level=True,
    )


def test_public_expected_interpretations_match_module_2_schema() -> None:
    cases = json.loads(SAMPLE_FILE.read_text(encoding="utf-8"))["cases"]

    for case in cases:
        batch = DirectiveBatch.model_validate(
            {"interpretations": case["expected_output"]["directive_interpretation"]}
        )
        assert len(batch.interpretations) == len(case["input"]["operator_notes"])


@pytest.mark.skipif(
    not RUN_LLM_TESTS,
    reason="Set RUN_LLM_INTEGRATION_TESTS=1 to call the configured model.",
)
def test_model_matches_public_directive_semantics() -> None:
    cases = json.loads(SAMPLE_FILE.read_text(encoding="utf-8"))["cases"]
    interpreter = OpenAIInterpreter(LLMSettings.from_env())

    for case in cases:
        scenario = case["input"]
        expected = case["expected_output"]["directive_interpretation"]
        actual = interpreter.interpret_notes(
            scenario["operator_notes"], Battery.model_validate(scenario["battery"])
        )

        actual_semantics = [
            {
                "note_index": item.note_index,
                "applies": item.applies,
                "directive_type": item.directive_type,
                "structured_adjustment": item.structured_adjustment,
            }
            for item in actual
        ]
        expected_semantics = [
            {key: item[key] for key in actual_semantics[0]}
            for item in expected
        ]
        assert actual_semantics == expected_semantics, scenario["scenario_id"]
