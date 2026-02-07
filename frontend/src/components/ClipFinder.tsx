import React, { useState, useEffect, useCallback } from 'react';
import {
  Search,
  TrendingUp,
  Star,
  Clock,
  Download,
  Heart,
  X,
  Filter,
  Sparkles,
  Eye,
  Loader2,
  RefreshCw,
  ChevronDown,
  ExternalLink,
  Play,
  AlertCircle,
} from 'lucide-react';

// =============================================================================
// Types
// =============================================================================

interface ClipSuggestion {
  id: string;
  external_id: string | null;
  title: string;
  description: string | null;
  url: string;
  thumbnail_url: string | null;
  anime_name: string | null;
  episode_info: string | null;
  duration: number | null;
  view_count: number;
  trending_score: number;
  quality_score: number;
  watermark_detected: number;
  is_downloaded: boolean;
  status: string;
  discovered_at: string;
  source_platform: string | null;
}

interface DailyPick {
  id: string;
  category: string;
  position: number;
  is_featured: boolean;
  suggestion: ClipSuggestion;
}

interface ClipStats {
  total_suggestions: number;
  active_suggestions: number;
  downloaded_clips: number;
  user_liked: number;
  user_dismissed: number;
}

// =============================================================================
// API Helpers
// =============================================================================

const API_BASE = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';

function authHeaders(): Record<string, string> {
  const headers: Record<string, string> = { 'Content-Type': 'application/json' };
  if (typeof localStorage !== 'undefined') {
    const token = localStorage.getItem('token');
    if (token) headers['Authorization'] = `Bearer ${token}`;
  }
  return headers;
}

async function apiFetch(path: string, options: RequestInit = {}) {
  const res = await fetch(`${API_BASE}${path}`, {
    ...options,
    headers: { ...authHeaders(), ...(options.headers || {}) },
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail || 'Request failed');
  }
  return res.json();
}

// =============================================================================
// Main Component
// =============================================================================

export default function ClipFinder() {
  const [tab, setTab] = useState<'discover' | 'daily' | 'search'>('discover');
  const [suggestions, setSuggestions] = useState<ClipSuggestion[]>([]);
  const [dailyPicks, setDailyPicks] = useState<DailyPick[]>([]);
  const [stats, setStats] = useState<ClipStats | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [total, setTotal] = useState(0);

  // Filters
  const [sortBy, setSortBy] = useState('trending');
  const [animeName, setAnimeName] = useState('');
  const [minQuality, setMinQuality] = useState<number | null>(null);
  const [hideWatermarked, setHideWatermarked] = useState(false);
  const [showFilters, setShowFilters] = useState(false);

  // Search
  const [searchQuery, setSearchQuery] = useState('');
  const [searchResults, setSearchResults] = useState<ClipSuggestion[]>([]);
  const [searching, setSearching] = useState(false);

  // Pagination
  const [page, setPage] = useState(0);
  const limit = 20;

  const fetchSuggestions = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const params = new URLSearchParams({
        sort_by: sortBy,
        skip: String(page * limit),
        limit: String(limit),
        hide_watermarked: String(hideWatermarked),
      });
      if (animeName) params.set('anime_name', animeName);
      if (minQuality !== null) params.set('min_quality', String(minQuality));

      const data = await apiFetch(`/clips/suggestions?${params}`);
      setSuggestions(data.suggestions);
      setTotal(data.total);
    } catch (e: any) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }, [sortBy, page, animeName, minQuality, hideWatermarked]);

  const fetchDailyPicks = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await apiFetch('/clips/daily');
      setDailyPicks(data.picks);
    } catch (e: any) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }, []);

  const fetchStats = useCallback(async () => {
    try {
      const data = await apiFetch('/clips/stats');
      setStats(data);
    } catch {
      // Stats are non-critical
    }
  }, []);

  useEffect(() => {
    if (tab === 'discover') {
      fetchSuggestions();
    } else if (tab === 'daily') {
      fetchDailyPicks();
    }
    fetchStats();
  }, [tab, fetchSuggestions, fetchDailyPicks, fetchStats]);

  const handleSearch = async () => {
    if (!searchQuery.trim()) return;
    setSearching(true);
    setError(null);
    try {
      const data = await apiFetch('/clips/search', {
        method: 'POST',
        body: JSON.stringify({ anime_name: searchQuery, max_results: 20 }),
      });
      setSearchResults(data.suggestions);
    } catch (e: any) {
      setError(e.message);
    } finally {
      setSearching(false);
    }
  };

  const handleLike = async (id: string) => {
    try {
      await apiFetch(`/clips/suggestions/${id}/like`, { method: 'POST' });
      setSuggestions((prev) => prev.map((s) => (s.id === id ? { ...s, _liked: true } as any : s)));
    } catch {
      // silent
    }
  };

  const handleDismiss = async (id: string) => {
    try {
      await apiFetch(`/clips/suggestions/${id}/dismiss`, { method: 'POST' });
      setSuggestions((prev) => prev.filter((s) => s.id !== id));
      setTotal((t) => t - 1);
    } catch {
      // silent
    }
  };

  const handleDownload = async (id: string) => {
    try {
      await apiFetch(`/clips/suggestions/${id}/download`, { method: 'POST' });
      setSuggestions((prev) =>
        prev.map((s) => (s.id === id ? { ...s, is_downloaded: true } : s))
      );
    } catch (e: any) {
      setError(e.message);
    }
  };

  const triggerDiscovery = async () => {
    try {
      await apiFetch('/clips/discover', {
        method: 'POST',
        body: JSON.stringify({ max_per_source: 25 }),
      });
      // Refresh after a short delay
      setTimeout(fetchSuggestions, 3000);
    } catch (e: any) {
      setError(e.message);
    }
  };

  return (
    <div className="max-w-7xl mx-auto p-6">
      {/* Header */}
      <div className="bg-white rounded-lg shadow-lg p-6 mb-6">
        <div className="flex items-center justify-between mb-4">
          <div>
            <h2 className="text-2xl font-bold text-gray-900">Clip Finder</h2>
            <p className="text-sm text-gray-600 mt-1">
              Discover trending anime clips from across the web
            </p>
          </div>
          <button
            onClick={triggerDiscovery}
            className="flex items-center gap-2 px-4 py-2 bg-purple-600 text-white rounded-lg hover:bg-purple-700 text-sm font-medium"
          >
            <RefreshCw className="w-4 h-4" />
            Discover New
          </button>
        </div>

        {/* Stats Bar */}
        {stats && (
          <div className="grid grid-cols-5 gap-4 mb-4">
            <StatCard icon={<Sparkles className="w-4 h-4" />} label="Total" value={stats.total_suggestions} color="purple" />
            <StatCard icon={<TrendingUp className="w-4 h-4" />} label="Active" value={stats.active_suggestions} color="blue" />
            <StatCard icon={<Download className="w-4 h-4" />} label="Downloaded" value={stats.downloaded_clips} color="green" />
            <StatCard icon={<Heart className="w-4 h-4" />} label="Liked" value={stats.user_liked} color="pink" />
            <StatCard icon={<X className="w-4 h-4" />} label="Dismissed" value={stats.user_dismissed} color="gray" />
          </div>
        )}

        {/* Tabs */}
        <div className="flex gap-1 bg-gray-100 rounded-lg p-1">
          {(['discover', 'daily', 'search'] as const).map((t) => (
            <button
              key={t}
              onClick={() => setTab(t)}
              className={`flex-1 py-2 px-4 rounded-md text-sm font-medium transition-colors ${
                tab === t
                  ? 'bg-white text-purple-700 shadow-sm'
                  : 'text-gray-600 hover:text-gray-900'
              }`}
            >
              {t === 'discover' ? 'Trending' : t === 'daily' ? 'Daily Picks' : 'Search'}
            </button>
          ))}
        </div>
      </div>

      {/* Error Banner */}
      {error && (
        <div className="bg-red-50 border border-red-200 text-red-700 rounded-lg p-4 mb-6 flex items-center gap-3">
          <AlertCircle className="w-5 h-5 flex-shrink-0" />
          <span className="text-sm">{error}</span>
          <button onClick={() => setError(null)} className="ml-auto text-red-400 hover:text-red-600">
            <X className="w-4 h-4" />
          </button>
        </div>
      )}

      {/* Tab Content */}
      {tab === 'discover' && (
        <DiscoverTab
          suggestions={suggestions}
          loading={loading}
          total={total}
          page={page}
          limit={limit}
          sortBy={sortBy}
          animeName={animeName}
          minQuality={minQuality}
          hideWatermarked={hideWatermarked}
          showFilters={showFilters}
          onSortChange={setSortBy}
          onAnimeNameChange={setAnimeName}
          onMinQualityChange={setMinQuality}
          onHideWatermarkedChange={setHideWatermarked}
          onToggleFilters={() => setShowFilters(!showFilters)}
          onPageChange={setPage}
          onLike={handleLike}
          onDismiss={handleDismiss}
          onDownload={handleDownload}
        />
      )}

      {tab === 'daily' && (
        <DailyTab picks={dailyPicks} loading={loading} onDownload={handleDownload} onLike={handleLike} />
      )}

      {tab === 'search' && (
        <SearchTab
          query={searchQuery}
          results={searchResults}
          searching={searching}
          onQueryChange={setSearchQuery}
          onSearch={handleSearch}
          onDownload={handleDownload}
          onLike={handleLike}
        />
      )}
    </div>
  );
}

// =============================================================================
// Sub-Components
// =============================================================================

function StatCard({
  icon,
  label,
  value,
  color,
}: {
  icon: React.ReactNode;
  label: string;
  value: number;
  color: string;
}) {
  const colorMap: Record<string, string> = {
    purple: 'bg-purple-50 text-purple-700',
    blue: 'bg-blue-50 text-blue-700',
    green: 'bg-green-50 text-green-700',
    pink: 'bg-pink-50 text-pink-700',
    gray: 'bg-gray-50 text-gray-700',
  };
  return (
    <div className={`${colorMap[color]} rounded-lg p-3`}>
      <div className="flex items-center gap-2">
        {icon}
        <span className="text-xs font-medium">{label}</span>
      </div>
      <p className="text-xl font-bold mt-1">{value}</p>
    </div>
  );
}

// =============================================================================
// Discover Tab
// =============================================================================

function DiscoverTab({
  suggestions,
  loading,
  total,
  page,
  limit,
  sortBy,
  animeName,
  minQuality,
  hideWatermarked,
  showFilters,
  onSortChange,
  onAnimeNameChange,
  onMinQualityChange,
  onHideWatermarkedChange,
  onToggleFilters,
  onPageChange,
  onLike,
  onDismiss,
  onDownload,
}: {
  suggestions: ClipSuggestion[];
  loading: boolean;
  total: number;
  page: number;
  limit: number;
  sortBy: string;
  animeName: string;
  minQuality: number | null;
  hideWatermarked: boolean;
  showFilters: boolean;
  onSortChange: (v: string) => void;
  onAnimeNameChange: (v: string) => void;
  onMinQualityChange: (v: number | null) => void;
  onHideWatermarkedChange: (v: boolean) => void;
  onToggleFilters: () => void;
  onPageChange: (v: number) => void;
  onLike: (id: string) => void;
  onDismiss: (id: string) => void;
  onDownload: (id: string) => void;
}) {
  return (
    <>
      {/* Filter Bar */}
      <div className="bg-white rounded-lg shadow p-4 mb-6">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-4">
            <div>
              <label className="text-xs text-gray-500 block mb-1">Sort by</label>
              <select
                value={sortBy}
                onChange={(e) => onSortChange(e.target.value)}
                className="px-3 py-2 border border-gray-300 rounded-lg text-sm focus:ring-2 focus:ring-purple-500"
              >
                <option value="trending">Trending</option>
                <option value="quality">Quality</option>
                <option value="recent">Recent</option>
                <option value="views">Views</option>
              </select>
            </div>
            <div>
              <label className="text-xs text-gray-500 block mb-1">Anime</label>
              <input
                type="text"
                value={animeName}
                onChange={(e) => onAnimeNameChange(e.target.value)}
                placeholder="Filter by anime..."
                className="px-3 py-2 border border-gray-300 rounded-lg text-sm focus:ring-2 focus:ring-purple-500 w-48"
              />
            </div>
          </div>
          <button
            onClick={onToggleFilters}
            className="flex items-center gap-2 px-3 py-2 text-sm text-gray-600 hover:text-gray-900 border rounded-lg"
          >
            <Filter className="w-4 h-4" />
            Filters
            <ChevronDown className={`w-4 h-4 transition-transform ${showFilters ? 'rotate-180' : ''}`} />
          </button>
        </div>

        {showFilters && (
          <div className="mt-4 pt-4 border-t flex items-center gap-6">
            <div>
              <label className="text-xs text-gray-500 block mb-1">Min Quality</label>
              <input
                type="number"
                min={0}
                max={100}
                value={minQuality ?? ''}
                onChange={(e) => onMinQualityChange(e.target.value ? Number(e.target.value) : null)}
                placeholder="0-100"
                className="px-3 py-2 border border-gray-300 rounded-lg text-sm w-24"
              />
            </div>
            <label className="flex items-center gap-2 text-sm text-gray-700 cursor-pointer">
              <input
                type="checkbox"
                checked={hideWatermarked}
                onChange={(e) => onHideWatermarkedChange(e.target.checked)}
                className="rounded border-gray-300 text-purple-600 focus:ring-purple-500"
              />
              Hide watermarked clips
            </label>
          </div>
        )}
      </div>

      {/* Results */}
      {loading ? (
        <LoadingSpinner />
      ) : suggestions.length === 0 ? (
        <EmptyState message="No clips found" subtitle="Try adjusting your filters or trigger a new discovery" />
      ) : (
        <>
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-5">
            {suggestions.map((clip) => (
              <ClipCard
                key={clip.id}
                clip={clip}
                onLike={() => onLike(clip.id)}
                onDismiss={() => onDismiss(clip.id)}
                onDownload={() => onDownload(clip.id)}
              />
            ))}
          </div>

          {/* Pagination */}
          <div className="flex items-center justify-between mt-8">
            <p className="text-sm text-gray-600">
              Showing {page * limit + 1}-{Math.min((page + 1) * limit, total)} of {total}
            </p>
            <div className="flex gap-2">
              <button
                onClick={() => onPageChange(Math.max(0, page - 1))}
                disabled={page === 0}
                className="px-4 py-2 text-sm border rounded-lg disabled:opacity-50 disabled:cursor-not-allowed hover:bg-gray-50"
              >
                Previous
              </button>
              <button
                onClick={() => onPageChange(page + 1)}
                disabled={(page + 1) * limit >= total}
                className="px-4 py-2 text-sm border rounded-lg disabled:opacity-50 disabled:cursor-not-allowed hover:bg-gray-50"
              >
                Next
              </button>
            </div>
          </div>
        </>
      )}
    </>
  );
}

// =============================================================================
// Daily Picks Tab
// =============================================================================

function DailyTab({
  picks,
  loading,
  onDownload,
  onLike,
}: {
  picks: DailyPick[];
  loading: boolean;
  onDownload: (id: string) => void;
  onLike: (id: string) => void;
}) {
  const categories = ['trending', 'classic', 'underrated'] as const;
  const categoryLabels: Record<string, string> = {
    trending: 'Trending Now',
    classic: 'Classic Picks',
    underrated: 'Hidden Gems',
  };
  const categoryColors: Record<string, string> = {
    trending: 'bg-red-100 text-red-700 border-red-200',
    classic: 'bg-blue-100 text-blue-700 border-blue-200',
    underrated: 'bg-amber-100 text-amber-700 border-amber-200',
  };

  if (loading) return <LoadingSpinner />;

  if (picks.length === 0) {
    return <EmptyState message="No daily picks yet" subtitle="Picks are curated every morning at 8 AM UTC" />;
  }

  return (
    <div className="space-y-8">
      {categories.map((cat) => {
        const catPicks = picks.filter((p) => p.category === cat);
        if (catPicks.length === 0) return null;

        return (
          <div key={cat}>
            <div className="flex items-center gap-3 mb-4">
              <span className={`px-3 py-1 rounded-full text-sm font-semibold border ${categoryColors[cat]}`}>
                {categoryLabels[cat]}
              </span>
              <span className="text-sm text-gray-500">{catPicks.length} clips</span>
            </div>
            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-5">
              {catPicks.map((pick) => (
                <div key={pick.id} className="relative">
                  {pick.is_featured && (
                    <div className="absolute -top-2 -left-2 z-10 bg-yellow-400 text-yellow-900 text-xs font-bold px-2 py-1 rounded-full shadow">
                      Featured
                    </div>
                  )}
                  <ClipCard
                    clip={pick.suggestion}
                    onLike={() => onLike(pick.suggestion.id)}
                    onDismiss={() => {}}
                    onDownload={() => onDownload(pick.suggestion.id)}
                  />
                </div>
              ))}
            </div>
          </div>
        );
      })}
    </div>
  );
}

// =============================================================================
// Search Tab
// =============================================================================

function SearchTab({
  query,
  results,
  searching,
  onQueryChange,
  onSearch,
  onDownload,
  onLike,
}: {
  query: string;
  results: ClipSuggestion[];
  searching: boolean;
  onQueryChange: (v: string) => void;
  onSearch: () => void;
  onDownload: (id: string) => void;
  onLike: (id: string) => void;
}) {
  return (
    <>
      <div className="bg-white rounded-lg shadow p-6 mb-6">
        <h3 className="text-lg font-semibold text-gray-900 mb-3">Search for Anime Clips</h3>
        <div className="flex gap-3">
          <input
            type="text"
            value={query}
            onChange={(e) => onQueryChange(e.target.value)}
            onKeyDown={(e) => e.key === 'Enter' && onSearch()}
            placeholder="e.g. Jujutsu Kaisen, One Piece, Demon Slayer..."
            className="flex-1 px-4 py-3 border border-gray-300 rounded-lg text-sm focus:ring-2 focus:ring-purple-500 focus:border-purple-500"
          />
          <button
            onClick={onSearch}
            disabled={searching || !query.trim()}
            className="flex items-center gap-2 px-6 py-3 bg-purple-600 text-white rounded-lg hover:bg-purple-700 disabled:opacity-50 disabled:cursor-not-allowed text-sm font-medium"
          >
            {searching ? <Loader2 className="w-4 h-4 animate-spin" /> : <Search className="w-4 h-4" />}
            Search
          </button>
        </div>
      </div>

      {searching ? (
        <LoadingSpinner />
      ) : results.length > 0 ? (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-5">
          {results.map((clip) => (
            <ClipCard
              key={clip.id}
              clip={clip}
              onLike={() => onLike(clip.id)}
              onDismiss={() => {}}
              onDownload={() => onDownload(clip.id)}
            />
          ))}
        </div>
      ) : query ? (
        <EmptyState message="No results" subtitle="Try a different anime name" />
      ) : (
        <EmptyState message="Search for anime clips" subtitle="Enter an anime name to find trending clips from YouTube and Reddit" />
      )}
    </>
  );
}

// =============================================================================
// Clip Card
// =============================================================================

function ClipCard({
  clip,
  onLike,
  onDismiss,
  onDownload,
}: {
  clip: ClipSuggestion;
  onLike: () => void;
  onDismiss: () => void;
  onDownload: () => void;
}) {
  const [liked, setLiked] = useState(false);

  const formatDuration = (seconds: number | null) => {
    if (!seconds) return '--:--';
    const m = Math.floor(seconds / 60);
    const s = Math.floor(seconds % 60);
    return `${m}:${s.toString().padStart(2, '0')}`;
  };

  const formatViews = (count: number) => {
    if (count >= 1_000_000) return `${(count / 1_000_000).toFixed(1)}M`;
    if (count >= 1_000) return `${(count / 1_000).toFixed(1)}K`;
    return String(count);
  };

  const scoreColor = (score: number) => {
    if (score >= 70) return 'text-green-600 bg-green-100';
    if (score >= 40) return 'text-yellow-600 bg-yellow-100';
    return 'text-orange-600 bg-orange-100';
  };

  const platformIcon = (platform: string | null) => {
    if (platform === 'youtube') return 'YT';
    if (platform === 'reddit') return 'R';
    return '?';
  };

  return (
    <div className="bg-white rounded-lg shadow-md overflow-hidden hover:shadow-xl transition-shadow group">
      {/* Thumbnail */}
      <div className="relative aspect-video bg-gray-900">
        {clip.thumbnail_url ? (
          <img
            src={clip.thumbnail_url}
            alt={clip.title}
            className="w-full h-full object-cover"
          />
        ) : (
          <div className="w-full h-full flex items-center justify-center">
            <Play className="w-12 h-12 text-gray-600" />
          </div>
        )}

        {/* Overlay on hover */}
        <div className="absolute inset-0 bg-black bg-opacity-0 group-hover:bg-opacity-50 transition-opacity flex items-center justify-center">
          <a
            href={clip.url}
            target="_blank"
            rel="noopener noreferrer"
            className="opacity-0 group-hover:opacity-100 transition-opacity bg-white text-purple-600 rounded-full p-3 hover:bg-purple-50"
            onClick={(e) => e.stopPropagation()}
          >
            <ExternalLink className="w-6 h-6" />
          </a>
        </div>

        {/* Badges */}
        <div className="absolute top-2 left-2 flex gap-1.5">
          {clip.source_platform && (
            <span className="bg-black bg-opacity-75 text-white text-[10px] font-bold px-1.5 py-0.5 rounded">
              {platformIcon(clip.source_platform)}
            </span>
          )}
          {clip.watermark_detected === 1 && (
            <span className="bg-red-500 text-white text-[10px] font-bold px-1.5 py-0.5 rounded">
              WM
            </span>
          )}
        </div>

        <div className="absolute bottom-2 right-2 bg-black bg-opacity-75 text-white text-xs px-2 py-0.5 rounded">
          {formatDuration(clip.duration)}
        </div>
      </div>

      {/* Info */}
      <div className="p-3">
        <h3 className="text-sm font-semibold text-gray-900 line-clamp-2 mb-1.5" title={clip.title}>
          {clip.title}
        </h3>

        {clip.anime_name && (
          <p className="text-xs text-purple-600 font-medium mb-2">
            {clip.anime_name}
            {clip.episode_info && ` - ${clip.episode_info}`}
          </p>
        )}

        {/* Scores */}
        <div className="flex items-center gap-2 mb-3">
          <span className={`text-[10px] font-bold px-1.5 py-0.5 rounded-full ${scoreColor(clip.trending_score)}`}>
            T:{Math.round(clip.trending_score)}
          </span>
          <span className={`text-[10px] font-bold px-1.5 py-0.5 rounded-full ${scoreColor(clip.quality_score)}`}>
            Q:{Math.round(clip.quality_score)}
          </span>
          <span className="text-[10px] text-gray-500 flex items-center gap-0.5 ml-auto">
            <Eye className="w-3 h-3" />
            {formatViews(clip.view_count)}
          </span>
        </div>

        {/* Actions */}
        <div className="flex items-center gap-1.5">
          <button
            onClick={(e) => {
              e.stopPropagation();
              setLiked(true);
              onLike();
            }}
            className={`flex-1 flex items-center justify-center gap-1 px-2 py-1.5 rounded text-xs font-medium transition-colors ${
              liked
                ? 'bg-pink-100 text-pink-700'
                : 'bg-gray-100 text-gray-600 hover:bg-pink-50 hover:text-pink-600'
            }`}
          >
            <Heart className="w-3 h-3" fill={liked ? 'currentColor' : 'none'} />
            Like
          </button>
          <button
            onClick={(e) => {
              e.stopPropagation();
              onDownload();
            }}
            className={`flex-1 flex items-center justify-center gap-1 px-2 py-1.5 rounded text-xs font-medium transition-colors ${
              clip.is_downloaded
                ? 'bg-green-100 text-green-700'
                : 'bg-gray-100 text-gray-600 hover:bg-green-50 hover:text-green-600'
            }`}
          >
            <Download className="w-3 h-3" />
            {clip.is_downloaded ? 'Saved' : 'Get'}
          </button>
          <button
            onClick={(e) => {
              e.stopPropagation();
              onDismiss();
            }}
            className="flex items-center justify-center p-1.5 rounded text-xs text-gray-400 hover:bg-red-50 hover:text-red-500 transition-colors"
          >
            <X className="w-3.5 h-3.5" />
          </button>
        </div>
      </div>
    </div>
  );
}

// =============================================================================
// Shared UI
// =============================================================================

function LoadingSpinner() {
  return (
    <div className="flex items-center justify-center h-64">
      <Loader2 className="w-10 h-10 animate-spin text-purple-600" />
    </div>
  );
}

function EmptyState({ message, subtitle }: { message: string; subtitle: string }) {
  return (
    <div className="text-center py-16">
      <Search className="w-14 h-14 mx-auto text-gray-300 mb-4" />
      <p className="text-lg text-gray-600 font-medium">{message}</p>
      <p className="text-sm text-gray-400 mt-1">{subtitle}</p>
    </div>
  );
}
