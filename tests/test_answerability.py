"""Schema-driven answerability / ambiguity screening (agent/answerability.py)."""

import json
from pathlib import Path
from typing import Any

import pytest

from datamind.adapters.duckdb_adapter import DuckDBAdapter
from datamind.agent.answerability import (
    AMBIGUOUS,
    ANSWERABLE,
    UNANSWERABLE,
    assess_question,
    clarification_message,
    refusal_message,
    screen_question,
)
from datamind.agent.orchestrator import AgentOrchestrator
from datamind.config import AgentConfig
from datamind.llm.budget import BudgetExceeded
from datamind.retrieval.sqlite_fts import SQLiteFTSRetriever
from datamind.semantic.loader import load_semantic_model
from datamind.semantic.model import ColumnDef, MetricDef, SemanticModel, TableDef


def _library_model() -> SemanticModel:
    """A schema unrelated to the shipped examples."""
    return SemanticModel(
        name="city_library",
        description="Public library lending records.",
        tables=[
            TableDef(
                name="books",
                description="Catalogue of books held by the library.",
                columns=[
                    ColumnDef(name="book_id", type="INTEGER"),
                    ColumnDef(name="title", type="VARCHAR"),
                    ColumnDef(name="author", type="VARCHAR"),
                    ColumnDef(name="genre", type="VARCHAR", description="Genre such as fiction or history"),
                ],
            ),
            TableDef(
                name="loans",
                description="One row per book borrowed by a member.",
                columns=[
                    ColumnDef(name="loan_id", type="INTEGER"),
                    ColumnDef(name="book_id", type="INTEGER"),
                    ColumnDef(name="member_id", type="INTEGER"),
                    ColumnDef(name="loan_date", type="DATE"),
                    ColumnDef(name="late_fee", type="DECIMAL"),
                ],
            ),
        ],
        metrics=[
            MetricDef(name="loan_count", description="Number of loans", table="loans", expression="COUNT(*)"),
            MetricDef(name="fee_income", description="Total late fees collected", table="loans",
                      expression="SUM(late_fee)"),
        ],
    )


class StubClassifier:
    """Returns one canned classification reply (or raises) and records calls."""

    def __init__(self, reply: dict[str, Any] | str | Exception) -> None:
        self.reply = reply
        self.calls: list[list[dict[str, Any]]] = []

    def chat(self, messages, **kwargs):
        self.calls.append(list(messages))
        if isinstance(self.reply, Exception):
            raise self.reply
        content = self.reply if isinstance(self.reply, str) else json.dumps(self.reply)
        return {"role": "assistant", "content": content, "tool_calls": None}


def test_question_with_no_measurable_terms_is_ambiguous_without_llm():
    llm = StubClassifier(RuntimeError("must not be called"))
    a = assess_question("How is everything going lately?", _library_model(), llm)
    assert a.verdict == AMBIGUOUS
    assert llm.calls == []


def test_fully_grounded_question_is_answerable_without_llm():
    llm = StubClassifier(RuntimeError("must not be called"))
    a = assess_question("Which genre had the most loans per month?", _library_model(), llm)
    assert a.verdict == ANSWERABLE
    assert "genre" in a.grounded_terms and llm.calls == []


def test_capitalised_values_and_participles_are_not_treated_as_missing_attributes():
    a = screen_question("How many loans were recorded for books by Tolkien in the Fantasy genre?", _library_model())
    assert a.verdict == ANSWERABLE, a.ungrounded_terms


def test_unknown_terms_are_inconclusive_without_llm_and_proceed():
    a = assess_question("What is the average salary of librarians?", _library_model(), llm_client=None)
    assert a.verdict == ANSWERABLE
    assert set(a.ungrounded_terms) >= {"salary", "librarians"}


def test_llm_confirms_missing_attribute_refusal():
    llm = StubClassifier({"verdict": "unanswerable", "missing": ["librarian salary"], "reason": "no staff data"})
    model = _library_model()
    a = assess_question("What is the average salary of librarians?", model, llm)
    assert a.verdict == UNANSWERABLE and a.source == "llm"
    assert len(llm.calls) == 1
    # The classifier sees the schema and the unmatched words
    prompt = llm.calls[0][-1]["content"]
    assert "loans" in prompt and "salary" in prompt

    msg = refusal_message(a, model)
    assert "does not contain librarian salary" in msg
    assert "books, loans" in msg
    assert not any(ch.isdigit() for ch in msg)


def test_llm_refusal_must_name_an_unmatched_term():
    # 'Fantasy'-style filter values may make the LLM over-refuse; a refusal naming only
    # attributes the schema has is ignored when the question is otherwise grounded.
    llm = StubClassifier({"verdict": "unanswerable", "missing": ["genre"], "reason": "?"})
    a = assess_question("How many loans were overdue by genre?", _library_model(), llm)
    assert a.verdict == ANSWERABLE


def test_llm_refusal_overridden_when_question_mostly_matches_schema():
    # One unmatched word ('overdue') against several matched ones: likely a derived measure.
    llm = StubClassifier({"verdict": "unanswerable", "missing": ["overdue"], "reason": "no overdue flag"})
    a = assess_question("Which genre had the most overdue loans per author?", _library_model(), llm)
    assert a.verdict == ANSWERABLE
    # Mostly unmatched: the refusal stands.
    llm = StubClassifier({"verdict": "unanswerable", "missing": ["branch opening hours"]})
    a = assess_question("What are the branch opening hours for loans?", _library_model(), llm)
    assert a.verdict == UNANSWERABLE


def test_llm_ambiguity_applies_even_when_an_entity_is_grounded():
    llm = StubClassifier({"verdict": "ambiguous", "missing": [], "reason": "rank by what?"})
    assert assess_question("Which authors are popular?", _library_model(), llm).verdict == AMBIGUOUS
    assert assess_question("Anything noteworthy?", _library_model(), llm).verdict == AMBIGUOUS


def test_classifier_failure_falls_back_to_schema_default():
    model = _library_model()
    for bad in (RuntimeError("offline"), "not json at all", {"verdict": "maybe"}):
        llm = StubClassifier(bad)
        # Nothing in the question matches the schema -> refuse
        a = assess_question("What is the parking capacity downtown?", model, llm)
        assert a.verdict == UNANSWERABLE and a.source == "schema_default"
        # Something matches -> let the agent try
        a = assess_question("Which books trend downtown?", model, llm)
        assert a.verdict == ANSWERABLE


def test_thinking_tags_and_fences_are_stripped():
    raw = '<think>hmm</think>```json\n{"verdict": "unanswerable", "missing": ["parking"]}\n```'
    a = assess_question("What is the parking capacity downtown?", _library_model(), StubClassifier(raw))
    assert a.verdict == UNANSWERABLE and a.source == "llm"


def test_budget_exceeded_propagates():
    with pytest.raises(BudgetExceeded):
        assess_question("What is the parking capacity?", _library_model(), StubClassifier(BudgetExceeded("cap")))


def test_clarification_examples_come_from_model_metrics():
    msg = clarification_message(_library_model())
    assert "?" in msg and "clarify" in msg
    assert "number of loans" in msg and "total late fees collected" in msg


@pytest.fixture
def primary_env():
    demo_db = Path("examples/primary/demo.duckdb")
    model = load_semantic_model("examples/primary/semantic_model.yaml")
    adapter = DuckDBAdapter(demo_db, read_only=True)
    retriever = SQLiteFTSRetriever(":memory:", source_db_path=demo_db)
    retriever.build_index()
    return model, adapter, retriever


def test_orchestrator_refuses_before_any_sql(primary_env):
    model, adapter, retriever = primary_env
    llm = StubClassifier({"verdict": "unanswerable", "missing": ["staff headcount", "office locations"]})
    orch = AgentOrchestrator(llm_client=llm, db_adapter=adapter, retriever=retriever, semantic_model=model)
    res = orch.run("How many staff members do we have in each office?")
    assert res.lane == "schema_limitation_refusal"
    assert "does not contain" in res.answer and "SALES" in res.answer
    assert res.evidence_store.queries == []
    assert len(llm.calls) == 1


def test_orchestrator_clarifies_vague_question_without_llm(primary_env):
    model, adapter, retriever = primary_env
    llm = StubClassifier(RuntimeError("must not be called"))
    orch = AgentOrchestrator(llm_client=llm, db_adapter=adapter, retriever=retriever, semantic_model=model)
    res = orch.run("How are the numbers looking?")
    assert res.lane == "clarification" and "?" in res.answer
    assert llm.calls == []


def test_orchestrator_screen_can_be_disabled(primary_env):
    model, adapter, retriever = primary_env
    llm = StubClassifier("Sure.")
    orch = AgentOrchestrator(
        llm_client=llm, db_adapter=adapter, retriever=retriever, semantic_model=model,
        config=AgentConfig(answerability_check=False),
    )
    res = orch.run("How are the numbers looking?")
    assert res.lane == "freeform_sql" and res.answer == "Sure."
