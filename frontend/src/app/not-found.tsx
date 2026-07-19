export const dynamic = 'force-dynamic'

export default function NotFound() {
  return (
    <div className="flex flex-col items-center justify-center min-h-screen bg-surface-0 text-white p-4">
      <h1 className="text-4xl font-bold mb-2">404 - Page Not Found</h1>
      <p className="text-muted text-sm mb-6">The workspace or page you are looking for does not exist.</p>
      <a href="/dashboard" className="px-4 py-2 bg-brand-600 hover:bg-brand-500 rounded-lg text-sm font-medium transition-colors">
        Return to Dashboard
      </a>
    </div>
  )
}
