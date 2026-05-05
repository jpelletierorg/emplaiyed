"""Generic form adapter for unknown/direct-company application forms.

Uses DOM inspection to discover fields, maps them to profile data,
fills required fields, uploads files, and submits.
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


class GenericAdapter(BaseAdapter):
    """Handles generic HTML application forms."""

    async def discover_fields(self, session: BrowserSession) -> list[dict]:
        """Discover all input/select/textarea fields in the first form."""
        fields = await session.evaluate("""
        () => {
            const form = document.querySelector('form');
            if (!form) return [];

            const fields = [];
            const inputs = form.querySelectorAll(
                'input:not([type="hidden"]):not([type="submit"]):not([type="button"]), ' +
                'select, textarea'
            );

            for (const el of inputs) {
                // Find associated label
                let label = '';
                if (el.id) {
                    const labelEl = document.querySelector(`label[for="${el.id}"]`);
                    if (labelEl) label = labelEl.innerText.trim();
                }
                if (!label && el.closest('label')) {
                    label = el.closest('label').innerText.trim();
                }
                if (!label) {
                    label = el.getAttribute('placeholder') || el.getAttribute('aria-label') || '';
                }

                // Build a unique selector
                let selector = '';
                if (el.id) {
                    selector = `#${el.id}`;
                } else if (el.name) {
                    const tag = el.tagName.toLowerCase();
                    selector = `${tag}[name="${el.name}"]`;
                } else {
                    continue;  // Skip fields we can't target
                }

                fields.push({
                    selector: selector,
                    name: el.name || '',
                    label: label,
                    required: el.required || el.getAttribute('aria-required') === 'true',
                    type: el.type || el.tagName.toLowerCase(),
                });
            }
            return fields;
        }
        """)
        logger.info("Discovered %d fields", len(fields))
        return fields

    async def fill_and_submit(
        self,
        session: BrowserSession,
        profile: Profile,
        *,
        resume_path: Path | None = None,
        letter_path: Path | None = None,
    ) -> SubmissionEvidence:
        """Fill required fields and submit the form."""
        fields = await self.discover_fields(session)

        plan = build_form_plan(
            profile,
            fields,
            resume_path=resume_path,
            letter_path=letter_path,
        )

        if plan.unmapped_required:
            logger.warning("Cannot map required fields: %s", plan.unmapped_required)
            await session.screenshot("blocked_unmapped_fields.png")
            return SubmissionEvidence(
                confirmed=False,
                confirmation_text=f"Blocked: unmapped required fields: {', '.join(plan.unmapped_required)}",
                final_url=session.url,
                screenshot_path=session._artifact_dir / "blocked_unmapped_fields.png",
            )

        # Fill text fields
        for mapping in plan.text_fields:
            try:
                await session.fill(mapping.selector, mapping.value)
                logger.debug("Filled %s = %s", mapping.selector, mapping.value[:20])
            except Exception as exc:
                logger.warning("Failed to fill %s: %s", mapping.selector, exc)

        # Upload files
        for mapping in plan.file_uploads:
            try:
                await session.upload_file(mapping.selector, mapping.value)
                logger.debug("Uploaded %s to %s", mapping.value, mapping.selector)
            except Exception as exc:
                logger.warning("Failed to upload to %s: %s", mapping.selector, exc)

        await session.screenshot("03_filled_form.png")

        # Find and click submit
        submit = await _find_submit_button(session)
        if not submit:
            logger.warning("No submit button found")
            return SubmissionEvidence(
                confirmed=False,
                confirmation_text="No submit button found",
                final_url=session.url,
            )

        await submit.click()

        # Wait for page to settle after submission
        try:
            await session.page.wait_for_load_state("domcontentloaded", timeout=10000)
        except Exception:
            pass

        return await capture_submission_evidence(session)


async def _find_submit_button(session: BrowserSession):
    """Find the submit button on the page."""
    selectors = [
        'button[type="submit"]',
        'input[type="submit"]',
        'button:has-text("Submit")',
        'button:has-text("Apply")',
        'button:has-text("Soumettre")',
        'button:has-text("Postuler")',
        'button:has-text("Send")',
        'button:has-text("Envoyer")',
    ]
    for sel in selectors:
        try:
            el = await session.query_selector(sel)
            if el:
                visible = await el.is_visible()
                if visible:
                    return el
        except Exception:
            continue
    return None
