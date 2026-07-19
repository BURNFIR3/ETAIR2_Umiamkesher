'use client'
import { useEffect, useState } from 'react'
import { useParams, useRouter } from 'next/navigation'
import Link from 'next/link'
import { filesApi } from '@/lib/api'
import {
  ArrowLeft, FileText, Clock, CheckCircle2, XCircle,
  Download, GitBranch, MessageSquare, ChevronDown, ChevronUp,
  Loader2, AlertTriangle, Zap, Tag, User, Calendar, Hash,
  Send, Plus, Globe, Trash2
} from 'lucide-react'
import { formatDistanceToNow, format } from 'date-fns'

const STATUS_META: Record<string, { badge: string; icon: any; label: string }> = {
  draft: { badge: 'badge-yellow', icon: Clock, label: 'Draft' },
  approved: { badge: 'badge-green', icon: CheckCircle2, label: 'Approved' },
  superseded: { badge: 'badge-gray', icon: XCircle, label: 'Superseded' },
  archived: { badge: 'badge-gray', icon: XCircle, label: 'Archived' },
}

export default function FileDetailPage() {
  const { workspaceId, fileId } = useParams<{ workspaceId: string; fileId: string }>()
  const router = useRouter()

  const [file, setFile] = useState<any>(null)
  const [versions, setVersions] = useState<any[]>([])
  const [comments, setComments] = useState<any[]>([])
  const [loading, setLoading] = useState(true)
  const [showVersions, setShowVersions] = useState(true)
  const [comment, setComment] = useState('')
  const [submittingComment, setSubmittingComment] = useState(false)
  const [updatingStatus, setUpdatingStatus] = useState(false)

  useEffect(() => {
    loadAll()
  }, [fileId])

  const loadAll = async () => {
    setLoading(true)
    try {
      const [fileRes, versRes, commRes] = await Promise.all([
        filesApi.get(fileId),
        filesApi.versions(fileId),
        filesApi.comments(fileId),
      ])
      setFile(fileRes.data)
      setVersions(versRes.data)
      setComments(commRes.data)
    } catch {
      router.push(`/workspace/${workspaceId}`)
    } finally {
      setLoading(false)
    }
  }

  const downloadFile = async () => {
    try {
      const res = await filesApi.downloadUrl(fileId)
      const link = document.createElement('a')
      link.href = res.data.url
      link.download = file.original_name
      link.click()
    } catch { alert('Download failed') }
  }

  const updateStatus = async (status: string) => {
    setUpdatingStatus(true)
    try {
      await filesApi.updateStatus(fileId, status)
      setFile({ ...file, status })
    } catch (err: any) {
      alert(err.response?.data?.detail || 'Failed to update status')
    } finally {
      setUpdatingStatus(false)
    }
  }

  const submitComment = async () => {
    if (!comment.trim()) return
    setSubmittingComment(true)
    try {
      await filesApi.addComment(fileId, comment)
      setComment('')
      const res = await filesApi.comments(fileId)
      setComments(res.data)
    } finally {
      setSubmittingComment(false)
    }
  }

  if (loading) {
    return (
      <div className="min-h-screen bg-surface-0 flex items-center justify-center">
        <Loader2 className="w-6 h-6 animate-spin text-brand-400" />
      </div>
    )
  }

  if (!file) return null

  const stat = STATUS_META[file.status] || STATUS_META.draft
  const StatIcon = stat.icon

  return (
    <div className="min-h-screen bg-surface-0">
      {/* Topbar */}
      <nav className="border-b border-border bg-surface-1/80 backdrop-blur-md sticky top-0 z-40">
        <div className="px-6 h-14 flex items-center gap-4">
          <Link href={`/workspace/${workspaceId}`} className="btn-ghost p-2">
            <ArrowLeft className="w-4 h-4" />
          </Link>
          <div className="w-px h-5 bg-border" />
          <div className="flex items-center gap-2">
            <div className="w-7 h-7 rounded-lg bg-gradient-brand flex items-center justify-center">
              <Zap className="w-3.5 h-3.5 text-white" />
            </div>
            <span className="text-muted text-sm">ETAIR</span>
            <span className="text-muted text-sm">/</span>
            <span className="text-white text-sm font-medium truncate max-w-xs">{file.title || file.original_name}</span>
          </div>
          <div className="ml-auto flex items-center gap-2">
            <button onClick={downloadFile} className="btn-secondary">
              <Download className="w-4 h-4" />
              Download
            </button>
          </div>
        </div>
      </nav>

      <div className="max-w-6xl mx-auto px-6 py-8 grid grid-cols-3 gap-6">
        {/* Main column */}
        <div className="col-span-2 space-y-6">
          {/* File header */}
          <div className="card">
            <div className="flex items-start gap-4">
              <div className="w-12 h-12 rounded-xl bg-surface-2 border border-border flex items-center justify-center flex-shrink-0">
                <FileText className="w-6 h-6 text-brand-400" />
              </div>
              <div className="flex-1">
                <h1 className="text-xl font-bold text-white">{file.title || file.original_name}</h1>
                {file.description && (
                  <p className="text-muted text-sm mt-1">{file.description}</p>
                )}
                <div className="flex items-center gap-2 mt-3 flex-wrap">
                  <span className={stat.badge}>
                    <StatIcon className="w-2.5 h-2.5" />
                    {stat.label}
                  </span>
                  <span className="badge-blue">v{file.version_number}</span>
                  <span className="badge-gray">{file.file_family?.replace('_', ' ')}</span>
                  <span className={`text-xs ${file.processing_status === 'done' ? 'text-emerald-400' : file.processing_status === 'failed' ? 'text-red-400' : 'text-amber-400'}`}>
                    ● {file.processing_status}
                  </span>
                </div>
              </div>
            </div>

            {/* Status actions */}
            <div className="mt-5 pt-5 border-t border-border flex items-center gap-2">
              <span className="text-xs text-muted font-medium">Change status:</span>
              {['draft', 'approved', 'superseded'].map(s => (
                <button
                  key={s}
                  onClick={() => updateStatus(s)}
                  disabled={updatingStatus || file.status === s}
                  className={`text-xs px-3 py-1.5 rounded-lg border transition-all ${
                    file.status === s
                      ? 'bg-brand-900/30 border-brand-700/50 text-brand-300'
                      : 'bg-surface-2 border-border text-muted hover:text-white hover:border-brand-500/40'
                  }`}
                >
                  {updatingStatus ? <Loader2 className="w-3 h-3 animate-spin inline" /> : null}
                  {s.charAt(0).toUpperCase() + s.slice(1)}
                </button>
              ))}
            </div>
          </div>

          {/* Tags */}
          {file.tags?.length > 0 && (
            <div className="card">
              <div className="flex items-center gap-2 mb-3">
                <Tag className="w-4 h-4 text-muted" />
                <span className="text-sm font-medium text-white">Tags</span>
              </div>
              <div className="flex flex-wrap gap-2">
                {file.tags.map((t: string) => (
                  <span key={t} className="badge-blue">{t}</span>
                ))}
              </div>
            </div>
          )}

          {/* Comments */}
          <div className="card">
            <div className="flex items-center gap-2 mb-4">
              <MessageSquare className="w-4 h-4 text-muted" />
              <span className="text-sm font-medium text-white">Comments</span>
              <span className="badge-gray ml-1">{comments.length}</span>
            </div>

            {comments.length === 0 ? (
              <p className="text-sm text-muted">No comments yet.</p>
            ) : (
              <div className="space-y-3 mb-4">
                {comments.map((c: any) => (
                  <div key={c.comment_id} className="flex gap-3">
                    <div className="w-7 h-7 rounded-full bg-brand-800 border border-brand-600/50 flex items-center justify-center flex-shrink-0 text-xs font-medium text-brand-300">
                      {c.user_id.slice(0, 2).toUpperCase()}
                    </div>
                    <div className="flex-1 bg-surface-2 rounded-lg p-3">
                      <p className="text-sm text-white">{c.content}</p>
                      <p className="text-xs text-muted mt-1">
                        {formatDistanceToNow(new Date(c.created_at))} ago
                        {c.page_number && ` · Page ${c.page_number}`}
                      </p>
                    </div>
                  </div>
                ))}
              </div>
            )}

            <div className="flex gap-2 mt-3">
              <input
                className="input flex-1"
                placeholder="Add a comment…"
                value={comment}
                onChange={e => setComment(e.target.value)}
                onKeyDown={e => e.key === 'Enter' && submitComment()}
              />
              <button onClick={submitComment} disabled={submittingComment || !comment.trim()} className="btn-primary">
                {submittingComment ? <Loader2 className="w-4 h-4 animate-spin" /> : <Send className="w-4 h-4" />}
              </button>
            </div>
          </div>
        </div>

        {/* Right column */}
        <div className="space-y-4">
          {/* Metadata */}
          <div className="card">
            <h3 className="text-sm font-semibold text-white mb-4">File Information</h3>
            <div className="space-y-3">
              {[
                { icon: Hash, label: 'File ID', value: file.file_id.slice(0, 12) + '…' },
                { icon: Hash, label: 'Document ID', value: file.document_id.slice(0, 12) + '…' },
                { icon: Calendar, label: 'Uploaded', value: formatDistanceToNow(new Date(file.upload_ts)) + ' ago' },
                { icon: User, label: 'Uploader role', value: file.uploader_role },
                { icon: FileText, label: 'File size', value: `${(file.file_size_bytes / 1024).toFixed(1)} KB` },
                { icon: Globe, label: 'Language', value: file.language?.toUpperCase() || '—' },
              ].map(({ icon: Icon, label, value }) => (
                <div key={label} className="flex items-start gap-3">
                  <Icon className="w-3.5 h-3.5 text-muted mt-0.5 flex-shrink-0" />
                  <div>
                    <p className="text-xs text-muted">{label}</p>
                    <p className="text-sm text-white font-medium">{value}</p>
                  </div>
                </div>
              ))}
            </div>
          </div>

          {/* Access roles */}
          <div className="card">
            <h3 className="text-sm font-semibold text-white mb-3">Access Control</h3>
            {!file.access_roles || file.access_roles.length === 0 ? (
              <p className="text-xs text-muted">Accessible to all workspace members</p>
            ) : (
              <div className="flex flex-wrap gap-1">
                {file.access_roles.map((r: string) => (
                  <span key={r} className="badge-purple">{r}</span>
                ))}
              </div>
            )}
          </div>

          {/* Version history */}
          <div className="card">
            <button
              onClick={() => setShowVersions(!showVersions)}
              className="flex items-center justify-between w-full"
            >
              <div className="flex items-center gap-2">
                <GitBranch className="w-4 h-4 text-muted" />
                <span className="text-sm font-semibold text-white">Version History</span>
                <span className="badge-gray">{versions.length}</span>
              </div>
              {showVersions ? <ChevronUp className="w-4 h-4 text-muted" /> : <ChevronDown className="w-4 h-4 text-muted" />}
            </button>

            {showVersions && (
              <div className="mt-4 space-y-2">
                {versions.map((v: any) => {
                  const isCurrent = v.file_id === fileId
                  const vStat = STATUS_META[v.status] || STATUS_META.draft
                  const VIcon = vStat.icon
                  return (
                    <div
                      key={v.file_id}
                      className={`flex items-center gap-3 p-2.5 rounded-lg border text-sm ${
                        isCurrent ? 'bg-brand-900/20 border-brand-700/40' : 'bg-surface-2 border-border/50'
                      }`}
                    >
                      <div className={`w-6 h-6 rounded-full border flex items-center justify-center flex-shrink-0 text-xs font-bold ${
                        isCurrent ? 'bg-brand-600 border-brand-500 text-white' : 'bg-surface-3 border-border text-muted'
                      }`}>
                        {v.version_number}
                      </div>
                      <div className="flex-1 min-w-0">
                        <div className="flex items-center gap-1.5">
                          <span className={`text-xs ${isCurrent ? 'text-brand-300 font-medium' : 'text-muted'}`}>
                            v{v.version_number}
                          </span>
                          <span className={vStat.badge + ' text-xs'}>
                            <VIcon className="w-2 h-2" />
                            {vStat.label}
                          </span>
                          {isCurrent && <span className="badge-blue text-xs">Current</span>}
                        </div>
                        <p className="text-xs text-muted mt-0.5">
                          {format(new Date(v.upload_ts), 'MMM d, yyyy')}
                        </p>
                      </div>
                      {!isCurrent && (
                        <Link
                          href={`/workspace/${workspaceId}/file/${v.file_id}`}
                          className="text-xs text-brand-400 hover:text-brand-300"
                        >
                          View
                        </Link>
                      )}
                    </div>
                  )
                })}
              </div>
            )}
          </div>

          {/* Hard Delete Card */}
          <div className="card border-red-900/40 bg-red-950/10">
            <div className="flex items-center gap-2 mb-2 text-red-400">
              <Trash2 className="w-4 h-4" />
              <h3 className="text-sm font-semibold">Danger Zone</h3>
            </div>
            <p className="text-xs text-muted mb-4">
              Permanently delete this file along with all its text chunks, embeddings, vector indices, and corresponding knowledge graph entities and edges.
            </p>
            <button
              onClick={() => {
                if (window.confirm("Are you sure you want to permanently hard delete this file and all its corresponding knowledge graph and data wherever it is stored? This action cannot be undone.")) {
                  filesApi.deleteFile(fileId).then(() => {
                    router.push(`/workspace/${workspaceId}`)
                  }).catch((err: any) => {
                    alert(err?.response?.data?.detail || "Failed to delete file")
                  })
                }
              }}
              className="w-full py-2 px-3 rounded-lg bg-red-600/20 border border-red-500/40 text-red-400 hover:bg-red-600 hover:text-white transition-all text-xs font-semibold flex items-center justify-center gap-2"
            >
              <Trash2 className="w-3.5 h-3.5" />
              Hard Delete File & Graph Data
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}
