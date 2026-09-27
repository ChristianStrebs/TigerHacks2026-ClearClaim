"""Chat where Gemini calls ClearClaim's own tools: plan search, the bill, and the calculator.

Gemini decides which tools a question needs; the tools do the lookups and the math, so
every dollar figure comes from our code. Returns None whenever the loop can't finish, and
the chat answers the single-shot way instead.
"""

from __future__ import annotations

import logging
import math
import time
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from google.genai import types

from app.schemas import (
    AgentStep,
    AgentTool,
    BenefitsSnapshot,
    ChatTurn,
    CostEstimate,
    EobScanResponse,
    Source,
)
from app.services.benefits import estimate_out_of_pocket
from app.services.bills import describe_rights, describe_scans
from app.services.gemini import CHAT_INSTRUCTION, GeminiService, history_contents
from app.services.indexing import search_plan
from app.services.storage import MemberStore, SavedPlan

logger = logging.getLogger("clearclaim.agent")

MAX_TOOL_ROUNDS = 4
MAX_CALLS_PER_ROUND = 4
_TIME_BUDGET_SECONDS = 60.0
_MAX_AMOUNT = 10_000_000
_MAX_QUERY_CHARS = 200

_TOOL_RULES = """Tools:
- search_plan: look up the member's plan rules, such as copays, what's covered, prior
  authorization, or what counts toward the deductible.
- get_bill: read the member's scanned bills. Use it for any question about their bill.
- estimate_cost: the member's share of a billed amount. Call it whenever they ask what
  something will cost; never do the math yourself.
- check_rights: patient protections, like the No Surprises Act, found on their latest bill.
Call only the tools the question needs; general definitions need none. Take plan details
and dollar figures only from tool results and the benefits snapshot."""

AGENT_INSTRUCTION = f"{CHAT_INSTRUCTION}\n{_TOOL_RULES}"

_TOOLS = types.Tool(
    function_declarations=[
        types.FunctionDeclaration(
            name="search_plan",
            description="Search the member's health plan documents for relevant passages.",
            parameters_json_schema={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "What to look up, like 'MRI prior authorization'.",
                    }
                },
                "required": ["query"],
            },
        ),
        types.FunctionDeclaration(
            name="get_bill",
            description="Read the member's scanned medical bills, newest first.",
        ),
        types.FunctionDeclaration(
            name="estimate_cost",
            description=(
                "Calculate what the member would pay for an in-network billed amount, "
                "using their remaining deductible, coinsurance, and out-of-pocket max."
            ),
            parameters_json_schema={
                "type": "object",
                "properties": {
                    "amount": {"type": "number", "description": "The billed amount in dollars."}
                },
                "required": ["amount"],
            },
        ),
        types.FunctionDeclaration(
            name="check_rights",
            description="List the patient protections that may apply to the latest bill.",
        ),
    ]
)


@dataclass
class AgentAnswer:
    text: str
    steps: list[AgentStep]
    sources: list[Source]
    cost_estimate: CostEstimate | None


def _money(amount: float) -> str:
    return f"${amount:,.0f}" if amount == int(amount) else f"${amount:,.2f}"


def _count(n: int, noun: str) -> str:
    return f"{n} {noun}" if n == 1 else f"{n} {noun}s"


class _Toolbox:
    """Runs the tools for one question and keeps what they found."""

    def __init__(
        self,
        gemini: GeminiService,
        store: MemberStore,
        plan: SavedPlan,
        benefits: BenefitsSnapshot,
        scans: Sequence[EobScanResponse],
    ) -> None:
        self._gemini = gemini
        self._store = store
        self._plan = plan
        self._benefits = benefits
        self._scans = scans
        self.steps: list[AgentStep] = []
        self.sources: list[Source] = []
        self.cost_estimate: CostEstimate | None = None

    def run(self, name: str | None, args: dict[str, Any]) -> dict[str, Any]:
        match name:
            case "search_plan":
                return self._search_plan(args.get("query"))
            case "get_bill":
                return self._get_bill()
            case "estimate_cost":
                return self._estimate_cost(args.get("amount"))
            case "check_rights":
                return self._check_rights()
            case _:
                return {"error": f"There is no tool named {name!r}."}

    def _record(self, tool: AgentTool, label: str, result: str) -> None:
        self.steps.append(AgentStep(tool=tool, label=label, result=result))

    def _search_plan(self, query: object) -> dict[str, Any]:
        if not isinstance(query, str) or not query.strip():
            return {"error": "query must be a non-empty string."}
        query = query.strip()[:_MAX_QUERY_CHARS]
        hits = search_plan(self._gemini, self._store, self._plan, query)
        for hit in hits:
            source = Source(
                document=hit.document, snippet=hit.text[:280], score=round(hit.score, 4)
            )
            if source not in self.sources:
                self.sources.append(source)
        found = f"Found {_count(len(hits), 'passage')}" if hits else "Nothing matched"
        self._record("search_plan", f"Searched your plan for \u201c{query}\u201d", found)
        if not hits:
            return {"result": "Nothing in the plan documents matched."}
        return {"result": "\n\n".join(f"[{hit.document}] {hit.text}" for hit in hits)}

    def _get_bill(self) -> dict[str, Any]:
        if not self._scans:
            self._record("get_bill", "Looked for your scanned bill", "No bill scanned yet")
            return {"result": "No bill has been scanned yet."}
        latest = self._scans[0]
        label = (
            "Read your scanned bill"
            if len(self._scans) == 1
            else f"Read your {len(self._scans)} scanned bills"
        )
        summary = (
            f"{latest.provider or 'Latest bill'}: billed {_money(latest.total_billed)}, "
            f"you should pay {_money(latest.you_owe)}"
        )
        self._record("get_bill", label, summary)
        return {"result": f"Latest scanned bill:\n{describe_scans(self._scans)}"}

    def _estimate_cost(self, amount: object) -> dict[str, Any]:
        if (
            isinstance(amount, bool)
            or not isinstance(amount, int | float)
            or not math.isfinite(amount)
            or not 0 <= amount <= _MAX_AMOUNT
        ):
            return {"error": f"amount must be a dollar amount from 0 to {_MAX_AMOUNT:,}."}
        estimate = estimate_out_of_pocket(float(amount), self._benefits)
        self.cost_estimate = estimate
        self._record(
            "estimate_cost",
            f"Calculated your cost for {_money(estimate.billed_amount)}",
            f"You'd pay about {_money(estimate.estimated_out_of_pocket)}",
        )
        return {
            "result": f"Cost estimate (use these exact figures): {estimate.explanation}",
            "estimated_out_of_pocket": estimate.estimated_out_of_pocket,
        }

    def _check_rights(self) -> dict[str, Any]:
        label = "Checked your patient protections"
        if not self._scans:
            self._record("check_rights", label, "No bill scanned yet")
            return {"result": "No bill has been scanned yet."}
        findings = self._scans[0].rights
        if not findings:
            self._record("check_rights", label, "None apply to your latest bill")
            return {"result": "No patient protections were found on the latest bill."}
        self._record("check_rights", label, ", ".join(finding.title for finding in findings))
        return {"result": "\n".join(describe_rights(findings))}


def _config(*, allow_tools: bool) -> types.GenerateContentConfig:
    mode = (
        types.FunctionCallingConfigMode.AUTO
        if allow_tools
        else types.FunctionCallingConfigMode.NONE
    )
    return types.GenerateContentConfig(
        system_instruction=AGENT_INSTRUCTION,
        temperature=0.2,
        tools=[_TOOLS],
        tool_config=types.ToolConfig(
            function_calling_config=types.FunctionCallingConfig(mode=mode)
        ),
    )


def answer_with_tools(
    gemini: GeminiService,
    store: MemberStore,
    plan: SavedPlan,
    benefits: BenefitsSnapshot,
    benefits_text: str,
    scans: Sequence[EobScanResponse],
    question: str,
    history: Sequence[ChatTurn] = (),
    billed_amount: float | None = None,
) -> AgentAnswer | None:
    """Let Gemini call tools for up to MAX_TOOL_ROUNDS rounds, then answer.

    None when Gemini is off, every model fails, or it still wants tools after the last round.
    """
    if not gemini.enabled:
        return None
    toolbox = _Toolbox(gemini, store, plan, benefits, scans)
    prompt = f"Benefits snapshot:\n{benefits_text}\n\nMember question: {question}"
    if billed_amount is not None:
        prompt += (
            f"\n\nThe member wants an estimate for a billed amount of {_money(billed_amount)}."
        )
    contents = history_contents(history)
    contents.append(types.Content(role="user", parts=[types.Part(text=prompt)]))
    deadline = time.monotonic() + _TIME_BUDGET_SECONDS

    for round_number in range(MAX_TOOL_ROUNDS + 1):
        if time.monotonic() > deadline:
            logger.warning("Tool loop ran out of time after %d rounds", round_number)
            return None
        last_round = round_number == MAX_TOOL_ROUNDS
        response = gemini.generate_turn(contents, _config(allow_tools=not last_round))
        if response is None:
            return None
        calls = response.function_calls or []
        if not calls:
            text = (response.text or "").strip()
            if not text:
                return None
            return AgentAnswer(text, toolbox.steps, toolbox.sources, toolbox.cost_estimate)
        if last_round:
            break
        contents.append(response.candidates[0].content)
        # Every call needs a response, even ones past the per-round limit.
        contents.append(
            types.Content(
                role="user",
                parts=[
                    types.Part(
                        function_response=types.FunctionResponse(
                            id=call.id,
                            name=call.name,
                            response=(
                                toolbox.run(call.name, call.args or {})
                                if i < MAX_CALLS_PER_ROUND
                                else {"error": "Too many tools at once; ask again next turn."}
                            ),
                        )
                    )
                    for i, call in enumerate(calls)
                ],
            )
        )
    logger.warning("Gemini still wanted tools after %d rounds", MAX_TOOL_ROUNDS)
    return None
