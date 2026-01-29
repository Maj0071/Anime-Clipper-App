'use client';

import { useState } from 'react';
import { Sparkles, Loader2, Download, Zap, Film, Scissors, Clapperboard, MonitorPlay } from 'lucide-react';

interface AutoEditStudioProps {
  selectedCandidateIds: string[];
  videoId: string;
}

interface Template {
  id: string;
  name: string;
  tagline: string;
  badge: string;
  badgeColor: string;
  icon: React.ReactNode;
  features: string[];
}

const TEMPLATES: Template[] = [
  {
    id: 'anime_hype',
    name: 'Velocity',
    tagline: 'The #1 viral anime style',
    badge: 'VIRAL',
    badgeColor: 'bg-red-500',
    icon: <Zap className="w-6 h-6" />,
    features: [
      'Extreme speed ramps (0.3x/2.2x)',
      'Hyper-saturated colors',
      'White flash transitions',
      'Bass-boosted impact audio',
    ],
  },
  {
    id: 'clean_flow',
    name: 'Flow',
    tagline: 'Smooth & mesmerizing',
    badge: 'SMOOTH',
    badgeColor: 'bg-blue-500',
    icon: <Film className="w-6 h-6" />,
    features: [
      'Dreamy warm color grade',
      'Smooth dissolve transitions',
      'Gentle Ken Burns drift',
      'Deep vignette glow',
    ],
  },
  {
    id: 'hard_cuts',
    name: 'Hard Cuts',
    tagline: 'Raw aggressive energy',
    badge: 'ENERGY',
    badgeColor: 'bg-orange-500',
    icon: <Scissors className="w-6 h-6" />,
    features: [
      'Instant hard cuts (0ms)',
      'Near-monochrome dark look',
      'Extreme contrast + crush',
      'Cyan shadow tint',
    ],
  },
  {
    id: 'cinematic',
    name: 'Cinematic',
    tagline: 'Film-quality AMV feel',
    badge: 'FILM',
    badgeColor: 'bg-amber-600',
    icon: <Clapperboard className="w-6 h-6" />,
    features: [
      'Letterbox + film grain',
      'Dramatic slow-mo peaks',
      'Elegant fade transitions',
      'Muted warm palette',
    ],
  },
  {
    id: 'glitch',
    name: 'Glitch',
    tagline: 'Cyberpunk digital chaos',
    badge: 'CYBER',
    badgeColor: 'bg-purple-600',
    icon: <MonitorPlay className="w-6 h-6" />,
    features: [
      'Extreme RGB split effect',
      'Neon-boosted saturation',
      'Pixelize transitions',
      'Random speed stutters',
    ],
  },
];

export default function AutoEditStudio({ selectedCandidateIds, videoId }: AutoEditStudioProps) {
  const [selectedTemplate, setSelectedTemplate] = useState<string | null>(null);
  const [outputs, setOutputs] = useState<string[]>(['9:16']);
  const [maxDuration, setMaxDuration] = useState(30);
  const [processing, setProcessing] = useState(false);
  const [renderId, setRenderId] = useState<string | null>(null);
  const [status, setStatus] = useState<string | null>(null);
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

  const startAutoEdit = async () => {
    if (selectedCandidateIds.length === 0 || !selectedTemplate) return;
    setProcessing(true);
    setStatus(`Applying ${TEMPLATES.find(t => t.id === selectedTemplate)?.name} template...`);
    setRenderFiles(null);

    try {
      const headers: Record<string, string> = { 'Content-Type': 'application/json', ...getHeaders() };
      const res = await fetch('/api/renders/auto-edit', {
        method: 'POST',
        headers,
        body: JSON.stringify({
          candidate_ids: selectedCandidateIds,
          auto_edit_template: selectedTemplate,
          outputs: outputs.length ? outputs : ['9:16'],
          max_duration: maxDuration,
          loudness: '-14',
        }),
      });
      if (!res.ok) throw new Error('Failed to start auto-edit');
      const { render_id } = await res.json();
      setRenderId(render_id);
      setStatus('Processing with FFmpeg effects...');

      const poll = async () => {
        const r = await fetch(`/api/renders/${render_id}`, { headers: getHeaders() });
        if (!r.ok) return;
        const d = await r.json();
        if (d.status === 'completed' && d.files) {
          setRenderFiles(d.files);
          // Auto-download all files
          let delay = 0;
          for (const [candidateId, formats] of Object.entries(d.files as Record<string, Record<string, string>>)) {
            for (const format of Object.keys(formats)) {
              setTimeout(() => downloadClip(candidateId, format, render_id), delay);
              delay += 800;
            }
          }
          setStatus('Done! Check your downloads.');
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

  const downloadClip = (candidateId: string, format: string, renderIdParam?: string) => {
    const useRenderId = renderIdParam || renderId;
    if (!useRenderId) return;

    const urlFormat = format.replace(':', 'x');
    const downloadUrl = `/api/renders/${useRenderId}/download/${candidateId}/${urlFormat}`;
    const a = document.createElement('a');
    a.href = downloadUrl;
    a.download = `clip_${candidateId.slice(0, 8)}_${urlFormat}_auto.mp4`;
    a.style.display = 'none';
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
  };

  return (
    <div className="mt-10 bg-white rounded-xl shadow-lg p-6">
      {/* Header */}
      <div className="flex items-center gap-3 mb-6">
        <div className="bg-gradient-to-r from-orange-500 to-red-600 p-3 rounded-xl">
          <Sparkles className="w-6 h-6 text-white" />
        </div>
        <div>
          <h2 className="text-xl font-bold text-gray-900">Auto-Edit Studio</h2>
          <p className="text-sm text-gray-500">Apply trending templates with viral-ready effects</p>
        </div>
      </div>

      {/* Template Cards */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-5 gap-4 mb-6">
        {TEMPLATES.map((tmpl) => (
          <button
            key={tmpl.id}
            onClick={() => setSelectedTemplate(tmpl.id === selectedTemplate ? null : tmpl.id)}
            className={`relative text-left p-4 rounded-xl border-2 transition-all ${
              selectedTemplate === tmpl.id
                ? 'border-orange-500 bg-orange-50 shadow-md'
                : 'border-gray-200 hover:border-gray-300 hover:shadow-sm'
            }`}
          >
            {/* Badge */}
            <span className={`absolute top-2 right-2 text-[10px] font-bold text-white px-2 py-0.5 rounded-full ${tmpl.badgeColor}`}>
              {tmpl.badge}
            </span>

            {/* Icon + Name */}
            <div className={`mb-2 ${selectedTemplate === tmpl.id ? 'text-orange-600' : 'text-gray-600'}`}>
              {tmpl.icon}
            </div>
            <h3 className="font-bold text-gray-900 text-sm">{tmpl.name}</h3>
            <p className="text-xs text-gray-500 mb-3">{tmpl.tagline}</p>

            {/* Features */}
            <ul className="space-y-1">
              {tmpl.features.map((feat, i) => (
                <li key={i} className="text-xs text-gray-600 flex items-start gap-1.5">
                  <span className="text-orange-400 mt-0.5 flex-shrink-0">&#x2022;</span>
                  {feat}
                </li>
              ))}
            </ul>
          </button>
        ))}
      </div>

      {/* Controls (shown after selecting template) */}
      {selectedTemplate && (
        <div className="space-y-4 mb-6 p-4 bg-gray-50 rounded-lg">
          {/* Aspect Ratio */}
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-2">Aspect ratio:</label>
            <div className="flex flex-wrap gap-3">
              {[
                { value: '9:16', label: 'TikTok / Reels' },
                { value: '1:1', label: 'Square' },
                { value: '4:5', label: 'Portrait' },
              ].map((fmt) => (
                <label
                  key={fmt.value}
                  className={`flex items-center gap-2 px-3 py-2 rounded-lg border cursor-pointer text-sm transition-all ${
                    outputs.includes(fmt.value)
                      ? 'border-orange-400 bg-orange-50 text-orange-700'
                      : 'border-gray-200 text-gray-600 hover:border-gray-300'
                  }`}
                >
                  <input
                    type="checkbox"
                    checked={outputs.includes(fmt.value)}
                    onChange={() => toggleOutput(fmt.value)}
                    className="w-3.5 h-3.5 text-orange-500 rounded"
                  />
                  {fmt.label} ({fmt.value})
                </label>
              ))}
            </div>
          </div>

          {/* Duration Slider */}
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-2">
              Max duration: <span className="text-orange-600 font-bold">{maxDuration}s</span>
            </label>
            <input
              type="range"
              min={5}
              max={60}
              value={maxDuration}
              onChange={(e) => setMaxDuration(Number(e.target.value))}
              className="w-full accent-orange-500"
            />
            <div className="flex justify-between text-xs text-gray-400 mt-1">
              <span>5s</span>
              <span>30s</span>
              <span>60s</span>
            </div>
          </div>
        </div>
      )}

      {/* Process Button */}
      <button
        onClick={startAutoEdit}
        disabled={selectedCandidateIds.length === 0 || !selectedTemplate || processing}
        className="w-full px-6 py-4 bg-gradient-to-r from-orange-500 to-red-600 text-white font-bold text-lg rounded-xl hover:from-orange-600 hover:to-red-700 disabled:opacity-50 disabled:cursor-not-allowed flex items-center justify-center gap-3 transition-all transform hover:scale-[1.02]"
      >
        {processing ? (
          <>
            <Loader2 className="w-6 h-6 animate-spin" />
            Auto-Editing...
          </>
        ) : (
          <>
            <Sparkles className="w-6 h-6" />
            Auto-Edit {selectedCandidateIds.length} Clip{selectedCandidateIds.length !== 1 ? 's' : ''}
            {selectedTemplate && (
              <span className="text-sm opacity-80">
                ({TEMPLATES.find(t => t.id === selectedTemplate)?.name})
              </span>
            )}
          </>
        )}
      </button>

      {selectedCandidateIds.length === 0 && (
        <p className="text-center text-sm text-amber-600 mt-3">
          Select clips above to auto-edit
        </p>
      )}

      {!selectedTemplate && selectedCandidateIds.length > 0 && (
        <p className="text-center text-sm text-amber-600 mt-3">
          Choose a template above to get started
        </p>
      )}

      {/* Status */}
      {status && (
        <div className={`mt-4 p-4 rounded-lg text-sm flex items-center gap-2 ${
          status.includes('Done')
            ? 'bg-green-50 border border-green-200 text-green-800'
            : status.includes('Failed')
            ? 'bg-red-50 border border-red-200 text-red-800'
            : 'bg-orange-50 border border-orange-200 text-orange-800'
        }`}>
          {processing && <Loader2 className="w-4 h-4 animate-spin" />}
          {status.includes('Done') && <Sparkles className="w-4 h-4" />}
          {status}
        </div>
      )}

      {/* Download buttons for completed renders */}
      {renderFiles && (
        <div className="mt-4 space-y-2">
          {Object.entries(renderFiles).map(([candidateId, formats]) =>
            Object.entries(formats as Record<string, string>).map(([format]) => (
              <button
                key={`${candidateId}-${format}`}
                onClick={() => downloadClip(candidateId, format)}
                className="inline-flex items-center gap-2 px-4 py-2 mr-2 bg-gray-100 hover:bg-gray-200 text-gray-800 text-sm rounded-lg transition-colors"
              >
                <Download className="w-4 h-4" />
                Clip {candidateId.slice(0, 6)} — {format}
              </button>
            ))
          )}
        </div>
      )}
    </div>
  );
}
