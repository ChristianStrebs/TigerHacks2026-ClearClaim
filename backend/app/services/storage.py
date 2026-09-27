"""Each member's plan, plan search index, bill scans, and chat history.

Two backends implement :class:`Storage`:

* :class:`InMemoryStorage` keeps everything in this process. It's used by the
  tests and whenever Supabase isn't configured (a single local member).
* :class:`SupabaseStorage` saves to Postgres through the Supabase Data API,
  sending the member's own access token so row level security keeps members'
  data apart. Schema: ``supabase/migrations/*_per_user_data.sql``.
"""

from __future__ import annotations

import logging
import time
import uuid
from collections import deque
from dataclasses import dataclass, field
from threading import RLock
from typing import Any, Protocol

import httpx
import numpy as np

from app.auth import Member
from app.config import Settings
from app.schemas import ChatResponse, EobScanResponse
from app.services.benefits import PlanProfile

logger = logging.getLogger("clearclaim.storage")

MAX_SAVED_SCANS = 5
MAX_CHAT_HISTORY = 50


class StorageError(RuntimeError):
    """The database couldn't complete the request."""


class PlanReplacedError(StorageError):
    """The member switched plans mid-request, so a result for the old plan wasn't saved."""


@dataclass
class Chunk:
    document: str
    text: str
    embedding: list[float]


@dataclass
class SearchHit:
    document: str
    text: str
    score: float


@dataclass(frozen=True)
class SavedPlan:
    id: str
    profile: PlanProfile
    embed_model: str


@dataclass(frozen=True)
class SavedTurn:
    question: str
    response: ChatResponse


@dataclass(frozen=True)
class BillEntry:
    """What one saved bill adds to the member's running totals."""

    scan_id: str
    file_sha256: str | None
    applied_to_deductible: float


class MemberStore(Protocol):
    """One member's data. Replacing or clearing the plan also drops its chunks, scans, and chats."""

    def get_plan(self) -> SavedPlan | None: ...

    def replace_plan(
        self, plan: PlanProfile, chunks: list[Chunk], embed_model: str
    ) -> SavedPlan: ...

    def clear_plan(self) -> None: ...

    def search(self, embedding: list[float], k: int = 4) -> list[SearchHit]: ...

    def chunk_count(self) -> int: ...

    def add_scan(self, plan_id: str, scan: EobScanResponse) -> None: ...

    def list_scans(self, limit: int = MAX_SAVED_SCANS) -> list[EobScanResponse]: ...

    def get_scan(self, scan_id: str) -> EobScanResponse | None: ...

    def bill_ledger(self) -> list[BillEntry]:
        """Every saved bill for the current plan, not just the most recent few."""
        ...

    def delete_scan(self, scan_id: str) -> None: ...

    def clear_scans(self) -> None: ...

    def add_chat(self, plan_id: str, question: str, response: ChatResponse) -> None: ...

    def list_chat(self, limit: int = MAX_CHAT_HISTORY) -> list[SavedTurn]: ...


class Storage(Protocol):
    backend_name: str

    def for_member(self, member: Member) -> MemberStore: ...

    def close(self) -> None: ...


def _cosine(matrix: np.ndarray, query: np.ndarray) -> np.ndarray:
    denom = np.linalg.norm(matrix, axis=1) * np.linalg.norm(query)
    denom[denom == 0] = 1e-12
    return (matrix @ query) / denom


def _is_uuid(value: str) -> bool:
    try:
        uuid.UUID(value)
    except ValueError:
        return False
    return True


# --------------------------------------------------------------------------- #
# In memory
# --------------------------------------------------------------------------- #
@dataclass
class _MemberData:
    plan: SavedPlan | None = None
    chunks: list[Chunk] = field(default_factory=list)
    matrix: np.ndarray | None = None
    # Every bill counts toward the deductible, so only the listing is capped.
    scans: list[EobScanResponse] = field(default_factory=list)
    chats: deque[SavedTurn] = field(default_factory=lambda: deque(maxlen=MAX_CHAT_HISTORY))


class InMemoryStorage:
    backend_name = "in-memory"

    def __init__(self) -> None:
        self._lock = RLock()
        self._members: dict[str, _MemberData] = {}

    def for_member(self, member: Member) -> InMemoryMemberStore:
        with self._lock:
            data = self._members.setdefault(member.id, _MemberData())
        return InMemoryMemberStore(data, self._lock)

    def close(self) -> None:
        pass


class InMemoryMemberStore:
    def __init__(self, data: _MemberData, lock: RLock) -> None:
        self._data = data
        self._lock = lock

    def get_plan(self) -> SavedPlan | None:
        return self._data.plan

    def replace_plan(self, plan: PlanProfile, chunks: list[Chunk], embed_model: str) -> SavedPlan:
        if not chunks:
            raise StorageError("A plan needs at least one indexed chunk.")
        matrix = np.array([c.embedding for c in chunks], dtype=np.float32)
        saved = SavedPlan(id=str(uuid.uuid4()), profile=plan, embed_model=embed_model)
        with self._lock:
            self._data.plan, self._data.chunks, self._data.matrix = saved, list(chunks), matrix
            self._data.scans.clear()
            self._data.chats.clear()
        return saved

    def clear_plan(self) -> None:
        with self._lock:
            self._data.plan, self._data.chunks, self._data.matrix = None, [], None
            self._data.scans.clear()
            self._data.chats.clear()

    def search(self, embedding: list[float], k: int = 4) -> list[SearchHit]:
        with self._lock:
            chunks, matrix = self._data.chunks, self._data.matrix
        if matrix is None:
            return []
        scores = _cosine(matrix, np.array(embedding, dtype=np.float32))
        return [
            SearchHit(document=chunks[i].document, text=chunks[i].text, score=float(scores[i]))
            for i in np.argsort(scores)[::-1][:k]
        ]

    def chunk_count(self) -> int:
        return len(self._data.chunks)

    def _require_plan(self, plan_id: str) -> None:
        if self._data.plan is None or self._data.plan.id != plan_id:
            raise PlanReplacedError("The plan changed before this result was saved.")

    def add_scan(self, plan_id: str, scan: EobScanResponse) -> None:
        with self._lock:
            self._require_plan(plan_id)
            self._data.scans.append(scan)

    def list_scans(self, limit: int = MAX_SAVED_SCANS) -> list[EobScanResponse]:
        with self._lock:
            return list(reversed(self._data.scans))[:limit]

    def get_scan(self, scan_id: str) -> EobScanResponse | None:
        with self._lock:
            return next((s for s in self._data.scans if s.scan_id == scan_id), None)

    def bill_ledger(self) -> list[BillEntry]:
        with self._lock:
            return [
                BillEntry(s.scan_id, s.file_sha256, s.applied_to_deductible)
                for s in self._data.scans
            ]

    def delete_scan(self, scan_id: str) -> None:
        with self._lock:
            self._data.scans = [s for s in self._data.scans if s.scan_id != scan_id]

    def clear_scans(self) -> None:
        with self._lock:
            self._data.scans.clear()

    def add_chat(self, plan_id: str, question: str, response: ChatResponse) -> None:
        with self._lock:
            self._require_plan(plan_id)
            self._data.chats.append(SavedTurn(question=question, response=response))

    def list_chat(self, limit: int = MAX_CHAT_HISTORY) -> list[SavedTurn]:
        with self._lock:
            return list(self._data.chats)[-limit:]


# --------------------------------------------------------------------------- #
# Supabase
# --------------------------------------------------------------------------- #
_FOREIGN_KEY_VIOLATION = "23503"
# A token signed a moment ago can look "issued in the future" when the auth
# server's clock runs slightly ahead of the database's; it's valid once the
# clocks catch up.
_JWT_ISSUED_IN_FUTURE = "PGRST303"
_CLOCK_SKEW_RETRIES = 2
_CLOCK_SKEW_WAIT_SECONDS = 1.0


class SupabaseStorage:
    backend_name = "supabase"

    def __init__(self, settings: Settings, transport: httpx.BaseTransport | None = None) -> None:
        # One pooled client for every request; each call adds that member's token.
        self._http = httpx.Client(
            base_url=f"{settings.supabase_url.rstrip('/')}/rest/v1",
            headers={"apikey": settings.supabase_publishable_key},
            timeout=settings.supabase_timeout_seconds,
            transport=transport,
        )

    def for_member(self, member: Member) -> SupabaseMemberStore:
        if not member.access_token:
            raise StorageError("Supabase storage needs the member's access token.")
        return SupabaseMemberStore(self._http, member)

    def close(self) -> None:
        self._http.close()


def _plan_row(plan: PlanProfile, embed_model: str) -> dict[str, Any]:
    return {
        "name": plan.name,
        "source": plan.source,
        "deductible_total": plan.deductible_total,
        "deductible_met": plan.deductible_met,
        "coinsurance_rate": plan.coinsurance_rate,
        "oop_max": plan.oop_max,
        "demo_fields": list(plan.demo_fields),
        "summary": plan.summary,
        "summary_live": plan.summary_live,
        "embed_model": embed_model,
    }


def _saved_plan(row: dict[str, Any]) -> SavedPlan:
    profile = PlanProfile(
        name=row["name"],
        source=row["source"],
        deductible_total=float(row["deductible_total"]),
        deductible_met=float(row["deductible_met"]),
        coinsurance_rate=float(row["coinsurance_rate"]),
        oop_max=float(row["oop_max"]),
        summary=row["summary"],
        summary_live=row["summary_live"],
        demo_fields=list(row["demo_fields"]),
    )
    return SavedPlan(id=row["id"], profile=profile, embed_model=row["embed_model"])


def _error_body(response: httpx.Response) -> dict[str, Any]:
    if not response.is_error or "json" not in response.headers.get("content-type", ""):
        return {}
    body = response.json()
    return body if isinstance(body, dict) else {}


class SupabaseMemberStore:
    def __init__(self, http: httpx.Client, member: Member) -> None:
        self._http = http
        self._member = member

    def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, str] | None = None,
        body: Any = None,
        prefer: str | None = None,
    ) -> Any:
        headers = {"Authorization": f"Bearer {self._member.access_token}"}
        if prefer:
            headers["Prefer"] = prefer
        for attempt in range(_CLOCK_SKEW_RETRIES + 1):
            try:
                response = self._http.request(
                    method, path, params=params, json=body, headers=headers
                )
            except httpx.HTTPError as exc:
                logger.warning("Supabase %s %s failed: %s", method, path, exc)
                raise StorageError("Couldn't reach the database.") from exc
            error = _error_body(response)
            if error.get("code") != _JWT_ISSUED_IN_FUTURE or attempt == _CLOCK_SKEW_RETRIES:
                break
            time.sleep(_CLOCK_SKEW_WAIT_SECONDS)
        if response.is_error:
            logger.warning(
                "Supabase %s %s returned %s: %s", method, path, response.status_code, error
            )
            if error.get("code") == _FOREIGN_KEY_VIOLATION:
                raise PlanReplacedError("The plan changed before this result was saved.")
            raise StorageError(f"The database rejected the request ({response.status_code}).")
        return response.json() if response.content else None

    def get_plan(self) -> SavedPlan | None:
        rows = self._request("GET", "/plans", params={"select": "*", "limit": "1"})
        return _saved_plan(rows[0]) if rows else None

    def replace_plan(self, plan: PlanProfile, chunks: list[Chunk], embed_model: str) -> SavedPlan:
        plan_id = self._request(
            "POST",
            "/rpc/replace_plan",
            body={
                "new_plan": _plan_row(plan, embed_model),
                "new_chunks": [
                    {"document": c.document, "content": c.text, "embedding": c.embedding}
                    for c in chunks
                ],
            },
        )
        return SavedPlan(id=str(plan_id), profile=plan, embed_model=embed_model)

    def clear_plan(self) -> None:
        self._request("DELETE", "/plans", params={"user_id": f"eq.{self._member.id}"})

    def search(self, embedding: list[float], k: int = 4) -> list[SearchHit]:
        rows = self._request(
            "POST",
            "/rpc/match_plan_chunks",
            body={"query_embedding": embedding, "match_count": k},
        )
        return [
            SearchHit(document=r["document"], text=r["content"], score=float(r["similarity"]))
            for r in rows or []
        ]

    def chunk_count(self) -> int:
        rows = self._request("GET", "/plan_chunks", params={"select": "id"})
        return len(rows or [])

    def add_scan(self, plan_id: str, scan: EobScanResponse) -> None:
        self._request(
            "POST",
            "/bill_scans",
            body={
                "id": scan.scan_id,
                "plan_id": plan_id,
                "file_name": scan.file_name[:300],
                "result": scan.model_dump(mode="json"),
            },
            prefer="return=minimal",
        )

    def list_scans(self, limit: int = MAX_SAVED_SCANS) -> list[EobScanResponse]:
        rows = self._request(
            "GET",
            "/bill_scans",
            params={"select": "result", "order": "created_at.desc", "limit": str(limit)},
        )
        return [EobScanResponse.model_validate(r["result"]) for r in rows or []]

    def get_scan(self, scan_id: str) -> EobScanResponse | None:
        if not _is_uuid(scan_id):
            return None
        rows = self._request(
            "GET", "/bill_scans", params={"select": "result", "id": f"eq.{scan_id}", "limit": "1"}
        )
        return EobScanResponse.model_validate(rows[0]["result"]) if rows else None

    def bill_ledger(self) -> list[BillEntry]:
        rows = self._request(
            "GET",
            "/bill_scans",
            params={
                "select": "id,applied:result->applied_to_deductible,"
                "file_sha256:result->>file_sha256"
            },
        )
        return [
            BillEntry(
                scan_id=str(r["id"]),
                file_sha256=r.get("file_sha256"),
                applied_to_deductible=float(r.get("applied") or 0),
            )
            for r in rows or []
        ]

    def delete_scan(self, scan_id: str) -> None:
        if _is_uuid(scan_id):
            self._request("DELETE", "/bill_scans", params={"id": f"eq.{scan_id}"})

    def clear_scans(self) -> None:
        self._request("DELETE", "/bill_scans", params={"user_id": f"eq.{self._member.id}"})

    def add_chat(self, plan_id: str, question: str, response: ChatResponse) -> None:
        self._request(
            "POST",
            "/chat_messages",
            body={
                "plan_id": plan_id,
                "question": question[:4000],
                "response": response.model_dump(mode="json"),
            },
            prefer="return=minimal",
        )

    def list_chat(self, limit: int = MAX_CHAT_HISTORY) -> list[SavedTurn]:
        rows = self._request(
            "GET",
            "/chat_messages",
            params={"select": "question,response", "order": "id.desc", "limit": str(limit)},
        )
        return [
            SavedTurn(question=r["question"], response=ChatResponse.model_validate(r["response"]))
            for r in reversed(rows or [])
        ]


def create_storage(settings: Settings) -> Storage:
    if settings.supabase_enabled:
        return SupabaseStorage(settings)
    return InMemoryStorage()
