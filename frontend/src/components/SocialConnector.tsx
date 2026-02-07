import React, { useState, useEffect, useCallback } from 'react';
import {
  Link2,
  Unlink,
  Send,
  Calendar,
  Clock,
  Loader2,
  AlertCircle,
  X,
  CheckCircle,
  ExternalLink,
  Trash2,
  Plus,
} from 'lucide-react';

// =============================================================================
// Types
// =============================================================================

interface SocialAccount {
  id: string;
  platform: string;
  account_name: string | null;
  account_id: string | null;
  is_active: boolean;
  expires_at: string | null;
  created_at: string;
}

interface ScheduledPost {
  id: string;
  platform: string;
  account_name: string | null;
  video_path: string;
  caption: string | null;
  hashtags: string[];
  scheduled_time: string;
  status: string;
  posted_at: string | null;
  post_url: string | null;
  error_message: string | null;
  created_at: string;
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

export default function SocialConnector() {
  const [tab, setTab] = useState<'accounts' | 'post' | 'schedule'>('accounts');
  const [accounts, setAccounts] = useState<SocialAccount[]>([]);
  const [scheduledPosts, setScheduledPosts] = useState<ScheduledPost[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);

  const fetchAccounts = useCallback(async () => {
    try {
      const data = await apiFetch('/social/accounts');
      setAccounts(data);
    } catch (e: any) {
      setError(e.message);
    }
  }, []);

  const fetchScheduled = useCallback(async () => {
    try {
      const data = await apiFetch('/social/schedule');
      setScheduledPosts(data);
    } catch (e: any) {
      setError(e.message);
    }
  }, []);

  useEffect(() => {
    setLoading(true);
    Promise.all([fetchAccounts(), fetchScheduled()]).finally(() => setLoading(false));
  }, [fetchAccounts, fetchScheduled]);

  const activeAccounts = accounts.filter((a) => a.is_active);

  return (
    <div className="max-w-5xl mx-auto p-6">
      {/* Header */}
      <div className="bg-white rounded-lg shadow-lg p-6 mb-6">
        <h2 className="text-2xl font-bold text-gray-900 mb-1">Social Media</h2>
        <p className="text-sm text-gray-600">
          Connect your TikTok and Instagram accounts to post clips directly
        </p>

        {/* Tabs */}
        <div className="flex gap-1 bg-gray-100 rounded-lg p-1 mt-4">
          {(['accounts', 'post', 'schedule'] as const).map((t) => (
            <button
              key={t}
              onClick={() => setTab(t)}
              className={`flex-1 py-2 px-4 rounded-md text-sm font-medium transition-colors ${
                tab === t
                  ? 'bg-white text-purple-700 shadow-sm'
                  : 'text-gray-600 hover:text-gray-900'
              }`}
            >
              {t === 'accounts' ? 'Accounts' : t === 'post' ? 'Post Now' : 'Scheduled'}
            </button>
          ))}
        </div>
      </div>

      {/* Notifications */}
      {error && (
        <div className="bg-red-50 border border-red-200 text-red-700 rounded-lg p-4 mb-6 flex items-center gap-3">
          <AlertCircle className="w-5 h-5 flex-shrink-0" />
          <span className="text-sm">{error}</span>
          <button onClick={() => setError(null)} className="ml-auto text-red-400 hover:text-red-600">
            <X className="w-4 h-4" />
          </button>
        </div>
      )}

      {success && (
        <div className="bg-green-50 border border-green-200 text-green-700 rounded-lg p-4 mb-6 flex items-center gap-3">
          <CheckCircle className="w-5 h-5 flex-shrink-0" />
          <span className="text-sm">{success}</span>
          <button onClick={() => setSuccess(null)} className="ml-auto text-green-400 hover:text-green-600">
            <X className="w-4 h-4" />
          </button>
        </div>
      )}

      {loading ? (
        <div className="flex items-center justify-center h-64">
          <Loader2 className="w-10 h-10 animate-spin text-purple-600" />
        </div>
      ) : (
        <>
          {tab === 'accounts' && (
            <AccountsTab
              accounts={accounts}
              onConnect={async (platform) => {
                try {
                  const data = await apiFetch(`/social/auth/${platform}`);
                  // Redirect to OAuth flow
                  window.location.href = data.auth_url;
                } catch (e: any) {
                  setError(e.message);
                }
              }}
              onDisconnect={async (id) => {
                try {
                  await apiFetch(`/social/accounts/${id}`, { method: 'DELETE' });
                  setAccounts((prev) => prev.map((a) => (a.id === id ? { ...a, is_active: false } : a)));
                  setSuccess('Account disconnected');
                } catch (e: any) {
                  setError(e.message);
                }
              }}
            />
          )}

          {tab === 'post' && (
            <PostTab
              accounts={activeAccounts}
              onPost={async (accountId, videoPath, caption, hashtags) => {
                setError(null);
                try {
                  const result = await apiFetch(`/social/accounts/${accountId}/post`, {
                    method: 'POST',
                    body: JSON.stringify({ video_path: videoPath, caption, hashtags }),
                  });
                  if (result.success) {
                    setSuccess(`Posted successfully${result.post_url ? ` - ${result.post_url}` : ''}`);
                  } else {
                    setError(result.error || 'Posting failed');
                  }
                } catch (e: any) {
                  setError(e.message);
                }
              }}
            />
          )}

          {tab === 'schedule' && (
            <ScheduleTab
              accounts={activeAccounts}
              posts={scheduledPosts}
              onSchedule={async (accountId, videoPath, caption, hashtags, scheduledTime) => {
                setError(null);
                try {
                  await apiFetch('/social/schedule', {
                    method: 'POST',
                    body: JSON.stringify({
                      account_id: accountId,
                      video_path: videoPath,
                      caption,
                      hashtags,
                      scheduled_time: scheduledTime,
                    }),
                  });
                  setSuccess('Post scheduled');
                  fetchScheduled();
                } catch (e: any) {
                  setError(e.message);
                }
              }}
              onCancel={async (postId) => {
                try {
                  await apiFetch(`/social/schedule/${postId}`, { method: 'DELETE' });
                  setScheduledPosts((prev) => prev.filter((p) => p.id !== postId));
                  setSuccess('Scheduled post cancelled');
                } catch (e: any) {
                  setError(e.message);
                }
              }}
            />
          )}
        </>
      )}
    </div>
  );
}

// =============================================================================
// Accounts Tab
// =============================================================================

function AccountsTab({
  accounts,
  onConnect,
  onDisconnect,
}: {
  accounts: SocialAccount[];
  onConnect: (platform: string) => void;
  onDisconnect: (id: string) => void;
}) {
  const platforms = [
    { key: 'tiktok', name: 'TikTok', color: 'bg-black text-white', hoverColor: 'hover:bg-gray-800' },
    { key: 'instagram', name: 'Instagram', color: 'bg-gradient-to-r from-purple-500 to-pink-500 text-white', hoverColor: 'hover:opacity-90' },
  ];

  return (
    <div className="space-y-6">
      {/* Connect Buttons */}
      <div className="bg-white rounded-lg shadow p-6">
        <h3 className="text-lg font-semibold text-gray-900 mb-4">Connect a Platform</h3>
        <div className="flex gap-4">
          {platforms.map((p) => (
            <button
              key={p.key}
              onClick={() => onConnect(p.key)}
              className={`flex items-center gap-3 px-6 py-3 rounded-lg text-sm font-semibold ${p.color} ${p.hoverColor} transition-opacity`}
            >
              <Link2 className="w-5 h-5" />
              Connect {p.name}
            </button>
          ))}
        </div>
      </div>

      {/* Connected Accounts */}
      <div className="bg-white rounded-lg shadow p-6">
        <h3 className="text-lg font-semibold text-gray-900 mb-4">Connected Accounts</h3>

        {accounts.length === 0 ? (
          <p className="text-sm text-gray-500 text-center py-8">
            No accounts connected yet. Connect TikTok or Instagram above.
          </p>
        ) : (
          <div className="space-y-3">
            {accounts.map((account) => (
              <div
                key={account.id}
                className={`flex items-center justify-between p-4 border rounded-lg ${
                  account.is_active ? 'border-gray-200' : 'border-gray-100 bg-gray-50 opacity-60'
                }`}
              >
                <div className="flex items-center gap-4">
                  <div
                    className={`w-10 h-10 rounded-full flex items-center justify-center text-white text-xs font-bold ${
                      account.platform === 'tiktok' ? 'bg-black' : 'bg-gradient-to-r from-purple-500 to-pink-500'
                    }`}
                  >
                    {account.platform === 'tiktok' ? 'TT' : 'IG'}
                  </div>
                  <div>
                    <p className="text-sm font-semibold text-gray-900">
                      {account.account_name || account.platform}
                    </p>
                    <p className="text-xs text-gray-500">
                      {account.platform.charAt(0).toUpperCase() + account.platform.slice(1)}
                      {!account.is_active && ' (Disconnected)'}
                      {account.expires_at && account.is_active && (
                        <> &middot; Expires {new Date(account.expires_at).toLocaleDateString()}</>
                      )}
                    </p>
                  </div>
                </div>

                {account.is_active && (
                  <button
                    onClick={() => onDisconnect(account.id)}
                    className="flex items-center gap-1.5 px-3 py-1.5 text-xs text-red-600 border border-red-200 rounded-lg hover:bg-red-50 transition-colors"
                  >
                    <Unlink className="w-3.5 h-3.5" />
                    Disconnect
                  </button>
                )}
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

// =============================================================================
// Post Tab
// =============================================================================

function PostTab({
  accounts,
  onPost,
}: {
  accounts: SocialAccount[];
  onPost: (accountId: string, videoPath: string, caption: string, hashtags: string[]) => Promise<void>;
}) {
  const [accountId, setAccountId] = useState(accounts[0]?.id || '');
  const [videoPath, setVideoPath] = useState('');
  const [caption, setCaption] = useState('');
  const [hashtagsStr, setHashtagsStr] = useState('');
  const [posting, setPosting] = useState(false);

  if (accounts.length === 0) {
    return (
      <div className="bg-white rounded-lg shadow p-6 text-center py-12">
        <Link2 className="w-12 h-12 mx-auto text-gray-300 mb-3" />
        <p className="text-gray-600 font-medium">No connected accounts</p>
        <p className="text-sm text-gray-400 mt-1">Connect a TikTok or Instagram account first</p>
      </div>
    );
  }

  const handlePost = async () => {
    if (!accountId || !videoPath) return;
    setPosting(true);
    const hashtags = hashtagsStr
      .split(/[,\s]+/)
      .map((t) => t.replace(/^#/, '').trim())
      .filter(Boolean);
    await onPost(accountId, videoPath, caption, hashtags);
    setPosting(false);
  };

  return (
    <div className="bg-white rounded-lg shadow p-6">
      <h3 className="text-lg font-semibold text-gray-900 mb-6">Post a Clip</h3>

      <div className="space-y-5">
        <div>
          <label className="text-sm font-medium text-gray-700 block mb-1.5">Account</label>
          <select
            value={accountId}
            onChange={(e) => setAccountId(e.target.value)}
            className="w-full px-3 py-2.5 border border-gray-300 rounded-lg text-sm focus:ring-2 focus:ring-purple-500"
          >
            {accounts.map((a) => (
              <option key={a.id} value={a.id}>
                {a.account_name || a.platform} ({a.platform})
              </option>
            ))}
          </select>
        </div>

        <div>
          <label className="text-sm font-medium text-gray-700 block mb-1.5">
            Video Path / URL
          </label>
          <input
            type="text"
            value={videoPath}
            onChange={(e) => setVideoPath(e.target.value)}
            placeholder="e.g. /tmp/videos/downloads/clip.mp4 or https://..."
            className="w-full px-3 py-2.5 border border-gray-300 rounded-lg text-sm focus:ring-2 focus:ring-purple-500"
          />
          <p className="text-xs text-gray-400 mt-1">
            TikTok: local file path | Instagram: publicly accessible URL
          </p>
        </div>

        <div>
          <label className="text-sm font-medium text-gray-700 block mb-1.5">Caption</label>
          <textarea
            value={caption}
            onChange={(e) => setCaption(e.target.value)}
            rows={3}
            placeholder="Write your caption..."
            className="w-full px-3 py-2.5 border border-gray-300 rounded-lg text-sm focus:ring-2 focus:ring-purple-500 resize-none"
          />
        </div>

        <div>
          <label className="text-sm font-medium text-gray-700 block mb-1.5">Hashtags</label>
          <input
            type="text"
            value={hashtagsStr}
            onChange={(e) => setHashtagsStr(e.target.value)}
            placeholder="anime, onepiece, viral (comma separated)"
            className="w-full px-3 py-2.5 border border-gray-300 rounded-lg text-sm focus:ring-2 focus:ring-purple-500"
          />
        </div>

        <button
          onClick={handlePost}
          disabled={posting || !accountId || !videoPath}
          className="w-full flex items-center justify-center gap-2 px-6 py-3 bg-purple-600 text-white rounded-lg hover:bg-purple-700 disabled:opacity-50 disabled:cursor-not-allowed text-sm font-semibold"
        >
          {posting ? <Loader2 className="w-4 h-4 animate-spin" /> : <Send className="w-4 h-4" />}
          {posting ? 'Posting...' : 'Post Now'}
        </button>
      </div>
    </div>
  );
}

// =============================================================================
// Schedule Tab
// =============================================================================

function ScheduleTab({
  accounts,
  posts,
  onSchedule,
  onCancel,
}: {
  accounts: SocialAccount[];
  posts: ScheduledPost[];
  onSchedule: (accountId: string, videoPath: string, caption: string, hashtags: string[], scheduledTime: string) => Promise<void>;
  onCancel: (postId: string) => void;
}) {
  const [showForm, setShowForm] = useState(false);
  const [accountId, setAccountId] = useState(accounts[0]?.id || '');
  const [videoPath, setVideoPath] = useState('');
  const [caption, setCaption] = useState('');
  const [hashtagsStr, setHashtagsStr] = useState('');
  const [scheduledTime, setScheduledTime] = useState('');
  const [submitting, setSubmitting] = useState(false);

  const handleSchedule = async () => {
    if (!accountId || !videoPath || !scheduledTime) return;
    setSubmitting(true);
    const hashtags = hashtagsStr
      .split(/[,\s]+/)
      .map((t) => t.replace(/^#/, '').trim())
      .filter(Boolean);
    const isoTime = new Date(scheduledTime).toISOString();
    await onSchedule(accountId, videoPath, caption, hashtags, isoTime);
    setSubmitting(false);
    setShowForm(false);
    setVideoPath('');
    setCaption('');
    setHashtagsStr('');
    setScheduledTime('');
  };

  const statusColors: Record<string, string> = {
    pending: 'bg-yellow-100 text-yellow-700',
    posted: 'bg-green-100 text-green-700',
    failed: 'bg-red-100 text-red-700',
  };

  return (
    <div className="space-y-6">
      {/* New Schedule Form */}
      {!showForm ? (
        <button
          onClick={() => setShowForm(true)}
          disabled={accounts.length === 0}
          className="w-full flex items-center justify-center gap-2 py-4 border-2 border-dashed border-gray-300 rounded-lg text-gray-500 hover:border-purple-400 hover:text-purple-600 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
        >
          <Plus className="w-5 h-5" />
          Schedule a Post
        </button>
      ) : (
        <div className="bg-white rounded-lg shadow p-6">
          <div className="flex items-center justify-between mb-4">
            <h3 className="text-lg font-semibold text-gray-900">Schedule New Post</h3>
            <button onClick={() => setShowForm(false)} className="text-gray-400 hover:text-gray-600">
              <X className="w-5 h-5" />
            </button>
          </div>

          <div className="space-y-4">
            <div className="grid grid-cols-2 gap-4">
              <div>
                <label className="text-sm font-medium text-gray-700 block mb-1">Account</label>
                <select
                  value={accountId}
                  onChange={(e) => setAccountId(e.target.value)}
                  className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm focus:ring-2 focus:ring-purple-500"
                >
                  {accounts.map((a) => (
                    <option key={a.id} value={a.id}>
                      {a.account_name || a.platform} ({a.platform})
                    </option>
                  ))}
                </select>
              </div>
              <div>
                <label className="text-sm font-medium text-gray-700 block mb-1">Schedule Time</label>
                <input
                  type="datetime-local"
                  value={scheduledTime}
                  onChange={(e) => setScheduledTime(e.target.value)}
                  className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm focus:ring-2 focus:ring-purple-500"
                />
              </div>
            </div>

            <div>
              <label className="text-sm font-medium text-gray-700 block mb-1">Video Path / URL</label>
              <input
                type="text"
                value={videoPath}
                onChange={(e) => setVideoPath(e.target.value)}
                placeholder="/tmp/videos/downloads/clip.mp4"
                className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm focus:ring-2 focus:ring-purple-500"
              />
            </div>

            <div>
              <label className="text-sm font-medium text-gray-700 block mb-1">Caption</label>
              <textarea
                value={caption}
                onChange={(e) => setCaption(e.target.value)}
                rows={2}
                placeholder="Write your caption..."
                className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm focus:ring-2 focus:ring-purple-500 resize-none"
              />
            </div>

            <div>
              <label className="text-sm font-medium text-gray-700 block mb-1">Hashtags</label>
              <input
                type="text"
                value={hashtagsStr}
                onChange={(e) => setHashtagsStr(e.target.value)}
                placeholder="anime, viral, fyp"
                className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm focus:ring-2 focus:ring-purple-500"
              />
            </div>

            <button
              onClick={handleSchedule}
              disabled={submitting || !accountId || !videoPath || !scheduledTime}
              className="w-full flex items-center justify-center gap-2 px-6 py-2.5 bg-purple-600 text-white rounded-lg hover:bg-purple-700 disabled:opacity-50 disabled:cursor-not-allowed text-sm font-semibold"
            >
              {submitting ? <Loader2 className="w-4 h-4 animate-spin" /> : <Calendar className="w-4 h-4" />}
              {submitting ? 'Scheduling...' : 'Schedule Post'}
            </button>
          </div>
        </div>
      )}

      {/* Scheduled Posts List */}
      <div className="bg-white rounded-lg shadow p-6">
        <h3 className="text-lg font-semibold text-gray-900 mb-4">
          Scheduled Posts
          <span className="text-sm font-normal text-gray-500 ml-2">({posts.length})</span>
        </h3>

        {posts.length === 0 ? (
          <p className="text-sm text-gray-500 text-center py-8">
            No scheduled posts. Create one above.
          </p>
        ) : (
          <div className="space-y-3">
            {posts.map((post) => (
              <div key={post.id} className="flex items-center justify-between p-4 border rounded-lg">
                <div className="flex items-center gap-4 min-w-0">
                  <div
                    className={`w-10 h-10 rounded-full flex items-center justify-center text-white text-xs font-bold flex-shrink-0 ${
                      post.platform === 'tiktok' ? 'bg-black' : 'bg-gradient-to-r from-purple-500 to-pink-500'
                    }`}
                  >
                    {post.platform === 'tiktok' ? 'TT' : 'IG'}
                  </div>
                  <div className="min-w-0">
                    <p className="text-sm font-medium text-gray-900 truncate">
                      {post.caption || 'No caption'}
                    </p>
                    <div className="flex items-center gap-3 text-xs text-gray-500 mt-0.5">
                      <span className="flex items-center gap-1">
                        <Clock className="w-3 h-3" />
                        {new Date(post.scheduled_time).toLocaleString()}
                      </span>
                      <span className={`px-1.5 py-0.5 rounded-full text-[10px] font-semibold ${statusColors[post.status] || 'bg-gray-100 text-gray-600'}`}>
                        {post.status}
                      </span>
                    </div>
                    {post.error_message && (
                      <p className="text-xs text-red-500 mt-1 truncate">{post.error_message}</p>
                    )}
                  </div>
                </div>

                <div className="flex items-center gap-2 flex-shrink-0">
                  {post.post_url && (
                    <a
                      href={post.post_url}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="p-2 text-gray-400 hover:text-purple-600 transition-colors"
                    >
                      <ExternalLink className="w-4 h-4" />
                    </a>
                  )}
                  {post.status === 'pending' && (
                    <button
                      onClick={() => onCancel(post.id)}
                      className="p-2 text-gray-400 hover:text-red-500 transition-colors"
                    >
                      <Trash2 className="w-4 h-4" />
                    </button>
                  )}
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
