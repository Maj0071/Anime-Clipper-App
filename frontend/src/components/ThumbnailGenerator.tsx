'use client';

import { useState } from 'react';
import { Image, Wand2, Download, Loader2, Check, Type, Square, Circle } from 'lucide-react';

interface Thumbnail {
  id: string;
  candidate_id: string;
  frame_time: number;
  style: string;
  text_overlay: string | null;
  image_url: string;
  quality_score: number;
}

interface ThumbnailGeneratorProps {
  candidateId: string;
  onGenerate?: (thumbnails: Thumbnail[]) => void;
}

const STYLES = [
  { id: 'default', name: 'Default', description: 'Clean frame', icon: <Square className="w-4 h-4" /> },
  { id: 'anime', name: 'Anime', description: 'Enhanced colors', icon: <Wand2 className="w-4 h-4" /> },
  { id: 'text', name: 'With Text', description: 'Add caption', icon: <Type className="w-4 h-4" /> },
  { id: 'vignette', name: 'Vignette', description: 'Focus effect', icon: <Circle className="w-4 h-4" /> },
  { id: 'neon', name: 'Neon', description: 'Glowing style', icon: <Wand2 className="w-4 h-4" /> },
  { id: 'border', name: 'Bordered', description: 'White frame', icon: <Square className="w-4 h-4" /> },
];

export default function ThumbnailGenerator({ candidateId, onGenerate }: ThumbnailGeneratorProps) {
  const [selectedStyles, setSelectedStyles] = useState<string[]>(['default', 'anime']);
  const [textOverlay, setTextOverlay] = useState('');
  const [autoSelect, setAutoSelect] = useState(true);
  const [customTime, setCustomTime] = useState<number | null>(null);
  const [generating, setGenerating] = useState(false);
  const [thumbnails, setThumbnails] = useState<Thumbnail[]>([]);
  const [qualityAnalysis, setQualityAnalysis] = useState<Record<string, unknown> | null>(null);
  const [selectedThumbnail, setSelectedThumbnail] = useState<string | null>(null);

  const getHeaders = (): Record<string, string> => {
    const h: Record<string, string> = {};
    if (typeof localStorage !== 'undefined' && localStorage.getItem('token')) {
      h['Authorization'] = `Bearer ${localStorage.getItem('token')}`;
    }
    return h;
  };

  const toggleStyle = (styleId: string) => {
    setSelectedStyles(prev =>
      prev.includes(styleId)
        ? prev.filter(s => s !== styleId)
        : [...prev, styleId]
    );
  };

  const handleGenerate = async () => {
    if (selectedStyles.length === 0) return;

    setGenerating(true);
    try {
      const res = await fetch('/api/thumbnails', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...getHeaders() },
        body: JSON.stringify({
          candidate_id: candidateId,
          styles: selectedStyles,
          text_overlay: textOverlay.trim() || null,
          auto_select_frame: autoSelect,
          custom_frame_time: customTime,
        }),
      });

      if (res.ok) {
        const data = await res.json();
        setThumbnails(data.thumbnails);
        setQualityAnalysis(data.quality_analysis);
        if (data.thumbnails.length > 0) {
          setSelectedThumbnail(data.thumbnails[0].id);
        }
        onGenerate?.(data.thumbnails);
      }
    } catch (e) {
      console.error('Failed to generate thumbnails:', e);
    }
    setGenerating(false);
  };

  const handleDownload = (thumbnail: Thumbnail) => {
    const a = document.createElement('a');
    a.href = thumbnail.image_url;
    a.download = `thumbnail_${thumbnail.style}.jpg`;
    a.click();
  };

  return (
    <div className="bg-white rounded-xl shadow-lg p-6">
      {/* Header */}
      <div className="flex items-center gap-3 mb-6">
        <div className="bg-gradient-to-r from-cyan-500 to-blue-600 p-3 rounded-xl">
          <Image className="w-6 h-6 text-white" />
        </div>
        <div>
          <h2 className="text-xl font-bold text-gray-900">AI Thumbnail Generator</h2>
          <p className="text-sm text-gray-500">Create eye-catching thumbnails for your clips</p>
        </div>
      </div>

      {/* Style Selection */}
      <div className="mb-6">
        <label className="block text-sm font-medium text-gray-700 mb-3">
          Select Styles to Generate:
        </label>
        <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-2">
          {STYLES.map(style => (
            <button
              key={style.id}
              onClick={() => toggleStyle(style.id)}
              className={`flex flex-col items-center gap-2 p-3 rounded-lg border-2 transition-all ${
                selectedStyles.includes(style.id)
                  ? 'border-cyan-500 bg-cyan-50 text-cyan-700'
                  : 'border-gray-200 text-gray-600 hover:border-gray-300'
              }`}
            >
              <div className={selectedStyles.includes(style.id) ? 'text-cyan-500' : 'text-gray-400'}>
                {style.icon}
              </div>
              <span className="text-sm font-medium">{style.name}</span>
              <span className="text-[10px] text-gray-500">{style.description}</span>
            </button>
          ))}
        </div>
      </div>

      {/* Text Overlay (shown if 'text' style selected) */}
      {selectedStyles.includes('text') && (
        <div className="mb-6">
          <label className="block text-sm font-medium text-gray-700 mb-2">
            Text Overlay:
          </label>
          <input
            type="text"
            value={textOverlay}
            onChange={(e) => setTextOverlay(e.target.value)}
            placeholder="e.g., Best Anime Fight Scene!"
            className="w-full px-4 py-2 border border-gray-200 rounded-lg focus:ring-2 focus:ring-cyan-500"
            maxLength={50}
          />
        </div>
      )}

      {/* Frame Selection */}
      <div className="mb-6 p-4 bg-gray-50 rounded-lg">
        <label className="flex items-center gap-3 cursor-pointer mb-3">
          <input
            type="checkbox"
            checked={autoSelect}
            onChange={(e) => setAutoSelect(e.target.checked)}
            className="w-4 h-4 text-cyan-500 rounded"
          />
          <div>
            <span className="text-sm font-medium text-gray-700">Auto-select best frame</span>
            <p className="text-xs text-gray-500">AI analyzes faces, sharpness, and colors</p>
          </div>
        </label>

        {!autoSelect && (
          <div className="mt-3">
            <label className="block text-xs font-medium text-gray-600 mb-1">
              Custom frame time (seconds):
            </label>
            <input
              type="number"
              value={customTime || ''}
              onChange={(e) => setCustomTime(e.target.value ? parseFloat(e.target.value) : null)}
              placeholder="0.0"
              step="0.1"
              className="w-32 px-3 py-1.5 border border-gray-200 rounded-lg text-sm"
            />
          </div>
        )}
      </div>

      {/* Generate Button */}
      <button
        onClick={handleGenerate}
        disabled={selectedStyles.length === 0 || generating}
        className="w-full px-6 py-3 bg-gradient-to-r from-cyan-500 to-blue-600 text-white font-bold rounded-xl hover:from-cyan-600 hover:to-blue-700 disabled:opacity-50 flex items-center justify-center gap-2 transition-all"
      >
        {generating ? (
          <>
            <Loader2 className="w-5 h-5 animate-spin" />
            Generating...
          </>
        ) : (
          <>
            <Wand2 className="w-5 h-5" />
            Generate {selectedStyles.length} Thumbnail{selectedStyles.length !== 1 ? 's' : ''}
          </>
        )}
      </button>

      {/* Quality Analysis */}
      {qualityAnalysis && Object.keys(qualityAnalysis).length > 0 && (
        <div className="mt-4 p-3 bg-cyan-50 border border-cyan-200 rounded-lg text-sm">
          <span className="font-medium text-cyan-700">Frame Analysis: </span>
          <span className="text-cyan-600">
            {qualityAnalysis.faces_detected !== undefined && `${qualityAnalysis.faces_detected} faces detected`}
            {qualityAnalysis.quality_score !== undefined && ` • Quality: ${Math.round(qualityAnalysis.quality_score as number)}%`}
          </span>
        </div>
      )}

      {/* Generated Thumbnails */}
      {thumbnails.length > 0 && (
        <div className="mt-6">
          <h3 className="text-sm font-medium text-gray-700 mb-3">Generated Thumbnails:</h3>
          <div className="grid grid-cols-2 md:grid-cols-3 gap-4">
            {thumbnails.map(thumb => (
              <div
                key={thumb.id}
                onClick={() => setSelectedThumbnail(thumb.id)}
                className={`relative rounded-lg overflow-hidden border-2 cursor-pointer transition-all ${
                  selectedThumbnail === thumb.id
                    ? 'border-cyan-500 shadow-lg'
                    : 'border-gray-200 hover:border-gray-300'
                }`}
              >
                <img
                  src={thumb.image_url}
                  alt={`Thumbnail ${thumb.style}`}
                  className="w-full aspect-video object-cover"
                />

                {/* Selected indicator */}
                {selectedThumbnail === thumb.id && (
                  <div className="absolute top-2 right-2 w-6 h-6 bg-cyan-500 rounded-full flex items-center justify-center">
                    <Check className="w-4 h-4 text-white" />
                  </div>
                )}

                {/* Info overlay */}
                <div className="absolute bottom-0 left-0 right-0 bg-gradient-to-t from-black/70 to-transparent p-2">
                  <div className="flex items-center justify-between">
                    <span className="text-xs text-white font-medium">{thumb.style}</span>
                    <button
                      onClick={(e) => {
                        e.stopPropagation();
                        handleDownload(thumb);
                      }}
                      className="p-1 bg-white/20 rounded hover:bg-white/40 transition-colors"
                    >
                      <Download className="w-3 h-3 text-white" />
                    </button>
                  </div>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
