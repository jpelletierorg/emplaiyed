"""Interactive work console — Textual TUI for reviewing and acting on work items."""

from __future__ import annotations

import logging
import subprocess
import sys
from datetime import datetime

logger = logging.getLogger(__name__)

from textual import work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal
from textual.widgets import Footer, Header, OptionList, Static, TabbedContent, TabPane
from textual.widgets.option_list import Option

from emplaiyed.console.funnel_stats import compute_funnel
from emplaiyed.console.stages import STAGE_GROUPS, STAGE_TAB_ORDER
from emplaiyed.core.database import (
    get_application,
    get_default_db_path,
    get_opportunity,
    init_db,
    list_applications,
    list_applications_by_statuses,
    list_events,
    list_interactions,
    list_pending_work_items,
    list_status_transitions,
    save_event,
    save_interaction,
)
from emplaiyed.core.models import (
    Application,
    ApplicationStatus,
    Interaction,
    InteractionType,
    ScheduledEvent,
    WorkType,
)
from emplaiyed.generation.pipeline import get_asset_dir, has_assets
from emplaiyed.tracker.state_machine import can_transition, transition
from emplaiyed.work.queue import complete_work_item, create_work_item, skip_work_item

# Tab ID mappings
_TAB_IDS = {name: f"tab-{name.lower()}" for name in STAGE_TAB_ORDER}
_ID_TO_TAB = {v: k for k, v in _TAB_IDS.items()}

# Actions valid per tab
_TAB_ACTIONS: dict[str, set[str]] = {
    "Queue": {"cursor_down", "cursor_up", "mark_done", "mark_passed", "open_assets", "open_url"},
    "Applied": {"cursor_down", "cursor_up", "open_url", "add_note", "mark_response", "mark_ghosted", "log_followup"},
    "Active": {"cursor_down", "cursor_up", "open_url", "add_note", "schedule_interview", "interview_completed", "mark_rejected", "mark_offer"},
    "Offers": {"cursor_down", "cursor_up", "open_url", "add_note", "mark_rejected", "accept_offer"},
    "Closed": {"cursor_down", "cursor_up", "open_url"},
    "Funnel": set(),
}

_ALWAYS_VALID = {"prev_tab", "next_tab", "quit"}


class WorkConsoleApp(App):
    """TUI for reviewing and acting on pending work items."""

    TITLE = "Work Console"

    CSS = """
    #main-tabs {
        height: 1fr;
    }
    .tab-content {
        height: 1fr;
    }
    .tab-list {
        width: 1fr;
        min-width: 30;
        max-width: 50;
    }
    .tab-detail {
        width: 3fr;
        padding: 1 2;
        overflow-y: auto;
    }
    #detail-funnel {
        width: 1fr;
        padding: 1 2;
    }
    """

    BINDINGS = [
        Binding("j", "cursor_down", "Next", show=True),
        Binding("k", "cursor_up", "Prev", show=True),
        Binding("left", "prev_tab", "Prev Tab", show=True),
        Binding("right", "next_tab", "Next Tab", show=True),
        Binding("d", "mark_done", "Done", show=True),
        Binding("p", "mark_passed", "Pass", show=True),
        Binding("o", "open_assets", "Open assets", show=True),
        Binding("u", "open_url", "Open URL", show=True),
        Binding("n", "add_note", "Note", show=True),
        Binding("r", "mark_response", "Response", show=True),
        Binding("g", "mark_ghosted", "Ghosted", show=True),
        Binding("s", "schedule_interview", "Schedule", show=True),
        Binding("c", "interview_completed", "Completed", show=True),
        Binding("x", "mark_rejected", "Rejected", show=True),
        Binding("f", "log_followup", "Follow-up", show=True),
        Binding("o", "mark_offer", "Offer", show=True),
        Binding("a", "accept_offer", "Accept", show=True),
        Binding("q", "quit", "Quit", show=True),
    ]

    def __init__(self, *, db_path=None):
        super().__init__()
        self._db_path = db_path
        self._conn = None
        self._queue_apps: list[Application] = []
        self._tab_apps: dict[str, list[Application]] = {}
        self._generating: set[str] = set()

    def compose(self) -> ComposeResult:
        yield Header()
        with TabbedContent(id="main-tabs"):
            for tab_name in STAGE_TAB_ORDER:
                tab_key = tab_name.lower()
                with TabPane(tab_name, id=_TAB_IDS[tab_name]):
                    if tab_name == "Funnel":
                        yield Static("", id=f"detail-{tab_key}", classes="tab-detail")
                    else:
                        with Horizontal(classes="tab-content"):
                            yield OptionList(id=f"list-{tab_key}", classes="tab-list")
                            yield Static("", id=f"detail-{tab_key}", classes="tab-detail")
        yield Footer()

    def on_mount(self) -> None:
        path = self._db_path or get_default_db_path()
        self._conn = init_db(path)
        self._refresh_all()

    # ------------------------------------------------------------------
    # Refresh
    # ------------------------------------------------------------------

    def _refresh_all(self) -> None:
        self._refresh_queue()
        for tab_name in STAGE_GROUPS:
            self._refresh_pipeline_tab(tab_name)
        self._refresh_funnel()
        self._update_tab_labels()

    def _refresh_queue(self) -> None:
        queue_statuses = [
            ApplicationStatus.SCORED,
            ApplicationStatus.OUTREACH_PENDING,
            ApplicationStatus.FOLLOW_UP_PENDING,
        ]
        self._queue_apps = list_applications_by_statuses(self._conn, queue_statuses)
        self._queue_apps.sort(key=lambda a: a.score or 0, reverse=True)
        option_list = self.query_one("#list-queue", OptionList)
        option_list.clear_options()
        if not self._queue_apps:
            self.sub_title = "0 pending"
            detail = self.query_one("#detail-queue", Static)
            detail.update("All caught up! No pending work items.")
            return
        self.sub_title = f"{len(self._queue_apps)} pending"
        for app in self._queue_apps:
            opp = get_opportunity(self._conn, app.opportunity_id)
            label = f"{opp.company} — {opp.title}" if opp else app.id
            option_list.add_option(Option(label, id=app.id))
        for app in self._queue_apps:
            if not has_assets(app.id):
                self._trigger_asset_generation(app.id)
        option_list.highlighted = 0
        self._show_queue_detail(0)

    def _refresh_pipeline_tab(self, tab_name: str) -> None:
        statuses = STAGE_GROUPS[tab_name]
        apps = list_applications_by_statuses(self._conn, statuses)
        self._tab_apps[tab_name] = apps
        tab_key = tab_name.lower()
        try:
            option_list = self.query_one(f"#list-{tab_key}", OptionList)
        except Exception:
            return  # tab content not yet mounted
        option_list.clear_options()
        if not apps:
            try:
                detail = self.query_one(f"#detail-{tab_key}", Static)
                detail.update(f"No applications in {tab_name} stage.")
            except Exception:
                pass
            return
        for app in apps:
            opp = get_opportunity(self._conn, app.opportunity_id)
            label = f"{opp.company} — {opp.title}" if opp else app.id
            option_list.add_option(Option(label, id=app.id))
        option_list.highlighted = 0
        self._show_pipeline_detail(tab_name, 0)

    def _refresh_funnel(self) -> None:
        all_apps = list_applications(self._conn)
        all_transitions: list = []
        for app in all_apps:
            all_transitions.extend(list_status_transitions(self._conn, app.id))
        snapshot = compute_funnel(all_apps, all_transitions)

        lines = ["FUNNEL DASHBOARD", "=" * 40, ""]
        for stage in snapshot.stages:
            line = f"  {stage.name:<15} {stage.count:>3}"
            if stage.conversion_pct is not None:
                line += f"   ({stage.conversion_pct:.0f}% from prev)"
            if stage.avg_time_in_stage is not None:
                days = stage.avg_time_in_stage.total_seconds() / 86400
                if days >= 1:
                    line += f"   avg {days:.0f}d in stage"
                else:
                    hours = stage.avg_time_in_stage.total_seconds() / 3600
                    line += f"   avg {hours:.0f}h in stage"
            lines.append(line)

        lines.extend([
            "",
            f"  Total:   {snapshot.total}",
            f"  Active:  {snapshot.active}",
            f"  Closed:  {snapshot.closed}",
        ])

        detail = self.query_one("#detail-funnel", Static)
        detail.update("\n".join(lines))

    def _update_tab_labels(self) -> None:
        try:
            tc = self.query_one(TabbedContent)
        except Exception:
            return
        queue_count = len(self._queue_apps)
        tc.get_tab(_TAB_IDS["Queue"]).label = f"Queue ({queue_count})"
        for tab_name in STAGE_GROUPS:
            count = len(self._tab_apps.get(tab_name, []))
            tc.get_tab(_TAB_IDS[tab_name]).label = f"{tab_name} ({count})"
        tc.get_tab(_TAB_IDS["Funnel"]).label = "Funnel"

    # ------------------------------------------------------------------
    # Detail rendering
    # ------------------------------------------------------------------

    def _show_queue_detail(self, idx: int) -> None:
        if idx >= len(self._queue_apps):
            return
        app = self._queue_apps[idx]
        opp = get_opportunity(self._conn, app.opportunity_id)

        lines: list[str] = []
        if opp:
            lines.append(f"Company:  {opp.company}")
            lines.append(f"Role:     {opp.title}")
            if opp.location:
                lines.append(f"Location: {opp.location}")
            if opp.source_url:
                lines.append(f"URL:      {opp.source_url}")

        if app.score is not None:
            lines.append(f"Score:    {app.score}")

        lines.append("")

        if app.day_to_day:
            lines.append("Day-to-day:")
            lines.append(app.day_to_day)
            lines.append("")

        if app.why_it_fits:
            lines.append("Why it fits:")
            lines.append(app.why_it_fits)
            lines.append("")

        if has_assets(app.id):
            lines.append("Assets: Ready (o to open)")
        elif app.id in self._generating:
            lines.append("Assets: Generating...")
        else:
            lines.append("Assets: Not generated")
            self._trigger_asset_generation(app.id)

        detail = self.query_one("#detail-queue", Static)
        detail.update("\n".join(lines))

    def _show_pipeline_detail(self, tab_name: str, idx: int) -> None:
        apps = self._tab_apps.get(tab_name, [])
        if idx >= len(apps):
            return
        app = apps[idx]
        opp = get_opportunity(self._conn, app.opportunity_id)

        lines: list[str] = []
        if opp:
            lines.append(f"Company:  {opp.company}")
            lines.append(f"Role:     {opp.title}")
            if opp.location:
                lines.append(f"Location: {opp.location}")
            if opp.source_url:
                lines.append(f"URL:      {opp.source_url}")

        lines.append(f"Status:   {app.status.value}")
        if app.score is not None:
            lines.append(f"Score:    {app.score}")

        lines.append("")

        if app.day_to_day:
            lines.append("Day-to-day:")
            lines.append(app.day_to_day)
            lines.append("")

        if app.why_it_fits:
            lines.append("Why it fits:")
            lines.append(app.why_it_fits)
            lines.append("")

        # Timeline
        lines.append("─" * 40)
        lines.append("TIMELINE")
        lines.append("")

        timeline_entries: list[tuple[datetime, str]] = []

        for t in list_status_transitions(self._conn, app.id):
            timeline_entries.append(
                (t.transitioned_at, f"{t.from_status} → {t.to_status}")
            )

        for ix in list_interactions(self._conn, app.id):
            label = ix.content or ""
            if len(label) > 60:
                label = label[:57] + "..."
            timeline_entries.append(
                (ix.created_at, f"[{ix.type.value}] {label}")
            )

        for ev in list_events(self._conn, application_id=app.id):
            label = ev.notes or ""
            if len(label) > 60:
                label = label[:57] + "..."
            timeline_entries.append(
                (ev.scheduled_date, f"[EVENT] {ev.event_type} — {label}")
            )

        timeline_entries.sort(key=lambda e: e[0])

        if timeline_entries:
            for ts, desc in timeline_entries:
                lines.append(f"  {ts.strftime('%b %d %H:%M')}  {desc}")
        else:
            lines.append("  (no activity recorded)")

        try:
            detail = self.query_one(f"#detail-{tab_name.lower()}", Static)
        except Exception:
            return  # tab content not yet mounted
        detail.update("\n".join(lines))

    # ------------------------------------------------------------------
    # Data helpers
    # ------------------------------------------------------------------

    @property
    def _active_tab(self) -> str:
        try:
            tc = self.query_one(TabbedContent)
            return _ID_TO_TAB.get(tc.active, "Queue")
        except Exception:
            return "Queue"

    def _current_queue_app(self) -> Application | None:
        if self._active_tab != "Queue":
            return None
        option_list = self.query_one("#list-queue", OptionList)
        idx = option_list.highlighted
        if idx is not None and 0 <= idx < len(self._queue_apps):
            return self._queue_apps[idx]
        return None

    def _current_pipeline_app(self) -> Application | None:
        tab = self._active_tab
        if tab in ("Queue", "Funnel"):
            return None
        apps = self._tab_apps.get(tab, [])
        option_list = self.query_one(f"#list-{tab.lower()}", OptionList)
        idx = option_list.highlighted
        if idx is not None and 0 <= idx < len(apps):
            return apps[idx]
        return None

    # ------------------------------------------------------------------
    # Event handlers
    # ------------------------------------------------------------------

    def on_option_list_option_highlighted(self, event: OptionList.OptionHighlighted) -> None:
        list_id = event.option_list.id
        if not list_id or not list_id.startswith("list-"):
            return
        tab_key = list_id[5:]  # strip "list-"
        tab_name = None
        for name in STAGE_TAB_ORDER:
            if name.lower() == tab_key:
                tab_name = name
                break
        if tab_name is None:
            return
        idx = event.option_index
        if idx is None:
            return
        if tab_name == "Queue":
            if 0 <= idx < len(self._queue_apps):
                self._show_queue_detail(idx)
        else:
            apps = self._tab_apps.get(tab_name, [])
            if 0 <= idx < len(apps):
                self._show_pipeline_detail(tab_name, idx)

    def on_tabbed_content_tab_activated(self, event: TabbedContent.TabActivated) -> None:
        self.refresh_bindings()

    def check_action(self, action: str, parameters: tuple[object, ...]) -> bool | None:
        if action in _ALWAYS_VALID:
            return True
        tab = self._active_tab
        valid = _TAB_ACTIONS.get(tab, set())
        return action in valid

    # ------------------------------------------------------------------
    # Navigation actions
    # ------------------------------------------------------------------

    def action_cursor_down(self) -> None:
        tab = self._active_tab
        if tab == "Funnel":
            return
        option_list = self.query_one(f"#list-{tab.lower()}", OptionList)
        option_list.action_cursor_down()

    def action_cursor_up(self) -> None:
        tab = self._active_tab
        if tab == "Funnel":
            return
        option_list = self.query_one(f"#list-{tab.lower()}", OptionList)
        option_list.action_cursor_up()

    def action_prev_tab(self) -> None:
        current = self._active_tab
        idx = STAGE_TAB_ORDER.index(current)
        prev_idx = (idx - 1) % len(STAGE_TAB_ORDER)
        tc = self.query_one(TabbedContent)
        tc.active = _TAB_IDS[STAGE_TAB_ORDER[prev_idx]]

    def action_next_tab(self) -> None:
        current = self._active_tab
        idx = STAGE_TAB_ORDER.index(current)
        next_idx = (idx + 1) % len(STAGE_TAB_ORDER)
        tc = self.query_one(TabbedContent)
        tc.active = _TAB_IDS[STAGE_TAB_ORDER[next_idx]]

    # ------------------------------------------------------------------
    # Queue actions
    # ------------------------------------------------------------------

    def action_mark_done(self) -> None:
        if self._active_tab != "Queue":
            return
        app = self._current_queue_app()
        if app is None:
            return
        if app.status == ApplicationStatus.OUTREACH_PENDING:
            # Already has a work item — find and complete it
            pending = list_pending_work_items(self._conn)
            for wi in pending:
                if wi.application_id == app.id:
                    complete_work_item(self._conn, wi.id)
                    break
        elif app.status == ApplicationStatus.SCORED:
            # No work item yet — create one and immediately complete it
            opp = get_opportunity(self._conn, app.opportunity_id)
            title = f"Apply to {opp.company} — {opp.title}" if opp else f"Apply for {app.id}"
            wi = create_work_item(
                self._conn,
                application_id=app.id,
                work_type=WorkType.OUTREACH,
                title=title,
                instructions=f"Review and send application.",
                target_status=ApplicationStatus.OUTREACH_SENT,
                previous_status=ApplicationStatus.SCORED,
                pending_status=ApplicationStatus.OUTREACH_PENDING,
            )
            complete_work_item(self._conn, wi.id)
        self._refresh_all()

    def action_mark_passed(self) -> None:
        if self._active_tab != "Queue":
            return
        app = self._current_queue_app()
        if app is None:
            return
        if app.status == ApplicationStatus.OUTREACH_PENDING:
            # Has a work item — skip it, then transition to PASSED
            pending = list_pending_work_items(self._conn)
            for wi in pending:
                if wi.application_id == app.id:
                    skip_work_item(self._conn, wi.id)
                    break
            refreshed = get_application(self._conn, app.id)
            if refreshed and can_transition(refreshed.status, ApplicationStatus.PASSED):
                transition(self._conn, app.id, ApplicationStatus.PASSED)
        elif app.status == ApplicationStatus.SCORED:
            # No work item — transition directly to PASSED
            transition(self._conn, app.id, ApplicationStatus.PASSED)
        self._refresh_all()

    def action_open_assets(self) -> None:
        if self._active_tab != "Queue":
            return
        app = self._current_queue_app()
        if app is None:
            return
        if not has_assets(app.id):
            return
        asset_dir = get_asset_dir(app.id)
        if sys.platform == "darwin":
            subprocess.run(["open", str(asset_dir)])
        elif sys.platform == "linux":
            subprocess.run(["xdg-open", str(asset_dir)])

    # ------------------------------------------------------------------
    # Universal actions
    # ------------------------------------------------------------------

    def action_open_url(self) -> None:
        tab = self._active_tab
        if tab == "Funnel":
            return
        opp = None
        if tab == "Queue":
            queue_app = self._current_queue_app()
            if queue_app:
                opp = get_opportunity(self._conn, queue_app.opportunity_id)
        else:
            app = self._current_pipeline_app()
            if app:
                opp = get_opportunity(self._conn, app.opportunity_id)
        if opp is None or not opp.source_url:
            return
        import webbrowser

        webbrowser.open(opp.source_url)

    # ------------------------------------------------------------------
    # Pipeline actions
    # ------------------------------------------------------------------

    def action_add_note(self) -> None:
        app = self._current_pipeline_app()
        if app is None:
            return
        from emplaiyed.console.modals import NoteModal

        def _on_note(text: str | None) -> None:
            if text is None:
                return
            save_interaction(
                self._conn,
                Interaction(
                    application_id=app.id,
                    type=InteractionType.NOTE,
                    direction="internal",
                    channel="console",
                    content=text,
                    created_at=datetime.now(),
                ),
            )
            self.notify("Note added")

        self.push_screen(NoteModal(), callback=_on_note)

    def action_log_followup(self) -> None:
        if self._active_tab != "Applied":
            return
        app = self._current_pipeline_app()
        if app is None:
            return
        if app.status == ApplicationStatus.FOLLOW_UP_2:
            self.notify("No more follow-ups", severity="warning")
            return
        if app.status == ApplicationStatus.OUTREACH_SENT:
            target = ApplicationStatus.FOLLOW_UP_1
        elif app.status == ApplicationStatus.FOLLOW_UP_1:
            target = ApplicationStatus.FOLLOW_UP_2
        else:
            self.notify("Cannot log follow-up from this status", severity="warning")
            return

        from emplaiyed.console.modals import LogFollowUpModal

        def _on_followup(text: str | None) -> None:
            if text is None:
                return
            save_interaction(
                self._conn,
                Interaction(
                    application_id=app.id,
                    type=InteractionType.FOLLOW_UP,
                    direction="outbound",
                    channel="console",
                    content=text,
                    created_at=datetime.now(),
                ),
            )
            transition(self._conn, app.id, target)
            self.notify("Follow-up logged")
            self._refresh_all()

        self.push_screen(LogFollowUpModal(), callback=_on_followup)

    def action_mark_response(self) -> None:
        if self._active_tab != "Applied":
            return
        app = self._current_pipeline_app()
        if app is None:
            return
        if not can_transition(app.status, ApplicationStatus.RESPONSE_RECEIVED):
            self.notify("Cannot mark response from this status", severity="warning")
            return

        from emplaiyed.console.modals import ResponseReceivedModal

        def _on_response(data: dict | None) -> None:
            if data is None:
                return
            save_interaction(
                self._conn,
                Interaction(
                    application_id=app.id,
                    type=InteractionType.EMAIL_RECEIVED,
                    direction="inbound",
                    channel="console",
                    content=data["description"],
                    created_at=datetime.now(),
                ),
            )
            transition(self._conn, app.id, ApplicationStatus.RESPONSE_RECEIVED)
            if data.get("schedule"):
                sched = data["schedule"]
                save_event(
                    self._conn,
                    ScheduledEvent(
                        application_id=app.id,
                        event_type=sched["event_type"],
                        scheduled_date=sched["scheduled_date"],
                        notes=sched.get("notes"),
                        created_at=datetime.now(),
                    ),
                )
                if can_transition(ApplicationStatus.RESPONSE_RECEIVED, ApplicationStatus.INTERVIEW_SCHEDULED):
                    transition(self._conn, app.id, ApplicationStatus.INTERVIEW_SCHEDULED)
            self.notify("Marked as response received")
            self._refresh_all()

        self.push_screen(ResponseReceivedModal(), callback=_on_response)

    def action_mark_ghosted(self) -> None:
        if self._active_tab != "Applied":
            return
        app = self._current_pipeline_app()
        if app is None:
            return
        if not can_transition(app.status, ApplicationStatus.GHOSTED):
            self.notify("Cannot mark ghosted from this status", severity="warning")
            return
        transition(self._conn, app.id, ApplicationStatus.GHOSTED)
        self.notify("Marked as ghosted")
        self._refresh_all()

    def action_schedule_interview(self) -> None:
        if self._active_tab != "Active":
            return
        app = self._current_pipeline_app()
        if app is None:
            return
        from emplaiyed.console.modals import ScheduleInterviewModal

        def _on_schedule(data: dict | None) -> None:
            if data is None:
                return
            save_event(
                self._conn,
                ScheduledEvent(
                    application_id=app.id,
                    event_type=data["event_type"],
                    scheduled_date=data["scheduled_date"],
                    notes=data.get("notes"),
                    created_at=datetime.now(),
                ),
            )
            if can_transition(app.status, ApplicationStatus.INTERVIEW_SCHEDULED):
                transition(self._conn, app.id, ApplicationStatus.INTERVIEW_SCHEDULED)
            self.notify("Interview scheduled")
            self._refresh_all()

        self.push_screen(ScheduleInterviewModal(), callback=_on_schedule)

    def action_interview_completed(self) -> None:
        if self._active_tab != "Active":
            return
        app = self._current_pipeline_app()
        if app is None:
            return
        if not can_transition(app.status, ApplicationStatus.INTERVIEW_COMPLETED):
            self.notify("Cannot mark completed from this status", severity="warning")
            return
        transition(self._conn, app.id, ApplicationStatus.INTERVIEW_COMPLETED)
        self.notify("Interview completed")
        self._refresh_all()

    def action_mark_rejected(self) -> None:
        tab = self._active_tab
        if tab not in ("Active", "Offers"):
            return
        app = self._current_pipeline_app()
        if app is None:
            return
        if not can_transition(app.status, ApplicationStatus.REJECTED):
            self.notify("Cannot mark rejected from this status", severity="warning")
            return
        transition(self._conn, app.id, ApplicationStatus.REJECTED)
        self.notify("Marked as rejected")
        self._refresh_all()

    def action_mark_offer(self) -> None:
        if self._active_tab != "Active":
            return
        app = self._current_pipeline_app()
        if app is None:
            return
        if app.status != ApplicationStatus.INTERVIEW_COMPLETED:
            self.notify("Can only mark offer on completed interviews", severity="warning")
            return

        from emplaiyed.console.modals import NoteModal

        def _on_offer(text: str | None) -> None:
            if text is None:
                return
            save_interaction(
                self._conn,
                Interaction(
                    application_id=app.id,
                    type=InteractionType.NOTE,
                    direction="internal",
                    channel="console",
                    content=f"Offer received: {text}",
                    created_at=datetime.now(),
                ),
            )
            transition(self._conn, app.id, ApplicationStatus.OFFER_RECEIVED)
            self.notify("Offer recorded")
            self._refresh_all()

        self.push_screen(NoteModal(), callback=_on_offer)

    def action_accept_offer(self) -> None:
        if self._active_tab != "Offers":
            return
        app = self._current_pipeline_app()
        if app is None:
            return
        if not can_transition(app.status, ApplicationStatus.ACCEPTED):
            self.notify("Cannot accept from this status", severity="warning")
            return
        transition(self._conn, app.id, ApplicationStatus.ACCEPTED)
        self.notify("Offer accepted!")
        self._refresh_all()

    # ------------------------------------------------------------------
    # Asset generation (background)
    # ------------------------------------------------------------------

    def _trigger_asset_generation(self, app_id: str) -> None:
        if app_id in self._generating:
            return
        self._generating.add(app_id)
        self._generate_assets_bg(app_id)

    @work(thread=True)
    def _generate_assets_bg(self, app_id: str) -> None:
        import asyncio

        from emplaiyed.core.profile_store import get_default_profile_path, load_profile
        from emplaiyed.generation.pipeline import generate_assets

        conn = init_db(self._db_path or get_default_db_path())
        try:
            app = get_application(conn, app_id)
            if app is None:
                return
            opp = get_opportunity(conn, app.opportunity_id)
            if opp is None:
                return
            profile_path = get_default_profile_path()
            if not profile_path.exists():
                return
            profile = load_profile(profile_path)
            asyncio.run(generate_assets(profile, opp, app_id))
            self.call_from_thread(self._refresh_current_queue_detail)
        except Exception:
            logger.warning("Asset generation failed for %s", app_id, exc_info=True)
        finally:
            self._generating.discard(app_id)
            conn.close()

    def _refresh_current_queue_detail(self) -> None:
        if self._active_tab != "Queue":
            return
        option_list = self.query_one("#list-queue", OptionList)
        idx = option_list.highlighted
        if idx is not None and 0 <= idx < len(self._queue_apps):
            self._show_queue_detail(idx)
