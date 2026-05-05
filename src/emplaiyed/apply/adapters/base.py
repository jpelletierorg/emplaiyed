"""Base adapter interface for portal-specific application flows."""

from __future__ import annotations

import abc
from pathlib import Path

from emplaiyed.apply.artifacts import SubmissionEvidence
from emplaiyed.apply.browser import BrowserSession
from emplaiyed.core.models import Profile


class BaseAdapter(abc.ABC):
    """Interface for portal-specific application submission.

    Each adapter knows how to:
    1. Discover form fields on its portal
    2. Fill required fields from the candidate profile
    3. Upload resume and cover letter
    4. Submit the application
    5. Detect confirmation
    """

    @abc.abstractmethod
    async def discover_fields(self, session: BrowserSession) -> list[dict]:
        """Discover form fields on the current page.

        Returns a list of field descriptors with keys:
            - selector: CSS selector to target the field
            - name: field name attribute
            - label: visible label text
            - required: whether the field is required
            - type: input type (text, file, email, tel, select, textarea)
        """
        ...

    @abc.abstractmethod
    async def fill_and_submit(
        self,
        session: BrowserSession,
        profile: Profile,
        *,
        resume_path: Path | None = None,
        letter_path: Path | None = None,
    ) -> SubmissionEvidence:
        """Fill the application form and submit it.

        Returns evidence of the submission attempt.
        """
        ...
