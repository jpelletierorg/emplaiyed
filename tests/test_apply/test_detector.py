"""Tests for portal detection (URL-based only, no browser needed)."""

from __future__ import annotations

from emplaiyed.apply.detector import _URL_PATTERNS
from emplaiyed.core.models import PortalKind

import re


class TestURLPatterns:
    def test_greenhouse_boards(self):
        url = "https://boards.greenhouse.io/company/jobs/123"
        matches = [
            kind
            for pattern, kind in _URL_PATTERNS
            if re.search(pattern, url, re.IGNORECASE)
        ]
        assert PortalKind.GREENHOUSE in matches

    def test_greenhouse_jobs(self):
        url = "https://jobs.greenhouse.io/company/123"
        matches = [
            kind
            for pattern, kind in _URL_PATTERNS
            if re.search(pattern, url, re.IGNORECASE)
        ]
        assert PortalKind.GREENHOUSE in matches

    def test_lever(self):
        url = "https://jobs.lever.co/company/abc-def-123"
        matches = [
            kind
            for pattern, kind in _URL_PATTERNS
            if re.search(pattern, url, re.IGNORECASE)
        ]
        assert PortalKind.LEVER in matches

    def test_ashby(self):
        url = "https://jobs.ashbyhq.com/company/job-id"
        matches = [
            kind
            for pattern, kind in _URL_PATTERNS
            if re.search(pattern, url, re.IGNORECASE)
        ]
        assert PortalKind.ASHBY in matches

    def test_unknown_url(self):
        url = "https://company.com/careers/engineer"
        matches = [
            kind
            for pattern, kind in _URL_PATTERNS
            if re.search(pattern, url, re.IGNORECASE)
        ]
        assert len(matches) == 0
