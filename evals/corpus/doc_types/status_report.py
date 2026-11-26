"""Project status report with a task table, in English. Analyze only.

A project block opens it: the report date, the project, the project manager and the overall
status, all of which change per document. Its first value is a date, which is what DocForge's
rule for "label | value" tables looks for in a single example (the DPIA's block starts with a
short word instead). The summary, the tasks, the risks and who prepared the report change per
document; the confidentiality notice is boilerplate.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from evals.corpus.model import (
    Clause,
    DocTypeSpec,
    Field,
    FreeText,
    Heading,
    InfoRow,
    InfoTable,
    TableBlock,
    Title,
)
from evals.corpus.values import PEOPLE, fmt_date, pick, seeded, spaced_date

# Plain descriptions of internal projects, not names of anything.
PROJECTS = (
    "Harbour data migration",
    "Field service app relaunch",
    "Warehouse scanner rollout",
    "Customer portal redesign",
    "Finance system upgrade",
    "Identity management rollout",
    "Archive digitisation",
    "Sensor analytics pilot",
)
STATUSES = (
    "On track",
    "On track, minor delays",
    "At risk: budget",
    "At risk: schedule",
    "Delayed by one week",
    "Delayed by two weeks",
    "Ahead of plan",
    "On hold, waiting for approval",
)
SUMMARIES = (
    "The test phase started as planned. Two of the five interfaces passed their acceptance "
    "tests, and the remaining three are scheduled for next week.",
    "Most of the work this period went into data cleansing. The cut-over plan was approved by "
    "the project board, and the rehearsal is booked.",
    "The vendor delivered the second release late, which used up the buffer in the plan. The "
    "team is re-planning the training sessions around the new date.",
    "User feedback from the pilot was positive. The rollout to the remaining sites will start "
    "once the last open defect is fixed.",
    "The design phase closed with the sign-off of the target architecture. The budget forecast "
    "is unchanged, and hiring for the build phase has started.",
    "Licence costs came in higher than budgeted. The steering committee will decide next week "
    "whether to reduce the scope or to release the reserve.",
    "All workstreams are on schedule. The data protection review is complete, and the first "
    "users will be migrated at the start of the next period.",
    "Progress was slower than planned because two team members were absent. The critical path "
    "is not affected yet, but the buffer is down to three days.",
)
RISK_TEXTS = (
    "The interface partner has not confirmed the test window; if it slips, go-live moves by a "
    "week.",
    "Key users are needed for testing during the year-end close, when they have little time.",
    "The legacy system's support contract ends in June, which leaves no room for delays.",
    "Two open defects block the sign-off; the vendor has promised fixes for the next release.",
    "The budget reserve is almost used up, so any new change request needs funding first.",
    "Network capacity at two sites may not be enough for the new scanners; a survey is booked.",
    "The training material is not translated yet, which could delay the rollout abroad.",
    "One supplier may be acquired, which could change the terms of the support contract.",
)
TASKS = (
    "Finish the interface tests",
    "Migrate the master data",
    "Train the key users",
    "Sign off the test report",
    "Order the remaining hardware",
    "Update the operations manual",
    "Run the cut-over rehearsal",
    "Review the access rights",
    "Close the open defects",
    "Prepare the go-live communication",
)
TASK_STATUSES = ("Done", "In progress", "Not started", "Blocked")


def _values(pair: str):
    def values(index: int) -> dict[str, Any]:
        start = spaced_date(pair, "period", index, date(2026, 3, 2), stride=14)
        end = start + timedelta(days=11)
        manager = pick(PEOPLE, pair, "manager", index)
        author = pick(PEOPLE, pair, "prepared_by", index)
        if author == manager:  # pick() is a permutation, so the shifted index gives someone else
            author = pick(PEOPLE, pair, "prepared_by", index + len(PEOPLE) // 2)
        rng = seeded(pair, "tasks", index)
        owners = [p for p in PEOPLE if p not in (manager, author)]
        tasks = [
            [task, rng.choice(owners), fmt_date(end + timedelta(days=7 * (i + 1)), "en"),
             rng.choice(TASK_STATUSES)]
            for i, task in enumerate(rng.sample(TASKS, 2 + index % 4))
        ]
        return {
            "report_date": fmt_date(end + timedelta(days=1), "en"),
            "project": pick(PROJECTS, pair, "project", index),
            "manager": manager,
            "status": pick(STATUSES, pair, "status", index),
            "prepared_by": author,
            "summary": pick(SUMMARIES, pair, "summary", index),
            "tasks": tasks,
            "risks": pick(RISK_TEXTS, pair, "risks", index),
        }

    return values


def _spec_en() -> DocTypeSpec:
    pair = "status_report_en"
    return DocTypeSpec(
        pair=pair,
        doc_type="status_report",
        lang="en",
        blocks=(
            Title("title", "PROJECT STATUS REPORT"),
            InfoTable("info.project", (
                InfoRow("cell.report_date", "Report date", key="report_date", field_type="date"),
                InfoRow("cell.project", "Project", key="project"),
                InfoRow("cell.manager", "Project manager", key="manager", field_type="person"),
                InfoRow("cell.status", "Overall status", key="status"),
            )),
            Field("field.prepared_by", "Prepared by", "prepared_by", "person"),
            Heading("heading.summary", "1. Summary"),
            FreeText("text.summary", "summary"),
            Heading("heading.tasks", "2. Tasks"),
            TableBlock("table.tasks", ("Task", "Owner", "Due", "Status"), "tasks"),
            Heading("heading.risks", "3. Risks and issues"),
            FreeText("text.risks", "risks"),
            Heading("heading.confidentiality", "4. Confidentiality"),
            Clause(
                "clause.confidentiality",
                "This report is for the project board and the named recipients only. Do not "
                "forward it outside the organisation without the project manager's consent.",
            ),
        ),
        footer="Internal — Page ",
        values=_values(pair),
    )


SPECS = (_spec_en(),)
