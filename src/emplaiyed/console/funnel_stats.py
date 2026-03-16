"""Pure functions for computing funnel/pipeline statistics.

No database or Textual dependencies — operates on lists of models.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import timedelta

from emplaiyed.console.stages import STAGE_GROUPS
from emplaiyed.core.models import Application, StatusTransition


@dataclass
class StageStats:
    name: str
    count: int = 0
    conversion_pct: float | None = None  # % converted from previous stage
    avg_time_in_stage: timedelta | None = None


@dataclass
class FunnelSnapshot:
    stages: list[StageStats] = field(default_factory=list)
    total: int = 0
    active: int = 0  # non-closed
    closed: int = 0
    closed_breakdown: dict[str, int] = field(default_factory=dict)


def compute_funnel(
    applications: list[Application],
    transitions: list[StatusTransition],
) -> FunnelSnapshot:
    """Compute funnel statistics from application and transition data.

    *applications* is the full list of all applications.
    *transitions* is the full list of all status transitions across all apps.
    """
    # Count apps per stage group
    status_to_stage: dict[str, str] = {}
    for stage_name, statuses in STAGE_GROUPS.items():
        for s in statuses:
            status_to_stage[s.value] = stage_name

    stage_counts: dict[str, int] = {name: 0 for name in STAGE_GROUPS}
    closed_statuses = {s.value for s in STAGE_GROUPS["Closed"]}

    for app in applications:
        stage = status_to_stage.get(app.status.value)
        if stage:
            stage_counts[stage] += 1

    # Compute which apps ever reached each stage (for conversion rates)
    apps_that_reached: dict[str, set[str]] = {name: set() for name in STAGE_GROUPS}
    for t in transitions:
        stage = status_to_stage.get(t.to_status)
        if stage:
            apps_that_reached[stage].add(t.application_id)

    # Also count current status for apps with no history
    for app in applications:
        stage = status_to_stage.get(app.status.value)
        if stage:
            apps_that_reached[stage].add(app.id)

    # Compute avg time in stage from transitions
    # For each app, measure time between entering a stage and leaving it
    stage_durations: dict[str, list[timedelta]] = {name: [] for name in STAGE_GROUPS}

    # Build per-app transition sequences
    app_transitions: dict[str, list[StatusTransition]] = {}
    for t in transitions:
        app_transitions.setdefault(t.application_id, []).append(t)

    for app_id, ts in app_transitions.items():
        ts.sort(key=lambda x: x.transitioned_at)
        for i, t in enumerate(ts):
            from_stage = status_to_stage.get(t.from_status)
            if from_stage and i > 0:
                # Time in from_stage = this transition time - previous transition time
                prev_t = ts[i - 1]
                if status_to_stage.get(prev_t.to_status) == from_stage:
                    delta = t.transitioned_at - prev_t.transitioned_at
                    stage_durations[from_stage].append(delta)

    # Build stage stats
    ordered_stages = ["Applied", "Active", "Offers", "Closed"]
    stages: list[StageStats] = []
    for i, name in enumerate(ordered_stages):
        reached = len(apps_that_reached[name])
        conv_pct = None
        if i > 0:
            prev_reached = len(apps_that_reached[ordered_stages[i - 1]])
            if prev_reached > 0:
                conv_pct = (reached / prev_reached) * 100

        durations = stage_durations[name]
        avg_time = None
        if durations:
            total_secs = sum(d.total_seconds() for d in durations)
            avg_time = timedelta(seconds=total_secs / len(durations))

        stages.append(StageStats(
            name=name,
            count=stage_counts[name],
            conversion_pct=conv_pct,
            avg_time_in_stage=avg_time,
        ))

    total = len(applications)
    closed = sum(1 for a in applications if a.status.value in closed_statuses)

    closed_breakdown: dict[str, int] = {}
    for s in STAGE_GROUPS["Closed"]:
        count = sum(1 for a in applications if a.status == s)
        if count > 0:
            closed_breakdown[s.value] = count

    return FunnelSnapshot(
        stages=stages,
        total=total,
        active=total - closed,
        closed=closed,
        closed_breakdown=closed_breakdown,
    )
