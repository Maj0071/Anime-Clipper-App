'use client';

import { useEffect, useState } from 'react';
import { useRouter } from 'next/navigation';
import { Film, CheckCircle, XCircle, Loader2, TrendingUp } from 'lucide-react';

interface AnalyzePageProps {
  params: {
    id: string;
  };
}

interface JobStatus {
  job_id: string;
  video_id: string;
  type: string;
  status: string;
  progress: number;
  logs: Record<string, any>;
  created_at: string;
}

export default function AnalyzePage({ params }: AnalyzePageProps) {
  const router = useRouter();
  const [jobStatus, setJobStatus] = useState<JobStatus | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    // Poll for job status every 2 seconds
    const pollStatus = async () => {
      try {
        const response = await fetch(`/api/videos/${params.id}/jobs`, {
          headers: {
            'Authorization': `Bearer ${localStorage.getItem('token')}`
          }
        });

        if (!response.ok) throw new Error('Failed to fetch job status');

        const jobs = await response.json();
        const latestJob = jobs[0]; // Get most recent job

        setJobStatus(latestJob);

        // If completed, redirect to gallery
        if (latestJob.status === 'completed') {
          setTimeout(() => {
            router.push(`/gallery/${params.id}`);
          }, 2000);
        }

        // If failed, stop polling
        if (latestJob.status === 'failed') {
          setError(latestJob.logs.error || 'Analysis failed');
        }
      } catch (err) {
        setError(err instanceof Error ? err.message : 'Unknown error');
      }
    };

    pollStatus();
    const interval = setInterval(pollStatus, 2000);

    return () => clearInterval(interval);
  }, [params.id, router]);

  const getStatusIcon = () => {
    if (!jobStatus) return <Loader2 className="w-12 h-12 animate-spin text-purple-600" />;

    switch (jobStatus.status) {
      case 'completed':
        return <CheckCircle className="w-12 h-12 text-green-600" />;
      case 'failed':
        return <XCircle className="w-12 h-12 text-red-600" />;
      case 'processing':
        return <Loader2 className="w-12 h-12 animate-spin text-purple-600" />;
      default:
        return <Loader2 className="w-12 h-12 animate-spin text-gray-400" />;
    }
  };

  const getStatusMessage = () => {
    if (!jobStatus) return 'Initializing...';

    switch (jobStatus.status) {
      case 'pending':
        return 'Waiting to start...';
      case 'processing':
        return 'Analyzing your video...';
      case 'completed':
        return 'Analysis complete! Redirecting...';
      case 'failed':
        return 'Analysis failed';
      default:
        return jobStatus.status;
    }
  };

  const steps = [
    { id: 1, name: 'Uploading', progress: 10 },
    { id: 2, name: 'Transcribing', progress: 30 },
    { id: 3, name: 'Scene Detection', progress: 50 },
    { id: 4, name: 'Motion Analysis', progress: 70 },
    { id: 5, name: 'Generating Clips', progress: 90 },
    { id: 6, name: 'Complete', progress: 100 }
  ];

  const currentProgress = jobStatus?.progress || 0;

  return (
    <div className="min-h-screen bg-gray-50 flex items-center justify-center p-6">
      <div className="max-w-2xl w-full">
        {/* Status Card */}
        <div className="bg-white rounded-lg shadow-xl p-8">
          <div className="text-center mb-8">
            <div className="flex justify-center mb-4">
              {getStatusIcon()}
            </div>
            <h1 className="text-3xl font-bold text-gray-900 mb-2">
              {getStatusMessage()}
            </h1>
            <p className="text-gray-600">
              Video ID: {params.id.slice(0, 8)}...
            </p>
          </div>

          {/* Progress Bar */}
          {jobStatus && jobStatus.status !== 'failed' && (
            <div className="mb-8">
              <div className="flex justify-between text-sm text-gray-600 mb-2">
                <span>Progress</span>
                <span>{currentProgress}%</span>
              </div>
              <div className="w-full bg-gray-200 rounded-full h-3 overflow-hidden">
                <div
                  className="bg-gradient-to-r from-purple-600 to-blue-600 h-full transition-all duration-500 ease-out"
                  style={{ width: `${currentProgress}%` }}
                />
              </div>
            </div>
          )}

          {/* Steps */}
          {jobStatus && jobStatus.status === 'processing' && (
            <div className="space-y-3 mb-8">
              {steps.map((step) => {
                const isComplete = currentProgress >= step.progress;
                const isCurrent = currentProgress >= step.progress - 20 && currentProgress < step.progress;

                return (
                  <div
                    key={step.id}
                    className={`flex items-center gap-3 p-3 rounded-lg transition-colors ${
                      isCurrent ? 'bg-purple-50 border border-purple-200' : ''
                    }`}
                  >
                    <div
                      className={`w-8 h-8 rounded-full flex items-center justify-center transition-colors ${
                        isComplete
                          ? 'bg-green-500 text-white'
                          : isCurrent
                          ? 'bg-purple-600 text-white'
                          : 'bg-gray-200 text-gray-400'
                      }`}
                    >
                      {isComplete ? (
                        <CheckCircle className="w-5 h-5" />
                      ) : isCurrent ? (
                        <Loader2 className="w-5 h-5 animate-spin" />
                      ) : (
                        step.id
                      )}
                    </div>
                    <span
                      className={`font-medium ${
                        isCurrent ? 'text-purple-900' : isComplete ? 'text-gray-900' : 'text-gray-400'
                      }`}
                    >
                      {step.name}
                    </span>
                  </div>
                );
              })}
            </div>
          )}

          {/* Error Message */}
          {error && (
            <div className="bg-red-50 border border-red-200 rounded-lg p-4 mb-6">
              <div className="flex items-start gap-3">
                <XCircle className="w-5 h-5 text-red-600 flex-shrink-0 mt-0.5" />
                <div>
                  <h3 className="font-semibold text-red-900 mb-1">Analysis Failed</h3>
                  <p className="text-sm text-red-700">{error}</p>
                  <button
                    onClick={() => router.push('/')}
                    className="mt-3 text-sm text-red-600 hover:text-red-700 underline"
                  >
                    Try uploading again
                  </button>
                </div>
              </div>
            </div>
          )}

          {/* Success Message */}
          {jobStatus?.status === 'completed' && (
            <div className="bg-green-50 border border-green-200 rounded-lg p-4 mb-6">
              <div className="flex items-center gap-3">
                <CheckCircle className="w-5 h-5 text-green-600" />
                <div>
                  <h3 className="font-semibold text-green-900">
                    Found {jobStatus.logs.candidates_generated || 0} clips!
                  </h3>
                  <p className="text-sm text-green-700">
                    Redirecting to clip gallery...
                  </p>
                </div>
              </div>
            </div>
          )}

          {/* Info Box */}
          <div className="bg-blue-50 border border-blue-200 rounded-lg p-4">
            <div className="flex items-start gap-3">
              <TrendingUp className="w-5 h-5 text-blue-600 flex-shrink-0 mt-0.5" />
              <div>
                <h3 className="font-semibold text-blue-900 mb-1">What's happening?</h3>
                <ul className="text-sm text-blue-700 space-y-1">
                  <li>• AI is transcribing dialogue with Whisper</li>
                  <li>• Detecting scenes and motion intensity</li>
                  <li>• Finding viral-worthy moments</li>
                  <li>• Creating thumbnails for each clip</li>
                </ul>
                <p className="text-xs text-blue-600 mt-2">
                  This usually takes 2-5 minutes depending on video length
                </p>
              </div>
            </div>
          </div>
        </div>

        {/* Cancel Button */}
        {jobStatus && ['pending', 'processing'].includes(jobStatus.status) && (
          <div className="text-center mt-6">
            <button
              onClick={() => router.push('/')}
              className="text-gray-600 hover:text-gray-900 text-sm"
            >
              Cancel and return home
            </button>
          </div>
        )}
      </div>
    </div>
  );
}