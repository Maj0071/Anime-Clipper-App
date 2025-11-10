import React, { useState, useEffect } from 'react';
import { Play, Download, Star, Clock, TrendingUp, Film } from 'lucide-react';

interface Candidate {
  id: string;
  start_s: number;
  end_s: number;
  score: number;
  features: {
    speech_hook: number;
    motion: number;
    audio_peak: number;
    keyword_match: number;
    scene_freshness: number;
  };
  thumb_url: string;
}

interface GalleryProps {
  videoId: string;
  onSelectCandidates: (selectedIds: string[]) => void;
}

export default function CandidateGallery({ videoId, onSelectCandidates }: GalleryProps) {
  const [candidates, setCandidates] = useState<Candidate[]>([]);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [loading, setLoading] = useState(true);
  const [sortBy, setSortBy] = useState<'score' | 'duration'>('score');
  const [previewId, setPreviewId] = useState<string | null>(null);

  useEffect(() => {
    fetchCandidates();
  }, [videoId]);

  const fetchCandidates = async () => {
    try {
      const response = await fetch(`/api/videos/${videoId}/candidates`, {
        headers: {
          'Authorization': `Bearer ${localStorage.getItem('token')}`
        }
      });
      
      if (!response.ok) throw new Error('Failed to fetch candidates');
      
      const data = await response.json();
      setCandidates(data.candidates);
    } catch (error) {
      console.error('Error fetching candidates:', error);
    } finally {
      setLoading(false);
    }
  };

  const toggleSelect = (id: string) => {
    const newSelected = new Set(selected);
    if (newSelected.has(id)) {
      newSelected.delete(id);
    } else {
      newSelected.add(id);
    }
    setSelected(newSelected);
    onSelectCandidates(Array.from(newSelected));
  };

  const selectAll = () => {
    const allIds = candidates.map(c => c.id);
    setSelected(new Set(allIds));
    onSelectCandidates(allIds);
  };

  const deselectAll = () => {
    setSelected(new Set());
    onSelectCandidates([]);
  };

  const sortedCandidates = [...candidates].sort((a, b) => {
    if (sortBy === 'score') {
      return b.score - a.score;
    } else {
      return (b.end_s - b.start_s) - (a.end_s - a.start_s);
    }
  });

  const formatTime = (seconds: number) => {
    const mins = Math.floor(seconds / 60);
    const secs = Math.floor(seconds % 60);
    return `${mins}:${secs.toString().padStart(2, '0')}`;
  };

  const getScoreColor = (score: number) => {
    if (score >= 0.8) return 'text-green-600 bg-green-100';
    if (score >= 0.6) return 'text-yellow-600 bg-yellow-100';
    return 'text-orange-600 bg-orange-100';
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center h-64">
        <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-purple-600"></div>
      </div>
    );
  }

  return (
    <div className="max-w-7xl mx-auto p-6">
      {/* Header */}
      <div className="bg-white rounded-lg shadow-lg p-6 mb-6">
        <div className="flex items-center justify-between mb-4">
          <div>
            <h2 className="text-2xl font-bold text-gray-900">
              Clip Candidates
            </h2>
            <p className="text-sm text-gray-600 mt-1">
              {candidates.length} clips found • {selected.size} selected
            </p>
          </div>
          
          <div className="flex items-center gap-4">
            <div>
              <label className="text-sm text-gray-600 mr-2">Sort by:</label>
              <select
                value={sortBy}
                onChange={(e) => setSortBy(e.target.value as 'score' | 'duration')}
                className="px-3 py-2 border border-gray-300 rounded-lg text-sm focus:ring-2 focus:ring-purple-500"
              >
                <option value="score">Score</option>
                <option value="duration">Duration</option>
              </select>
            </div>
            
            {selected.size === 0 ? (
              <button
                onClick={selectAll}
                className="px-4 py-2 text-sm font-medium text-purple-600 border border-purple-600 rounded-lg hover:bg-purple-50"
              >
                Select All
              </button>
            ) : (
              <button
                onClick={deselectAll}
                className="px-4 py-2 text-sm font-medium text-gray-600 border border-gray-300 rounded-lg hover:bg-gray-50"
              >
                Deselect All
              </button>
            )}
          </div>
        </div>

        {/* Quick Stats */}
        <div className="grid grid-cols-4 gap-4">
          <div className="bg-purple-50 p-3 rounded-lg">
            <div className="flex items-center gap-2 text-purple-700">
              <Star className="w-4 h-4" />
              <span className="text-sm font-medium">Avg Score</span>
            </div>
            <p className="text-2xl font-bold text-purple-900 mt-1">
              {(candidates.reduce((sum, c) => sum + c.score, 0) / candidates.length).toFixed(2)}
            </p>
          </div>
          
          <div className="bg-blue-50 p-3 rounded-lg">
            <div className="flex items-center gap-2 text-blue-700">
              <Clock className="w-4 h-4" />
              <span className="text-sm font-medium">Total Duration</span>
            </div>
            <p className="text-2xl font-bold text-blue-900 mt-1">
              {formatTime(candidates.reduce((sum, c) => sum + (c.end_s - c.start_s), 0))}
            </p>
          </div>
          
          <div className="bg-green-50 p-3 rounded-lg">
            <div className="flex items-center gap-2 text-green-700">
              <TrendingUp className="w-4 h-4" />
              <span className="text-sm font-medium">High Scores</span>
            </div>
            <p className="text-2xl font-bold text-green-900 mt-1">
              {candidates.filter(c => c.score >= 0.7).length}
            </p>
          </div>
          
          <div className="bg-orange-50 p-3 rounded-lg">
            <div className="flex items-center gap-2 text-orange-700">
              <Download className="w-4 h-4" />
              <span className="text-sm font-medium">Selected</span>
            </div>
            <p className="text-2xl font-bold text-orange-900 mt-1">
              {selected.size}
            </p>
          </div>
        </div>
      </div>

      {/* Candidate Grid */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
        {sortedCandidates.map((candidate) => {
          const isSelected = selected.has(candidate.id);
          const duration = candidate.end_s - candidate.start_s;
          
          return (
            <div
              key={candidate.id}
              className={`bg-white rounded-lg shadow-lg overflow-hidden transition-all cursor-pointer ${
                isSelected ? 'ring-4 ring-purple-500 transform scale-105' : 'hover:shadow-xl'
              }`}
              onClick={() => toggleSelect(candidate.id)}
            >
              {/* Thumbnail */}
              <div className="relative aspect-video bg-gray-900">
                <img
                  src={candidate.thumb_url}
                  alt={`Clip ${candidate.id}`}
                  className="w-full h-full object-cover"
                />
                
                {/* Overlay Controls */}
                <div className="absolute inset-0 bg-black bg-opacity-0 hover:bg-opacity-40 transition-opacity flex items-center justify-center">
                  <button
                    onClick={(e) => {
                      e.stopPropagation();
                      setPreviewId(candidate.id);
                    }}
                    className="opacity-0 hover:opacity-100 transition-opacity bg-white text-purple-600 rounded-full p-4 hover:bg-purple-50"
                  >
                    <Play className="w-8 h-8" />
                  </button>
                </div>
                
                {/* Selection Indicator */}
                {isSelected && (
                  <div className="absolute top-3 right-3 bg-purple-600 text-white rounded-full p-2">
                    <svg className="w-5 h-5" fill="currentColor" viewBox="0 0 20 20">
                      <path fillRule="evenodd" d="M16.707 5.293a1 1 0 010 1.414l-8 8a1 1 0 01-1.414 0l-4-4a1 1 0 011.414-1.414L8 12.586l7.293-7.293a1 1 0 011.414 0z" clipRule="evenodd" />
                    </svg>
                  </div>
                )}
                
                {/* Duration Badge */}
                <div className="absolute bottom-3 left-3 bg-black bg-opacity-75 text-white text-xs px-2 py-1 rounded">
                  {formatTime(duration)}
                </div>
              </div>

              {/* Info */}
              <div className="p-4">
                <div className="flex items-center justify-between mb-3">
                  <span className={`px-3 py-1 rounded-full text-sm font-semibold ${getScoreColor(candidate.score)}`}>
                    Score: {(candidate.score * 100).toFixed(0)}%
                  </span>
                  <span className="text-sm text-gray-500">
                    {formatTime(candidate.start_s)} - {formatTime(candidate.end_s)}
                  </span>
                </div>

                {/* Feature Breakdown */}
                <div className="space-y-2">
                  {Object.entries(candidate.features).map(([key, value]) => {
                    const labels: Record<string, string> = {
                      speech_hook: 'Hook',
                      motion: 'Motion',
                      audio_peak: 'Audio',
                      keyword_match: 'Keywords',
                      scene_freshness: 'Fresh'
                    };
                    
                    return (
                      <div key={key} className="flex items-center justify-between text-xs">
                        <span className="text-gray-600">{labels[key]}</span>
                        <div className="flex items-center gap-2">
                          <div className="w-24 bg-gray-200 rounded-full h-1.5">
                            <div
                              className="bg-purple-600 h-1.5 rounded-full"
                              style={{ width: `${value * 100}%` }}
                            />
                          </div>
                          <span className="text-gray-700 font-medium w-8 text-right">
                            {(value * 100).toFixed(0)}
                          </span>
                        </div>
                      </div>
                    );
                  })}
                </div>
              </div>
            </div>
          );
        })}
      </div>

      {/* Empty State */}
      {candidates.length === 0 && (
        <div className="text-center py-12">
          <Film className="w-16 h-16 mx-auto text-gray-400 mb-4" />
          <p className="text-lg text-gray-600">No candidates found</p>
          <p className="text-sm text-gray-500">Try uploading a video first</p>
        </div>
      )}
    </div>
  );
}