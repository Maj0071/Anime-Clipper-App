'use client';

import { useState, useEffect } from 'react';
import { Music, Play, Pause, Zap, Moon, Heart, Crown, Coffee, Loader2, Wand2 } from 'lucide-react';

interface MusicTrack {
  id: string;
  title: string;
  artist: string;
  duration: number;
  file_url: string;
  preview_url: string;
  mood: string;
  energy: number;
  genre: string;
  bpm: number | null;
  uses: number;
}

interface MusicLibraryProps {
  onSelectTrack: (track: MusicTrack) => void;
  candidateId?: string;  // For auto-matching
}

const MOOD_ICONS: Record<string, React.ReactNode> = {
  hype: <Zap className="w-4 h-4" />,
  dark: <Moon className="w-4 h-4" />,
  emotional: <Heart className="w-4 h-4" />,
  epic: <Crown className="w-4 h-4" />,
  chill: <Coffee className="w-4 h-4" />,
};

const MOOD_COLORS: Record<string, string> = {
  hype: 'bg-red-100 text-red-600',
  dark: 'bg-purple-100 text-purple-600',
  emotional: 'bg-pink-100 text-pink-600',
  epic: 'bg-amber-100 text-amber-600',
  chill: 'bg-blue-100 text-blue-600',
};

export default function MusicLibrary({ onSelectTrack, candidateId }: MusicLibraryProps) {
  const [tracks, setTracks] = useState<MusicTrack[]>([]);
  const [loading, setLoading] = useState(true);
  const [mood, setMood] = useState<string | null>(null);
  const [playingId, setPlayingId] = useState<string | null>(null);
  const [audio, setAudio] = useState<HTMLAudioElement | null>(null);
  const [matchedTracks, setMatchedTracks] = useState<MusicTrack[]>([]);
  const [matching, setMatching] = useState(false);

  const getHeaders = (): Record<string, string> => {
    const h: Record<string, string> = {};
    if (typeof localStorage !== 'undefined' && localStorage.getItem('token')) {
      h['Authorization'] = `Bearer ${localStorage.getItem('token')}`;
    }
    return h;
  };

  useEffect(() => {
    fetchTracks();
  }, [mood]);

  useEffect(() => {
    return () => {
      if (audio) {
        audio.pause();
      }
    };
  }, [audio]);

  const fetchTracks = async () => {
    setLoading(true);
    try {
      const params = new URLSearchParams();
      if (mood) params.append('mood', mood);
      params.append('sort_by', 'uses');

      const res = await fetch(`/api/music?${params}`, { headers: getHeaders() });
      if (res.ok) {
        const data = await res.json();
        setTracks(data);
      }
    } catch (e) {
      console.error('Failed to fetch tracks:', e);
    }
    setLoading(false);
  };

  const handleAutoMatch = async () => {
    if (!candidateId) return;

    setMatching(true);
    try {
      const res = await fetch('/api/music/match', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...getHeaders() },
        body: JSON.stringify({ candidate_id: candidateId }),
      });

      if (res.ok) {
        const data = await res.json();
        setMatchedTracks(data.recommended);
      }
    } catch (e) {
      console.error('Failed to match music:', e);
    }
    setMatching(false);
  };

  const togglePlay = (track: MusicTrack) => {
    if (playingId === track.id) {
      audio?.pause();
      setPlayingId(null);
    } else {
      if (audio) {
        audio.pause();
      }
      const newAudio = new Audio(track.preview_url || track.file_url);
      newAudio.play();
      newAudio.onended = () => setPlayingId(null);
      setAudio(newAudio);
      setPlayingId(track.id);
    }
  };

  const handleSelectTrack = async (track: MusicTrack) => {
    // Track usage
    try {
      await fetch(`/api/music/${track.id}/use`, {
        method: 'POST',
        headers: getHeaders(),
      });
    } catch (e) {
      // Ignore tracking errors
    }

    onSelectTrack(track);
  };

  const formatDuration = (seconds: number) => {
    const mins = Math.floor(seconds / 60);
    const secs = Math.floor(seconds % 60);
    return `${mins}:${secs.toString().padStart(2, '0')}`;
  };

  const formatNumber = (n: number) => {
    if (n >= 1000) return `${(n / 1000).toFixed(1)}k`;
    return n.toString();
  };

  const displayTracks = matchedTracks.length > 0 ? matchedTracks : tracks;

  return (
    <div className="bg-white rounded-xl shadow-lg p-6">
      {/* Header */}
      <div className="flex items-center justify-between mb-6">
        <div className="flex items-center gap-3">
          <div className="bg-gradient-to-r from-green-500 to-emerald-600 p-3 rounded-xl">
            <Music className="w-6 h-6 text-white" />
          </div>
          <div>
            <h2 className="text-xl font-bold text-gray-900">Music Library</h2>
            <p className="text-sm text-gray-500">Royalty-free tracks for your clips</p>
          </div>
        </div>

        {candidateId && (
          <button
            onClick={handleAutoMatch}
            disabled={matching}
            className="flex items-center gap-2 px-4 py-2 bg-green-100 text-green-700 rounded-lg hover:bg-green-200 transition-colors disabled:opacity-50"
          >
            {matching ? (
              <Loader2 className="w-4 h-4 animate-spin" />
            ) : (
              <Wand2 className="w-4 h-4" />
            )}
            Auto-Match Music
          </button>
        )}
      </div>

      {/* Matched tracks banner */}
      {matchedTracks.length > 0 && (
        <div className="mb-4 p-3 bg-green-50 border border-green-200 rounded-lg flex items-center justify-between">
          <span className="text-sm text-green-700">
            Showing {matchedTracks.length} recommended tracks for your clip
          </span>
          <button
            onClick={() => setMatchedTracks([])}
            className="text-xs text-green-600 hover:underline"
          >
            Show all
          </button>
        </div>
      )}

      {/* Mood Filter */}
      <div className="flex gap-2 mb-6 flex-wrap">
        <button
          onClick={() => setMood(null)}
          className={`px-3 py-2 rounded-lg text-sm font-medium transition-colors ${
            mood === null
              ? 'bg-gray-800 text-white'
              : 'bg-gray-100 text-gray-600 hover:bg-gray-200'
          }`}
        >
          All
        </button>
        {['hype', 'dark', 'emotional', 'epic', 'chill'].map(m => (
          <button
            key={m}
            onClick={() => setMood(m)}
            className={`flex items-center gap-1.5 px-3 py-2 rounded-lg text-sm font-medium transition-colors ${
              mood === m
                ? MOOD_COLORS[m].replace('100', '500').replace('600', 'white bg')
                : `${MOOD_COLORS[m]} hover:opacity-80`
            }`}
          >
            {MOOD_ICONS[m]}
            {m.charAt(0).toUpperCase() + m.slice(1)}
          </button>
        ))}
      </div>

      {/* Track List */}
      {loading ? (
        <div className="flex items-center justify-center py-12">
          <Loader2 className="w-8 h-8 animate-spin text-green-500" />
        </div>
      ) : (
        <div className="space-y-2">
          {displayTracks.map(track => (
            <div
              key={track.id}
              className="flex items-center gap-4 p-3 rounded-lg border border-gray-100 hover:border-green-300 hover:bg-green-50/50 transition-all group"
            >
              {/* Play button */}
              <button
                onClick={() => togglePlay(track)}
                className={`w-10 h-10 rounded-full flex items-center justify-center transition-colors ${
                  playingId === track.id
                    ? 'bg-green-500 text-white'
                    : 'bg-gray-100 text-gray-600 group-hover:bg-green-100 group-hover:text-green-600'
                }`}
              >
                {playingId === track.id ? (
                  <Pause className="w-4 h-4" />
                ) : (
                  <Play className="w-4 h-4 ml-0.5" />
                )}
              </button>

              {/* Track info */}
              <div className="flex-1 min-w-0">
                <h4 className="font-medium text-gray-900 truncate">{track.title}</h4>
                <p className="text-xs text-gray-500">{track.artist}</p>
              </div>

              {/* Metadata */}
              <div className="flex items-center gap-4 text-xs text-gray-400">
                <span className={`px-2 py-0.5 rounded-full ${MOOD_COLORS[track.mood]}`}>
                  {track.mood}
                </span>
                {track.bpm && <span>{track.bpm} BPM</span>}
                <span>{formatDuration(track.duration)}</span>
                <span>{formatNumber(track.uses)} uses</span>
              </div>

              {/* Energy bar */}
              <div className="w-20">
                <div className="h-1.5 bg-gray-200 rounded-full overflow-hidden">
                  <div
                    className="h-full bg-gradient-to-r from-green-400 to-green-600"
                    style={{ width: `${track.energy}%` }}
                  />
                </div>
                <p className="text-[10px] text-gray-400 text-center mt-0.5">
                  Energy {track.energy}%
                </p>
              </div>

              {/* Select button */}
              <button
                onClick={() => handleSelectTrack(track)}
                className="px-4 py-2 bg-green-500 text-white text-sm font-medium rounded-lg opacity-0 group-hover:opacity-100 transition-opacity hover:bg-green-600"
              >
                Use
              </button>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
