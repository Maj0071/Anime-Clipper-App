import React from 'react';
import { Check } from 'lucide-react';

interface Template {
  id: string;
  name: string;
  description: string;
  preview: string;
  features: string[];
}

interface TemplateSelectorProps {
  selected: string;
  onSelect: (templateId: string) => void;
}

const templates: Template[] = [
  {
    id: 'clean',
    name: 'Clean Subtitles',
    description: 'Professional, high-contrast text with outline',
    preview: '/previews/clean.jpg',
    features: [
      'White text with black outline',
      'Traditional positioning',
      'Safe for all platforms',
      'Easy to read'
    ]
  },
  {
    id: 'manga',
    name: 'Manga Pop',
    description: 'Bold, comic-style text with dynamic effects',
    preview: '/previews/manga.jpg',
    features: [
      'Bold yellow text',
      'Thick black borders',
      'Subtle zoom effect',
      'High energy feel'
    ]
  },
  {
    id: 'impact',
    name: 'Impact Text',
    description: 'Word-by-word emphasis for dramatic effect',
    preview: '/previews/impact.jpg',
    features: [
      'Pop-in animation',
      'Emphasized keywords',
      'Staggered layout',
      'Maximum attention'
    ]
  },
  {
    id: 'karaoke',
    name: 'Karaoke Style',
    description: 'Progressive word highlighting like karaoke',
    preview: '/previews/karaoke.jpg',
    features: [
      'Word-by-word highlight',
      'Smooth transitions',
      'Easy to follow',
      'Engaging format'
    ]
  }
];

export default function TemplateSelector({ selected, onSelect }: TemplateSelectorProps) {
  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-2xl font-bold text-gray-900 mb-2">
          Choose Caption Style
        </h2>
        <p className="text-gray-600">
          Select how you want captions to appear in your clips
        </p>
      </div>

      <div className="grid md:grid-cols-2 gap-6">
        {templates.map((template) => {
          const isSelected = selected === template.id;

          return (
            <button
              key={template.id}
              onClick={() => onSelect(template.id)}
              className={`relative text-left p-6 rounded-lg border-2 transition-all hover:shadow-lg ${
                isSelected
                  ? 'border-purple-600 bg-purple-50 shadow-lg'
                  : 'border-gray-200 hover:border-purple-300'
              }`}
            >
              {/* Selection Indicator */}
              {isSelected && (
                <div className="absolute top-4 right-4 bg-purple-600 text-white rounded-full p-1">
                  <Check className="w-5 h-5" />
                </div>
              )}

              {/* Preview Image */}
              <div className="aspect-video bg-gray-200 rounded-lg mb-4 overflow-hidden">
                <div className="w-full h-full flex items-center justify-center text-gray-500">
                  <span className="text-sm">Preview</span>
                </div>
              </div>

              {/* Template Info */}
              <h3 className="text-xl font-bold text-gray-900 mb-2">
                {template.name}
              </h3>
              <p className="text-sm text-gray-600 mb-4">
                {template.description}
              </p>

              {/* Features */}
              <ul className="space-y-1">
                {template.features.map((feature, idx) => (
                  <li key={idx} className="flex items-center gap-2 text-sm text-gray-700">
                    <div className="w-1.5 h-1.5 bg-purple-600 rounded-full" />
                    {feature}
                  </li>
                ))}
              </ul>
            </button>
          );
        })}
      </div>

      {/* Aspect Ratio Selector */}
      <div className="bg-gray-50 rounded-lg p-6">
        <h3 className="text-lg font-semibold text-gray-900 mb-4">
          Output Formats
        </h3>
        <div className="grid grid-cols-3 gap-4">
          {[
            { ratio: '9:16', label: 'TikTok/Reels', size: '1080x1920' },
            { ratio: '1:1', label: 'IG Feed', size: '1080x1080' },
            { ratio: '4:5', label: 'IG Story', size: '1080x1350' }
          ].map((format) => (
            <label
              key={format.ratio}
              className="flex items-center gap-3 p-4 border rounded-lg cursor-pointer hover:bg-white transition-colors"
            >
              <input
                type="checkbox"
                defaultChecked={format.ratio === '9:16'}
                className="w-4 h-4 text-purple-600 rounded"
              />
              <div>
                <div className="font-medium text-gray-900">{format.ratio}</div>
                <div className="text-xs text-gray-500">{format.label}</div>
                <div className="text-xs text-gray-400">{format.size}</div>
              </div>
            </label>
          ))}
        </div>
      </div>

      {/* Additional Options */}
      <div className="bg-gray-50 rounded-lg p-6">
        <h3 className="text-lg font-semibold text-gray-900 mb-4">
          Customization
        </h3>
        <div className="space-y-4">
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-2">
              Watermark Text
            </label>
            <input
              type="text"
              defaultValue="@myanime"
              placeholder="@yourhandle"
              className="w-full px-4 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-purple-500 focus:border-transparent"
            />
            <p className="text-xs text-gray-500 mt-1">
              Will appear in top-left corner
            </p>
          </div>

          <div>
            <label className="flex items-center gap-3">
              <input
                type="checkbox"
                defaultChecked
                className="w-4 h-4 text-purple-600 rounded"
              />
              <div>
                <div className="font-medium text-gray-900">Enable Captions</div>
                <div className="text-sm text-gray-600">
                  Auto-generated from speech
                </div>
              </div>
            </label>
          </div>

          <div>
            <label className="flex items-center gap-3">
              <input
                type="checkbox"
                defaultChecked
                className="w-4 h-4 text-purple-600 rounded"
              />
              <div>
                <div className="font-medium text-gray-900">Normalize Audio</div>
                <div className="text-sm text-gray-600">
                  -14 LUFS loudness standard
                </div>
              </div>
            </label>
          </div>
        </div>
      </div>
    </div>
  );
}