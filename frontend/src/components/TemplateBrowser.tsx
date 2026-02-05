'use client';

import { useState, useEffect } from 'react';
import { Sparkles, Download, Heart, Search, Filter, Save, Loader2 } from 'lucide-react';

interface Template {
  id: string;
  name: string;
  description: string;
  category: string;
  settings: Record<string, unknown>;
  is_public: boolean;
  downloads: number;
  likes: number;
  preview_url: string | null;
  is_owner: boolean;
}

interface TemplateBrowserProps {
  onSelectTemplate: (template: Template) => void;
  currentSettings?: Record<string, unknown>;
}

const CATEGORIES = [
  { id: 'all', name: 'All' },
  { id: 'velocity', name: 'Velocity' },
  { id: 'flow', name: 'Flow' },
  { id: 'cinematic', name: 'Cinematic' },
  { id: 'glitch', name: 'Glitch' },
  { id: 'custom', name: 'Custom' },
];

export default function TemplateBrowser({ onSelectTemplate, currentSettings }: TemplateBrowserProps) {
  const [templates, setTemplates] = useState<Template[]>([]);
  const [loading, setLoading] = useState(true);
  const [category, setCategory] = useState('all');
  const [search, setSearch] = useState('');
  const [showSaveModal, setShowSaveModal] = useState(false);
  const [saveName, setSaveName] = useState('');
  const [saving, setSaving] = useState(false);

  const getHeaders = (): Record<string, string> => {
    const h: Record<string, string> = {};
    if (typeof localStorage !== 'undefined' && localStorage.getItem('token')) {
      h['Authorization'] = `Bearer ${localStorage.getItem('token')}`;
    }
    return h;
  };

  useEffect(() => {
    fetchTemplates();
  }, [category]);

  const fetchTemplates = async () => {
    setLoading(true);
    try {
      const params = new URLSearchParams();
      if (category !== 'all') params.append('category', category);
      params.append('include_system', 'true');
      params.append('include_public', 'true');
      params.append('include_mine', 'true');

      const res = await fetch(`/api/templates?${params}`, { headers: getHeaders() });
      if (res.ok) {
        const data = await res.json();
        setTemplates(data);
      }
    } catch (e) {
      console.error('Failed to fetch templates:', e);
    }
    setLoading(false);
  };

  const handleUseTemplate = async (template: Template) => {
    // Track usage
    try {
      await fetch(`/api/templates/${template.id}/use`, {
        method: 'POST',
        headers: getHeaders(),
      });
    } catch (e) {
      // Ignore tracking errors
    }

    onSelectTemplate(template);
  };

  const handleLike = async (templateId: string, e: React.MouseEvent) => {
    e.stopPropagation();
    try {
      await fetch(`/api/templates/${templateId}/like`, {
        method: 'POST',
        headers: getHeaders(),
      });
      // Refresh templates
      fetchTemplates();
    } catch (e) {
      console.error('Failed to like template:', e);
    }
  };

  const handleSaveTemplate = async () => {
    if (!saveName.trim() || !currentSettings) return;

    setSaving(true);
    try {
      const res = await fetch('/api/templates', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...getHeaders() },
        body: JSON.stringify({
          name: saveName,
          description: 'Custom template',
          category: 'custom',
          settings: currentSettings,
          is_public: false,
        }),
      });

      if (res.ok) {
        setShowSaveModal(false);
        setSaveName('');
        fetchTemplates();
      }
    } catch (e) {
      console.error('Failed to save template:', e);
    }
    setSaving(false);
  };

  const filteredTemplates = templates.filter(t =>
    search === '' || t.name.toLowerCase().includes(search.toLowerCase())
  );

  const formatNumber = (n: number) => {
    if (n >= 1000) return `${(n / 1000).toFixed(1)}k`;
    return n.toString();
  };

  return (
    <div className="bg-white rounded-xl shadow-lg p-6">
      {/* Header */}
      <div className="flex items-center justify-between mb-6">
        <div className="flex items-center gap-3">
          <div className="bg-gradient-to-r from-purple-500 to-indigo-600 p-3 rounded-xl">
            <Sparkles className="w-6 h-6 text-white" />
          </div>
          <div>
            <h2 className="text-xl font-bold text-gray-900">Template Marketplace</h2>
            <p className="text-sm text-gray-500">Browse and apply community presets</p>
          </div>
        </div>

        {currentSettings && (
          <button
            onClick={() => setShowSaveModal(true)}
            className="flex items-center gap-2 px-4 py-2 bg-purple-100 text-purple-700 rounded-lg hover:bg-purple-200 transition-colors"
          >
            <Save className="w-4 h-4" />
            Save Current Settings
          </button>
        )}
      </div>

      {/* Search & Filter */}
      <div className="flex gap-4 mb-6">
        <div className="flex-1 relative">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-400" />
          <input
            type="text"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Search templates..."
            className="w-full pl-10 pr-4 py-2 border border-gray-200 rounded-lg focus:ring-2 focus:ring-purple-500"
          />
        </div>

        <div className="flex gap-2">
          {CATEGORIES.map(cat => (
            <button
              key={cat.id}
              onClick={() => setCategory(cat.id)}
              className={`px-3 py-2 rounded-lg text-sm font-medium transition-colors ${
                category === cat.id
                  ? 'bg-purple-500 text-white'
                  : 'bg-gray-100 text-gray-600 hover:bg-gray-200'
              }`}
            >
              {cat.name}
            </button>
          ))}
        </div>
      </div>

      {/* Template Grid */}
      {loading ? (
        <div className="flex items-center justify-center py-12">
          <Loader2 className="w-8 h-8 animate-spin text-purple-500" />
        </div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
          {filteredTemplates.map(template => (
            <button
              key={template.id}
              onClick={() => handleUseTemplate(template)}
              className="text-left p-4 rounded-xl border-2 border-gray-200 hover:border-purple-400 hover:shadow-md transition-all group"
            >
              {/* Preview placeholder */}
              <div className="h-24 bg-gradient-to-br from-purple-100 to-indigo-100 rounded-lg mb-3 flex items-center justify-center">
                <Sparkles className="w-8 h-8 text-purple-400" />
              </div>

              <h3 className="font-bold text-gray-900 mb-1 group-hover:text-purple-600">
                {template.name}
              </h3>
              <p className="text-xs text-gray-500 mb-3 line-clamp-2">
                {template.description || 'Custom editing preset'}
              </p>

              <div className="flex items-center justify-between">
                <div className="flex items-center gap-3 text-xs text-gray-400">
                  <span className="flex items-center gap-1">
                    <Download className="w-3 h-3" />
                    {formatNumber(template.downloads)}
                  </span>
                  <button
                    onClick={(e) => handleLike(template.id, e)}
                    className="flex items-center gap-1 hover:text-red-500 transition-colors"
                  >
                    <Heart className="w-3 h-3" />
                    {formatNumber(template.likes)}
                  </button>
                </div>

                <span className={`text-[10px] px-2 py-0.5 rounded-full font-medium ${
                  template.category === 'velocity' ? 'bg-red-100 text-red-600' :
                  template.category === 'flow' ? 'bg-blue-100 text-blue-600' :
                  template.category === 'cinematic' ? 'bg-amber-100 text-amber-600' :
                  template.category === 'glitch' ? 'bg-purple-100 text-purple-600' :
                  'bg-gray-100 text-gray-600'
                }`}>
                  {template.category}
                </span>
              </div>

              {template.is_owner && (
                <span className="inline-block mt-2 text-[10px] bg-green-100 text-green-600 px-2 py-0.5 rounded-full">
                  Your Template
                </span>
              )}
            </button>
          ))}
        </div>
      )}

      {/* Save Modal */}
      {showSaveModal && (
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50">
          <div className="bg-white rounded-xl p-6 w-full max-w-md">
            <h3 className="text-lg font-bold mb-4">Save Template</h3>
            <input
              type="text"
              value={saveName}
              onChange={(e) => setSaveName(e.target.value)}
              placeholder="Template name..."
              className="w-full px-4 py-2 border border-gray-200 rounded-lg mb-4"
            />
            <div className="flex gap-3">
              <button
                onClick={() => setShowSaveModal(false)}
                className="flex-1 px-4 py-2 border border-gray-200 rounded-lg hover:bg-gray-50"
              >
                Cancel
              </button>
              <button
                onClick={handleSaveTemplate}
                disabled={!saveName.trim() || saving}
                className="flex-1 px-4 py-2 bg-purple-500 text-white rounded-lg hover:bg-purple-600 disabled:opacity-50"
              >
                {saving ? 'Saving...' : 'Save'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
