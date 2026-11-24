"""Output validity and safety defaults, through the integration contracts."""

import pytest
from homeassistant.components import ai_task

from custom_components.deepseek_ai.api import ApiError
from custom_components.deepseek_ai.settings import agent_settings
from custom_components.deepseek_ai.structured import (
    evaluation_result,
    evaluation_schema,
    parse_result,
)


@pytest.mark.parametrize("kind", ["ai_task", "evaluation", "stt", "tts"])
def test_nonconversation_never_accepts_home_tools(kind):
    with pytest.raises(ValueError, match="task_tools_forbidden"):
        agent_settings(kind, {"llm_hass_api": ["homeassistant"]})


def test_web_and_home_tools_incompatible_even_in_persisted_options():
    with pytest.raises(ValueError, match="web_tools_conflict"):
        agent_settings("conversation", {"web": True, "llm_hass_api": ["assist"]})


@pytest.mark.parametrize(
    "value", ['{"flag":"yes"}', "{}", '{"flag":true,"extra":1}', '{"flag":NaN}', "not json"]
)
def test_invalid_json_contract_rejected(value):
    schema = {
        "type": "object",
        "properties": {"flag": {"type": "boolean"}},
        "required": ["flag"],
        "additionalProperties": False,
    }
    with pytest.raises(ApiError):
        parse_result(value, schema)


def test_evaluation_distribution_and_expected_score():
    task = ai_task.EvaluationTask(
        name="test",
        questions={
            "urgent": ai_task.ScoreQuestion(
                type="score", instructions="Urgency", criteria=["none", "soon", "now"]
            )
        },
    )
    schema = evaluation_schema(task)
    valid = parse_result('{"urgent":{"score":0.3,"probabilities":[0.8,0.1,0.1]}}', schema)
    result = evaluation_result(task, valid)
    assert result.answers["urgent"].score == 0.3
    valid["urgent"]["probabilities"] = [0.8, 0.1, 0.3]
    with pytest.raises(ApiError, match="distribution"):
        evaluation_result(task, valid)


@pytest.mark.parametrize(
    "value",
    ['{"number":1e999}', '{"number":1,"number":2}', '{"number":NaN}', '{"number":Infinity}'],
)
def test_json_nonfinite_and_duplicate_values_fail(value):
    with pytest.raises(ApiError):
        parse_result(value, {"type": "object", "properties": {"number": {"type": "number"}}})


@pytest.mark.parametrize(
    "kind,data",
    [
        ("noul", {"noul": -0.1}),
        ("noul", {"noul": 1.1}),
        ("choice", {"choice": "a", "probabilities": {"a": 0.1, "b": 0.9}}),
        ("choice", {"choice": "a", "probabilities": {"a": 0.1, "b": 0.1}}),
        ("choice", {"choice": "a", "probabilities": {"a": 1}}),
        ("score", {"score": 0, "probabilities": [0.5, 0.5]}),
        ("score", {"score": 1, "probabilities": [0.5]}),
    ],
)
def test_evaluation_rejects_invalid_range_distribution_or_consistency(kind, data):
    question = {"type": kind, "instructions": "Fixture"}
    if kind != "noul":
        question["criteria"] = {"a": "A", "b": "B"} if kind == "choice" else ["low", "high"]
    task = ai_task.EvaluationTask(name="fixture", questions={"q": question})
    import json

    with pytest.raises(ApiError):
        evaluation_result(task, parse_result(json.dumps({"q": data}), evaluation_schema(task)))
