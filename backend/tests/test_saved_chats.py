"""Answered questions are saved so the conversation survives a page refresh."""

from __future__ import annotations

from fastapi.testclient import TestClient


def test_answered_questions_are_saved_in_order(client: TestClient) -> None:
    first = client.post("/api/chat", json={"message": "What is my deductible?"}).json()
    client.post("/api/chat", json={"message": "Is my wellness visit covered?"})

    history = client.get("/api/chat/history").json()

    assert [turn["question"] for turn in history] == [
        "What is my deductible?",
        "Is my wellness visit covered?",
    ]
    assert history[0]["response"]["answer"] == first["answer"]


def test_switching_or_clearing_the_plan_starts_a_new_conversation(client: TestClient) -> None:
    client.post("/api/chat", json={"message": "What is my deductible?"})

    client.post("/api/plan/sample")
    assert client.get("/api/chat/history").json() == []

    client.post("/api/chat", json={"message": "What is my deductible?"})
    client.post("/api/plan/clear")
    assert client.get("/api/chat/history").json() == []


def test_new_visitor_has_no_conversation(fresh_client: TestClient) -> None:
    assert fresh_client.get("/api/chat/history").json() == []
