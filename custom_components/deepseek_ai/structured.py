"""Strict JSON contracts for generation and experimental, uncalibrated decisions."""

import json
import math
from typing import Any

import probatio
from homeassistant.components import ai_task
from homeassistant.helpers import llm
from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError, ValidationError

from .api import ApiError


def schema_for(structure: Any) -> dict[str, Any]:
    return probatio.to_openapi(structure, custom_serializer=llm.selector_serializer)


def parse_result(text: str, schema: dict[str, Any]) -> Any:
    try:
        value = json.loads(text, parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
        Draft202012Validator(schema).validate(value)
        return value
    except (ValueError, TypeError, ValidationError, SchemaError):
        raise ApiError("invalid_structured_result") from None


def evaluation_schema(task: ai_task.EvaluationTask) -> dict[str, Any]:
    fields = {}
    probability = {"type": "number", "minimum": 0, "maximum": 1}
    for key, question in task.questions.items():
        if question["type"] == "noul":
            props = {"noul": probability}
        elif question["type"] == "choice":
            props = {"choice": {"type": "string", "enum": list(question["criteria"])}, "probabilities": {"type": "object", "properties": dict.fromkeys(question["criteria"], probability), "required": list(question["criteria"]), "additionalProperties": False}}
        elif question["type"] == "score":
            count = len(question["criteria"])
            props = {"score": {"type": "number", "minimum": 0, "maximum": count - 1}, "probabilities": {"type": "array", "items": probability, "minItems": count, "maxItems": count}}
        else:
            raise ApiError("unsupported_evaluation_type")
        fields[key] = {"type": "object", "properties": props, "required": list(props), "additionalProperties": False}
    return {"type": "object", "properties": fields, "required": list(fields), "additionalProperties": False}


def evaluation_result(task: ai_task.EvaluationTask, data: dict[str, Any]) -> ai_task.EvaluationTaskResult:
    answers = {}
    for key, question in task.questions.items():
        value = data[key]
        if question["type"] == "noul":
            answers[key] = ai_task.NoulAnswer(noul=value["noul"])
            continue
        probabilities = value["probabilities"]
        numbers = list(probabilities.values()) if isinstance(probabilities, dict) else probabilities
        if not all(math.isfinite(number) for number in numbers) or not math.isclose(sum(numbers), 1, abs_tol=1e-6):
            raise ApiError("invalid_probability_distribution")
        if question["type"] == "choice":
            if probabilities[value["choice"]] < max(numbers):
                raise ApiError("inconsistent_choice")
            answers[key] = ai_task.ChoiceAnswer(choice=value["choice"], probabilities=probabilities)
        else:
            expected = sum(index * probability for index, probability in enumerate(numbers))
            if not math.isclose(value["score"], expected, abs_tol=1e-6):
                raise ApiError("inconsistent_score")
            answers[key] = ai_task.ScoreAnswer(score=value["score"], probabilities=probabilities)
    return ai_task.EvaluationTaskResult(answers=answers)

