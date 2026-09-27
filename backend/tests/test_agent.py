"""Agentic chat: Gemini calls our tools, the steps are shown, and chat never breaks."""

from __future__ import annotations

from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any, get_args

import pytest
from fastapi.testclient import TestClient
from google.genai import types

from app.schemas import AgentTool
from app.services import agent as agent_module
from app.services.agent import _TOOLS, MAX_CALLS_PER_ROUND, MAX_TOOL_ROUNDS
from app.services.storage import SearchHit


@dataclass
class _Request:
    contents: list[types.Content]
    config: types.GenerateContentConfig


class _ScriptedModels:
    """Answers each generate_content call with the next scripted reply."""

    def __init__(self, replies: list[types.GenerateContentResponse]) -> None:
        self.replies = replies
        self.requests: list[_Request] = []

    def generate_content(
        self, *, contents: list, config: types.GenerateContentConfig, **_: object
    ) -> types.GenerateContentResponse:
        self.requests.append(_Request(list(contents), config))
        return self.replies.pop(0)

    def tool_results(self, request: int) -> list[dict[str, Any]]:
        """What the tools sent back to Gemini before the given request."""
        return [
            part.function_response.response for part in self.requests[request].contents[-1].parts
        ]


def _reply(*parts: types.Part) -> types.GenerateContentResponse:
    content = types.Content(role="model", parts=list(parts))
    return types.GenerateContentResponse(candidates=[types.Candidate(content=content)])


def _call(name: str, **args: object) -> types.Part:
    return types.Part(function_call=types.FunctionCall(name=name, args=args))


def _text(text: str) -> types.GenerateContentResponse:
    return _reply(types.Part(text=text))


def _go_live(client: TestClient, *replies: types.GenerateContentResponse) -> _ScriptedModels:
    models = _ScriptedModels(list(replies))
    client.app.state.services.gemini._client = SimpleNamespace(models=models)
    return models


def _scan_sample(client: TestClient, name: str) -> dict:
    pdf = client.get(f"/api/samples/{name}").content
    scan = client.post("/api/eob/scan", files={"file": (name, pdf, "application/pdf")})
    scan.raise_for_status()
    return scan.json()


def test_the_calculator_does_the_math(client: TestClient) -> None:
    models = _go_live(
        client, _reply(_call("estimate_cost", amount=18000)), _text("You'd pay about that.")
    )

    body = client.post("/api/chat", json={"message": "What would an $18,000 surgery cost?"}).json()

    assert body["demo_mode"] is False
    assert body["answer"] == "You'd pay about that."
    estimate = body["cost_estimate"]
    assert estimate["billed_amount"] == 18000
    (result,) = models.tool_results(1)
    assert result["estimated_out_of_pocket"] == estimate["estimated_out_of_pocket"]
    assert body["steps"] == [
        {
            "tool": "estimate_cost",
            "label": "Calculated your cost for $18,000",
            "result": f"You'd pay about ${estimate['estimated_out_of_pocket']:,.0f}",
        }
    ]


def test_steps_are_saved_with_the_answer(client: TestClient) -> None:
    _go_live(client, _reply(_call("estimate_cost", amount=500)), _text("About $500."))

    client.post("/api/chat", json={"message": "What would $500 cost?"}).raise_for_status()

    (saved,) = client.get("/api/chat/history").json()
    assert saved["response"]["steps"][0]["tool"] == "estimate_cost"


def test_plan_search_results_become_sources(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    queries: list[str] = []

    def fake_search(*args: object) -> list[SearchHit]:
        queries.append(str(args[-1]))
        return [SearchHit(document="Silver PPO", text="MRI needs prior authorization.", score=0.9)]

    monkeypatch.setattr(agent_module, "search_plan", fake_search)
    models = _go_live(
        client, _reply(_call("search_plan", query="MRI prior authorization")), _text("Yes.")
    )

    body = client.post("/api/chat", json={"message": "Do I need approval for an MRI?"}).json()

    assert queries == ["MRI prior authorization"]
    assert body["sources"][0]["document"] == "Silver PPO"
    assert body["steps"][0]["label"] == "Searched your plan for \u201cMRI prior authorization\u201d"
    assert body["steps"][0]["result"] == "Found 1 passage"
    assert "prior authorization" in models.tool_results(1)[0]["result"]


def test_bill_and_rights_tools_in_one_round(client: TestClient) -> None:
    scan = _scan_sample(client, "surprise-bill.pdf")
    models = _go_live(
        client, _reply(_call("get_bill"), _call("check_rights")), _text("Here's your bill.")
    )

    body = client.post("/api/chat", json={"message": "Is my ER bill right?"}).json()

    assert [step["tool"] for step in body["steps"]] == ["get_bill", "check_rights"]
    assert body["bill_scan_id"] == scan["scan_id"]
    bill, rights = models.tool_results(1)
    assert "01400" in bill["result"]
    assert scan["rights"][0]["title"] in rights["result"]
    assert body["steps"][1]["result"] == scan["rights"][0]["title"]


def test_bill_tools_without_a_scan_say_so(client: TestClient) -> None:
    _go_live(client, _reply(_call("get_bill")), _text("Scan your bill first."))

    body = client.post("/api/chat", json={"message": "What's on my bill?"}).json()

    assert body["steps"][0]["result"] == "No bill scanned yet"
    assert body["bill_scan_id"] is None


def test_the_loop_stops_at_the_cap_and_answers_the_plain_way(client: TestClient) -> None:
    greedy = [_reply(_call("get_bill")) for _ in range(MAX_TOOL_ROUNDS + 1)]
    models = _go_live(client, *greedy, _text("Plain answer."))

    body = client.post("/api/chat", json={"message": "What's on my bill?"}).json()

    assert body["answer"] == "Plain answer."
    assert body["steps"] == []
    assert len(models.requests) == MAX_TOOL_ROUNDS + 2
    last_agent_turn = models.requests[MAX_TOOL_ROUNDS].config
    assert last_agent_turn.tool_config.function_calling_config.mode == "NONE"


def test_too_many_calls_in_one_round_are_refused(client: TestClient) -> None:
    calls = [_call("estimate_cost", amount=100 * n) for n in range(1, MAX_CALLS_PER_ROUND + 2)]
    models = _go_live(client, _reply(*calls), _text("Done."))

    body = client.post("/api/chat", json={"message": "Compare costs."}).json()

    assert len(body["steps"]) == MAX_CALLS_PER_ROUND
    results = models.tool_results(1)
    assert len(results) == len(calls)
    assert "error" in results[-1]


def test_bad_tool_calls_get_an_error_and_no_step(client: TestClient) -> None:
    models = _go_live(
        client,
        _reply(_call("estimate_cost", amount=-5), _call("send_email")),
        _text("Sorry."),
    )

    body = client.post("/api/chat", json={"message": "Cost?"}).json()

    assert body["steps"] == []
    assert body["cost_estimate"] is None
    assert all("error" in result for result in models.tool_results(1))


def test_gemini_failing_falls_back_to_the_offline_answer(client: TestClient) -> None:
    def fail(**_: object) -> None:
        raise ConnectionError("network down")

    client.app.state.services.gemini._client = SimpleNamespace(
        models=SimpleNamespace(generate_content=fail)
    )

    body = client.post("/api/chat", json={"message": "What is a deductible?"}).json()

    assert body["demo_mode"] is True
    assert body["steps"] == []
    assert "deductible" in body["answer"].lower()


def test_offline_chat_has_no_steps(client: TestClient) -> None:
    body = client.post("/api/chat", json={"message": "What is a deductible?"}).json()

    assert body["steps"] == []


def test_every_declared_tool_can_be_a_step() -> None:
    declared = {declaration.name for declaration in _TOOLS.function_declarations}

    assert declared == set(get_args(AgentTool))
