'use client';

import { useState } from 'react';
import { Sparkles, Loader2, Download, Zap, Film, Scissors, Clapperboard, MonitorPlay, Flame, Music, MessageSquare, Wand2, Target, Shuffle, Focus } from 'lucide-react';

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

// Caption style options
const CAPTION_STYLES = [
  { id: 'pop', name: 'Pop', description: 'Scale up on each word' },
  { id: 'bounce', name: 'Bounce', description: 'Vertical bounce animation' },
  { id: 'highlight', name: 'Highlight', description: 'Color change on keywords' },
  { id: 'glow', name: 'Glow', description: 'Neon glow effect' },
];

// Effect intensity options
const EFFECT_INTENSITIES = [
  { id: 'low', name: 'Subtle', description: 'Light effects' },
  { id: 'medium', name: 'Balanced', description: 'Default intensity' },
  { id: 'high', name: 'Maximum', description: 'Heavy effects' },
];

// Hook text templates
const HOOK_TEMPLATES = [
  { id: 'wait_for_it', text: 'Wait for it...' },
  { id: 'insane', text: 'This scene is insane' },
  { id: 'watch_end', text: 'Watch until the end' },
  { id: 'hits_different', text: 'This hits different' },
  { id: 'goosebumps', text: 'Gave me goosebumps' },
  { id: 'peak_fiction', text: 'Peak fiction' },
];

// Hook text styles
const HOOK_STYLES = [
  { id: 'bold', name: 'Bold', description: 'Classic white text' },
  { id: 'glitch', name: 'Glitch', description: 'Cyberpunk style' },
  { id: 'neon', name: 'Neon', description: 'Glowing effect' },
];

const TEMPLATES: Template[] = [
  {
    id: 'viral_anime',
    name: 'Viral Anime',
    tagline: 'Maximum TikTok impact',
    badge: 'NEW',
    badgeColor: 'bg-pink-500',
    icon: <Flame className="w-6 h-6" />,
    features: [
      'White flash on impacts',
      'Dynamic screen shake',
      'Zoom pulses on action',
      'VHS scanlines + glitch',
      'Beat sync support',
    ],
  },
  {
    id: 'anime_hype',
    name: 'Velocity',
    tagline: 'The #1 viral anime style',
    badge: 'VIRAL',
    badgeColor: 'bg-red-500',
    icon: <Zap className="w-6 h-6" />,
    features: [
      'Extreme speed ramps (0.3x/2.2x)',
      'WHITE FLASH impacts (NEW)',
      'Enhanced screen shake',
      'Hyper-saturated colors',
      'Beat-synced cuts',
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
      'Smooth flow transitions',
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
      'Whip pan transitions',
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

  // NEW: Viral editing options
  const [enableBeatSync, setEnableBeatSync] = useState(false);
  const [captionText, setCaptionText] = useState('');
  const [captionStyle, setCaptionStyle] = useState('pop');
  const [effectIntensity, setEffectIntensity] = useState('medium');
  const [showAdvanced, setShowAdvanced] = useState(false);

  // MEDIUM PRIORITY: Hook optimization
  const [enableSmartReframe, setEnableSmartReframe] = useState(true);
  const [hookText, setHookText] = useState('');
  const [hookStyle, setHookStyle] = useState('bold');
  const [reorderForHook, setReorderForHook] = useState(false);

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
          // NEW: Viral editing options
          enable_beat_sync: enableBeatSync,
          caption_text: captionText.trim() || null,
          caption_style: captionStyle,
          effect_intensity: effectIntensity,
          // MEDIUM PRIORITY: Hook optimization
          enable_smart_reframe: enableSmartReframe,
          hook_text: hookText.trim() || null,
          hook_style: hookStyle,
          reorder_for_hook: reorderForHook,
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

          {/* Beat Sync Toggle - The #1 Viral Factor */}
          <div className="pt-2 border-t border-gray-200">
            <label className="flex items-center gap-3 cursor-pointer group">
              <div className="relative">
                <input
                  type="checkbox"
                  checked={enableBeatSync}
                  onChange={(e) => setEnableBeatSync(e.target.checked)}
                  className="sr-only"
                />
                <div className={`w-11 h-6 rounded-full transition-colors ${enableBeatSync ? 'bg-orange-500' : 'bg-gray-300'}`}>
                  <div className={`absolute top-0.5 left-0.5 w-5 h-5 bg-white rounded-full shadow transition-transform ${enableBeatSync ? 'translate-x-5' : ''}`} />
                </div>
              </div>
              <div className="flex items-center gap-2">
                <Music className="w-4 h-4 text-orange-500" />
                <span className="text-sm font-medium text-gray-700">Beat Sync</span>
                <span className="text-[10px] bg-red-500 text-white px-1.5 py-0.5 rounded-full font-bold">#1 VIRAL</span>
              </div>
            </label>
            <p className="text-xs text-gray-500 mt-1 ml-14">Align cuts to music beats for maximum impact</p>
          </div>

          {/* Advanced Options Toggle */}
          <button
            type="button"
            onClick={() => setShowAdvanced(!showAdvanced)}
            className="flex items-center gap-2 text-sm text-gray-600 hover:text-orange-600 transition-colors mt-2"
          >
            <Wand2 className="w-4 h-4" />
            {showAdvanced ? 'Hide' : 'Show'} Advanced Options
          </button>

          {/* Advanced Options Panel */}
          {showAdvanced && (
            <div className="space-y-4 pt-3 border-t border-gray-200 mt-3">
              {/* Caption Input */}
              <div>
                <label className="flex items-center gap-2 text-sm font-medium text-gray-700 mb-2">
                  <MessageSquare className="w-4 h-4" />
                  Caption Text (optional)
                </label>
                <input
                  type="text"
                  value={captionText}
                  onChange={(e) => setCaptionText(e.target.value)}
                  placeholder="e.g., This scene is insane..."
                  className="w-full px-3 py-2 border border-gray-200 rounded-lg text-sm focus:ring-2 focus:ring-orange-500 focus:border-transparent"
                  maxLength={100}
                />
                <p className="text-xs text-gray-400 mt-1">Animated caption overlay on your clip</p>
              </div>

              {/* Caption Style */}
              {captionText && (
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-2">Caption Style:</label>
                  <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
                    {CAPTION_STYLES.map((style) => (
                      <button
                        key={style.id}
                        type="button"
                        onClick={() => setCaptionStyle(style.id)}
                        className={`px-3 py-2 rounded-lg border text-sm transition-all ${
                          captionStyle === style.id
                            ? 'border-orange-400 bg-orange-50 text-orange-700'
                            : 'border-gray-200 text-gray-600 hover:border-gray-300'
                        }`}
                      >
                        <div className="font-medium">{style.name}</div>
                        <div className="text-[10px] text-gray-500">{style.description}</div>
                      </button>
                    ))}
                  </div>
                </div>
              )}

              {/* Effect Intensity */}
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-2">Effect Intensity:</label>
                <div className="flex gap-2">
                  {EFFECT_INTENSITIES.map((intensity) => (
                    <button
                      key={intensity.id}
                      type="button"
                      onClick={() => setEffectIntensity(intensity.id)}
                      className={`flex-1 px-3 py-2 rounded-lg border text-sm transition-all ${
                        effectIntensity === intensity.id
                          ? 'border-orange-400 bg-orange-50 text-orange-700'
                          : 'border-gray-200 text-gray-600 hover:border-gray-300'
                      }`}
                    >
                      <div className="font-medium">{intensity.name}</div>
                      <div className="text-[10px] text-gray-500">{intensity.description}</div>
                    </button>
                  ))}
                </div>
              </div>

              {/* Smart Reframing Toggle */}
              <div className="pt-3 border-t border-gray-200">
                <label className="flex items-center gap-3 cursor-pointer group">
                  <div className="relative">
                    <input
                      type="checkbox"
                      checked={enableSmartReframe}
                      onChange={(e) => setEnableSmartReframe(e.target.checked)}
                      className="sr-only"
                    />
                    <div className={`w-11 h-6 rounded-full transition-colors ${enableSmartReframe ? 'bg-blue-500' : 'bg-gray-300'}`}>
                      <div className={`absolute top-0.5 left-0.5 w-5 h-5 bg-white rounded-full shadow transition-transform ${enableSmartReframe ? 'translate-x-5' : ''}`} />
                    </div>
                  </div>
                  <div className="flex items-center gap-2">
                    <Focus className="w-4 h-4 text-blue-500" />
                    <span className="text-sm font-medium text-gray-700">Smart Reframe</span>
                  </div>
                </label>
                <p className="text-xs text-gray-500 mt-1 ml-14">Keep characters centered when cropping</p>
              </div>

              {/* Hook Optimization Section */}
              <div className="pt-3 border-t border-gray-200">
                <div className="flex items-center gap-2 mb-3">
                  <Target className="w-4 h-4 text-purple-500" />
                  <span className="text-sm font-medium text-gray-700">Hook Optimization</span>
                  <span className="text-[10px] bg-purple-500 text-white px-1.5 py-0.5 rounded-full font-bold">RETENTION</span>
                </div>

                {/* Reorder for Hook Toggle */}
                <label className="flex items-center gap-3 cursor-pointer mb-3">
                  <div className="relative">
                    <input
                      type="checkbox"
                      checked={reorderForHook}
                      onChange={(e) => setReorderForHook(e.target.checked)}
                      className="sr-only"
                    />
                    <div className={`w-11 h-6 rounded-full transition-colors ${reorderForHook ? 'bg-purple-500' : 'bg-gray-300'}`}>
                      <div className={`absolute top-0.5 left-0.5 w-5 h-5 bg-white rounded-full shadow transition-transform ${reorderForHook ? 'translate-x-5' : ''}`} />
                    </div>
                  </div>
                  <div className="flex items-center gap-2">
                    <Shuffle className="w-4 h-4 text-purple-500" />
                    <span className="text-sm text-gray-700">Start with best moment</span>
                  </div>
                </label>

                {/* Hook Text Input */}
                <div className="mb-3">
                  <label className="block text-xs font-medium text-gray-600 mb-1">Hook Text (first 2-3s):</label>
                  <div className="flex gap-2">
                    <input
                      type="text"
                      value={hookText}
                      onChange={(e) => setHookText(e.target.value)}
                      placeholder="e.g., Wait for it..."
                      className="flex-1 px-3 py-2 border border-gray-200 rounded-lg text-sm focus:ring-2 focus:ring-purple-500 focus:border-transparent"
                      maxLength={50}
                    />
                  </div>
                </div>

                {/* Hook Templates */}
                <div className="flex flex-wrap gap-1 mb-3">
                  {HOOK_TEMPLATES.map((template) => (
                    <button
                      key={template.id}
                      type="button"
                      onClick={() => setHookText(template.text)}
                      className={`px-2 py-1 text-xs rounded-full border transition-all ${
                        hookText === template.text
                          ? 'border-purple-400 bg-purple-50 text-purple-700'
                          : 'border-gray-200 text-gray-600 hover:border-gray-300'
                      }`}
                    >
                      {template.text}
                    </button>
                  ))}
                </div>

                {/* Hook Style (show only if hook text entered) */}
                {hookText && (
                  <div>
                    <label className="block text-xs font-medium text-gray-600 mb-1">Hook Style:</label>
                    <div className="flex gap-2">
                      {HOOK_STYLES.map((style) => (
                        <button
                          key={style.id}
                          type="button"
                          onClick={() => setHookStyle(style.id)}
                          className={`flex-1 px-2 py-1.5 rounded-lg border text-xs transition-all ${
                            hookStyle === style.id
                              ? 'border-purple-400 bg-purple-50 text-purple-700'
                              : 'border-gray-200 text-gray-600 hover:border-gray-300'
                          }`}
                        >
                          <div className="font-medium">{style.name}</div>
                        </button>
                      ))}
                    </div>
                  </div>
                )}
              </div>
            </div>
          )}
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
