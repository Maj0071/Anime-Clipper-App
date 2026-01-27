'use client';

import { useState } from 'react';
import { useRouter } from 'next/navigation';
import Link from 'next/link';
import CandidateGallery from '@/components/CandidateGallery';
import { Film, Download, Loader2, ArrowLeft, Share2 } from 'lucide-react';

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
        }),
      });
      if (!res.ok) throw new Error('Failed to start render');
      const { render_id } = await res.json();
      setRenderId(render_id);
      setRenderStatus('Rendering started. This may take a few minutes.');
      // Poll for completion
      const poll = async () => {
        const r = await fetch(`/api/renders/${render_id}`, { headers: getHeaders() });
        if (!r.ok) return;
        const d = await r.json();
        setRenderStatus(`Status: ${d.status}`);
        if (d.status === 'completed' && d.files) {
          setRenderStatus('Render complete! Your clips are ready to download.');
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
              <p className="text-xs text-gray-500 mt-1">9:16 = TikTok / Reels</p>
            </div>
          </div>

          <div className="mt-4">
            <label className="block text-sm font-medium text-gray-700 mb-2">Watermark</label>
            <input
              type="text"
              value={watermark}
              onChange={(e) => setWatermark(e.target.value)}
              placeholder="@yourhandle"
              className="w-full max-w-xs px-4 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-purple-500"
            />
          </div>

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
              <h3 className="text-lg font-bold text-gray-900 mb-4 flex items-center gap-2">
                <Download className="w-5 h-5 text-purple-600" />
                Download Your Clips
              </h3>
              <div className="space-y-4">
                {Object.entries(renderFiles).map(([candidateId, formats]) => (
                  <div key={candidateId} className="bg-white rounded-lg p-4 shadow-sm">
                    <p className="text-sm text-gray-600 mb-2">Clip {candidateId.slice(0, 8)}...</p>
                    <div className="flex flex-wrap gap-2">
                      {Object.entries(formats).map(([format, url]) => (
                        <a
                          key={format}
                          href={`/api/renders/${renderId}/download/${candidateId}/${format.replace(':', 'x')}`}
                          download
                          className="inline-flex items-center gap-2 px-4 py-2 bg-purple-600 text-white text-sm font-medium rounded-lg hover:bg-purple-700 transition-colors"
                        >
                          <Download className="w-4 h-4" />
                          {format}
                        </a>
                      ))}
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
