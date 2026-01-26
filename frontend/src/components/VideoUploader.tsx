import React, { useState, useCallback } from 'react';
import { Upload, Film, AlertCircle, CheckCircle } from 'lucide-react';

interface UploadProps {
  onUploadComplete: (videoId: string) => void;
}

export type ClipLengthPreset = '15' | '30' | '60' | 'custom';

export const CLIP_PRESETS: Record<ClipLengthPreset, { label: string; target: number; min: number; max: number }> = {
  '15': { label: '15 sec', target: 15, min: 10, max: 20 },
  '30': { label: '30 sec', target: 30, min: 22, max: 45 },
  '60': { label: '1 min (TikTok/Reels)', target: 60, min: 45, max: 90 },
  custom: { label: 'Custom', target: 60, min: 30, max: 120 },
};

export default function VideoUploader({ onUploadComplete }: UploadProps) {
  const [file, setFile] = useState<File | null>(null);
  const [title, setTitle] = useState('');
  const [keywords, setKeywords] = useState('');
  const [clipPreset, setClipPreset] = useState<ClipLengthPreset>('60');
  const [customSeconds, setCustomSeconds] = useState(60);
  const [uploading, setUploading] = useState(false);
  const [progress, setProgress] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const [dragActive, setDragActive] = useState(false);

  const handleDrag = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    if (e.type === "dragenter" || e.type === "dragover") {
      setDragActive(true);
    } else if (e.type === "dragleave") {
      setDragActive(false);
    }
  }, []);

  const handleDrop = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    setDragActive(false);
    
    const droppedFile = e.dataTransfer.files?.[0];
    if (droppedFile && droppedFile.type.startsWith('video/')) {
      setFile(droppedFile);
      setError(null);
    } else {
      setError('Please upload a valid video file (MP4, MKV, AVI, etc.)');
    }
  }, []);

  const handleFileSelect = (e: React.ChangeEvent<HTMLInputElement>) => {
    const selectedFile = e.target.files?.[0];
    if (selectedFile) {
      setFile(selectedFile);
      setError(null);
    }
  };

  const getHeaders = (): Record<string, string> => {
    const h: Record<string, string> = {};
    if (typeof localStorage !== 'undefined' && localStorage.getItem('token')) {
      h['Authorization'] = `Bearer ${localStorage.getItem('token')}`;
    }
    return h;
  };

  const uploadVideo = async () => {
    if (!file) return;

    setUploading(true);
    setError(null);
    setProgress(0);

    const isLocal = process.env.NEXT_PUBLIC_LOCAL_MODE === 'true';

    try {
      let upload_id: string;
      let local_ext: string | undefined;

      if (isLocal) {
        // Direct upload to backend (saved to disk)
        setProgress(10);
        const fd = new FormData();
        fd.append('file', file);
        const up = await fetch('/api/videos/upload', {
          method: 'POST',
          headers: getHeaders(),
          body: fd,
        });
        if (!up.ok) throw new Error('Direct upload failed');
        const d = await up.json();
        upload_id = d.upload_id;
        local_ext = d.ext || '.mp4';
        setProgress(50);
      } else {
        // S3: init then PUT to signed URL
        const initHeaders: Record<string, string> = { 'Content-Type': 'application/json', ...getHeaders() };
        const initResponse = await fetch('/api/videos/uploads/init', {
          method: 'POST',
          headers: initHeaders,
          body: JSON.stringify({
            filename: file.name,
            filesize: file.size,
            content_type: file.type,
          }),
        });
        if (!initResponse.ok) throw new Error('Failed to initialize upload');
        const { upload_url, upload_id: u } = await initResponse.json();
        upload_id = u;

        const xhr = new XMLHttpRequest();
        xhr.upload.addEventListener('progress', (e) => {
          if (e.lengthComputable)
            setProgress(10 + Math.round((e.loaded / e.total) * 40));
        });
        xhr.open('PUT', upload_url);
        xhr.setRequestHeader('Content-Type', file.type);
        await new Promise<void>((resolve, reject) => {
          xhr.onload = () => (xhr.status === 200 ? resolve() : reject(new Error('Upload failed')));
          xhr.onerror = () => reject(new Error('Upload failed'));
          xhr.send(file);
        });
        setProgress(50);
      }

      // Create video record
      const videoHeaders: Record<string, string> = { 'Content-Type': 'application/json', ...getHeaders() };
      const videoResponse = await fetch('/api/videos', {
        method: 'POST',
        headers: videoHeaders,
        body: JSON.stringify({
          upload_id,
          title: title || file.name,
          tags: keywords.split(',').map(k => k.trim()).filter(Boolean),
          ...(isLocal ? { source: 'local', local_ext } : {}),
        }),
      });

      if (!videoResponse.ok) throw new Error('Failed to create video record');
      const { video_id } = await videoResponse.json();

      // Start analysis with user's clip length
      const preset = clipPreset === 'custom'
        ? { target: customSeconds, min: Math.max(10, Math.floor(customSeconds * 0.7)), max: Math.min(180, Math.ceil(customSeconds * 1.5)) }
        : CLIP_PRESETS[clipPreset];
      const analysisHeaders: Record<string, string> = { 'Content-Type': 'application/json', ...getHeaders() };
      const analysisResponse = await fetch('/api/jobs/analyze', {
        method: 'POST',
        headers: analysisHeaders,
        body: JSON.stringify({
          video_id,
          keywords: keywords.split(',').map(k => k.trim()).filter(Boolean),
          targets: {
            clip_min_s: preset.min,
            clip_max_s: preset.max,
            target_s: preset.target
          }
        })
      });

      if (!analysisResponse.ok) throw new Error('Failed to start analysis');

      onUploadComplete(video_id);
      
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Upload failed');
    } finally {
      setUploading(false);
    }
  };

  return (
    <div className="max-w-2xl mx-auto p-6">
      <div className="bg-white rounded-lg shadow-lg p-8">
        <div className="flex items-center gap-3 mb-6">
          <Film className="w-8 h-8 text-purple-600" />
          <h2 className="text-2xl font-bold text-gray-900">Upload Anime Video</h2>
        </div>

        {/* Drag & Drop Area */}
        <div
          onDragEnter={handleDrag}
          onDragLeave={handleDrag}
          onDragOver={handleDrag}
          onDrop={handleDrop}
          className={`border-2 border-dashed rounded-lg p-12 text-center transition-colors ${
            dragActive 
              ? 'border-purple-500 bg-purple-50' 
              : 'border-gray-300 hover:border-purple-400'
          }`}
        >
          {!file ? (
            <div>
              <Upload className="w-16 h-16 mx-auto mb-4 text-gray-400" />
              <p className="text-lg font-medium text-gray-700 mb-2">
                Drag and drop your video here
              </p>
              <p className="text-sm text-gray-500 mb-4">or</p>
              <label className="inline-block">
                <span className="px-6 py-3 bg-purple-600 text-white rounded-lg cursor-pointer hover:bg-purple-700 transition-colors">
                  Browse Files
                </span>
                <input
                  type="file"
                  accept="video/*"
                  onChange={handleFileSelect}
                  className="hidden"
                />
              </label>
              <p className="text-xs text-gray-400 mt-4">
                Supports MP4, MKV, AVI, MOV (max 2GB)
              </p>
            </div>
          ) : (
            <div className="flex items-center justify-center gap-4">
              <CheckCircle className="w-8 h-8 text-green-500" />
              <div className="text-left">
                <p className="font-medium text-gray-900">{file.name}</p>
                <p className="text-sm text-gray-500">
                  {(file.size / 1024 / 1024).toFixed(2)} MB
                </p>
              </div>
              <button
                onClick={() => setFile(null)}
                className="ml-4 text-sm text-red-600 hover:text-red-700"
              >
                Remove
              </button>
            </div>
          )}
        </div>

        {/* Form Fields */}
        {file && (
          <div className="mt-6 space-y-4">
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-2">
                Clip length (ideal for TikTok/Instagram)
              </label>
              <div className="flex flex-wrap gap-2 mb-2">
                {(Object.keys(CLIP_PRESETS) as ClipLengthPreset[]).map((key) => (
                  <button
                    key={key}
                    type="button"
                    onClick={() => setClipPreset(key)}
                    className={`px-4 py-2 rounded-lg text-sm font-medium transition-colors ${
                      clipPreset === key
                        ? 'bg-purple-600 text-white'
                        : 'bg-gray-100 text-gray-700 hover:bg-gray-200'
                    }`}
                  >
                    {CLIP_PRESETS[key].label}
                  </button>
                ))}
              </div>
              {clipPreset === 'custom' && (
                <div className="flex items-center gap-2 mt-2">
                  <input
                    type="number"
                    min={15}
                    max={180}
                    value={customSeconds}
                    onChange={(e) => setCustomSeconds(Math.max(15, Math.min(180, Number(e.target.value) || 60)))}
                    className="w-24 px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-purple-500"
                  />
                  <span className="text-sm text-gray-600">seconds</span>
                </div>
              )}
              <p className="text-xs text-gray-500 mt-1">
                1 min works best for Reels and TikTok to keep viewers engaged
              </p>
            </div>

            <div>
              <label className="block text-sm font-medium text-gray-700 mb-2">
                Video Title (Optional)
              </label>
              <input
                type="text"
                value={title}
                onChange={(e) => setTitle(e.target.value)}
                placeholder="My Awesome Anime Clip"
                className="w-full px-4 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-purple-500 focus:border-transparent"
              />
            </div>

            <div>
              <label className="block text-sm font-medium text-gray-700 mb-2">
                Keywords (Optional)
              </label>
              <input
                type="text"
                value={keywords}
                onChange={(e) => setKeywords(e.target.value)}
                placeholder="fight, epic, action (comma-separated)"
                className="w-full px-4 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-purple-500 focus:border-transparent"
              />
              <p className="text-xs text-gray-500 mt-1">
                e.g. fight, epic — helps find the best action moments
              </p>
            </div>
          </div>
        )}

        {/* Error Message */}
        {error && (
          <div className="mt-4 p-4 bg-red-50 border border-red-200 rounded-lg flex items-start gap-3">
            <AlertCircle className="w-5 h-5 text-red-600 flex-shrink-0 mt-0.5" />
            <p className="text-sm text-red-700">{error}</p>
          </div>
        )}

        {/* Progress Bar */}
        {uploading && (
          <div className="mt-6">
            <div className="flex justify-between text-sm text-gray-600 mb-2">
              <span>Uploading...</span>
              <span>{progress}%</span>
            </div>
            <div className="w-full bg-gray-200 rounded-full h-2 overflow-hidden">
              <div
                className="bg-purple-600 h-full transition-all duration-300 ease-out"
                style={{ width: `${progress}%` }}
              />
            </div>
          </div>
        )}

        {/* Upload Button */}
        {file && !uploading && (
          <button
            onClick={uploadVideo}
            className="mt-6 w-full px-6 py-3 bg-purple-600 text-white font-medium rounded-lg hover:bg-purple-700 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
          >
            Start Analysis
          </button>
        )}

        {/* Info Box */}
        <div className="mt-6 p-4 bg-blue-50 border border-blue-200 rounded-lg">
          <h3 className="text-sm font-semibold text-blue-900 mb-2">
            What happens next?
          </h3>
          <ul className="text-sm text-blue-800 space-y-1">
            <li>• AI analyzes your video for viral moments</li>
            <li>• Transcribes dialogue with Whisper AI</li>
            <li>• Detects scenes, motion, and audio peaks</li>
            <li>• Generates 5-20 optimized clip candidates</li>
            <li>• Processing typically takes 2-5 minutes</li>
          </ul>
        </div>
      </div>
    </div>
  );
}