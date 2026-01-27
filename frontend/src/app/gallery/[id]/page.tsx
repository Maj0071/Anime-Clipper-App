'use client';

import { useState } from 'react';
import { useRouter } from 'next/navigation';
import Link from 'next/link';
import CandidateGallery from '@/components/CandidateGallery';
import { Film, Download, Loader2, ArrowLeft, Sparkles } from 'lucide-react';

interface GalleryPageProps {
  params: { id: string };
}

export default function GalleryPage({ params }: GalleryPageProps) {
  const router = useRouter();
  const [selectedIds, setSelectedIds] = useState<string[]>([]);
  const [outputs, setOutputs] = useState<string[]>(['9:16']);
  const [processing, setProcessing] = useState(false);
  const [renderId, setRenderId] = useState<string | null>(null);
  const [status, setStatus] = useState<string | null>(null);
  const [renderFiles, setRenderFiles] = useState<Record<string, Record<string, string>> | null>(null);
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

  const startDownload = async () => {
    if (selectedIds.length === 0) return;
    setProcessing(true);
    setStatus('Processing clips with auto-captions...');
    setRenderFiles(null);
    try {
      const headers: Record<string, string> = { 'Content-Type': 'application/json', ...getHeaders() };
      const res = await fetch('/api/renders', {
        method: 'POST',
        headers,
        body: JSON.stringify({
          candidate_ids: selectedIds,
          template: 'clean',
          outputs: outputs.length ? outputs : ['9:16'],
          watermark: '',
          loudness: '-14',
          captions: 'off',
          auto_edit: true,
          hook_text: '',  // Will use random relatable caption
          cta_text: '',
        }),
      });
      if (!res.ok) throw new Error('Failed to process');
      const { render_id } = await res.json();
      setRenderId(render_id);
      setStatus('Adding captions and optimizing for social media...');
      // Poll for completion then auto-download
      const poll = async () => {
        const r = await fetch(`/api/renders/${render_id}`, { headers: getHeaders() });
        if (!r.ok) return;
        const d = await r.json();
        if (d.status === 'completed' && d.files) {
          setStatus('Done! Downloading to your Downloads folder...');
          setRenderFiles(d.files);
          // Auto-download all files
          for (const [candidateId, formats] of Object.entries(d.files as Record<string, Record<string, string>>)) {
            for (const format of Object.keys(formats)) {
              await downloadClip(candidateId, format, render_id);
              await new Promise(resolve => setTimeout(resolve, 500));
            }
          }
          setStatus('Downloaded! Check your Downloads folder.');
          setProcessing(false);
          return;
        }
        if (d.status === 'failed') {
          setStatus('Failed. Please try again.');
          setProcessing(false);
          return;
        }
        setTimeout(poll, 2000);
      };
      setTimeout(poll, 2000);
    } catch (e) {
      setStatus(e instanceof Error ? e.message : 'Failed');
      setProcessing(false);
    }
  };

  const downloadClip = async (candidateId: string, format: string, renderIdParam?: string) => {
    const useRenderId = renderIdParam || renderId;
    if (!useRenderId) return;

    const downloadKey = `${candidateId}-${format}`;
    setDownloading(downloadKey);
    try {
      const urlFormat = format.replace(':', 'x');
      const response = await fetch(`/api/renders/${useRenderId}/download/${candidateId}/${urlFormat}`, {
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
    } finally {
      setDownloading(null);
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

        {/* Download Panel - Simple and Clean */}
        <div className="mt-10 bg-white rounded-xl shadow-lg p-6">
          <div className="flex items-center gap-3 mb-6">
            <div className="bg-gradient-to-r from-purple-600 to-pink-600 p-3 rounded-xl">
              <Download className="w-6 h-6 text-white" />
            </div>
            <div>
              <h2 className="text-xl font-bold text-gray-900">Download for Social Media</h2>
              <p className="text-sm text-gray-500">Auto-adds relatable captions + optimizes for posting</p>
            </div>
          </div>

          {/* Format Selection */}
          <div className="mb-6">
            <label className="block text-sm font-medium text-gray-700 mb-3">Choose format:</label>
            <div className="flex flex-wrap gap-3">
              {[
                { value: '9:16', label: 'TikTok / Reels', desc: 'Vertical' },
                { value: '1:1', label: 'Instagram Feed', desc: 'Square' },
                { value: '4:5', label: 'Instagram Story', desc: 'Portrait' },
              ].map((format) => (
                <label
                  key={format.value}
                  className={`flex items-center gap-3 px-4 py-3 rounded-lg border-2 cursor-pointer transition-all ${
                    outputs.includes(format.value)
                      ? 'border-purple-500 bg-purple-50'
                      : 'border-gray-200 hover:border-gray-300'
                  }`}
                >
                  <input
                    type="checkbox"
                    checked={outputs.includes(format.value)}
                    onChange={() => toggleOutput(format.value)}
                    className="w-4 h-4 text-purple-600 rounded"
                  />
                  <div>
                    <p className="font-medium text-gray-900">{format.label}</p>
                    <p className="text-xs text-gray-500">{format.desc}</p>
                  </div>
                </label>
              ))}
            </div>
          </div>

          {/* Download Button */}
          <button
            onClick={startDownload}
            disabled={selectedIds.length === 0 || processing}
            className="w-full px-6 py-4 bg-gradient-to-r from-purple-600 to-pink-600 text-white font-bold text-lg rounded-xl hover:from-purple-700 hover:to-pink-700 disabled:opacity-50 disabled:cursor-not-allowed flex items-center justify-center gap-3 transition-all transform hover:scale-[1.02]"
          >
            {processing ? (
              <>
                <Loader2 className="w-6 h-6 animate-spin" />
                Processing...
              </>
            ) : (
              <>
                <Download className="w-6 h-6" />
                Download {selectedIds.length} Clip{selectedIds.length !== 1 ? 's' : ''}
              </>
            )}
          </button>

          {selectedIds.length === 0 && (
            <p className="text-center text-sm text-amber-600 mt-3">
              Select clips above to download
            </p>
          )}

          {/* Status */}
          {status && (
            <div className={`mt-4 p-4 rounded-lg text-sm flex items-center gap-2 ${
              status.includes('Done') || status.includes('Downloaded')
                ? 'bg-green-50 border border-green-200 text-green-800'
                : 'bg-blue-50 border border-blue-200 text-blue-800'
            }`}>
              {processing && <Loader2 className="w-4 h-4 animate-spin" />}
              {(status.includes('Done') || status.includes('Downloaded')) && <Sparkles className="w-4 h-4" />}
              {status}
            </div>
          )}

          {/* What you get */}
          <div className="mt-6 p-4 bg-gray-50 rounded-lg">
            <p className="text-sm font-medium text-gray-700 mb-2">Each clip includes:</p>
            <ul className="text-sm text-gray-600 space-y-1">
              <li className="flex items-center gap-2">
                <span className="text-green-500">✓</span> Random relatable caption overlay
              </li>
              <li className="flex items-center gap-2">
                <span className="text-green-500">✓</span> Smooth fade transitions
              </li>
              <li className="flex items-center gap-2">
                <span className="text-green-500">✓</span> Enhanced colors for social media
              </li>
              <li className="flex items-center gap-2">
                <span className="text-green-500">✓</span> Optimized audio levels
              </li>
            </ul>
          </div>
        </div>
      </main>
    </div>
  );
}
