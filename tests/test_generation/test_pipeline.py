"""Tests for the asset generation pipeline."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest
from pydantic_ai.models.test import TestModel

from emplaiyed.core.database import (
    get_application,
    init_db,
    list_pending_work_items,
    save_application,
    save_opportunity,
)
from emplaiyed.core.models import (
    Application,
    ApplicationStatus,
    Aspirations,
    Employment,
    Opportunity,
    Profile,
)
from emplaiyed.generation.pipeline import (
    AssetPaths,
    generate_assets,
    generate_assets_and_enqueue,
    generate_assets_batch,
    has_assets,
)


@pytest.fixture
def profile() -> Profile:
    return Profile(
        name="Alice Test",
        email="alice@example.com",
        skills=["Python", "AWS"],
        employment_history=[
            Employment(company="Acme", title="Dev"),
        ],
        aspirations=Aspirations(target_roles=["Cloud Architect"]),
    )


@pytest.fixture
def opportunity() -> Opportunity:
    return Opportunity(
        id="opp-1",
        source="jobbank",
        source_url="https://jobbank.gc.ca/job/12345",
        company="BigCorp",
        title="Cloud Architect",
        description="Design cloud infrastructure.",
        location="Montreal, QC",
        scraped_at=datetime.now(),
    )


@pytest.fixture
def db(tmp_path: Path):
    conn = init_db(tmp_path / "pipeline.db")
    yield conn
    conn.close()


class TestHasAssets:
    def test_returns_false_when_no_files(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            "emplaiyed.generation.pipeline._find_project_root",
            lambda: tmp_path,
        )
        assert has_assets("nonexistent-app") is False

    def test_returns_false_when_partial_files(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            "emplaiyed.generation.pipeline._find_project_root",
            lambda: tmp_path,
        )
        asset_dir = tmp_path / "data" / "assets" / "partial-app"
        asset_dir.mkdir(parents=True)
        (asset_dir / "cv.pdf").write_bytes(b"fake")
        # letter.pdf missing
        assert has_assets("partial-app") is False

    def test_returns_true_when_both_pdfs_exist(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            "emplaiyed.generation.pipeline._find_project_root",
            lambda: tmp_path,
        )
        asset_dir = tmp_path / "data" / "assets" / "full-app"
        asset_dir.mkdir(parents=True)
        (asset_dir / "cv.pdf").write_bytes(b"fake")
        (asset_dir / "letter.pdf").write_bytes(b"fake")
        assert has_assets("full-app") is True


class TestGenerateAssets:
    async def test_creates_all_four_files(self, profile, opportunity, tmp_path):
        model = TestModel()
        asset_dir = tmp_path / "assets" / "test-app"

        paths = await generate_assets(
            profile, opportunity, "test-app",
            _model_override=model,
            asset_dir=asset_dir,
        )

        assert isinstance(paths, AssetPaths)
        assert paths.cv_md.exists()
        assert paths.cv_pdf.exists()
        assert paths.letter_md.exists()
        assert paths.letter_pdf.exists()

    async def test_cv_markdown_has_content(self, profile, opportunity, tmp_path):
        model = TestModel()
        asset_dir = tmp_path / "assets" / "test-app"

        paths = await generate_assets(
            profile, opportunity, "test-app",
            _model_override=model,
            asset_dir=asset_dir,
        )

        cv_text = paths.cv_md.read_text()
        assert len(cv_text) > 0
        assert "#" in cv_text  # has markdown headings

    async def test_letter_markdown_has_content(self, profile, opportunity, tmp_path):
        model = TestModel()
        asset_dir = tmp_path / "assets" / "test-app"

        paths = await generate_assets(
            profile, opportunity, "test-app",
            _model_override=model,
            asset_dir=asset_dir,
        )

        letter_text = paths.letter_md.read_text()
        assert len(letter_text) > 0

    async def test_pdf_files_have_content(self, profile, opportunity, tmp_path):
        model = TestModel()
        asset_dir = tmp_path / "assets" / "test-app"

        paths = await generate_assets(
            profile, opportunity, "test-app",
            _model_override=model,
            asset_dir=asset_dir,
        )

        assert paths.cv_pdf.stat().st_size > 0
        assert paths.letter_pdf.stat().st_size > 0


class TestGenerateAssetsAndEnqueue:
    async def test_creates_work_item(self, profile, opportunity, db):
        model = TestModel()
        save_opportunity(db, opportunity)

        app = Application(
            id="app-1",
            opportunity_id="opp-1",
            status=ApplicationStatus.SCORED,
            created_at=datetime.now(),
            updated_at=datetime.now(),
        )
        save_application(db, app)

        paths = await generate_assets_and_enqueue(
            db, profile, opportunity, "app-1",
            _model_override=model,
            asset_dir=db.execute("SELECT 1").fetchone() and Path("/tmp/test-assets-enqueue"),
        )

        # Verify work item was created
        items = list_pending_work_items(db)
        assert len(items) == 1
        assert "BigCorp" in items[0].title

        # Verify app transitioned to OUTREACH_PENDING
        updated = get_application(db, "app-1")
        assert updated.status == ApplicationStatus.OUTREACH_PENDING

    async def test_work_item_instructions_reference_assets(self, profile, opportunity, db, tmp_path):
        model = TestModel()
        save_opportunity(db, opportunity)

        app = Application(
            id="app-1",
            opportunity_id="opp-1",
            status=ApplicationStatus.SCORED,
            created_at=datetime.now(),
            updated_at=datetime.now(),
        )
        save_application(db, app)

        asset_dir = tmp_path / "assets" / "app-1"
        await generate_assets_and_enqueue(
            db, profile, opportunity, "app-1",
            _model_override=model,
            asset_dir=asset_dir,
        )

        items = list_pending_work_items(db)
        instructions = items[0].instructions
        assert "cv.pdf" in instructions
        assert "letter.pdf" in instructions
        assert "jobbank.gc.ca/job/12345" in instructions


class TestGenerateAssetsBatch:
    async def test_processes_multiple_apps(self, profile, db, tmp_path):
        model = TestModel()
        now = datetime.now()

        opps = []
        scored_apps = []
        for i in range(3):
            opp = Opportunity(
                id=f"opp-{i}",
                source="jobbank",
                company=f"Corp{i}",
                title=f"Role{i}",
                description=f"Description {i}",
                scraped_at=now,
            )
            save_opportunity(db, opp)
            opps.append(opp)

            app = Application(
                id=f"app-{i}",
                opportunity_id=f"opp-{i}",
                status=ApplicationStatus.SCORED,
                created_at=now,
                updated_at=now,
            )
            save_application(db, app)
            scored_apps.append((f"app-{i}", opp))

        results = await generate_assets_batch(
            db, profile, scored_apps,
            top_n=2,
            _model_override=model,
        )

        assert len(results) == 2
        items = list_pending_work_items(db)
        assert len(items) == 2

    async def test_respects_top_n(self, profile, db, tmp_path):
        model = TestModel()
        now = datetime.now()

        scored_apps = []
        for i in range(5):
            opp = Opportunity(
                id=f"opp-{i}",
                source="jobbank",
                company=f"Corp{i}",
                title=f"Role{i}",
                description=f"Description {i}",
                scraped_at=now,
            )
            save_opportunity(db, opp)

            app = Application(
                id=f"app-{i}",
                opportunity_id=f"opp-{i}",
                status=ApplicationStatus.SCORED,
                created_at=now,
                updated_at=now,
            )
            save_application(db, app)
            scored_apps.append((f"app-{i}", opp))

        results = await generate_assets_batch(
            db, profile, scored_apps,
            top_n=3,
            _model_override=model,
        )

        assert len(results) == 3
        items = list_pending_work_items(db)
        assert len(items) == 3

    async def test_empty_list_returns_empty(self, profile, db):
        results = await generate_assets_batch(
            db, profile, [],
            _model_override=TestModel(),
        )
        assert results == []
