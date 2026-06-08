"""Project endpoints: group templates and define shared, inheritable metadata.

A project is owner-scoped (same model as templates). A template belongs to at
most one project (a nullable ``project_id`` FK). The project's free-form metadata
is inherited by its templates at generation time (see services/generation.py).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ...db.models import Project, Template
from ..auth import CurrentUser, get_current_user
from ..deps import get_db
from ..schemas import ProjectCreate, ProjectUpdate
from ..serializers import project_detail_dto, project_dto, template_dto

router = APIRouter(tags=["projects"])


def _get_project(db: Session, project_id: str, user: CurrentUser) -> Project:
    p = db.get(Project, project_id)
    # Same no-leak 404 as templates: someone else's (or unowned) project reads as missing.
    if p is None or p.owner_id != user.id:
        raise HTTPException(status_code=404, detail="project not found")
    return p


def _owned_template(db: Session, template_id: str, user: CurrentUser) -> Template:
    t = db.get(Template, template_id)
    if t is None or t.owner_id != user.id:
        raise HTTPException(status_code=404, detail="template not found")
    return t


@router.post("/projects", status_code=201)
def create_project(
    req: ProjectCreate,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
) -> dict:
    name = (req.name or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="project name is required")
    p = Project(
        name=name,
        description=(req.description or None),
        meta={str(k): str(v) for k, v in (req.metadata or {}).items()},
        owner_id=user.id,
    )
    db.add(p)
    db.commit()
    db.refresh(p)
    return project_dto(p)


@router.get("/projects")
def list_projects(
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
) -> list[dict]:
    rows = (
        db.query(Project)
        .filter(Project.owner_id == user.id)
        .order_by(Project.created_at.desc())
        .all()
    )
    return [project_dto(p) for p in rows]


@router.get("/projects/{project_id}")
def get_project(
    project_id: str,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
) -> dict:
    p = _get_project(db, project_id, user)
    templates = (
        db.query(Template)
        .filter(Template.project_id == project_id, Template.owner_id == user.id)
        .order_by(Template.created_at.desc())
        .all()
    )
    return project_detail_dto(p, templates)


@router.patch("/projects/{project_id}")
def update_project(
    project_id: str,
    req: ProjectUpdate,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
) -> dict:
    p = _get_project(db, project_id, user)
    if req.name is not None and req.name.strip():
        p.name = req.name.strip()
    if req.description is not None:
        p.description = req.description.strip() or None
    if req.metadata is not None:
        # Full replace with a fresh dict (the JSON column isn't a MutableDict, so
        # in-place mutation wouldn't be flagged dirty).
        p.meta = {str(k): str(v) for k, v in req.metadata.items()}
    db.commit()
    db.refresh(p)
    return project_dto(p)


@router.delete("/projects/{project_id}", status_code=204)
def delete_project(
    project_id: str,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
) -> None:
    p = _get_project(db, project_id, user)
    # Unassign the project's templates — never delete them (they own versions,
    # packages and generation history and are independently valuable).
    db.query(Template).filter_by(project_id=project_id, owner_id=user.id).update(
        {Template.project_id: None}
    )
    db.delete(p)
    db.commit()


@router.post("/projects/{project_id}/templates/{template_id}")
def assign_template(
    project_id: str,
    template_id: str,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
) -> dict:
    """Assign a template to this project (re-pointing the single FK = at most one)."""
    _get_project(db, project_id, user)
    t = _owned_template(db, template_id, user)
    t.project_id = project_id
    db.commit()
    db.refresh(t)
    return template_dto(t)


@router.delete("/projects/{project_id}/templates/{template_id}", status_code=204)
def unassign_template(
    project_id: str,
    template_id: str,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
) -> None:
    _get_project(db, project_id, user)
    t = _owned_template(db, template_id, user)
    if t.project_id != project_id:
        raise HTTPException(status_code=404, detail="template not in this project")
    t.project_id = None
    db.commit()
