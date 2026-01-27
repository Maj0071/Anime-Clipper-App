'use client';

import { useState } from 'react';
import { useRouter } from 'next/navigation';
import Link from 'next/link';
import CandidateGallery from '@/components/CandidateGallery';
import { Film, Download, Loader2, ArrowLeft, Share2, Sparkles, Type, Zap } from 'lucide-react';

interface GalleryPageProps {
  params: { id: string };
}

export default function GalleryPage({ params }: GalleryPageProps) {
  const router = useRouter();
  const [selectedIds, setSelectedIds] = useState<string[]>([]);
  const [template, setTemplate] = useState('clean');
  const [outputs, setOutputs] = useState<string[]>(['9:16']);
  const [watermark, setWatermark] = useState('@myanime');
  const [rendering, setRendering] = useState(false);
  const [renderId, setRenderId] = useState<string | null>(null);
  const [renderStatus, setRenderStatus] = useState<string | null>(null);
  const [renderFiles, setRenderFiles] = useState<Record<string, Record<string, string>> | null>(null);
  // Auto-editing settings
  const [autoEdit, setAutoEdit] = useState(true);
  const [hookText, setHookText] = useState('');
  const [ctaText, setCtaText] = useState('Follow for more!');
  const [downloading, setDownloading] = useState<string | null>(null);

  const toggleOutput = (r: string) => {
    setOutputs((prev) =>
      prev.includes(r) ? prev.filter((x) => x !== r) : [...prev, r]
    );
  };

  const getHeaders = (): Record<string, string> => {
    const h: Record<string, string> = {};
    if (typeof localStorage !== 'undefined' && localStorage.getItem('token')) {
      h['Authorization'] = `Bearer ${localStorage.getItem('token')}`;
    }
    return h;
  };

  const startRender = async () => {
    if (selectedIds.length === 0) return;
    setRendering(true);
    setRenderStatus(null);
    setRenderFiles(null);
    try {
      const headers: Record<string, string> = { 'Content-Type': 'application/json', ...getHeaders() };
      const res = await fetch('/api/renders', {
        method: 'POST',
        headers,
        body: JSON.stringify({
          candidate_ids: selectedIds,
          template,
          outputs: outputs.length ? outputs : ['9:16'],
          watermark: watermark || undefined,
          loudness: '-14',
          captions: 'on',
          // Auto-editing settings for TikTok/Instagram ready clips
          auto_edit: autoEdit,
          hook_text: hookText || undefined,
          cta_text: ctaText || undefined,
        }),
      });
      if (!res.ok) throw new Error('Failed to start render');
      const { render_id } = await res.json();
      setRenderId(render_id);
      setRenderStatus('Rendering clips with auto-editing for social media...');
      // Poll for completion
      const poll = async () => {
        const r = await fetch(`/api/renders/${render_id}`, { headers: getHeaders() });
        if (!r.ok) return;
        const d = await r.json();
        setRenderStatus(`Status: ${d.status}`);
        if (d.status === 'completed' && d.files) {
          setRenderStatus('Ready to post! Your clips are optimized for TikTok & Instagram.');
          setRenderFiles(d.files);
          setRendering(false);
          return;
        }
        if (d.status === 'failed') {
          setRenderStatus('Render failed. Please try again.');
          setRendering(false);
          return;
        }
        setTimeout(poll, 3000);
      };
      setTimeout(poll, 2000);
    } catch (e) {
      setRenderStatus(e instanceof Error ? e.message : 'Render failed');
      setRendering(false);
    }
  };

  const downloadClip = async (candidateId: string, format: string) => {
    const downloadKey = `${candidateId}-${format}`;
    setDownloading(downloadKey);
    try {
      const urlFormat = format.replace(':', 'x');
      const response = await fetch(`/api/renders/${renderId}/download/${candidateId}/${urlFormat}`, {
        headers: getHeaders(),
      });
      if (!response.ok) throw new Error('Download failed');

      // Get the blob and trigger download
      const blob = await response.blob();
      const url = window.URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `clip_${candidateId.slice(0, 8)}_${urlFormat}.mp4`;
      document.body.appendChild(a);
      a.click();
      window.URL.revokeObjectURL(url);
      document.body.removeChild(a);
    } catch (e) {
      console.error('Download failed:', e);
      alert('Download failed. Please try again.');
    } finally {
      setDownloading(null);
    }
  };

  const downloadAll = async () => {
    if (!renderFiles || !renderId) return;
    setDownloading('all');

    // Download each file sequentially
    for (const [candidateId, formats] of Object.entries(renderFiles)) {
      for (const format of Object.keys(formats)) {
        await downloadClip(candidateId, format);
        // Small delay between downloads
        await new Promise(resolve => setTimeout(resolve, 500));
      }
    }
    setDownloading(null);
  };

  return (
    <div className="min-h-screen bg-gray-50">
      <header className="bg-white shadow-sm sticky top-0 z-10">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-4">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-4">
              <Link
                href="/"
                className="p-2 text-gray-600 hover:text-gray-900 hover:bg-gray-100 rounded-lg"
              >
                <ArrowLeft className="w-5 h-5" />
              </Link>
              <div className="flex items-center gap-3">
                <div className="bg-purple-600 p-2 rounded-lg">
                  <Film className="w-6 h-6 text-white" />
                </div>
                <div>
                  <h1 className="text-xl font-bold text-gray-900">Clip Gallery</h1>
                  <p className="text-sm text-gray-500">Video {params.id.slice(0, 8)}…</p>
                </div>
              </div>
            </div>
          </div>
        </div>
      </header>

      <main className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
        <CandidateGallery videoId={params.id} onSelectCandidates={setSelectedIds} />

        {/* Export / Render panel */}
        <div className="mt-10 bg-white rounded-xl shadow-lg p-6">
          <div className="flex items-center gap-2 mb-6">
            <Share2 className="w-6 h-6 text-purple-600" />
            <h2 className="text-xl font-bold text-gray-900">Export for TikTok & Instagram</h2>
            <span className="ml-2 px-2 py-1 bg-gradient-to-r from-pink-500 to-purple-500 text-white text-xs font-medium rounded-full flex items-center gap-1">
              <Sparkles className="w-3 h-3" />
              Auto-Edit Ready
            </span>
          </div>

          <div className="grid md:grid-cols-2 gap-8">
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-2">Caption style</label>
              <select
                value={template}
                onChange={(e) => setTemplate(e.target.value)}
                className="w-full px-4 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-purple-500"
              >
                <option value="clean">Clean</option>
                <option value="manga">Manga Pop</option>
                <option value="impact">Impact Text</option>
                <option value="karaoke">Karaoke</option>
              </select>
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-2">Aspect ratio</label>
              <div className="flex flex-wrap gap-2">
                {['9:16', '1:1', '4:5'].map((r) => (
                  <label key={r} className="flex items-center gap-2 cursor-pointer">
                    <input
                      type="checkbox"
                      checked={outputs.includes(r)}
                      onChange={() => toggleOutput(r)}
                      className="w-4 h-4 text-purple-600 rounded"
                    />
                    <span className="text-sm">{r}</span>
                  </label>
                ))}
              </div>
              <p className="text-xs text-gray-500 mt-1">9:16 = TikTok / Reels, 1:1 = IG Feed, 4:5 = IG Story</p>
            </div>
          </div>

          <div className="mt-6 grid md:grid-cols-2 gap-8">
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-2">Watermark</label>
              <input
                type="text"
                value={watermark}
                onChange={(e) => setWatermark(e.target.value)}
                placeholder="@yourhandle"
                className="w-full px-4 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-purple-500"
              />
            </div>
            <div>
              <label className="flex items-center gap-2 cursor-pointer">
                <input
                  type="checkbox"
                  checked={autoEdit}
                  onChange={(e) => setAutoEdit(e.target.checked)}
                  className="w-4 h-4 text-purple-600 rounded"
                />
                <span className="text-sm font-medium text-gray-700">Auto-Edit for Social Media</span>
              </label>
              <p className="text-xs text-gray-500 mt-1 ml-6">Adds fade transitions, color enhancement, and audio optimization</p>
            </div>
          </div>

          {autoEdit && (
            <div className="mt-6 p-4 bg-purple-50 rounded-lg border border-purple-100">
              <div className="flex items-center gap-2 mb-4">
                <Zap className="w-5 h-5 text-purple-600" />
                <h3 className="font-medium text-gray-900">Auto-Edit Settings</h3>
              </div>
              <div className="grid md:grid-cols-2 gap-4">
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-2 flex items-center gap-1">
                    <Type className="w-4 h-4" />
                    Hook Text (first 2 sec)
                  </label>
                  <input
                    type="text"
                    value={hookText}
                    onChange={(e) => setHookText(e.target.value)}
                    placeholder="Watch this!"
                    className="w-full px-4 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-purple-500"
                  />
                  <p className="text-xs text-gray-500 mt-1">Attention-grabbing text at the start</p>
                </div>
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-2">Call-to-Action (end)</label>
                  <input
                    type="text"
                    value={ctaText}
                    onChange={(e) => setCtaText(e.target.value)}
                    placeholder="Follow for more!"
                    className="w-full px-4 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-purple-500"
                  />
                  <p className="text-xs text-gray-500 mt-1">Appears in the last 1.5 seconds</p>
                </div>
              </div>
            </div>
          )}

          <div className="mt-6 flex items-center gap-4">
            <button
              onClick={startRender}
              disabled={selectedIds.length === 0 || rendering}
              className="px-6 py-3 bg-purple-600 text-white font-medium rounded-lg hover:bg-purple-700 disabled:opacity-50 disabled:cursor-not-allowed flex items-center gap-2"
            >
              {rendering ? <Loader2 className="w-5 h-5 animate-spin" /> : <Download className="w-5 h-5" />}
              {rendering ? 'Rendering…' : `Render ${selectedIds.length} clip(s)`}
            </button>
            {selectedIds.length === 0 && (
              <p className="text-sm text-amber-600">Select at least one clip above.</p>
            )}
          </div>

          {renderStatus && (
            <div className={`mt-4 p-4 rounded-lg text-sm ${
              renderFiles ? 'bg-green-50 border border-green-200 text-green-800' : 'bg-blue-50 border border-blue-200 text-blue-800'
            }`}>
              {renderStatus}
            </div>
          )}

          {/* Download Section */}
          {renderFiles && Object.keys(renderFiles).length > 0 && (
            <div className="mt-6 p-6 bg-gradient-to-r from-purple-50 to-pink-50 rounded-xl border border-purple-200">
              <div className="flex items-center justify-between mb-4">
                <h3 className="text-lg font-bold text-gray-900 flex items-center gap-2">
                  <Download className="w-5 h-5 text-purple-600" />
                  Download Your Clips
                  <span className="text-sm font-normal text-gray-500">
                    ({Object.values(renderFiles).reduce((acc, f) => acc + Object.keys(f).length, 0)} files)
                  </span>
                </h3>
                <button
                  onClick={downloadAll}
                  disabled={downloading === 'all'}
                  className="inline-flex items-center gap-2 px-4 py-2 bg-gradient-to-r from-purple-600 to-pink-600 text-white text-sm font-medium rounded-lg hover:from-purple-700 hover:to-pink-700 transition-colors disabled:opacity-50"
                >
                  {downloading === 'all' ? (
                    <Loader2 className="w-4 h-4 animate-spin" />
                  ) : (
                    <Download className="w-4 h-4" />
                  )}
                  Download All
                </button>
              </div>
              <p className="text-sm text-green-600 mb-4 flex items-center gap-2">
                <Sparkles className="w-4 h-4" />
                Ready to post! Clips are optimized for TikTok & Instagram with auto-editing applied.
              </p>
              <div className="space-y-4">
                {Object.entries(renderFiles).map(([candidateId, formats]) => (
                  <div key={candidateId} className="bg-white rounded-lg p-4 shadow-sm">
                    <p className="text-sm text-gray-600 mb-3 font-medium">Clip {candidateId.slice(0, 8)}...</p>
                    <div className="flex flex-wrap gap-2">
                      {Object.entries(formats).map(([format, url]) => {
                        const downloadKey = `${candidateId}-${format}`;
                        const isDownloading = downloading === downloadKey;
                        return (
                          <button
                            key={format}
                            onClick={() => downloadClip(candidateId, format)}
                            disabled={isDownloading || downloading === 'all'}
                            className="inline-flex items-center gap-2 px-4 py-2 bg-purple-600 text-white text-sm font-medium rounded-lg hover:bg-purple-700 transition-colors disabled:opacity-50"
                          >
                            {isDownloading ? (
                              <Loader2 className="w-4 h-4 animate-spin" />
                            ) : (
                              <Download className="w-4 h-4" />
                            )}
                            {format === '9:16' ? 'TikTok/Reels' : format === '1:1' ? 'IG Feed' : 'IG Story'}
                          </button>
                        );
                      })}
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      </main>
    </div>
  );
}
