import { MessageSquare } from 'lucide-react';

export default function ChatPage() {
  return (
    <div className="flex min-h-screen flex-col items-center justify-center bg-slate-50 dark:bg-slate-900">
      <div className="flex items-center gap-2 text-teal-500">
        <MessageSquare className="h-8 w-8" />
        <h1 className="text-2xl font-semibold">Chat</h1>
      </div>
      <p className="mt-2 text-sm text-slate-500 dark:text-slate-400">
        Chat interface coming soon
      </p>
    </div>
  );
}
