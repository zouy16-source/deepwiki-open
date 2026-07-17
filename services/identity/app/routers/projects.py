import json

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import Project
from ..schemas import ProjectCreate, ProjectOut, ProjectUpdate

router = APIRouter()


@router.post("", response_model=ProjectOut, status_code=201)
def create_project(body: ProjectCreate, db: Session = Depends(get_db)):
    if db.scalar(select(Project).where(Project.code == body.code)):
        raise HTTPException(409, f"project code '{body.code}' already exists")
    data = body.model_dump()
    data["repos"] = json.dumps(data.get("repos") or [], ensure_ascii=False)
    data["repo_meta"] = json.dumps(data.get("repo_meta") or {}, ensure_ascii=False)
    project = Project(**data)
    db.add(project)
    db.commit()
    db.refresh(project)
    return project


@router.patch("/{project_id}", response_model=ProjectOut)
def update_project(project_id: int, body: ProjectUpdate, db: Session = Depends(get_db)):
    project = db.get(Project, project_id)
    if project is None:
        raise HTTPException(404, "project not found")
    if body.name is not None:
        project.name = body.name
    if body.description is not None:
        project.description = body.description
    if body.repos is not None:
        project.repos = json.dumps(body.repos, ensure_ascii=False)
    if body.repo_meta is not None:
        project.repo_meta = json.dumps(
            {k: v.model_dump() for k, v in body.repo_meta.items()}, ensure_ascii=False
        )
    if body.tapd_workspace_id is not None:
        project.tapd_workspace_id = body.tapd_workspace_id
    db.commit()
    db.refresh(project)
    return project


@router.get("", response_model=list[ProjectOut])
def list_projects(db: Session = Depends(get_db)):
    return db.scalars(select(Project).order_by(Project.id)).all()


@router.get("/{project_id}", response_model=ProjectOut)
def get_project(project_id: int, db: Session = Depends(get_db)):
    project = db.get(Project, project_id)
    if project is None:
        raise HTTPException(404, "project not found")
    return project
