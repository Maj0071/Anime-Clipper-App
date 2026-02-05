"""
Music Library API

Provides royalty-free music tracks with mood matching.
Auto-matches tracks to clip characteristics for perfect sync.
"""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import Optional, Dict, List
import logging

from app.database import get_db
from app.models import User, MusicTrack, Candidate, Video
from app.api.auth import get_current_user

logger = logging.getLogger(__name__)

router = APIRouter()


# ══════════════════════════════════════════════════════════════════════
#  REQUEST/RESPONSE MODELS
# ══════════════════════════════════════════════════════════════════════

class MusicTrackResponse(BaseModel):
    id: str
    title: str
    artist: Optional[str]
    duration: float
    file_url: str
    preview_url: Optional[str]
    mood: str
    energy: int
    genre: str
    bpm: Optional[int]
    uses: int
    license_type: str
    attribution: Optional[str]

    class Config:
        from_attributes = True


class MusicMatchRequest(BaseModel):
    candidate_id: str


class MusicMatchResponse(BaseModel):
    recommended: List[MusicTrackResponse]
    match_reasons: Dict[str, str]  # track_id -> reason


# ══════════════════════════════════════════════════════════════════════
#  BUILT-IN MUSIC LIBRARY (Placeholder tracks)
# ══════════════════════════════════════════════════════════════════════

# In production, these would be actual royalty-free tracks from a CDN
BUILT_IN_TRACKS = [
    # HYPE / ACTION tracks
    {
        'id': 'track_phonk_drift',
        'title': 'Midnight Drift',
        'artist': 'Anime Beats',
        'duration': 120.0,
        'mood': 'hype',
        'energy': 90,
        'genre': 'phonk',
        'bpm': 140,
        'uses': 45230,
    },
    {
        'id': 'track_phonk_shadow',
        'title': 'Shadow Monarch',
        'artist': 'Phonk Sensei',
        'duration': 95.0,
        'mood': 'hype',
        'energy': 95,
        'genre': 'phonk',
        'bpm': 145,
        'uses': 38920,
    },
    {
        'id': 'track_electronic_rush',
        'title': 'Adrenaline Rush',
        'artist': 'Synth Wave',
        'duration': 150.0,
        'mood': 'hype',
        'energy': 85,
        'genre': 'electronic',
        'bpm': 135,
        'uses': 29450,
    },

    # DARK / INTENSE tracks
    {
        'id': 'track_dark_awakening',
        'title': 'Dark Awakening',
        'artist': 'Void Echo',
        'duration': 110.0,
        'mood': 'dark',
        'energy': 80,
        'genre': 'phonk',
        'bpm': 130,
        'uses': 25670,
    },
    {
        'id': 'track_villain_theme',
        'title': 'Villain Theme',
        'artist': 'Anime OST',
        'duration': 180.0,
        'mood': 'dark',
        'energy': 70,
        'genre': 'orchestral',
        'bpm': 100,
        'uses': 18340,
    },

    # EMOTIONAL tracks
    {
        'id': 'track_emotional_rain',
        'title': 'Rain on Tokyo',
        'artist': 'Lofi Dreams',
        'duration': 200.0,
        'mood': 'emotional',
        'energy': 35,
        'genre': 'lofi',
        'bpm': 85,
        'uses': 32150,
    },
    {
        'id': 'track_piano_memories',
        'title': 'Memories',
        'artist': 'Piano Anime',
        'duration': 240.0,
        'mood': 'emotional',
        'energy': 30,
        'genre': 'orchestral',
        'bpm': 72,
        'uses': 28900,
    },
    {
        'id': 'track_emotional_farewell',
        'title': 'Farewell',
        'artist': 'String Ensemble',
        'duration': 190.0,
        'mood': 'emotional',
        'energy': 40,
        'genre': 'orchestral',
        'bpm': 80,
        'uses': 21450,
    },

    # EPIC tracks
    {
        'id': 'track_epic_battle',
        'title': 'Final Battle',
        'artist': 'Epic Orchestra',
        'duration': 210.0,
        'mood': 'epic',
        'energy': 85,
        'genre': 'orchestral',
        'bpm': 110,
        'uses': 41200,
    },
    {
        'id': 'track_epic_rise',
        'title': 'Hero\'s Rise',
        'artist': 'Cinematic Sounds',
        'duration': 165.0,
        'mood': 'epic',
        'energy': 90,
        'genre': 'orchestral',
        'bpm': 120,
        'uses': 35780,
    },

    # CHILL tracks
    {
        'id': 'track_lofi_sunset',
        'title': 'Sunset Drive',
        'artist': 'Lofi Beats',
        'duration': 180.0,
        'mood': 'chill',
        'energy': 40,
        'genre': 'lofi',
        'bpm': 90,
        'uses': 27650,
    },
    {
        'id': 'track_ambient_space',
        'title': 'Space Walk',
        'artist': 'Ambient Dreams',
        'duration': 220.0,
        'mood': 'chill',
        'energy': 25,
        'genre': 'electronic',
        'bpm': 75,
        'uses': 19340,
    },

    # K-POP inspired tracks
    {
        'id': 'track_kpop_energy',
        'title': 'Neon Lights',
        'artist': 'K-Pop Beats',
        'duration': 135.0,
        'mood': 'hype',
        'energy': 80,
        'genre': 'kpop',
        'bpm': 128,
        'uses': 33450,
    },
]


def _track_to_response(track: dict) -> dict:
    """Convert built-in track dict to response format."""
    return {
        'id': track['id'],
        'title': track['title'],
        'artist': track.get('artist', 'Unknown'),
        'duration': track['duration'],
        'file_url': f"/static/music/{track['id']}.mp3",  # Placeholder
        'preview_url': f"/static/music/{track['id']}_preview.mp3",  # Placeholder
        'mood': track['mood'],
        'energy': track['energy'],
        'genre': track['genre'],
        'bpm': track.get('bpm'),
        'uses': track['uses'],
        'license_type': 'royalty_free',
        'attribution': None,
    }


# ══════════════════════════════════════════════════════════════════════
#  API ENDPOINTS
# ══════════════════════════════════════════════════════════════════════

@router.get("", response_model=List[MusicTrackResponse])
async def list_tracks(
    mood: Optional[str] = None,
    genre: Optional[str] = None,
    min_energy: int = 0,
    max_energy: int = 100,
    min_bpm: Optional[int] = None,
    max_bpm: Optional[int] = None,
    sort_by: str = 'uses',  # 'uses', 'energy', 'bpm', 'duration'
    skip: int = 0,
    limit: int = 50,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    List available music tracks.

    - **mood**: Filter by mood (hype, dark, emotional, epic, chill)
    - **genre**: Filter by genre (phonk, electronic, orchestral, lofi, kpop)
    - **min_energy/max_energy**: Filter by energy level (0-100)
    - **min_bpm/max_bpm**: Filter by tempo
    - **sort_by**: Sort order
    """
    results = []

    # Filter built-in tracks
    for track in BUILT_IN_TRACKS:
        if mood and track['mood'] != mood:
            continue
        if genre and track['genre'] != genre:
            continue
        if track['energy'] < min_energy or track['energy'] > max_energy:
            continue
        if min_bpm and track.get('bpm', 0) < min_bpm:
            continue
        if max_bpm and track.get('bpm', 999) > max_bpm:
            continue

        results.append(_track_to_response(track))

    # Sort
    if sort_by == 'energy':
        results.sort(key=lambda x: x['energy'], reverse=True)
    elif sort_by == 'bpm':
        results.sort(key=lambda x: x['bpm'] or 0, reverse=True)
    elif sort_by == 'duration':
        results.sort(key=lambda x: x['duration'], reverse=True)
    else:  # uses
        results.sort(key=lambda x: x['uses'], reverse=True)

    # Also query database for user-uploaded tracks
    query = db.query(MusicTrack)

    if mood:
        query = query.filter(MusicTrack.mood == mood)
    if genre:
        query = query.filter(MusicTrack.genre == genre)
    query = query.filter(MusicTrack.energy >= min_energy, MusicTrack.energy <= max_energy)
    if min_bpm:
        query = query.filter(MusicTrack.bpm >= min_bpm)
    if max_bpm:
        query = query.filter(MusicTrack.bpm <= max_bpm)

    db_tracks = query.all()
    for track in db_tracks:
        results.append({
            'id': str(track.id),
            'title': track.title,
            'artist': track.artist,
            'duration': track.duration,
            'file_url': track.file_url,
            'preview_url': track.preview_url,
            'mood': track.mood,
            'energy': track.energy,
            'genre': track.genre,
            'bpm': track.bpm,
            'uses': track.uses,
            'license_type': track.license_type,
            'attribution': track.attribution,
        })

    # Paginate
    return results[skip:skip + limit]


@router.get("/moods")
async def list_moods(
    current_user: User = Depends(get_current_user)
):
    """Get available mood categories with descriptions."""
    return {
        'moods': [
            {'id': 'hype', 'name': 'Hype', 'description': 'High-energy action tracks', 'icon': 'zap'},
            {'id': 'dark', 'name': 'Dark', 'description': 'Intense villain/battle vibes', 'icon': 'moon'},
            {'id': 'emotional', 'name': 'Emotional', 'description': 'Sad/touching moments', 'icon': 'heart'},
            {'id': 'epic', 'name': 'Epic', 'description': 'Grand orchestral pieces', 'icon': 'crown'},
            {'id': 'chill', 'name': 'Chill', 'description': 'Relaxed lofi beats', 'icon': 'coffee'},
        ],
        'genres': [
            {'id': 'phonk', 'name': 'Phonk', 'description': 'Bass-heavy viral sound'},
            {'id': 'electronic', 'name': 'Electronic', 'description': 'Synth and EDM'},
            {'id': 'orchestral', 'name': 'Orchestral', 'description': 'Classical/cinematic'},
            {'id': 'lofi', 'name': 'Lo-Fi', 'description': 'Chill beats'},
            {'id': 'kpop', 'name': 'K-Pop', 'description': 'Korean pop style'},
        ]
    }


@router.get("/{track_id}", response_model=MusicTrackResponse)
async def get_track(
    track_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get a specific track by ID."""
    # Check built-in tracks
    for track in BUILT_IN_TRACKS:
        if track['id'] == track_id:
            return _track_to_response(track)

    # Check database
    track = db.query(MusicTrack).filter(MusicTrack.id == track_id).first()
    if not track:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Track not found"
        )

    return {
        'id': str(track.id),
        'title': track.title,
        'artist': track.artist,
        'duration': track.duration,
        'file_url': track.file_url,
        'preview_url': track.preview_url,
        'mood': track.mood,
        'energy': track.energy,
        'genre': track.genre,
        'bpm': track.bpm,
        'uses': track.uses,
        'license_type': track.license_type,
        'attribution': track.attribution,
    }


@router.post("/match", response_model=MusicMatchResponse)
async def match_music_to_clip(
    request: MusicMatchRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Auto-match music to a clip based on its characteristics.

    Analyzes the clip's action density, mood, and energy to recommend
    the best matching tracks from the library.
    """
    import os
    import glob as glob_mod

    # Get candidate
    candidate = db.query(Candidate).filter(Candidate.id == request.candidate_id).first()
    if not candidate:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Candidate not found"
        )

    # Get video
    video = db.query(Video).filter(
        Video.id == candidate.video_id,
        Video.user_id == current_user.id
    ).first()
    if not video:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied"
        )

    # Resolve video path
    video_path = None
    if video.src_url.startswith("file://"):
        local_src = video.src_url.replace("file://", "")
        if os.path.isfile(local_src):
            video_path = local_src
        else:
            matches = glob_mod.glob(f"/tmp/videos/{video.id}.*")
            if matches:
                video_path = matches[0]
    else:
        video_path = f"/tmp/videos/{video.id}.mp4"

    # Analyze clip characteristics
    clip_energy = 50  # Default
    clip_mood = 'hype'  # Default

    if video_path and os.path.exists(video_path):
        try:
            from app.services.virality_scorer import ViralityScorer

            scorer = ViralityScorer(video_path)
            result = scorer.calculate_score(candidate.start_s, candidate.end_s)

            # Map virality factors to music preferences
            action_score = result.factors.action_density
            audio_score = result.factors.audio_energy

            clip_energy = int((action_score + audio_score) / 2)

            # Determine mood based on factors
            if action_score >= 70:
                clip_mood = 'hype'
            elif action_score >= 50:
                clip_mood = 'epic'
            elif result.factors.color_vibrancy < 40:
                clip_mood = 'dark'
            elif audio_score < 40:
                clip_mood = 'emotional'
            else:
                clip_mood = 'chill'

        except Exception as e:
            logger.warning(f"Clip analysis failed, using defaults: {e}")

    # Find matching tracks
    recommended = []
    match_reasons = {}

    # Primary mood match
    mood_tracks = [t for t in BUILT_IN_TRACKS if t['mood'] == clip_mood]

    # Sort by energy proximity
    mood_tracks.sort(key=lambda t: abs(t['energy'] - clip_energy))

    for track in mood_tracks[:3]:
        response = _track_to_response(track)
        recommended.append(response)
        match_reasons[track['id']] = f"Perfect {clip_mood} mood match, energy {track['energy']}%"

    # Add high-use tracks from related moods
    related_moods = {
        'hype': ['epic', 'dark'],
        'epic': ['hype', 'emotional'],
        'dark': ['hype', 'epic'],
        'emotional': ['chill', 'epic'],
        'chill': ['emotional', 'lofi'],
    }

    for related_mood in related_moods.get(clip_mood, []):
        related_tracks = [t for t in BUILT_IN_TRACKS if t['mood'] == related_mood]
        related_tracks.sort(key=lambda t: t['uses'], reverse=True)
        for track in related_tracks[:1]:
            if track['id'] not in [r['id'] for r in recommended]:
                response = _track_to_response(track)
                recommended.append(response)
                match_reasons[track['id']] = f"Popular {related_mood} alternative"

    return {
        'recommended': recommended[:5],
        'match_reasons': match_reasons,
    }


@router.post("/{track_id}/use")
async def use_track(
    track_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Mark a track as used (increments use count)."""
    # Skip for built-in tracks
    for track in BUILT_IN_TRACKS:
        if track['id'] == track_id:
            return {'status': 'ok', 'uses': track['uses'] + 1}

    track = db.query(MusicTrack).filter(MusicTrack.id == track_id).first()
    if not track:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Track not found"
        )

    track.uses += 1
    db.commit()

    return {'status': 'ok', 'uses': track.uses}
