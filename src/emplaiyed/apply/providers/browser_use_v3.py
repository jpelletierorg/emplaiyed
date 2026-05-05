"""Browser Use v3 provider — single-step browser execution.

Manages a persistent Browser Use session with keep_alive=True so that
multiple sequential tasks can run in the same browser context (needed
for email verification flows where page state must be preserved).
"""

from __future__ import annotations

import logging
from pathlib import Path

import httpx

from browser_use_sdk.v3 import AsyncBrowserUse, FileUploadItem

from emplaiyed.apply.config import BrowserUseConfig
from emplaiyed.apply.result_schema import BrowserApplyState

logger = logging.getLogger(__name__)


class BrowserUseSession:
    """Manages a single Browser Use v3 session lifecycle."""

    def __init__(self, client: AsyncBrowserUse, config: BrowserUseConfig):
        self._client = client
        self._config = config
        self._session_id: str | None = None

    @property
    def session_id(self) -> str | None:
        return self._session_id

    async def create(self) -> str:
        """Create a new keep_alive session."""
        session = await self._client.sessions.create(
            proxy_country_code=self._config.proxy_country_code,
            keep_alive=True,
        )
        self._session_id = str(session.id)
        live_url = getattr(session, "live_url", None)
        logger.info("Session created: %s (live: %s)", self._session_id, live_url)
        return self._session_id

    async def upload_files(self, resume_path: Path, letter_path: Path) -> None:
        """Upload resume and cover letter PDFs to the session."""
        if not self._session_id:
            raise RuntimeError("No session created")

        files_to_upload: list[tuple[str, str, bytes]] = []
        if resume_path.exists():
            files_to_upload.append(
                ("resume.pdf", "application/pdf", resume_path.read_bytes())
            )
        if letter_path.exists():
            files_to_upload.append(
                ("cover_letter.pdf", "application/pdf", letter_path.read_bytes())
            )

        if not files_to_upload:
            logger.warning("No files to upload")
            return

        sdk_items = [
            FileUploadItem(name=name, contentType=ct) for name, ct, _ in files_to_upload
        ]

        logger.info("Uploading %d files to session", len(sdk_items))
        upload_resp = await self._client.sessions.upload_files(
            self._session_id, files=sdk_items
        )

        bytes_by_name = {name: data for name, _, data in files_to_upload}
        async with httpx.AsyncClient(timeout=60.0) as http:
            for item in upload_resp.files:
                file_bytes = bytes_by_name.get(item.name)
                if file_bytes is None:
                    continue
                content_type = next(
                    (ct for n, ct, _ in files_to_upload if n == item.name),
                    "application/octet-stream",
                )
                resp = await http.put(
                    item.upload_url,
                    content=file_bytes,
                    headers={"Content-Type": content_type},
                )
                logger.debug(
                    "Uploaded %s (%d bytes): status %d",
                    item.name,
                    len(file_bytes),
                    resp.status_code,
                )

    async def run_step(self, task: str) -> BrowserApplyState:
        """Run a single task step on this session.

        Returns structured BrowserApplyState. The session remains alive
        (keep_alive=True) so subsequent steps can continue in the same
        browser context.
        """
        if not self._session_id:
            raise RuntimeError("No session created")

        logger.info("Running browser step (session=%s)", self._session_id)
        logger.debug("Task prompt (%d chars): %s", len(task), task[:200])

        result = await self._client.run(
            task,
            session_id=self._session_id,
            keep_alive=True,
            model=self._config.model,
            output_schema=BrowserApplyState,
            max_cost_usd=self._config.max_cost_usd,
        )

        if result.output is None:
            logger.error(
                "Browser Use returned no output (status=%s, session=%s)",
                getattr(result, "status", "?"),
                self._session_id,
            )
            return BrowserApplyState(
                state="failed",
                error_reason=f"Browser Use returned no output (status={getattr(result, 'status', '?')})",
            )

        output: BrowserApplyState = result.output
        logger.info(
            "Browser step result: state=%s, cost=$%s",
            output.state,
            getattr(result, "total_cost_usd", "?"),
        )
        return output

    async def cleanup(self) -> None:
        """Stop and delete the session."""
        if not self._session_id:
            return
        try:
            await self._client.sessions.stop(self._session_id)
            await self._client.sessions.delete(self._session_id)
            logger.info("Session %s stopped and deleted", self._session_id)
        except Exception:
            logger.warning(
                "Failed to cleanup session %s", self._session_id, exc_info=True
            )
