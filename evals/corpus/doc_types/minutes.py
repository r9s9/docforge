"""Meeting minutes with an action-item table, in English.

The meeting, date, people, agenda, decisions and action items change per document; only the
title, headings and the distribution note are boilerplate. The distribution note is procedural,
so removing it is labelled benign.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from evals.corpus.model import Clause, DocTypeSpec, Field, FreeText, Heading, TableBlock, Title
from evals.corpus.values import PEOPLE, fmt_date, pick, seeded, spaced_date

MEETINGS = (
    "Project steering committee – warehouse platform",
    "Monthly service review – field service app",
    "Kick-off – document archive migration",
    "Release planning – online shop integration",
    "Data quality working group",
    "Security patch review",
    "Quarterly business review – sensor analytics",
    "Retrospective – identity management rollout",
)
AGENDA = (
    "Status of the migration plan, open risks, and the budget forecast for the next quarter.",
    "Review of last month's incidents, the support backlog, and the planned app release.",
    "Scope of the archive migration, the test strategy, and how the cut-over weekend will run.",
    "Changes in the payment provider's interface, the release calendar, and test coverage.",
    "Findings of the latest data quality report and who owns which correction.",
    "Patch status per server group, exceptions requested by the business, and the next window.",
    "Usage figures for the quarter, the renewal of the service contract, and new requirements.",
    "What went well in the rollout, what did not, and which follow-ups are still open.",
)
DECISIONS = (
    "The go-live moves to the second week of the month; the budget stays unchanged.",
    "Hotfix releases will ship every two weeks until the backlog is below twenty items.",
    "The migration will run over one weekend with a rollback plan approved in advance.",
    "The integration release is postponed until the new interface has passed acceptance tests.",
    "Each product category gets a named data owner, and corrections are reviewed weekly.",
    "Two servers keep their exception for one more cycle; all others are patched on schedule.",
    "The contract is renewed for one year, and a feature request list is drafted for Q3.",
    "Onboarding of user accounts is automated first; the remaining follow-ups go to the backlog.",
)
ACTIONS = (
    "Send the updated project plan to all attendees",
    "Book the test environment for the load test",
    "Confirm the budget with finance",
    "Draft the data processing agreement",
    "Prepare the user training material",
    "Review open incidents with the vendor",
    "Update the risk register",
    "Schedule the go-live rehearsal",
    "Collect feedback from the pilot users",
    "Clarify the licence count with procurement",
)


def _values(pair: str):
    def values(index: int) -> dict[str, Any]:
        held = spaced_date(pair, "date", index, date(2026, 3, 2))
        chair = pick(PEOPLE, pair, "chair", index)
        taker = pick(PEOPLE, pair, "taker", index)
        if taker == chair:  # pick() is a permutation, so the shifted index gives someone else
            taker = pick(PEOPLE, pair, "taker", index + len(PEOPLE) // 2)
        shuffled = sorted(PEOPLE, key=lambda name: seeded(pair, f"people:{name}", index).random())
        others = [p for p in shuffled if p not in (chair, taker)]
        rng = seeded(pair, "actions", index)
        actions = [
            [action, rng.choice(others[:4]), fmt_date(held + timedelta(days=7 * (i + 1)), "en")]
            for i, action in enumerate(rng.sample(ACTIONS, 2 + index % 4))
        ]
        return {
            "meeting": pick(MEETINGS, pair, "meeting", index),
            "date": fmt_date(held, "en"),
            "chair": chair,
            "minute_taker": taker,
            "attendees": ", ".join(others[: 3 + index % 3]),
            "agenda": pick(AGENDA, pair, "agenda", index),
            "decisions": pick(DECISIONS, pair, "decisions", index),
            "actions": actions,
        }

    return values


def _spec_en() -> DocTypeSpec:
    pair = "minutes_en"
    return DocTypeSpec(
        pair=pair,
        doc_type="minutes",
        lang="en",
        blocks=(
            Title("title", "MEETING MINUTES"),
            Field("field.meeting", "Meeting", "meeting", "text"),
            Field("field.date", "Date", "date", "date"),
            Field("field.chair", "Chair", "chair", "person"),
            Field("field.minute_taker", "Minute Taker", "minute_taker", "person"),
            Field("field.attendees", "Attendees", "attendees", "text"),
            Heading("heading.agenda", "1. Agenda"),
            FreeText("text.agenda", "agenda"),
            Heading("heading.decisions", "2. Decisions"),
            FreeText("text.decisions", "decisions"),
            Heading("heading.actions", "3. Action Items"),
            TableBlock("table.actions", ("Action", "Owner", "Due Date"), "actions"),
            Heading("heading.distribution", "4. Distribution"),
            Clause(
                "clause.distribution",
                "These minutes are sent to all attendees and to the steering commitee. "
                "Corrections must be sent to the minute taker within five working days; "
                "otherwise the minutes are deemed approved.",
                material=False,
            ),
        ),
        footer="Internal — Page ",
        values=_values(pair),
        mutations={
            "delete_clause": {"targets": ["heading.distribution", "clause.distribution"]},
            "fix_typo": {"target": "clause.distribution", "replace": [["commitee", "committee"]]},
            "whitespace_quotes": {
                "target": "clause.distribution",
                "replace": [
                    ["days; otherwise", "days;  otherwise"],
                    ["sent to all", "sent to  all"],
                ],
            },
            "heading_caps": {"target": "heading.decisions"},
            "empty_field": {"target": "field.chair"},
            "date_format": {"target": "field.date"},
            "invalid_value": {"target": "field.date", "value": "TBD"},
            "remove_row": {"target": "table.actions"},
            "remove_column": {"target": "table.actions", "column": 1},
            "delete_table": {"target": "table.actions"},
            "insert_benign": {
                "after": "clause.distribution",
                "text": "Note: The chair will schedule the next meeting.",
            },
        },
    )


SPECS = (_spec_en(),)
