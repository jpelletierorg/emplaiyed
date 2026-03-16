"""Profile API endpoints — view, edit, build wizard steps, enhance."""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, Form, Request, UploadFile, File
from fastapi.responses import HTMLResponse, RedirectResponse

from emplaiyed.api.app import templates
from emplaiyed.api.deps import get_profile, get_profile_path, get_data_dir
from emplaiyed.core.models import Profile
from emplaiyed.core.profile_store import load_profile, save_profile
from emplaiyed.profile.gap_analyzer import analyze_gaps, GapReport

logger = logging.getLogger(__name__)

router = APIRouter()


# ---------------------------------------------------------------------------
# Session-like state for the wizard (in-memory, single user)
# ---------------------------------------------------------------------------

_wizard_state: dict[str, Any] = {}


def _reset_wizard() -> None:
    _wizard_state.clear()


# ---------------------------------------------------------------------------
# View / Edit
# ---------------------------------------------------------------------------


@router.get("/profile/edit")
async def profile_edit_page(
    request: Request,
    profile: Profile | None = Depends(get_profile),
):
    from emplaiyed.api.routes.pages import NAV_ITEMS

    if profile is None:
        return RedirectResponse("/profile/build", status_code=303)

    gap_report = analyze_gaps(profile)
    ctx = {
        "request": request,
        "nav_items": NAV_ITEMS,
        "active_page": "Profile",
        "profile": profile,
        "gap_report": gap_report,
    }
    return templates.TemplateResponse("profile_edit.html", ctx)


@router.post("/api/profile/save")
async def save_profile_form(
    request: Request,
    profile_path: Path = Depends(get_profile_path),
):
    """Save profile edits from the edit form."""
    form = await request.form()

    # Load existing profile as a base
    profile = load_profile(profile_path) if profile_path.exists() else None
    if profile is None:
        return RedirectResponse("/profile/build", status_code=303)

    # Update scalar fields
    data = profile.model_dump()
    data["name"] = form.get("name", profile.name)
    data["email"] = form.get("email", profile.email)
    data["phone"] = form.get("phone", profile.phone) or None
    data["linkedin"] = form.get("linkedin", profile.linkedin) or None
    data["github"] = form.get("github", profile.github) or None

    # Address
    if data.get("address") is None:
        data["address"] = {}
    data["address"]["city"] = form.get("address_city") or None
    data["address"]["province_state"] = form.get("address_province") or None
    data["address"]["country"] = form.get("address_country") or None

    # Skills (comma-separated)
    skills_raw = form.get("skills", "")
    if skills_raw:
        data["skills"] = [s.strip() for s in skills_raw.split(",") if s.strip()]

    # Aspirations
    if data.get("aspirations") is None:
        data["aspirations"] = {}
    asp = data["aspirations"]
    target_roles_raw = form.get("target_roles", "")
    if target_roles_raw:
        asp["target_roles"] = [
            r.strip() for r in target_roles_raw.split(",") if r.strip()
        ]
    work_arr_raw = form.get("work_arrangement", "")
    if work_arr_raw:
        asp["work_arrangement"] = [
            w.strip() for w in work_arr_raw.split(",") if w.strip()
        ]
    geo_raw = form.get("geographic_preferences", "")
    if geo_raw:
        asp["geographic_preferences"] = [
            g.strip() for g in geo_raw.split(",") if g.strip()
        ]

    salary_min = form.get("salary_minimum")
    if salary_min:
        try:
            asp["salary_minimum"] = int(salary_min)
        except ValueError:
            pass
    salary_target = form.get("salary_target")
    if salary_target:
        try:
            asp["salary_target"] = int(salary_target)
        except ValueError:
            pass

    asp["urgency"] = form.get("urgency") or None
    asp["statement"] = form.get("statement") or None

    updated = Profile.model_validate(data)
    save_profile(updated, profile_path)

    return RedirectResponse("/profile", status_code=303)


# ---------------------------------------------------------------------------
# Build Wizard
# ---------------------------------------------------------------------------


@router.get("/profile/build")
async def wizard_start(
    request: Request,
    profile: Profile | None = Depends(get_profile),
):
    """Wizard step 1: Upload CV or start fresh."""
    from emplaiyed.api.routes.pages import NAV_ITEMS

    _reset_wizard()
    if profile:
        _wizard_state["existing_profile"] = profile

    ctx = {
        "request": request,
        "nav_items": NAV_ITEMS,
        "active_page": "Profile",
        "has_existing": profile is not None,
    }
    return templates.TemplateResponse("wizard/step1_upload.html", ctx)


@router.post("/api/profile/build/upload")
async def wizard_upload_cv(
    request: Request,
    cv_file: UploadFile | None = File(None),
    cv_text: str = Form(""),
):
    """Process CV upload (file or pasted text), parse with LLM, show extraction."""
    from emplaiyed.api.routes.pages import NAV_ITEMS
    from emplaiyed.profile.cv_parser import parse_cv_text, extract_text
    from emplaiyed.profile.builder import _merge_profiles, format_profile_summary

    profile: Profile | None = _wizard_state.get("existing_profile")
    error: str | None = None

    raw_text = ""
    if cv_file and cv_file.filename:
        # Save uploaded file temporarily
        data_dir = get_data_dir()
        uploads_dir = data_dir / "uploads"
        uploads_dir.mkdir(parents=True, exist_ok=True)
        tmp_path = uploads_dir / cv_file.filename
        content = await cv_file.read()
        tmp_path.write_bytes(content)
        try:
            raw_text = extract_text(tmp_path)
        except Exception as e:
            error = f"Could not extract text from file: {e}"
        finally:
            tmp_path.unlink(missing_ok=True)
    elif cv_text.strip():
        raw_text = cv_text.strip()

    if raw_text and not error:
        try:
            parsed = await parse_cv_text(raw_text)
            if profile:
                profile = _merge_profiles(profile, parsed)
            else:
                profile = parsed
            _wizard_state["profile"] = profile
            _wizard_state["cv_parsed"] = True
        except Exception as e:
            error = f"LLM parsing failed: {e}"
            logger.exception("CV parse error")

    if error or not raw_text:
        # Either error or user chose "start fresh"
        if not error and not raw_text:
            # Start fresh — no CV
            _wizard_state["cv_parsed"] = False
            ctx = {
                "request": request,
                "nav_items": NAV_ITEMS,
                "active_page": "Profile",
            }
            return templates.TemplateResponse("wizard/step2_basics.html", ctx)

        # Error case — show step 1 again with error
        ctx = {
            "request": request,
            "nav_items": NAV_ITEMS,
            "active_page": "Profile",
            "has_existing": _wizard_state.get("existing_profile") is not None,
            "error": error,
        }
        return templates.TemplateResponse("wizard/step1_upload.html", ctx)

    # Show extraction review
    ctx = {
        "request": request,
        "nav_items": NAV_ITEMS,
        "active_page": "Profile",
        "profile": profile,
        "summary": format_profile_summary(profile),
    }
    return templates.TemplateResponse("wizard/step3_review.html", ctx)


@router.post("/api/profile/build/basics")
async def wizard_basics(
    request: Request,
    name: str = Form(...),
    email: str = Form(...),
):
    """Step 2 (fresh start): Collect basic info and proceed to gaps."""
    from emplaiyed.api.routes.pages import NAV_ITEMS

    profile = Profile(name=name.strip(), email=email.strip())
    _wizard_state["profile"] = profile
    _wizard_state["cv_parsed"] = False

    return RedirectResponse("/profile/build/gaps", status_code=303)


@router.post("/api/profile/build/correct")
async def wizard_correct(
    request: Request,
    corrections: str = Form(""),
):
    """Apply free-text corrections to the parsed profile."""
    from emplaiyed.api.routes.pages import NAV_ITEMS
    from emplaiyed.profile.builder import _apply_corrections

    profile = _wizard_state.get("profile")
    if profile is None:
        return RedirectResponse("/profile/build", status_code=303)

    if corrections.strip() and corrections.strip().lower() not in ("no", "n", "none"):
        try:
            profile = await _apply_corrections(profile, corrections)
            _wizard_state["profile"] = profile
        except Exception as e:
            logger.exception("Correction failed")

    return RedirectResponse("/profile/build/gaps", status_code=303)


@router.get("/profile/build/gaps")
async def wizard_gaps_page(request: Request):
    """Step 4: Show gap-filling form."""
    from emplaiyed.api.routes.pages import NAV_ITEMS
    from emplaiyed.profile.builder import _GROUP_PROMPTS, _group_questions

    profile = _wizard_state.get("profile")
    if profile is None:
        return RedirectResponse("/profile/build", status_code=303)

    gap_report = analyze_gaps(profile)
    groups = _group_questions(gap_report)

    # Build display data for the template
    question_groups = []
    for group_name, fields in groups:
        question = _GROUP_PROMPTS.get(group_name, f"Tell me about: {', '.join(fields)}")
        question_groups.append(
            {
                "name": group_name,
                "fields": fields,
                "question": question,
            }
        )

    ctx = {
        "request": request,
        "nav_items": NAV_ITEMS,
        "active_page": "Profile",
        "profile": profile,
        "question_groups": question_groups,
        "has_gaps": len(question_groups) > 0,
    }
    return templates.TemplateResponse("wizard/step4_gaps.html", ctx)


@router.post("/api/profile/build/gaps")
async def wizard_fill_gaps(request: Request):
    """Process gap-filling answers and save the profile."""
    from emplaiyed.profile.builder import _parse_answer

    profile = _wizard_state.get("profile")
    if profile is None:
        return RedirectResponse("/profile/build", status_code=303)

    form = await request.form()

    # Process each group answer
    for key in form:
        if key.startswith("group_"):
            group_name = key[6:]  # strip "group_"
            answer = form[key]
            if (
                isinstance(answer, str)
                and answer.strip()
                and answer.strip().lower() not in ("skip", "none")
            ):
                # Get the fields for this group
                fields_key = f"fields_{group_name}"
                fields_raw = form.get(fields_key, "")
                if isinstance(fields_raw, str) and fields_raw:
                    fields = fields_raw.split(",")
                    try:
                        profile = await _parse_answer(profile, fields, answer)
                    except Exception:
                        logger.exception("Failed to parse answer for %s", group_name)

    # Save
    profile_path = get_profile_path()
    save_profile(profile, profile_path)
    _wizard_state["profile"] = profile
    _reset_wizard()

    return RedirectResponse("/profile", status_code=303)


# ---------------------------------------------------------------------------
# Enhance highlights
# ---------------------------------------------------------------------------


@router.get("/profile/enhance")
async def enhance_page(
    request: Request,
    profile: Profile | None = Depends(get_profile),
):
    """Show highlights quality analysis and enhancement UI."""
    from emplaiyed.api.routes.pages import NAV_ITEMS
    from emplaiyed.profile.quality_analyzer import analyze_highlight_quality

    if profile is None:
        return RedirectResponse("/profile/build", status_code=303)

    quality_report = analyze_highlight_quality(profile)
    roles_to_enrich = [hq for hq in quality_report if hq.weak_highlights]

    enrichment_data = []
    for hq in roles_to_enrich:
        emp = profile.employment_history[hq.employment_index]
        weak_texts = [emp.highlights[i] for i in hq.weak_highlights]
        enrichment_data.append(
            {
                "index": hq.employment_index,
                "company": emp.company,
                "title": emp.title,
                "weak_highlights": weak_texts,
                "all_highlights": emp.highlights,
            }
        )

    ctx = {
        "request": request,
        "nav_items": NAV_ITEMS,
        "active_page": "Profile",
        "profile": profile,
        "roles_to_enrich": enrichment_data,
        "all_strong": len(enrichment_data) == 0,
    }
    return templates.TemplateResponse("profile_enhance.html", ctx)


@router.post("/api/profile/enhance/{employment_index}")
async def enhance_role(
    request: Request,
    employment_index: int,
    context: str = Form(...),
    profile_path: Path = Depends(get_profile_path),
):
    """Rewrite highlights for a single role using user-provided context."""
    from emplaiyed.api.routes.pages import NAV_ITEMS
    from emplaiyed.profile.enricher import _rewrite_highlights

    profile = load_profile(profile_path)
    if employment_index >= len(profile.employment_history):
        return RedirectResponse("/profile/enhance", status_code=303)

    emp = profile.employment_history[employment_index]

    try:
        rewritten = await _rewrite_highlights(
            company=emp.company,
            title=emp.title,
            highlights=emp.highlights,
            user_context=context,
        )
    except Exception:
        logger.exception("Highlight rewrite failed")
        return RedirectResponse("/profile/enhance", status_code=303)

    # Return a partial with the rewritten highlights for review
    ctx = {
        "request": request,
        "employment_index": employment_index,
        "company": emp.company,
        "title": emp.title,
        "original": emp.highlights,
        "rewritten": rewritten,
    }
    return templates.TemplateResponse("partials/enhance_review.html", ctx)


@router.post("/api/profile/enhance/{employment_index}/accept")
async def accept_enhancement(
    employment_index: int,
    profile_path: Path = Depends(get_profile_path),
    request: Request = None,
):
    """Accept rewritten highlights and save."""
    form = await request.form()
    highlights_raw = form.getlist("highlight")
    highlights = [h for h in highlights_raw if isinstance(h, str) and h.strip()]

    if not highlights:
        return RedirectResponse("/profile/enhance", status_code=303)

    profile = load_profile(profile_path)
    if employment_index < len(profile.employment_history):
        profile.employment_history[employment_index].highlights = highlights
        save_profile(profile, profile_path)

    return RedirectResponse("/profile/enhance", status_code=303)
