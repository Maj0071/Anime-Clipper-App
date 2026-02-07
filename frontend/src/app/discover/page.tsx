'use client';

import { useRouter } from 'next/navigation';
import { Film, ArrowLeft } from 'lucide-react';
import ClipFinder from '@/components/ClipFinder';

export default function DiscoverPage() {
  const router = useRouter();

  return (
    <div className="min-h-screen bg-gradient-to-br from-purple-50 via-white to-blue-50">
      {/* Header */}
      <header className="bg-white shadow-sm">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-4">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-3">
              <button
                onClick={() => router.push('/')}
                className="p-2 text-gray-400 hover:text-gray-600 hover:bg-gray-100 rounded-lg"
              >
                <ArrowLeft className="w-5 h-5" />
              </button>
              <div className="bg-purple-600 p-2 rounded-lg">
                <Film className="w-6 h-6 text-white" />
              </div>
              <h1 className="text-2xl font-bold text-gray-900">
                Anime Auto-Clipper
              </h1>
            </div>
            <nav className="flex items-center gap-4">
              <a href="/" className="text-gray-600 hover:text-gray-900 text-sm">
                Home
              </a>
              <a href="/discover" className="text-purple-600 font-semibold text-sm">
                Discover
              </a>
              <a href="/social" className="text-gray-600 hover:text-gray-900 text-sm">
                Social
              </a>
            </nav>
          </div>
        </div>
      </header>

      {/* Main Content */}
      <main className="py-8">
        <ClipFinder />
      </main>
    </div>
  );
}
