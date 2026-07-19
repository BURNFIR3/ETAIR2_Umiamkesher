'use client'
import { useEffect, useState } from 'react'
import { useRouter } from 'next/navigation'
import Link from 'next/link'

export const dynamic = 'force-dynamic'
import { authApi, workspaceApi } from '@/lib/api'
import {
  Zap, Plus, Building2, Users, FileText, ChevronRight,
  Loader2, Globe, Layers, LogOut, RefreshCw, Trash2
} from 'lucide-react'

interface Workspace {
  workspace_id: string
  name: string
  slug: string
  description?: string
  industry?: string
  site_location?: string
  created_at: string
}

export default function DashboardPage() {
  const router = useRouter()
  const [workspaces, setWorkspaces] = useState<Workspace[]>([])
  const [archivedWorkspaces, setArchivedWorkspaces] = useState<Workspace[]>([])
  const [loading, setLoading] = useState(true)
  const [loadingArchived, setLoadingArchived] = useState(false)
  const [restoringWsId, setRestoringWsId] = useState<string | null>(null)
  const [deletingPermanentWsId, setDeletingPermanentWsId] = useState<string | null>(null)
  const [showCreate, setShowCreate] = useState(false)
  const [creating, setCreating] = useState(false)
  const [newWs, setNewWs] = useState({ name: '', description: '', industry: '', site_location: '' })
  const [user, setUser] = useState<any>(null)

  useEffect(() => {
    const token = localStorage.getItem('etair_token')
    if (!token) { router.push('/login'); return }
    const u = localStorage.getItem('etair_user')
    if (u) {
      try { setUser(JSON.parse(u)) } catch {}
    }
    loadWorkspaces()
    loadArchivedWorkspaces()
    authApi.me().then(res => {
      setUser(res.data)
      localStorage.setItem('etair_user', JSON.stringify(res.data))
    }).catch(() => {})
  }, [])

  const loadWorkspaces = async () => {
    setLoading(true)
    try {
      const res = await workspaceApi.list()
      setWorkspaces(res.data)
    } catch (err) {
      console.error('Failed to load workspaces', err)
    } finally {
      setLoading(false)
    }
  }

  const loadArchivedWorkspaces = async () => {
    setLoadingArchived(true)
    try {
      const res = await workspaceApi.listArchived()
      setArchivedWorkspaces(res.data)
    } catch (err) {
      console.error('Failed to load archived workspaces', err)
    } finally {
      setLoadingArchived(false)
    }
  }

  const restoreWorkspace = async (wsId: string) => {
    setRestoringWsId(wsId)
    try {
      await workspaceApi.restore(wsId)
      await loadWorkspaces()
      await loadArchivedWorkspaces()
    } catch (err: any) {
      alert(err.response?.data?.detail || 'Failed to restore workspace')
    } finally {
      setRestoringWsId(null)
    }
  }

  const deleteWorkspacePermanent = async (wsId: string, wsName: string) => {
    if (!confirm(`Are you sure you want to permanently hard delete the workspace "${wsName}" and ALL its files, knowledge graph, and data from the graveyard? This cannot be undone.`)) {
      return
    }
    setDeletingPermanentWsId(wsId)
    try {
      await workspaceApi.deletePermanent(wsId)
      await loadArchivedWorkspaces()
    } catch (err: any) {
      alert(err.response?.data?.detail || 'Failed to permanently delete workspace')
    } finally {
      setDeletingPermanentWsId(null)
    }
  }

  const createWorkspace = async (e: React.FormEvent) => {
    e.preventDefault()
    setCreating(true)
    try {
      const res = await workspaceApi.create(newWs)
      router.push(`/workspace/${res.data.workspace_id}`)
    } catch (err: any) {
      alert(err.response?.data?.detail || 'Failed to create workspace')
    } finally {
      setCreating(false)
    }
  }

  const logout = () => {
    localStorage.clear()
    router.push('/login')
  }

  const industryIcons: Record<string, string> = {
    'Oil & Gas': '🛢️',
    'Manufacturing': '⚙️',
    'Power': '⚡',
    'Process': '🏭',
    'Utilities': '💧',
    'Mining': '⛏️',
  }

  return (
    <div className="min-h-screen bg-surface-0 bg-mesh">
      {/* Topbar */}
      <nav className="border-b border-border bg-surface-1/80 backdrop-blur-md sticky top-0 z-50">
        <div className="max-w-6xl mx-auto px-6 h-14 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className="w-8 h-8 rounded-lg bg-gradient-brand flex items-center justify-center shadow-glow-sm">
              <Zap className="w-4 h-4 text-white" strokeWidth={2.5} />
            </div>
            <span className="font-bold text-white text-lg">ETAIR</span>
          </div>
          <div className="flex items-center gap-3">
            <div className="text-right hidden sm:block">
              <p className="text-sm font-medium text-white">{user?.full_name}</p>
              <p className="text-xs text-muted">{user?.email}</p>
            </div>
            <button onClick={logout} className="btn-ghost p-2" title="Sign out">
              <LogOut className="w-4 h-4" />
            </button>
          </div>
        </div>
      </nav>

      <main className="max-w-6xl mx-auto px-6 py-10">
        {/* Header */}
        <div className="flex items-center justify-between mb-8">
          <div>
            <h1 className="text-2xl font-bold text-white">
              Welcome back, {user?.full_name?.split(' ')[0] || 'Engineer'}
            </h1>
            <p className="text-muted text-sm mt-1">
              Select a workspace or create a new one to get started
            </p>
          </div>
          <button onClick={() => setShowCreate(true)} className="btn-primary">
            <Plus className="w-4 h-4" />
            New Workspace
          </button>
        </div>

        {/* Stats strip */}
        <div className="grid grid-cols-3 gap-4 mb-8">
          {[
            { icon: Layers, label: 'Workspaces', value: workspaces.length },
            { icon: FileText, label: 'Total Documents', value: '—' },
            { icon: Users, label: 'Team Members', value: '—' },
          ].map(({ icon: Icon, label, value }) => (
            <div key={label} className="card flex items-center gap-4">
              <div className="w-10 h-10 rounded-lg bg-brand-900/50 border border-brand-700/30 flex items-center justify-center">
                <Icon className="w-5 h-5 text-brand-400" />
              </div>
              <div>
                <p className="text-xs text-muted">{label}</p>
                <p className="text-xl font-bold text-white">{value}</p>
              </div>
            </div>
          ))}
        </div>

        {/* Workspaces */}
        {loading ? (
          <div className="flex items-center justify-center py-20">
            <Loader2 className="w-6 h-6 animate-spin text-brand-400" />
          </div>
        ) : workspaces.length === 0 ? (
          <div className="text-center py-20">
            <Building2 className="w-12 h-12 text-muted mx-auto mb-4 opacity-40" />
            <h2 className="text-lg font-semibold text-white mb-2">No workspaces yet</h2>
            <p className="text-muted text-sm mb-6">Create your first workspace to start organizing industrial documents</p>
            <button onClick={() => setShowCreate(true)} className="btn-primary">
              <Plus className="w-4 h-4" />
              Create Workspace
            </button>
          </div>
        ) : (
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
            {workspaces.map((ws) => (
              <Link
                key={ws.workspace_id}
                href={`/workspace/${ws.workspace_id}`}
                className="card-hover group flex flex-col gap-3"
              >
                <div className="flex items-start justify-between">
                  <div className="w-10 h-10 rounded-lg bg-gradient-to-br from-brand-700 to-purple-700 flex items-center justify-center text-lg flex-shrink-0">
                    {ws.industry ? (industryIcons[ws.industry] || '🏭') : '🏭'}
                  </div>
                  <ChevronRight className="w-4 h-4 text-muted group-hover:text-brand-400 group-hover:translate-x-0.5 transition-all" />
                </div>
                <div>
                  <h3 className="font-semibold text-white group-hover:text-brand-300 transition-colors">{ws.name}</h3>
                  {ws.description && (
                    <p className="text-sm text-muted mt-0.5 line-clamp-2">{ws.description}</p>
                  )}
                </div>
                <div className="flex items-center gap-3 mt-auto pt-2 border-t border-border/50">
                  {ws.industry && (
                    <span className="badge-blue text-xs">{ws.industry}</span>
                  )}
                  {ws.site_location && (
                    <span className="flex items-center gap-1 text-xs text-muted">
                      <Globe className="w-3 h-3" />
                      {ws.site_location}
                    </span>
                  )}
                </div>
              </Link>
            ))}
          </div>
        )}

        {/* Workspace Graveyard (Outside of active workspaces) */}
        <div className="mt-12 pt-8 border-t border-border">
          <div className="flex items-center justify-between mb-4">
            <div className="flex items-center gap-2 text-brand-300">
              <RefreshCw className="w-5 h-5" />
              <h2 className="text-lg font-bold text-white">Workspace Graveyard (Deleted Workspaces)</h2>
            </div>
            <button
              onClick={loadArchivedWorkspaces}
              disabled={loadingArchived}
              className="btn-secondary text-xs p-1.5"
              title="Refresh Graveyard"
            >
              {loadingArchived ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <RefreshCw className="w-3.5 h-3.5" />}
              Refresh Graveyard
            </button>
          </div>
          <p className="text-xs text-muted mb-4 leading-relaxed">
            Workspaces that have been soft-deleted are kept in the graveyard. As a Level 1 Administrator, you can restore them here at any time to regain access to their files, folders, and knowledge graphs.
          </p>

          {loadingArchived ? (
            <div className="py-8 text-center text-xs text-muted">
              <Loader2 className="w-4 h-4 animate-spin inline mr-2" />
              Loading graveyard workspaces...
            </div>
          ) : archivedWorkspaces.length === 0 ? (
            <div className="p-6 rounded-xl bg-surface-0 border border-border text-center text-xs text-muted italic">
              No soft-deleted workspaces found in the graveyard.
            </div>
          ) : (
            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
              {archivedWorkspaces.map((ws) => (
                <div key={ws.workspace_id} className="bg-surface-1 border border-border/80 rounded-xl p-4 flex flex-col justify-between opacity-85 hover:opacity-100 transition-all">
                  <div>
                    <div className="flex items-center justify-between mb-2">
                      <span className="badge-purple text-[10px]">Soft-Deleted</span>
                      <span className="text-[10px] text-muted">Created: {new Date(ws.created_at).toLocaleDateString()}</span>
                    </div>
                    <h3 className="font-semibold text-white text-sm mb-1">{ws.name}</h3>
                    {ws.description && (
                      <p className="text-xs text-muted line-clamp-2 mb-3">{ws.description}</p>
                    )}
                  </div>
                  <div className="flex gap-2 mt-3">
                    <button
                      onClick={() => restoreWorkspace(ws.workspace_id)}
                      disabled={restoringWsId === ws.workspace_id || deletingPermanentWsId === ws.workspace_id}
                      className="btn-primary text-xs py-2 flex-1 justify-center"
                    >
                      {restoringWsId === ws.workspace_id ? (
                        <Loader2 className="w-3.5 h-3.5 animate-spin mr-1.5" />
                      ) : (
                        <RefreshCw className="w-3.5 h-3.5 mr-1.5" />
                      )}
                      Restore
                    </button>
                    <button
                      onClick={() => deleteWorkspacePermanent(ws.workspace_id, ws.name)}
                      disabled={restoringWsId === ws.workspace_id || deletingPermanentWsId === ws.workspace_id}
                      className="btn-danger text-xs py-2 px-3 justify-center flex items-center gap-1.5"
                      title="Permanently Delete Workspace from Graveyard"
                    >
                      {deletingPermanentWsId === ws.workspace_id ? (
                        <Loader2 className="w-3.5 h-3.5 animate-spin" />
                      ) : (
                        <Trash2 className="w-3.5 h-3.5" />
                      )}
                      Delete
                    </button>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      </main>

      {/* Create Workspace Modal */}
      {showCreate && (
        <div className="fixed inset-0 bg-black/60 backdrop-blur-sm z-50 flex items-center justify-center p-4">
          <div className="bg-surface-1 border border-border rounded-2xl w-full max-w-md shadow-glow animate-slide-up">
            <div className="p-6 border-b border-border">
              <h2 className="text-lg font-semibold text-white">Create Workspace</h2>
              <p className="text-sm text-muted mt-1">Set up a workspace for your site, project, or department</p>
            </div>
            <form onSubmit={createWorkspace} className="p-6 space-y-4">
              <div>
                <label className="label">Workspace Name *</label>
                <input
                  className="input"
                  placeholder="e.g. Refinery Unit 4 — Engineering"
                  value={newWs.name}
                  onChange={e => setNewWs({ ...newWs, name: e.target.value })}
                  required
                  autoFocus
                />
              </div>
              <div>
                <label className="label">Description</label>
                <textarea
                  className="input h-20 resize-none"
                  placeholder="What is this workspace for?"
                  value={newWs.description}
                  onChange={e => setNewWs({ ...newWs, description: e.target.value })}
                />
              </div>
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="label">Industry</label>
                  <select
                    className="input"
                    value={newWs.industry}
                    onChange={e => setNewWs({ ...newWs, industry: e.target.value })}
                  >
                    <option value="">Select…</option>
                    {['Oil & Gas', 'Manufacturing', 'Power', 'Process', 'Utilities', 'Mining', 'Heavy Engineering', 'Other'].map(i => (
                      <option key={i} value={i}>{i}</option>
                    ))}
                  </select>
                </div>
                <div>
                  <label className="label">Site Location</label>
                  <input
                    className="input"
                    placeholder="e.g. Houston, TX"
                    value={newWs.site_location}
                    onChange={e => setNewWs({ ...newWs, site_location: e.target.value })}
                  />
                </div>
              </div>
              <div className="flex gap-3 pt-2">
                <button type="button" onClick={() => setShowCreate(false)} className="btn-secondary flex-1 justify-center">
                  Cancel
                </button>
                <button type="submit" disabled={creating} className="btn-primary flex-1 justify-center">
                  {creating ? <Loader2 className="w-4 h-4 animate-spin" /> : <Plus className="w-4 h-4" />}
                  {creating ? 'Creating…' : 'Create'}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  )
}
