"""
Template Marketplace API

Allows users to save, share, and load custom editing presets.
"""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import Optional, Dict, List
import logging

from app.database import get_db
from app.models import User, EditTemplate
from app.api.auth import get_current_user

logger = logging.getLogger(__name__)

router = APIRouter()


# ══════════════════════════════════════════════════════════════════════
#  REQUEST/RESPONSE MODELS
# ══════════════════════════════════════════════════════════════════════

class TemplateSettings(BaseModel):
    """All the settings that make up a template."""
    base_template: str = 'viral_anime'
    enable_beat_sync: bool = False
    effect_intensity: str = 'medium'
    enable_smart_reframe: bool = True
    caption_style: str = 'pop'
    hook_style: str = 'bold'
    reorder_for_hook: bool = False
    # Advanced settings
    saturation: Optional[float] = None
    contrast: Optional[float] = None
    shake_intensity: Optional[int] = None
    flash_enabled: Optional[bool] = None
    transition_type: Optional[str] = None


class CreateTemplateRequest(BaseModel):
    name: str
    description: Optional[str] = None
    category: str = 'custom'
    settings: TemplateSettings
    is_public: bool = False


class UpdateTemplateRequest(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    category: Optional[str] = None
    settings: Optional[TemplateSettings] = None
    is_public: Optional[bool] = None


class TemplateResponse(BaseModel):
    id: str
    user_id: Optional[str]
    name: str
    description: Optional[str]
    category: str
    settings: Dict
    is_public: bool
    downloads: int
    likes: int
    preview_url: Optional[str]
    thumbnail_url: Optional[str]
    created_at: str
    is_owner: bool

    class Config:
        from_attributes = True


# ══════════════════════════════════════════════════════════════════════
#  SYSTEM TEMPLATES (Built-in presets)
# ══════════════════════════════════════════════════════════════════════

SYSTEM_TEMPLATES = [
    {
        'id': 'sys_tiktok_viral',
        'name': 'TikTok Viral',
        'description': 'Optimized for maximum TikTok engagement. Beat sync + white flash + shake.',
        'category': 'velocity',
        'settings': {
            'base_template': 'viral_anime',
            'enable_beat_sync': True,
            'effect_intensity': 'high',
            'enable_smart_reframe': True,
            'caption_style': 'pop',
            'hook_style': 'bold',
            'reorder_for_hook': True,
        },
        'downloads': 15420,
        'likes': 3210,
    },
    {
        'id': 'sys_phonk_edit',
        'name': 'Phonk Edit',
        'description': 'Dark aggressive style with extreme speed ramps and heavy bass.',
        'category': 'velocity',
        'settings': {
            'base_template': 'anime_hype',
            'enable_beat_sync': True,
            'effect_intensity': 'high',
            'enable_smart_reframe': True,
            'caption_style': 'glow',
            'hook_style': 'glitch',
            'reorder_for_hook': False,
        },
        'downloads': 12350,
        'likes': 2890,
    },
    {
        'id': 'sys_amv_cinematic',
        'name': 'AMV Cinematic',
        'description': 'Film-quality look with letterbox, grain, and elegant fades.',
        'category': 'cinematic',
        'settings': {
            'base_template': 'cinematic',
            'enable_beat_sync': False,
            'effect_intensity': 'medium',
            'enable_smart_reframe': True,
            'caption_style': 'highlight',
            'hook_style': 'bold',
            'reorder_for_hook': False,
        },
        'downloads': 8920,
        'likes': 2150,
    },
    {
        'id': 'sys_aesthetic_flow',
        'name': 'Aesthetic Flow',
        'description': 'Dreamy smooth edits with warm colors and gentle transitions.',
        'category': 'flow',
        'settings': {
            'base_template': 'clean_flow',
            'enable_beat_sync': False,
            'effect_intensity': 'low',
            'enable_smart_reframe': True,
            'caption_style': 'bounce',
            'hook_style': 'bold',
            'reorder_for_hook': False,
        },
        'downloads': 7650,
        'likes': 1890,
    },
    {
        'id': 'sys_cyberpunk_glitch',
        'name': 'Cyberpunk Glitch',
        'description': 'Neon-drenched chaos with RGB splits and digital artifacts.',
        'category': 'glitch',
        'settings': {
            'base_template': 'glitch',
            'enable_beat_sync': True,
            'effect_intensity': 'high',
            'enable_smart_reframe': False,
            'caption_style': 'glow',
            'hook_style': 'glitch',
            'reorder_for_hook': True,
        },
        'downloads': 6230,
        'likes': 1540,
    },
]


# ══════════════════════════════════════════════════════════════════════
#  API ENDPOINTS
# ══════════════════════════════════════════════════════════════════════

@router.get("", response_model=List[TemplateResponse])
async def list_templates(
    category: Optional[str] = None,
    include_system: bool = True,
    include_public: bool = True,
    include_mine: bool = True,
    sort_by: str = 'downloads',  # 'downloads', 'likes', 'created_at'
    skip: int = 0,
    limit: int = 50,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    List available templates.

    - **category**: Filter by category (velocity, flow, cinematic, glitch, custom)
    - **include_system**: Include built-in system templates
    - **include_public**: Include community public templates
    - **include_mine**: Include user's own templates
    - **sort_by**: Sort order (downloads, likes, created_at)
    """
    results = []

    # Add system templates
    if include_system:
        for sys_tmpl in SYSTEM_TEMPLATES:
            if category and sys_tmpl['category'] != category:
                continue
            results.append({
                'id': sys_tmpl['id'],
                'user_id': None,
                'name': sys_tmpl['name'],
                'description': sys_tmpl['description'],
                'category': sys_tmpl['category'],
                'settings': sys_tmpl['settings'],
                'is_public': True,
                'downloads': sys_tmpl['downloads'],
                'likes': sys_tmpl['likes'],
                'preview_url': None,
                'thumbnail_url': None,
                'created_at': '2025-01-01T00:00:00',
                'is_owner': False,
            })

    # Query user templates
    query = db.query(EditTemplate)

    # Filter conditions
    conditions = []
    if include_mine:
        conditions.append(EditTemplate.user_id == str(current_user.id))
    if include_public:
        conditions.append(EditTemplate.is_public == 1)

    if conditions:
        from sqlalchemy import or_
        query = query.filter(or_(*conditions))

    if category:
        query = query.filter(EditTemplate.category == category)

    # Sort
    if sort_by == 'likes':
        query = query.order_by(EditTemplate.likes.desc())
    elif sort_by == 'created_at':
        query = query.order_by(EditTemplate.created_at.desc())
    else:
        query = query.order_by(EditTemplate.downloads.desc())

    templates = query.offset(skip).limit(limit).all()

    for tmpl in templates:
        results.append({
            'id': str(tmpl.id),
            'user_id': str(tmpl.user_id) if tmpl.user_id else None,
            'name': tmpl.name,
            'description': tmpl.description,
            'category': tmpl.category,
            'settings': tmpl.settings or {},
            'is_public': tmpl.is_public == 1,
            'downloads': tmpl.downloads,
            'likes': tmpl.likes,
            'preview_url': tmpl.preview_url,
            'thumbnail_url': tmpl.thumbnail_url,
            'created_at': tmpl.created_at.isoformat() if tmpl.created_at else '',
            'is_owner': str(tmpl.user_id) == str(current_user.id) if tmpl.user_id else False,
        })

    return results


@router.get("/{template_id}", response_model=TemplateResponse)
async def get_template(
    template_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get a specific template by ID."""
    # Check system templates first
    for sys_tmpl in SYSTEM_TEMPLATES:
        if sys_tmpl['id'] == template_id:
            return {
                'id': sys_tmpl['id'],
                'user_id': None,
                'name': sys_tmpl['name'],
                'description': sys_tmpl['description'],
                'category': sys_tmpl['category'],
                'settings': sys_tmpl['settings'],
                'is_public': True,
                'downloads': sys_tmpl['downloads'],
                'likes': sys_tmpl['likes'],
                'preview_url': None,
                'thumbnail_url': None,
                'created_at': '2025-01-01T00:00:00',
                'is_owner': False,
            }

    # Query database
    template = db.query(EditTemplate).filter(EditTemplate.id == template_id).first()

    if not template:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Template not found"
        )

    # Check access
    if template.is_public != 1 and str(template.user_id) != str(current_user.id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied"
        )

    return {
        'id': str(template.id),
        'user_id': str(template.user_id) if template.user_id else None,
        'name': template.name,
        'description': template.description,
        'category': template.category,
        'settings': template.settings or {},
        'is_public': template.is_public == 1,
        'downloads': template.downloads,
        'likes': template.likes,
        'preview_url': template.preview_url,
        'thumbnail_url': template.thumbnail_url,
        'created_at': template.created_at.isoformat() if template.created_at else '',
        'is_owner': str(template.user_id) == str(current_user.id) if template.user_id else False,
    }


@router.post("", response_model=TemplateResponse, status_code=status.HTTP_201_CREATED)
async def create_template(
    request: CreateTemplateRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Create a new custom template.

    Save your current editing settings as a reusable preset.
    """
    template = EditTemplate(
        user_id=str(current_user.id),
        name=request.name,
        description=request.description,
        category=request.category,
        settings=request.settings.dict() if request.settings else {},
        is_public=1 if request.is_public else 0,
    )

    db.add(template)
    db.commit()
    db.refresh(template)

    return {
        'id': str(template.id),
        'user_id': str(template.user_id),
        'name': template.name,
        'description': template.description,
        'category': template.category,
        'settings': template.settings or {},
        'is_public': template.is_public == 1,
        'downloads': 0,
        'likes': 0,
        'preview_url': None,
        'thumbnail_url': None,
        'created_at': template.created_at.isoformat() if template.created_at else '',
        'is_owner': True,
    }


@router.patch("/{template_id}", response_model=TemplateResponse)
async def update_template(
    template_id: str,
    request: UpdateTemplateRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Update an existing template."""
    template = db.query(EditTemplate).filter(EditTemplate.id == template_id).first()

    if not template:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Template not found"
        )

    if str(template.user_id) != str(current_user.id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Cannot edit templates you don't own"
        )

    if request.name is not None:
        template.name = request.name
    if request.description is not None:
        template.description = request.description
    if request.category is not None:
        template.category = request.category
    if request.settings is not None:
        template.settings = request.settings.dict()
    if request.is_public is not None:
        template.is_public = 1 if request.is_public else 0

    db.commit()
    db.refresh(template)

    return {
        'id': str(template.id),
        'user_id': str(template.user_id),
        'name': template.name,
        'description': template.description,
        'category': template.category,
        'settings': template.settings or {},
        'is_public': template.is_public == 1,
        'downloads': template.downloads,
        'likes': template.likes,
        'preview_url': template.preview_url,
        'thumbnail_url': template.thumbnail_url,
        'created_at': template.created_at.isoformat() if template.created_at else '',
        'is_owner': True,
    }


@router.delete("/{template_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_template(
    template_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Delete a template."""
    template = db.query(EditTemplate).filter(EditTemplate.id == template_id).first()

    if not template:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Template not found"
        )

    if str(template.user_id) != str(current_user.id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Cannot delete templates you don't own"
        )

    db.delete(template)
    db.commit()
    return None


@router.post("/{template_id}/use")
async def use_template(
    template_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Mark a template as used (increments download count).

    Call this when applying a template to track popularity.
    """
    # Skip for system templates (just return success)
    for sys_tmpl in SYSTEM_TEMPLATES:
        if sys_tmpl['id'] == template_id:
            return {'status': 'ok', 'downloads': sys_tmpl['downloads'] + 1}

    template = db.query(EditTemplate).filter(EditTemplate.id == template_id).first()

    if not template:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Template not found"
        )

    template.downloads += 1
    db.commit()

    return {'status': 'ok', 'downloads': template.downloads}


@router.post("/{template_id}/like")
async def like_template(
    template_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Like a template."""
    # Skip for system templates
    for sys_tmpl in SYSTEM_TEMPLATES:
        if sys_tmpl['id'] == template_id:
            return {'status': 'ok', 'likes': sys_tmpl['likes'] + 1}

    template = db.query(EditTemplate).filter(EditTemplate.id == template_id).first()

    if not template:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Template not found"
        )

    template.likes += 1
    db.commit()

    return {'status': 'ok', 'likes': template.likes}
