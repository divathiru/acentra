import { Activity } from 'lucide-react';

export default function LoginPage() {
  return (
    <div className="flex min-h-screen items-center justify-center bg-slate-50 dark:bg-slate-900">
      <div className="w-full max-w-sm rounded-2xl border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800 p-8 shadow-sm">
        <div className="mb-6 flex items-center justify-center gap-2 text-teal-500">
          <Activity className="h-8 w-8" />
          <h1 className="text-2xl font-semibold">HOA</h1>
        </div>
        <p className="text-center text-sm text-slate-500 dark:text-slate-400">
          Login coming soon
        </p>
      </div>
    </div>
  );
}
