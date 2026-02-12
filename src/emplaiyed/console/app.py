"""Interactive work console — Textual TUI for reviewing and acting on work items."""

from __future__ import annotations

import subprocess
import sys
from datetime import datetime

from textual import work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.widgets import Footer, Header, OptionList, Static
from textual.widgets.option_list import Option

from emplaiyed.core.database import (
    get_application,
    get_default_db_path,
    get_opportunity,
    init_db,
    list_applications,
    list_pending_work_items,
)
from emplaiyed.core.models import Application, ApplicationStatus, WorkItem, WorkStatus, WorkType
from emplaiyed.generation.pipeline import get_asset_dir, has_assets
from emplaiyed.tracker.state_machine import transition
from emplaiyed.work.queue import complete_work_item, create_work_item, skip_work_item

# Sentinel for sort key when application is missing
_NO_APP = Application(
    opportunity_id="", status=ApplicationStatus.DISCOVERED,
    created_at=datetime.min, updated_at=datetime.min,
)


class WorkConsoleApp(App):
    """TUI for reviewing and acting on pending work items."""

    TITLE = "Work Console"

    CSS = """
    #main {
        height: 1fr;
    }
    #item-list {
        width: 1fr;
        min-width: 30;
        max-width: 50;
    }
    #detail-pane {
        width: 3fr;
        padding: 1 2;
        overflow-y: auto;
    }
    """

    BINDINGS = [
        Binding("j", "cursor_down", "Next", show=True),
        Binding("k", "cursor_up", "Prev", show=True),
        Binding("d", "mark_done", "Done", show=True),
        Binding("p", "mark_passed", "Pass", show=True),
        Binding("o", "open_assets", "Open assets", show=True),
        Binding("u", "open_url", "Open URL", show=True),
        Binding("q", "quit", "Quit", show=True),
    ]

    def __init__(self, *, db_path=None):
        super().__init__()
        self._db_path = db_path
        self._conn = None
        self._items: list[WorkItem] = []
        self._generating: set[str] = set()

    def compose(self) -> ComposeResult:
        yield Header()
        with Horizontal(id="main"):
            yield OptionList(id="item-list")
            yield Static("", id="detail-pane")
        yield Footer()

    def on_mount(self) -> None:
        path = self._db_path or get_default_db_path()
        self._conn = init_db(path)
        self._refresh_items()

    def _refresh_items(self) -> None:
        self._items = list_pending_work_items(self._conn)
        # Sort by score descending so the best opportunities are at the top
        self._items.sort(
            key=lambda wi: (self._app_for_item(wi) or _NO_APP).score or 0,
            reverse=True,
        )
        option_list = self.query_one("#item-list", OptionList)
        option_list.clear_options()
        if not self._items:
            self._show_empty()
            return
        self.sub_title = f"{len(self._items)} pending"
        for item in self._items:
            opp = self._opp_for_item(item)
            label = f"{opp.company} — {opp.title}" if opp else item.title
            option_list.add_option(Option(label, id=item.id))
        # Kick off asset generation for all items that don't have assets yet
        for item in self._items:
            if not has_assets(item.application_id):
                self._trigger_asset_generation(item)
        option_list.highlighted = 0
        self._show_detail_for_index(0)

    def _show_empty(self) -> None:
        self.sub_title = "0 pending"
        detail = self.query_one("#detail-pane", Static)
        detail.update("All caught up! No pending work items.")

    def _opp_for_item(self, item: WorkItem):
        app = get_application(self._conn, item.application_id)
        if app is None:
            return None
        return get_opportunity(self._conn, app.opportunity_id)

    def _app_for_item(self, item: WorkItem):
        return get_application(self._conn, item.application_id)

    def on_option_list_option_highlighted(self, event: OptionList.OptionHighlighted) -> None:
        if event.option_list.id != "item-list":
            return
        idx = event.option_index
        if idx is not None and 0 <= idx < len(self._items):
            self._show_detail_for_index(idx)

    def _show_detail_for_index(self, idx: int) -> None:
        if idx >= len(self._items):
            return
        item = self._items[idx]
        opp = self._opp_for_item(item)
        app = self._app_for_item(item)

        lines: list[str] = []
        if opp:
            lines.append(f"Company:  {opp.company}")
            lines.append(f"Role:     {opp.title}")
            if opp.location:
                lines.append(f"Location: {opp.location}")
            if opp.source_url:
                lines.append(f"URL:      {opp.source_url}")

        if app and app.score is not None:
            lines.append(f"Score:    {app.score}")

        lines.append("")

        if app and app.day_to_day:
            lines.append("Day-to-day:")
            lines.append(app.day_to_day)
            lines.append("")

        if app and app.why_it_fits:
            lines.append("Why it fits:")
            lines.append(app.why_it_fits)
            lines.append("")

        # Asset status
        if has_assets(item.application_id):
            lines.append("Assets: Ready (o to open)")
        elif item.application_id in self._generating:
            lines.append("Assets: Generating...")
        else:
            lines.append("Assets: Not generated")
            self._trigger_asset_generation(item)

        detail = self.query_one("#detail-pane", Static)
        detail.update("\n".join(lines))

    def _trigger_asset_generation(self, item: WorkItem) -> None:
        if item.application_id in self._generating:
            return
        self._generating.add(item.application_id)
        self._generate_assets_bg(item)

    @work(thread=True)
    def _generate_assets_bg(self, item: WorkItem) -> None:
        import asyncio

        from emplaiyed.core.profile_store import get_default_profile_path, load_profile
        from emplaiyed.generation.pipeline import generate_assets

        # Open a separate DB connection for this thread (SQLite thread safety)
        conn = init_db(self._db_path or get_default_db_path())
        try:
            app = get_application(conn, item.application_id)
            if app is None:
                return
            opp = get_opportunity(conn, app.opportunity_id)
            if opp is None:
                return

            profile_path = get_default_profile_path()
            if not profile_path.exists():
                return
            profile = load_profile(profile_path)

            asyncio.run(generate_assets(profile, opp, item.application_id))
            self._generating.discard(item.application_id)
            self.call_from_thread(self._refresh_current_detail)
        finally:
            conn.close()

    def _refresh_current_detail(self) -> None:
        option_list = self.query_one("#item-list", OptionList)
        idx = option_list.highlighted
        if idx is not None and 0 <= idx < len(self._items):
            self._show_detail_for_index(idx)

    def _current_item(self) -> WorkItem | None:
        option_list = self.query_one("#item-list", OptionList)
        idx = option_list.highlighted
        if idx is not None and 0 <= idx < len(self._items):
            return self._items[idx]
        return None

    def action_cursor_down(self) -> None:
        option_list = self.query_one("#item-list", OptionList)
        option_list.action_cursor_down()

    def action_cursor_up(self) -> None:
        option_list = self.query_one("#item-list", OptionList)
        option_list.action_cursor_up()

    def action_mark_done(self) -> None:
        item = self._current_item()
        if item is None:
            return
        complete_work_item(self._conn, item.id)
        self._promote_next_scored()
        self._refresh_items()

    def action_mark_passed(self) -> None:
        item = self._current_item()
        if item is None:
            return
        app = get_application(self._conn, item.application_id)
        if app is None:
            return
        # Skip the work item first
        skip_work_item(self._conn, item.id)
        # Then transition to PASSED if possible
        from emplaiyed.tracker.state_machine import can_transition

        refreshed_app = get_application(self._conn, item.application_id)
        if refreshed_app and can_transition(refreshed_app.status, ApplicationStatus.PASSED):
            transition(self._conn, item.application_id, ApplicationStatus.PASSED)
        self._promote_next_scored()
        self._refresh_items()

    def _promote_next_scored(self) -> None:
        """Promote the next highest-scored SCORED application into the work queue."""
        scored = list_applications(self._conn, status=ApplicationStatus.SCORED)
        if not scored:
            return
        # Pick the highest score
        scored.sort(key=lambda a: a.score or 0, reverse=True)
        app = scored[0]
        opp = get_opportunity(self._conn, app.opportunity_id)
        if opp is None:
            return
        create_work_item(
            self._conn,
            application_id=app.id,
            work_type=WorkType.OUTREACH,
            title=f"Apply to {opp.company} — {opp.title}",
            instructions=f"Review and send application for {opp.title} at {opp.company}.",
            target_status=ApplicationStatus.OUTREACH_SENT,
            previous_status=ApplicationStatus.SCORED,
            pending_status=ApplicationStatus.OUTREACH_PENDING,
        )

    def action_open_assets(self) -> None:
        item = self._current_item()
        if item is None:
            return
        if not has_assets(item.application_id):
            return
        asset_dir = get_asset_dir(item.application_id)
        if sys.platform == "darwin":
            subprocess.run(["open", str(asset_dir)])
        elif sys.platform == "linux":
            subprocess.run(["xdg-open", str(asset_dir)])

    def action_open_url(self) -> None:
        item = self._current_item()
        if item is None:
            return
        opp = self._opp_for_item(item)
        if opp is None or not opp.source_url:
            return
        import webbrowser

        webbrowser.open(opp.source_url)
