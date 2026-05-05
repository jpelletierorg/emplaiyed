"""Lever ATS adapter.

Handles application submission on Lever-powered job boards (jobs.lever.co).
"""

from __future__ import annotations

import logging
from pathlib import Path

from emplaiyed.apply.adapters.base import BaseAdapter
from emplaiyed.apply.artifacts import SubmissionEvidence, capture_submission_evidence
from emplaiyed.apply.browser import BrowserSession
from emplaiyed.apply.form_mapper import build_form_plan
from emplaiyed.core.models import Profile

logger = logging.getLogger(__name__)


class LeverAdapter(BaseAdapter):
    """Handles Lever ATS application forms."""

    async def discover_fields(self, session: BrowserSession) -> list[dict]:
        """Discover fields on a Lever application form."""
        fields = await session.evaluate("""
        () => {
            const fields = [];
            const form = document.querySelector(
                '.application-form, .lever-application-form, form'
            );
            if (!form) return [];

            const inputs = form.querySelectorAll(
                'input:not([type="hidden"]):not([type="submit"]):not([type="button"]), ' +
                'select, textarea'
            );

            for (const el of inputs) {
                let label = '';
                if (el.id) {
                    const labelEl = document.querySelector(`label[for="${el.id}"]`);
                    if (labelEl) label = labelEl.innerText.trim();
                }
                if (!label && el.closest('.application-question')) {
                    const labelEl = el.closest('.application-question').querySelector('label, .question-label');
                    if (labelEl) label = labelEl.innerText.trim();
                }
                if (!label) {
                    label = el.getAttribute('placeholder') || el.getAttribute('aria-label') || '';
                }

                let selector = '';
                if (el.id) {
                    selector = `#${el.id}`;
                } else if (el.name) {
                    const tag = el.tagName.toLowerCase();
                    selector = `${tag}[name="${el.name}"]`;
                } else {
                    continue;
                }

                const isRequired = el.required
                    || el.getAttribute('aria-required') === 'true'
                    || (label && label.includes('*'));

                label = label.replace(/\\*/g, '').trim();

                fields.push({
                    selector: selector,
                    name: el.name || '',
                    label: label,
                    required: isRequired,
                    type: el.type || el.tagName.toLowerCase(),
                });
            }
            return fields;
        }
        """)
        logger.info("Lever: discovered %d fields", len(fields))
        return fields

    async def fill_and_submit(
        self,
        session: BrowserSession,
        profile: Profile,
        *,
        resume_path: Path | None = None,
        letter_path: Path | None = None,
    ) -> SubmissionEvidence:
        """Fill and submit a Lever application form."""
        fields = await self.discover_fields(session)

        plan = build_form_plan(
            profile,
            fields,
            resume_path=resume_path,
            letter_path=letter_path,
        )

        if plan.unmapped_required:
            logger.warning(
                "Lever: unmapped required fields: %s", plan.unmapped_required
            )
            await session.screenshot("blocked_unmapped_fields.png")
            return SubmissionEvidence(
                confirmed=False,
                confirmation_text=f"Blocked: unmapped required fields: {', '.join(plan.unmapped_required)}",
                final_url=session.url,
                screenshot_path=session._artifact_dir / "blocked_unmapped_fields.png",
            )

        for mapping in plan.text_fields:
            try:
                await session.fill(mapping.selector, mapping.value)
            except Exception as exc:
                logger.warning("Lever: failed to fill %s: %s", mapping.selector, exc)

        for mapping in plan.file_uploads:
            try:
                await session.upload_file(mapping.selector, mapping.value)
            except Exception as exc:
                logger.warning(
                    "Lever: failed to upload to %s: %s", mapping.selector, exc
                )

        await session.screenshot("03_filled_form.png")

        # Lever submit
        submit = await session.query_selector(
            'button.postings-btn[type="submit"], '
            'button[type="submit"], '
            'input[type="submit"]'
        )
        if not submit:
            return SubmissionEvidence(
                confirmed=False,
                confirmation_text="No submit button found",
                final_url=session.url,
            )

        await submit.click()

        try:
            await session.page.wait_for_load_state("domcontentloaded", timeout=10000)
        except Exception:
            pass

        return await capture_submission_evidence(session)
