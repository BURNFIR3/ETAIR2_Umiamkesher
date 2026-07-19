'use client'
import { useCallback, useEffect, useRef, useState } from 'react'
import { useParams, useRouter } from 'next/navigation'
import Link from 'next/link'
import { useDropzone } from 'react-dropzone'
import { filesApi, workspaceApi, queryApi, folderApi, graphApi, calendarApi } from '@/lib/api'
import {
  Zap, ArrowLeft, FileText, Upload, Search, MessageSquare,
  Filter, Clock, CheckCircle2, XCircle,
  Loader2, Send, X, FileArchive, Mic, Image,
  Table, Wrench, BarChart3, Users, GitBranch, RefreshCw,
  ExternalLink, BookOpen, Layers, Download, Eye, Plus,
  Shield, Trash2, ArrowUpDown, Settings, Crown, ChevronRight,
  AlertCircle, Edit3, Folder, FolderPlus, ShieldAlert, History, Lock, Unlock, CornerDownRight, Check, ShieldCheck, Network, Database, ChevronDown, ChevronUp, Calendar, CalendarPlus, CalendarClock, Bot
} from 'lucide-react'

const getErrorMsg = (err: any, fallback = 'Operation failed'): string => {
  const detail = err?.response?.data?.detail || err?.detail || err
  if (typeof detail === 'string') return detail
  if (Array.isArray(detail)) {
    return detail.map((d: any) => `${d.loc?.slice(-1)[0] || 'field'}: ${d.msg || JSON.stringify(d)}`).join('; ')
  }
  if (detail && typeof detail === 'object') {
    if (detail.msg) return detail.msg
    return JSON.stringify(detail)
  }
  return err?.message || fallback
}

import { formatDistanceToNow, format } from 'date-fns'
import dynamic from 'next/dynamic'
const ForceGraph2D = dynamic(() => import('react-force-graph-2d'), { ssr: false })

const FILE_FAMILY_META: Record<string, { icon: any; color: string; label: string }> = {
  text_office: { icon: FileText, color: 'text-blue-400', label: 'Document' },
  table: { icon: Table, color: 'text-emerald-400', label: 'Spreadsheet' },
  image: { icon: Image, color: 'text-amber-400', label: 'Image/Scan' },
  audio: { icon: Mic, color: 'text-purple-400', label: 'Audio' },
  cad: { icon: Wrench, color: 'text-cyan-400', label: 'CAD/Drawing' },
  operational: { icon: BarChart3, color: 'text-orange-400', label: 'Export/Log' },
  unknown: { icon: FileArchive, color: 'text-muted', label: 'File' },
}

const STATUS_META: Record<string, { badge: string; icon: any; label: string }> = {
  draft: { badge: 'badge-yellow', icon: Clock, label: 'Draft' },
  approved: { badge: 'badge-green', icon: CheckCircle2, label: 'Approved' },
  superseded: { badge: 'badge-gray', icon: XCircle, label: 'Superseded' },
  archived: { badge: 'badge-gray', icon: XCircle, label: 'Archived' },
}

const PROC_STATUS_META: Record<string, { color: string; label: string }> = {
  pending: { color: 'text-amber-400', label: 'Queued' },
  processing: { color: 'text-brand-400', label: 'Processing' },
  done: { color: 'text-emerald-400', label: 'Ready' },
  failed: { color: 'text-red-400', label: 'Failed' },
}

type Tab = 'files' | 'query' | 'roles' | 'members' | 'audit' | 'graph' | 'calendar' | 'settings'

export default function WorkspacePage() {
  const { workspaceId } = useParams<{ workspaceId: string }>()
  const router = useRouter()

  const [workspace, setWorkspace] = useState<any>(null)
  const [files, setFiles] = useState<any[]>([])
  const [roles, setRoles] = useState<any[]>([])
  const [members, setMembers] = useState<any[]>([])
  const [loading, setLoading] = useState(true)
  const [activeTab, setActiveTab] = useState<Tab>('files')
  const [showUpload, setShowUpload] = useState(false)
  const [search, setSearch] = useState('')
  const [statusFilter, setStatusFilter] = useState('')
  const [familyFilter, setFamilyFilter] = useState('')
  const [myLevel, setMyLevel] = useState<number>(999)

  // Folders & Branches state
  const [currentFolderId, setCurrentFolderId] = useState<string | null>(null)
  const [folders, setFolders] = useState<any[]>([])
  const [folderPath, setFolderPath] = useState<{ id: string | null; name: string }[]>([{ id: null, name: 'Root' }])
  const [showCreateFolder, setShowCreateFolder] = useState(false)
  const [newFolder, setNewFolder] = useState({ name: '', description: '', is_inherited: true, allowed_role_ids: [] as string[], min_access_level: '' })
  const [creatingFolder, setCreatingFolder] = useState(false)

  // Governance & ACL state
  const [auditLogs, setAuditLogs] = useState<any[]>([])
  const [showAclModal, setShowAclModal] = useState<{ type: 'file' | 'folder'; id: string; name: string; is_inherited: boolean; allowed_role_ids: string[]; min_access_level: number | null } | null>(null)
  const [updatingAcl, setUpdatingAcl] = useState(false)

  // Upload state
  const [uploadForm, setUploadForm] = useState({ title: '', description: '', tags: '', min_access_level: '', document_id: '', status: 'draft' })
  const [uploading, setUploading] = useState(false)
  const [uploadFile, setUploadFile] = useState<File | null>(null)
  const [uploadProgress, setUploadProgress] = useState(0)

  // Query state
  const [queryText, setQueryText] = useState('')
  const [querying, setQuerying] = useState(false)
  const [queryResult, setQueryResult] = useState<any>(null)
  const queryInputRef = useRef<HTMLInputElement>(null)

  // Role management state
  const [showCreateRole, setShowCreateRole] = useState(false)
  const [newRole, setNewRole] = useState({ name: '', level: '', description: '', branch: 'Main', parent_role_id: '', can_modify_graph: false })
  const [creatingRole, setCreatingRole] = useState(false)
  const [swapMode, setSwapMode] = useState(false)
  const [swapSelection, setSwapSelection] = useState<string[]>([])
  const [swapping, setSwapping] = useState(false)
  const [deletingRole, setDeletingRole] = useState<string | null>(null)

  // Invite state
  const [showInvite, setShowInvite] = useState(false)
  const [inviteEmail, setInviteEmail] = useState('')
  const [inviteRoleId, setInviteRoleId] = useState('')
  const [inviting, setInviting] = useState(false)

  // Graph state
  const [graphData, setGraphData] = useState<{ nodes: any[]; links: any[]; mutations?: any[] }>({ nodes: [], links: [], mutations: [] })
  const [graphMutations, setGraphMutations] = useState<any[]>([])
  const [graphLoading, setGraphLoading] = useState(false)
  const graphContainerRef = useRef<HTMLDivElement>(null)
  const [graphDimensions, setGraphDimensions] = useState({ width: 800, height: 600 })
  const [deleteConfirmation, setDeleteConfirmation] = useState('')
  const [deletingWorkspace, setDeletingWorkspace] = useState(false)

  // Calendar state
  const [calendarEvents, setCalendarEvents] = useState<any[]>([])
  const [calendarExpanded, setCalendarExpanded] = useState<any[]>([])
  const [calendarLoading, setCalendarLoading] = useState(false)
  const [calendarQuery, setCalendarQuery] = useState('')
  const [calendarQuerying, setCalendarQuerying] = useState(false)
  const [calendarView, setCalendarView] = useState<'list' | 'expanded'>('list')
  const [calendarTypeFilter, setCalendarTypeFilter] = useState('')
  const [showCreateEvent, setShowCreateEvent] = useState(false)
  const [newEventForm, setNewEventForm] = useState({ title: '', equipment_id: '', event_type: 'preventive', start_at: '', repeat_rule: '', description: '', confidence: 'high' })
  const [creatingEvent, setCreatingEvent] = useState(false)

  // Graph interactive states
  const [edgeMode, setEdgeMode] = useState(false)
  const [selectedSourceNode, setSelectedSourceNode] = useState<any | null>(null)
  const [selectedTargetNode, setSelectedTargetNode] = useState<any | null>(null)
  const [showAddEdgeModal, setShowAddEdgeModal] = useState(false)
  const [newEdgeData, setNewEdgeData] = useState({ label: '', comment: '', weight: 0.8 })
  const [addingEdge, setAddingEdge] = useState(false)
  const [selectedLinkDetails, setSelectedLinkDetails] = useState<any | null>(null)
  const [selectedNodeDetails, setSelectedNodeDetails] = useState<any | null>(null)
  const [showAddNodeModal, setShowAddNodeModal] = useState(false)
  const [newNodeData, setNewNodeData] = useState({ label: '', node_type: 'entity', branch: 'Main', description: '' })
  const [addingNode, setAddingNode] = useState(false)

  const BRANCH_COLORS = [
    '#34d399', '#f472b6', '#fb923c', '#a78bfa', '#38bdf8', '#facc15', '#4ade80', '#f87171', '#c084fc', '#2dd4bf'
  ]
  const uniqueBranches = Array.from(new Set(['Root', ...graphData.nodes.map((n: any) => n.branch || 'Root')]))
  const getBranchColor = (branch: string) => {
    if (!branch || branch === 'Root' || branch === 'Main') return '#60a5fa' // Root / default blue color
    const idx = uniqueBranches.indexOf(branch)
    if (idx <= 0) return BRANCH_COLORS[0]
    return BRANCH_COLORS[(idx - 1) % BRANCH_COLORS.length]
  }

  useEffect(() => {
    const token = localStorage.getItem('etair_token')
    if (!token) { router.push('/login'); return }
    loadAll()
  }, [workspaceId])

  const loadGraph = () => {
    setGraphLoading(true)
    graphApi.getWorkspaceGraph(workspaceId)
      .then(res => {
        setGraphData(res.data)
        if (res.data.mutations) setGraphMutations(res.data.mutations)
      })
      .catch(err => console.error('Graph load error:', err))
      .finally(() => setGraphLoading(false))
  }

  const doAddEdge = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!selectedSourceNode || !selectedTargetNode) return
    setAddingEdge(true)
    try {
      await graphApi.addEdge({
        workspace_id: workspaceId,
        from_node_id: selectedSourceNode.id,
        to_node_id: selectedTargetNode.id,
        label: newEdgeData.label || 'related to',
        comment: newEdgeData.comment,
        weight: newEdgeData.weight,
      })
      setShowAddEdgeModal(false)
      setSelectedSourceNode(null)
      setSelectedTargetNode(null)
      setNewEdgeData({ label: '', comment: '', weight: 0.8 })
      loadGraph()
    } catch (err: any) {
      alert(getErrorMsg(err, 'Failed to add custom edge'))
    } finally {
      setAddingEdge(false)
    }
  }

  const doDeleteMutation = async (mutationId: string) => {
    if (!confirm('Are you sure you want to delete this custom edge/mutation?')) return
    try {
      await graphApi.deleteMutation(mutationId)
      setSelectedLinkDetails(null)
      loadGraph()
    } catch (err: any) {
      alert(getErrorMsg(err, 'Failed to delete mutation'))
    }
  }

  const doAddNode = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!newNodeData.label.trim()) return
    setAddingNode(true)
    try {
      await graphApi.addNode({
        workspace_id: workspaceId,
        label: newNodeData.label.trim(),
        node_type: newNodeData.node_type,
        branch: newNodeData.branch || 'Main',
        properties: newNodeData.description ? { description: newNodeData.description } : {},
      })
      setShowAddNodeModal(false)
      setNewNodeData({ label: '', node_type: 'entity', branch: 'Main', description: '' })
      loadGraph()
    } catch (err: any) {
      alert(getErrorMsg(err, 'Failed to add node to graph'))
    } finally {
      setAddingNode(false)
    }
  }

  const doDeleteEdge = async (link: any) => {
    if (!confirm('Are you sure you want to delete this connection from the knowledge graph?')) return
    const fromId = typeof link.source === 'object' ? link.source.id : link.source
    const toId = typeof link.target === 'object' ? link.target.id : link.target
    try {
      if (link.edge_source === 'user' && link.id) {
        await graphApi.deleteMutation(link.id)
      } else {
        await graphApi.deleteEdge({
          workspace_id: workspaceId,
          from_node_id: fromId,
          to_node_id: toId,
        })
      }
      setSelectedLinkDetails(null)
      loadGraph()
    } catch (err: any) {
      alert(getErrorMsg(err, 'Failed to delete connection'))
    }
  }

  useEffect(() => {
    if (activeTab === 'graph') {
      loadGraph()
      // Measure container dimensions so ForceGraph2D gets explicit pixel size
      const el = graphContainerRef.current
      if (el) {
        setGraphDimensions({ width: el.offsetWidth || 800, height: el.offsetHeight || 600 })
        const ro = new ResizeObserver(entries => {
          const { width, height } = entries[0].contentRect
          if (width > 0 && height > 0) setGraphDimensions({ width, height })
        })
        ro.observe(el)
        return () => ro.disconnect()
      }
    }
  }, [activeTab, workspaceId])

  const loadAll = async () => {
    setLoading(true)
    try {
      const [wsRes, filesRes, rolesRes, membersRes, foldersRes, auditRes] = await Promise.all([
        workspaceApi.get(workspaceId),
        filesApi.list(workspaceId),
        workspaceApi.roles(workspaceId),
        workspaceApi.members(workspaceId),
        folderApi.list(workspaceId, null),
        workspaceApi.auditLogs(workspaceId, 150),
      ])
      setWorkspace(wsRes.data)
      setMyLevel(wsRes.data.my_role_level)
      setFiles(filesRes.data)
      setRoles(rolesRes.data)
      setMembers(membersRes.data)
      setFolders(foldersRes.data)
      setAuditLogs(auditRes.data)
    } catch (err: any) {
      if (err?.response?.status === 401) {
        localStorage.clear()
        router.push('/login')
      } else {
        console.error('Workspace load error:', err?.response?.data || err)
        router.push('/dashboard')
      }
    } finally { setLoading(false) }
  }

  const loadFolders = async (parentId: string | null = currentFolderId) => {
    try {
      const res = await folderApi.list(workspaceId, parentId)
      setFolders(res.data)
    } catch {}
  }

  const loadFiles = async (folderId: string | null = currentFolderId) => {
    try {
      const params: Record<string, string> = {}
      if (folderId) params.folder_id = folderId
      if (search) params.search = search
      if (statusFilter) params.status = statusFilter
      if (familyFilter) params.family = familyFilter
      const res = await filesApi.list(workspaceId, params)
      setFiles(res.data)
    } catch {}
  }

  useEffect(() => {
    const t = setTimeout(() => loadFiles(currentFolderId), 300)
    return () => clearTimeout(t)
  }, [search, statusFilter, familyFilter])

  useEffect(() => {
    loadFolders(currentFolderId)
    loadFiles(currentFolderId)
  }, [currentFolderId])

  useEffect(() => {
    const hasPending = files.some(f => ['pending', 'processing', 'queued'].includes(f.processing_status))
    if (!hasPending) return
    const interval = setInterval(() => {
      loadFiles(currentFolderId)
    }, 2500)
    return () => clearInterval(interval)
  }, [files, currentFolderId])


  const navigateFolder = (id: string | null, name: string, pathIndex?: number) => {
    setCurrentFolderId(id)
    if (pathIndex !== undefined) {
      setFolderPath(prev => prev.slice(0, pathIndex + 1))
    } else {
      setFolderPath(prev => [...prev, { id, name }])
    }
  }

  const createFolder = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!newFolder.name.trim()) return
    setCreatingFolder(true)
    try {
      await folderApi.create(workspaceId, {
        name: newFolder.name.trim(),
        parent_folder_id: currentFolderId,
        description: newFolder.description || undefined,
        is_inherited: newFolder.is_inherited,
        allowed_role_ids: newFolder.allowed_role_ids,
        min_access_level: newFolder.min_access_level ? parseInt(newFolder.min_access_level) : undefined,
      })
      setShowCreateFolder(false)
      setNewFolder({ name: '', description: '', is_inherited: true, allowed_role_ids: [], min_access_level: '' })
      await loadFolders()
      const wsRes = await workspaceApi.auditLogs(workspaceId, 150)
      setAuditLogs(wsRes.data)
    } catch (err: any) {
      alert(err.response?.data?.detail || 'Failed to create folder')
    } finally {
      setCreatingFolder(false)
    }
  }

  const deleteFolder = async (id: string, name: string) => {
    if (!confirm(`Delete folder "${name}"? It must be empty first.`)) return
    try {
      await folderApi.delete(workspaceId, id)
      await loadFolders()
    } catch (err: any) {
      alert(err.response?.data?.detail || 'Failed to delete folder')
    }
  }

  const doUpdateAcl = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!showAclModal) return
    setUpdatingAcl(true)
    try {
      if (showAclModal.type === 'file') {
        await filesApi.updateAcl(showAclModal.id, {
          is_inherited: showAclModal.is_inherited,
          allowed_role_ids: showAclModal.allowed_role_ids,
          min_access_level: showAclModal.min_access_level,
        })
        await loadFiles()
      } else {
        await folderApi.update(workspaceId, showAclModal.id, {
          is_inherited: showAclModal.is_inherited,
          allowed_role_ids: showAclModal.allowed_role_ids,
          min_access_level: showAclModal.min_access_level,
        })
        await loadFolders()
      }
      setShowAclModal(null)
      const wsRes = await workspaceApi.auditLogs(workspaceId, 150)
      setAuditLogs(wsRes.data)
    } catch (err: any) {
      alert(err.response?.data?.detail || 'Failed to update access policy')
    } finally {
      setUpdatingAcl(false)
    }
  }

  // Dropzone
  const onDrop = useCallback((accepted: File[]) => {
    if (accepted[0]) { setUploadFile(accepted[0]); setUploadForm(f => ({ ...f, title: accepted[0].name })); setShowUpload(true) }
  }, [])
  const { getRootProps, getInputProps, isDragActive } = useDropzone({ onDrop, multiple: false, noClick: true })

  const doUpload = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!uploadFile) return
    setUploading(true); setUploadProgress(20)
    try {
      const fd = new FormData()
      fd.append('file', uploadFile)
      if (uploadForm.title) fd.append('title', uploadForm.title)
      if (uploadForm.description) fd.append('description', uploadForm.description)
      if (uploadForm.tags) fd.append('tags', uploadForm.tags)
      if (uploadForm.min_access_level) fd.append('min_access_level', uploadForm.min_access_level)
      if (uploadForm.document_id) fd.append('document_id', uploadForm.document_id)
      if (currentFolderId) fd.append('folder_id', currentFolderId)
      fd.append('status', uploadForm.status)
      setUploadProgress(50)
      await filesApi.upload(workspaceId, fd)
      setUploadProgress(100)
      setShowUpload(false); setUploadFile(null)
      setUploadForm({ title: '', description: '', tags: '', min_access_level: '', document_id: '', status: 'draft' })
      await loadFiles()
    } catch (err: any) {
      alert(err.response?.data?.detail || 'Upload failed')
    } finally { setUploading(false); setUploadProgress(0) }
  }

  const doQuery = async () => {
    if (!queryText.trim()) return
    setQuerying(true); setQueryResult(null)
    try {
      const res = await queryApi.ask({ query: queryText, workspace_id: workspaceId })
      setQueryResult(res.data)
    } catch (err: any) {
      setQueryResult({ answer: getErrorMsg(err, 'Query failed.'), citations: [], related_files: [], confidence: 0, no_answer: true })
    } finally { setQuerying(false) }
  }

  const downloadFile = async (fileId: string, filename: string) => {
    try {
      const res = await filesApi.downloadUrl(fileId)
      const a = document.createElement('a'); a.href = res.data.url; a.download = filename; a.click()
    } catch { alert('Download failed') }
  }

  // ─── Role management ────────────────────────────────────────────────────────

  const createRole = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!newRole.name || !newRole.level) return
    setCreatingRole(true)
    try {
      await workspaceApi.createRole(workspaceId, {
        name: newRole.name,
        level: parseInt(newRole.level),
        description: newRole.description || undefined,
        branch: newRole.branch || 'Main',
        parent_role_id: newRole.parent_role_id || undefined,
        can_modify_graph: parseInt(newRole.level) === 1 ? true : newRole.can_modify_graph,
      })
      setShowCreateRole(false); setNewRole({ name: '', level: '', description: '', branch: 'Main', parent_role_id: '', can_modify_graph: false })
      const res = await workspaceApi.roles(workspaceId)
      setRoles(res.data)
    } catch (err: any) {
      alert(err.response?.data?.detail || 'Failed to create role')
    } finally { setCreatingRole(false) }
  }

  const toggleCanModifyGraph = async (role: any) => {
    const nextVal = !role.can_modify_graph
    try {
      await workspaceApi.updateRole(workspaceId, role.role_id, { can_modify_graph: nextVal })
      setRoles(roles.map(r => r.role_id === role.role_id ? { ...r, can_modify_graph: nextVal } : r))
    } catch (err: any) {
      alert(err.response?.data?.detail || 'Failed to update graph modification permission')
    }
  }

  const deleteRole = async (roleId: string) => {
    if (!confirm('Delete this role? This cannot be undone.')) return
    setDeletingRole(roleId)
    try {
      await workspaceApi.deleteRole(workspaceId, roleId)
      setRoles(roles.filter(r => r.role_id !== roleId))
    } catch (err: any) {
      alert(err.response?.data?.detail || 'Cannot delete this role')
    } finally { setDeletingRole(null) }
  }

  const toggleSwapSelect = (roleId: string) => {
    setSwapSelection(prev => {
      if (prev.includes(roleId)) return prev.filter(id => id !== roleId)
      if (prev.length >= 2) return [prev[1], roleId]
      return [...prev, roleId]
    })
  }

  const doSwap = async () => {
    if (swapSelection.length !== 2) return
    setSwapping(true)
    try {
      await workspaceApi.swapLevels(workspaceId, swapSelection[0], swapSelection[1])
      const res = await workspaceApi.roles(workspaceId)
      setRoles(res.data)
      setSwapMode(false); setSwapSelection([])
    } catch (err: any) {
      alert(err.response?.data?.detail || 'Swap failed')
    } finally { setSwapping(false) }
  }

  const doInvite = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!inviteEmail || !inviteRoleId) return
    setInviting(true)
    try {
      await workspaceApi.invite(workspaceId, { email: inviteEmail, role_id: inviteRoleId })
      setShowInvite(false); setInviteEmail(''); setInviteRoleId('')
      const res = await workspaceApi.members(workspaceId)
      setMembers(res.data)
    } catch (err: any) {
      alert(err.response?.data?.detail || 'Invite failed')
    } finally { setInviting(false) }
  }

  const doDeleteWorkspace = async (e: React.FormEvent) => {
    e.preventDefault()
    if (deleteConfirmation !== workspace?.name) return
    setDeletingWorkspace(true)
    try {
      await workspaceApi.delete(workspaceId, { confirmation_name: deleteConfirmation })
      router.push('/dashboard')
    } catch (err: any) {
      alert(err.response?.data?.detail || 'Delete failed')
    } finally { setDeletingWorkspace(false) }
  }

  const isAdmin = myLevel === 1

  return (
    <div className="min-h-screen bg-surface-0 flex flex-col" {...getRootProps()}>
      <input {...getInputProps()} />

      {isDragActive && (
        <div className="fixed inset-0 z-50 bg-brand-600/20 border-2 border-dashed border-brand-500 flex items-center justify-center">
          <div className="text-center">
            <Upload className="w-12 h-12 text-brand-400 mx-auto mb-3" />
            <p className="text-xl font-semibold text-white">Drop to upload</p>
          </div>
        </div>
      )}

      {/* Topbar */}
      <nav className="border-b border-border bg-surface-1/80 backdrop-blur-md sticky top-0 z-40">
        <div className="px-6 h-14 flex items-center gap-4">
          <Link href="/dashboard" className="btn-ghost p-2"><ArrowLeft className="w-4 h-4" /></Link>
          <div className="w-px h-5 bg-border" />
          <div className="flex items-center gap-2">
            <div className="w-7 h-7 rounded-lg bg-gradient-brand flex items-center justify-center">
              <Zap className="w-3.5 h-3.5 text-white" />
            </div>
            <span className="font-semibold text-white text-sm">{workspace?.name || '…'}</span>
          </div>
          {workspace?.industry && <span className="badge-blue">{workspace.industry}</span>}
          {workspace && (
            <span className="badge-purple text-xs">
              <Crown className="w-2.5 h-2.5" />
              {workspace.my_role_name} · Level {workspace.my_role_level}
            </span>
          )}
          <div className="ml-auto flex items-center gap-2">
            <button onClick={() => setShowUpload(true)} className="btn-primary">
              <Upload className="w-4 h-4" /> Upload
            </button>
          </div>
        </div>
      </nav>

      <div className="flex flex-1 overflow-hidden">
        {/* Sidebar */}
        <aside className="w-56 border-r border-border bg-surface-1/50 flex-shrink-0 flex flex-col">
          <div className="p-3 space-y-1">
            {([
              { tab: 'files' as Tab, icon: Layers, label: 'Documents & Branches' },
              { tab: 'query' as Tab, icon: MessageSquare, label: 'AI Query' },
              { tab: 'roles' as Tab, icon: Shield, label: 'Groups & Clearance' },
              { tab: 'members' as Tab, icon: Users, label: 'Team Members' },
              { tab: 'audit' as Tab, icon: History, label: 'Audit & Governance' },
              { tab: 'graph' as Tab, icon: Network, label: 'Knowledge Graph' },
              { tab: 'calendar' as Tab, icon: Calendar, label: 'Maintenance Calendar' },
              { tab: 'settings' as Tab, icon: Settings, label: 'Settings' },
            ] as const).map(({ tab, icon: Icon, label }) => (
              <button
                key={tab}
                onClick={() => setActiveTab(tab)}
                className={activeTab === tab ? 'sidebar-item-active w-full' : 'sidebar-item w-full'}
              >
                <Icon className="w-4 h-4" />{label}
              </button>
            ))}
          </div>
          {workspace && (
            <div className="mt-auto p-3 border-t border-border space-y-2">
              <div className="flex items-center justify-between text-xs">
                <span className="text-muted">Documents</span>
                <span className="font-medium text-white">{workspace.file_count || 0}</span>
              </div>
              <div className="flex items-center justify-between text-xs">
                <span className="text-muted">Members</span>
                <span className="font-medium text-white">{workspace.member_count || 0}</span>
              </div>
              <div className="flex items-center justify-between text-xs">
                <span className="text-muted">Roles</span>
                <span className="font-medium text-white">{roles.length}</span>
              </div>
            </div>
          )}
        </aside>

        {/* Main content */}
        <main className="flex-1 overflow-auto">

          {/* ── Files & Branches Tab ── */}
          {activeTab === 'files' && (
            <div className="p-6">
              {/* Folder Breadcrumb Navigation */}
              <div className="flex items-center justify-between mb-6 pb-4 border-b border-border bg-surface-1/40 p-4 rounded-xl">
                <div className="flex items-center gap-2 text-sm flex-wrap">
                  {folderPath.map((item, idx) => (
                    <div key={idx} className="flex items-center gap-2">
                      {idx > 0 && <ChevronRight className="w-4 h-4 text-muted" />}
                      <button
                        onClick={() => navigateFolder(item.id, item.name, idx)}
                        className={`font-medium hover:text-brand-400 transition-colors ${idx === folderPath.length - 1 ? 'text-white font-semibold' : 'text-muted'}`}
                      >
                        {item.name}
                      </button>
                    </div>
                  ))}
                </div>
                {isAdmin && (
                  <button onClick={() => setShowCreateFolder(true)} className="btn-secondary text-xs py-2 px-3 shadow-glow-sm">
                    <FolderPlus className="w-4 h-4 text-amber-400" /> New Branch / Folder
                  </button>
                )}
              </div>

              {/* Subfolders Grid */}
              {folders.length > 0 && (
                <div className="mb-6">
                  <h4 className="text-xs font-semibold uppercase tracking-wider text-muted mb-3 flex items-center gap-2">
                    <Folder className="w-3.5 h-3.5 text-amber-400" /> Sub-Branches / Folders ({folders.length})
                  </h4>
                  <div className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-3">
                    {folders.map(f => (
                      <div key={f.folder_id} className="bg-surface-1 border border-border rounded-xl p-3 flex items-center justify-between hover:border-amber-400/40 hover:shadow-glow-sm transition-all group">
                        <div
                          onClick={() => navigateFolder(f.folder_id, f.name)}
                          className="flex items-center gap-3 flex-1 min-w-0 cursor-pointer"
                        >
                          <div className="w-9 h-9 rounded-lg bg-amber-500/10 border border-amber-500/20 flex items-center justify-center flex-shrink-0">
                            <Folder className="w-4 h-4 text-amber-400 group-hover:scale-110 transition-transform" />
                          </div>
                          <div className="min-w-0 flex-1">
                            <p className="text-sm font-medium text-white truncate">{f.name}</p>
                            <p className="text-xs text-muted mt-0.5">{f.file_count || 0} doc{f.file_count !== 1 ? 's' : ''} · {f.subfolder_count || 0} folder{f.subfolder_count !== 1 ? 's' : ''}</p>
                          </div>
                        </div>
                        {isAdmin && (
                          <div className="flex items-center gap-1 opacity-0 group-hover:opacity-100 transition-opacity">
                            <button
                              onClick={() => setShowAclModal({ type: 'folder', id: f.folder_id, name: f.name, is_inherited: f.is_inherited, allowed_role_ids: f.allowed_role_ids || [], min_access_level: f.min_access_level })}
                              className="btn-ghost p-1.5 text-muted hover:text-white"
                              title="Folder Access Policy"
                            >
                              <Shield className="w-3.5 h-3.5" />
                            </button>
                            <button
                              onClick={() => deleteFolder(f.folder_id, f.name)}
                              className="btn-ghost p-1.5 text-muted hover:text-red-400"
                              title="Delete Folder"
                            >
                              <Trash2 className="w-3.5 h-3.5" />
                            </button>
                          </div>
                        )}
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {/* Document Search Bar */}
              <div className="flex items-center gap-3 mb-6">
                <div className="relative flex-1">
                  <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-muted" />
                  <input className="input pl-9" placeholder="Search documents…" value={search} onChange={e => setSearch(e.target.value)} />
                </div>
                <select className="input w-36" value={statusFilter} onChange={e => setStatusFilter(e.target.value)}>
                  <option value="">All Status</option>
                  <option value="draft">Draft</option>
                  <option value="approved">Approved</option>
                  <option value="superseded">Superseded</option>
                </select>
                <select className="input w-40" value={familyFilter} onChange={e => setFamilyFilter(e.target.value)}>
                  <option value="">All Types</option>
                  <option value="text_office">Documents</option>
                  <option value="table">Spreadsheets</option>
                  <option value="image">Images/Scans</option>
                  <option value="audio">Audio</option>
                  <option value="cad">CAD/Drawings</option>
                  <option value="operational">Exports/Logs</option>
                </select>
                <button onClick={() => loadFiles(currentFolderId)} className="btn-ghost p-2"><RefreshCw className="w-4 h-4" /></button>
              </div>

              {loading ? (
                <div className="flex items-center justify-center py-20"><Loader2 className="w-6 h-6 animate-spin text-brand-400" /></div>
              ) : files.length === 0 ? (
                <div className="text-center py-20">
                  <FileText className="w-12 h-12 text-muted mx-auto mb-4 opacity-30" />
                  <h3 className="text-lg font-semibold text-white mb-2">No documents</h3>
                  <p className="text-muted text-sm mb-6">{search || statusFilter || familyFilter ? 'No documents match your filters.' : 'Upload your first industrial document.'}</p>
                  <button onClick={() => setShowUpload(true)} className="btn-primary"><Upload className="w-4 h-4" />Upload Document</button>
                </div>
              ) : (
                <div className="space-y-2">
                  {files.map(f => {
                    const fam = FILE_FAMILY_META[f.file_family] || FILE_FAMILY_META.unknown
                    const FamIcon = fam.icon
                    const stat = STATUS_META[f.status] || STATUS_META.draft
                    const StatIcon = stat.icon
                    const proc = PROC_STATUS_META[f.processing_status] || PROC_STATUS_META.pending
                    return (
                      <div key={f.file_id} className="bg-surface-1 border border-border rounded-xl p-4 flex items-center gap-4 hover:border-brand-400/30 hover:shadow-glow-sm transition-all">
                        <div className="w-10 h-10 rounded-lg bg-surface-2 border border-border flex items-center justify-center flex-shrink-0">
                          <FamIcon className={`w-5 h-5 ${fam.color}`} />
                        </div>
                        <div className="flex-1 min-w-0">
                          <div className="flex items-center gap-2 flex-wrap">
                            <p className="font-medium text-white text-sm truncate">{f.title || f.original_name}</p>
                            <span className={stat.badge}><StatIcon className="w-2.5 h-2.5" />{stat.label}</span>
                            <span className="badge-gray">v{f.version_number}</span>
                            <span className={`text-xs ${proc.color}`}>● {proc.label}</span>
                            {f.min_access_level && (
                              <span className="badge-red text-xs">
                                <Shield className="w-2.5 h-2.5" />Level ≤ {f.min_access_level}
                              </span>
                            )}
                          </div>
                          <div className="flex items-center gap-3 mt-1 text-xs text-muted">
                            <span>{fam.label}</span><span>·</span>
                            <span>{(f.file_size_bytes / 1024).toFixed(1)} KB</span><span>·</span>
                            <span>{formatDistanceToNow(new Date(f.upload_ts))} ago</span>
                          </div>
                        </div>
                        <div className="flex items-center gap-1 flex-shrink-0">
                          {(isAdmin || f.uploader_id === workspace?.my_user_id) && (
                            <button
                              onClick={() => setShowAclModal({ type: 'file', id: f.file_id, name: f.title || f.original_name, is_inherited: f.is_inherited, allowed_role_ids: f.allowed_role_ids || [], min_access_level: f.min_access_level })}
                              className="btn-ghost p-1.5 text-muted hover:text-white"
                              title="Document Access Policy"
                            >
                              <Shield className="w-3.5 h-3.5" />
                            </button>
                          )}
                          <button onClick={() => downloadFile(f.file_id, f.original_name)} className="btn-ghost p-1.5" title="Download">
                            <Download className="w-3.5 h-3.5" />
                          </button>
                          <Link href={`/workspace/${workspaceId}/file/${f.file_id}`} className="btn-ghost p-1.5" title="View details">
                            <Eye className="w-3.5 h-3.5" />
                          </Link>
                        </div>
                      </div>
                    )
                  })}
                </div>
              )}
            </div>
          )}

          {/* ── Query Tab ── */}
          {activeTab === 'query' && (
            <div className="p-6 max-w-4xl mx-auto">
              <div className="mb-6">
                <h2 className="text-xl font-bold text-white">AI Knowledge Query</h2>
                <p className="text-muted text-sm mt-1">Powered by Groq · llama-3.3-70b-versatile · Answers grounded in your documents only.</p>
              </div>
              <div className="relative mb-6">
                <input
                  ref={queryInputRef}
                  className="input pr-14 py-3.5 text-base"
                  placeholder='e.g. "What is the procedure for replacing the seal on Pump P-204?"'
                  value={queryText}
                  onChange={e => setQueryText(e.target.value)}
                  onKeyDown={e => e.key === 'Enter' && !e.shiftKey && doQuery()}
                />
                <button onClick={doQuery} disabled={querying || !queryText.trim()} className="absolute right-2 top-1/2 -translate-y-1/2 btn-primary p-2">
                  {querying ? <Loader2 className="w-4 h-4 animate-spin" /> : <Send className="w-4 h-4" />}
                </button>
              </div>

              {querying && (
                <div className="card animate-pulse-slow">
                  <div className="flex items-center gap-3 text-brand-400">
                    <Loader2 className="w-5 h-5 animate-spin" />
                    <p className="text-sm">Searching {files.length} documents with hybrid retrieval…</p>
                  </div>
                </div>
              )}

              {queryResult && !querying && (
                <div className="space-y-4 animate-slide-up">
                  <div className={`card ${queryResult.no_answer ? 'border-amber-700/30' : 'border-brand-600/30'}`}>
                    <div className="flex items-center gap-2 mb-3">
                      <MessageSquare className={`w-4 h-4 ${queryResult.no_answer ? 'text-amber-400' : 'text-brand-400'}`} />
                      <span className="text-sm font-medium text-white">Answer</span>
                      {!queryResult.no_answer && (
                        <span className="ml-auto badge-blue">{Math.round((queryResult.confidence || 0) * 100)}% confidence</span>
                      )}
                      {queryResult.model_used && <span className="text-xs text-muted">{queryResult.model_used}</span>}
                    </div>
                    <p className="text-white text-sm leading-relaxed whitespace-pre-wrap">{typeof queryResult.answer === 'string' ? queryResult.answer : (Array.isArray(queryResult.answer) ? queryResult.answer.map((a: any) => a.msg || JSON.stringify(a)).join('; ') : JSON.stringify(queryResult.answer))}</p>
                  </div>

                  {queryResult.citations?.length > 0 && (
                    <div className="card">
                      <div className="flex items-center gap-2 mb-3">
                        <BookOpen className="w-4 h-4 text-muted" />
                        <span className="text-sm font-medium text-white">Sources</span>
                        <span className="badge-gray ml-auto">{queryResult.citations.length}</span>
                      </div>
                      <div className="space-y-2">
                        {queryResult.citations.map((cit: any, i: number) => {
                          const fam = FILE_FAMILY_META[cit.file_family] || FILE_FAMILY_META.unknown
                          const FamIcon = fam.icon
                          return (
                            <div key={i} className="flex items-start gap-3 p-3 rounded-lg bg-surface-2 border border-border/50">
                              <FamIcon className={`w-4 h-4 ${fam.color} mt-0.5 flex-shrink-0`} />
                              <div className="flex-1 min-w-0">
                                <p className="text-sm font-medium text-white truncate">{cit.title || cit.original_name}</p>
                                <p className="text-xs text-muted mt-0.5">v{cit.version_number}{cit.page_number && ` · Page ${cit.page_number}`} · {Math.round(cit.relevance_score * 100)}% relevance</p>
                              </div>
                              <Link href={`/workspace/${workspaceId}/file/${cit.file_id}`} className="btn-ghost p-1 flex-shrink-0">
                                <ExternalLink className="w-3.5 h-3.5" />
                              </Link>
                            </div>
                          )
                        })}
                      </div>
                    </div>
                  )}

                  {queryResult.related_files?.length > 0 && (
                    <div className="card">
                      <div className="flex items-center gap-2 mb-3">
                        <GitBranch className="w-4 h-4 text-muted" />
                        <span className="text-sm font-medium text-white">Related Files</span>
                      </div>
                      <div className="flex flex-wrap gap-2">
                        {queryResult.related_files.map((rf: any) => {
                          const fam = FILE_FAMILY_META[rf.file_family] || FILE_FAMILY_META.unknown
                          const FamIcon = fam.icon
                          return (
                            <Link key={rf.file_id} href={`/workspace/${workspaceId}/file/${rf.file_id}`} className="flex items-center gap-2 px-3 py-1.5 rounded-lg bg-surface-2 border border-border/50 hover:border-brand-400/40 transition-all text-sm">
                              <FamIcon className={`w-3.5 h-3.5 ${fam.color}`} />
                              <span className="text-white text-xs">{rf.title || rf.original_name}</span>
                            </Link>
                          )
                        })}
                      </div>
                    </div>
                  )}
                </div>
              )}

              {!queryResult && !querying && (
                <div className="mt-8">
                  <p className="text-xs text-muted font-medium uppercase tracking-wider mb-3">Example queries</p>
                  <div className="flex flex-wrap gap-2">
                    {['What maintenance procedures apply to Pump P-204?', 'Show me all approved safety procedures', 'Find inspection reports from last quarter', 'What standards are referenced in the piping manual?'].map(q => (
                      <button key={q} onClick={() => { setQueryText(q); setTimeout(doQuery, 100) }} className="text-xs px-3 py-2 rounded-lg border border-border bg-surface-2 hover:border-brand-400/40 text-muted hover:text-white transition-all">{q}</button>
                    ))}
                  </div>
                </div>
              )}
            </div>
          )}

          {/* ── Roles Tab ── */}
          {activeTab === 'roles' && (
            <div className="p-6 max-w-3xl mx-auto">
              <div className="flex items-center justify-between mb-6">
                <div>
                  <h2 className="text-xl font-bold text-white">Role Levels</h2>
                  <p className="text-muted text-sm mt-1">
                    Level 1 = highest authority. Higher numbers = less priority.
                    {!isAdmin && <span className="text-amber-400 ml-2">View only — Level 1 required to manage roles.</span>}
                  </p>
                </div>
                {isAdmin && (
                  <div className="flex items-center gap-2">
                    <button
                      onClick={() => { setSwapMode(!swapMode); setSwapSelection([]) }}
                      className={swapMode ? 'btn-primary' : 'btn-secondary'}
                    >
                      <ArrowUpDown className="w-4 h-4" />
                      {swapMode ? 'Cancel Swap' : 'Swap Levels'}
                    </button>
                    <button onClick={() => setShowCreateRole(true)} className="btn-primary">
                      <Plus className="w-4 h-4" /> Add Role
                    </button>
                  </div>
                )}
              </div>

              {/* Swap instruction banner */}
              {swapMode && (
                <div className="mb-4 p-4 rounded-xl bg-brand-900/30 border border-brand-700/40 flex items-start gap-3">
                  <ArrowUpDown className="w-5 h-5 text-brand-400 flex-shrink-0 mt-0.5" />
                  <div className="flex-1">
                    <p className="text-sm text-white font-medium">Select two roles to swap their level numbers</p>
                    <p className="text-xs text-muted mt-1">
                      Members stay in their roles — only the level numbers are exchanged.
                      All members' authority changes accordingly.
                    </p>
                    {swapSelection.length > 0 && (
                      <p className="text-xs text-brand-300 mt-2">
                        Selected: {swapSelection.map(id => roles.find(r => r.role_id === id)?.name).join(' ↔ ')}
                      </p>
                    )}
                  </div>
                  {swapSelection.length === 2 && (
                    <button onClick={doSwap} disabled={swapping} className="btn-primary flex-shrink-0">
                      {swapping ? <Loader2 className="w-4 h-4 animate-spin" /> : <ArrowUpDown className="w-4 h-4" />}
                      Confirm Swap
                    </button>
                  )}
                </div>
              )}

              {/* Roles list grouped by branch */}
              <div className="space-y-6">
                {roles.length === 0 ? (
                  <div className="text-center py-12 text-muted">No roles defined yet.</div>
                ) : (
                  Array.from(new Set(roles.map(r => r.branch || 'Main'))).map(branchName => {
                    const branchRoles = roles.filter(r => (r.branch || 'Main') === branchName)
                    return (
                      <div key={branchName} className="space-y-2">
                        <div className="flex items-center gap-2 px-1">
                          <span className="text-xs font-semibold uppercase tracking-wider text-brand-300 bg-brand-900/30 px-2.5 py-1 rounded-full border border-brand-700/40">
                            Branch: {branchName}
                          </span>
                        </div>
                        {branchRoles.map(role => {
                          const isSelected = swapSelection.includes(role.role_id)
                          const isL1 = role.level === 1
                          const parentRole = roles.find(r => r.role_id === role.parent_role_id)
                          return (
                            <div
                              key={role.role_id}
                              onClick={() => swapMode && isAdmin && toggleSwapSelect(role.role_id)}
                              className={`flex items-center gap-4 p-4 rounded-xl border transition-all ${
                                swapMode ? 'cursor-pointer' : ''
                              } ${
                                isSelected
                                  ? 'bg-brand-900/40 border-brand-500/60 shadow-glow-sm'
                                  : swapMode
                                  ? 'bg-surface-1 border-border hover:border-brand-400/40'
                                  : 'bg-surface-1 border-border'
                              }`}
                            >
                              {/* Level badge */}
                              <div className={`w-12 h-12 rounded-xl flex items-center justify-center flex-shrink-0 font-bold text-lg ${
                                isL1
                                  ? 'bg-gradient-brand text-white shadow-glow-sm'
                                  : 'bg-surface-2 border border-border text-muted'
                              }`}>
                                {role.level}
                              </div>

                              {/* Info */}
                              <div className="flex-1 min-w-0">
                                <div className="flex items-center gap-2 flex-wrap">
                                  <p className="font-semibold text-white">{role.name}</p>
                                  {isL1 && <Crown className="w-3.5 h-3.5 text-amber-400" />}
                                  {parentRole && (
                                    <span className="text-[11px] bg-surface-2 border border-border px-2 py-0.5 rounded text-muted">
                                      ↳ Sub-role of L{parentRole.level} ({parentRole.name})
                                    </span>
                                  )}
                                </div>
                                {role.description && <p className="text-xs text-muted mt-0.5">{role.description}</p>}
                                <p className="text-xs text-muted mt-1">
                                  {role.member_count} member{role.member_count !== 1 ? 's' : ''}
                                  {' · '}
                                  {isL1 ? 'Full authority' : `Authority level ${role.level}`}
                                </p>
                              </div>

                              {/* Graph modification permission toggle */}
                              <div className="flex items-center gap-2 mr-2">
                                <span className={`text-xs px-2.5 py-1 rounded-full border flex items-center gap-1.5 ${
                                  isL1 || role.can_modify_graph
                                    ? 'bg-purple-900/30 border-purple-600/50 text-purple-300'
                                    : 'bg-surface-2 border-border text-muted'
                                }`}>
                                  <input
                                    type="checkbox"
                                    checked={isL1 || role.can_modify_graph}
                                    onChange={() => !isL1 && toggleCanModifyGraph(role)}
                                    disabled={isL1 || !isAdmin}
                                    className="rounded border-border text-purple-500 focus:ring-purple-500 bg-surface-3 cursor-pointer"
                                  />
                                  <span>Modify Graph</span>
                                </span>
                              </div>

                              {/* Swap indicator */}
                              {swapMode && isSelected && (
                                <span className="badge-blue flex-shrink-0">✓ Selected</span>
                              )}

                              {/* Actions (not in swap mode) */}
                              {!swapMode && isAdmin && (
                                <button
                                  onClick={() => deleteRole(role.role_id)}
                                  disabled={deletingRole === role.role_id}
                                  className="btn-ghost p-2 flex-shrink-0 hover:text-red-400"
                                  title="Delete role"
                                >
                                  {deletingRole === role.role_id
                                    ? <Loader2 className="w-4 h-4 animate-spin" />
                                    : <Trash2 className="w-4 h-4" />}
                                </button>
                              )}
                            </div>
                          )
                        })}
                      </div>
                    )
                  })
                )}
              </div>

              {/* Level guide */}
              <div className="mt-6 p-4 rounded-xl bg-surface-2 border border-border">
                <p className="text-xs font-medium text-muted uppercase tracking-wider mb-2">How levels work</p>
                <div className="space-y-1 text-xs text-muted">
                  <p>• <span className="text-white">Level 1</span> — highest authority, can manage roles and invite members</p>
                  <p>• Higher numbers = lower priority in the hierarchy</p>
                  <p>• Files can restrict access to "Level ≤ N" users only</p>
                  <p>• Use <span className="text-brand-400">Swap Levels</span> to reorganize without reassigning members</p>
                </div>
              </div>
            </div>
          )}

          {/* ── Members Tab ── */}
          {activeTab === 'members' && (
            <div className="p-6 max-w-3xl mx-auto">
              <div className="flex items-center justify-between mb-6">
                <div>
                  <h2 className="text-xl font-bold text-white">Team Members</h2>
                  <p className="text-muted text-sm mt-1">Sorted by role level (highest authority first)</p>
                </div>
                {isAdmin && (
                  <button onClick={() => setShowInvite(true)} className="btn-primary">
                    <Plus className="w-4 h-4" /> Invite Member
                  </button>
                )}
              </div>

              <div className="space-y-2">
                {members.map((m: any) => (
                  <div key={m.user_id} className="flex items-center gap-4 p-4 rounded-xl bg-surface-1 border border-border">
                    <div className="w-10 h-10 rounded-full bg-brand-800 border border-brand-600/40 flex items-center justify-center font-semibold text-brand-300 text-sm flex-shrink-0">
                      {m.full_name.split(' ').map((n: string) => n[0]).join('').slice(0, 2).toUpperCase()}
                    </div>
                    <div className="flex-1 min-w-0">
                      <p className="font-medium text-white text-sm">{m.full_name}</p>
                      <p className="text-xs text-muted">{m.email}</p>
                    </div>
                    <div className="flex items-center gap-2 flex-shrink-0">
                      <div className={`flex items-center gap-1.5 px-2.5 py-1 rounded-lg border text-xs font-medium ${
                        m.role_level === 1 ? 'bg-brand-900/40 border-brand-700/50 text-brand-300' : 'bg-surface-2 border-border text-muted'
                      }`}>
                        {m.role_level === 1 && <Crown className="w-3 h-3 text-amber-400" />}
                        {m.role_name}
                        <span className="opacity-60">· L{m.role_level}</span>
                      </div>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* ── Audit & Governance Tab ── */}
          {activeTab === 'audit' && (
            <div className="p-6 max-w-5xl mx-auto">
              <div className="flex items-center justify-between mb-6">
                <div>
                  <h2 className="text-xl font-bold text-white flex items-center gap-2">
                    <History className="w-5 h-5 text-brand-400" /> Audit & Governance Ledger
                  </h2>
                  <p className="text-muted text-sm mt-1">
                    Immutable activity and security governance log. Tracks all level changes, folder creations, member additions, and document policy exceptions.
                  </p>
                </div>
              </div>

              <div className="bg-surface-1 border border-border rounded-xl overflow-hidden">
                {auditLogs.length === 0 ? (
                  <div className="text-center py-12 text-muted">No audit events recorded yet.</div>
                ) : (
                  <div className="divide-y divide-border">
                    {auditLogs.map((log: any) => (
                      <div key={log.audit_id} className="p-4 flex items-start justify-between gap-4 hover:bg-surface-2/40 transition-colors">
                        <div className="flex items-start gap-3">
                          <div className="w-8 h-8 rounded-lg bg-surface-2 border border-border flex items-center justify-center flex-shrink-0 mt-0.5">
                            <ShieldCheck className="w-4 h-4 text-brand-400" />
                          </div>
                          <div>
                            <div className="flex items-center gap-2 flex-wrap">
                              <span className="font-semibold text-white text-sm capitalize">{log.action.replace(/_/g, ' ')}</span>
                              <span className="badge-gray text-xs">{formatDistanceToNow(new Date(log.ts))} ago</span>
                            </div>
                            <p className="text-xs text-muted mt-1">
                              User ID: <span className="font-mono text-brand-300">{log.user_id}</span>
                              {log.file_id && <> · File ID: <span className="font-mono text-emerald-300">{log.file_id}</span></>}
                            </p>
                            {log.extra && Object.keys(log.extra).length > 0 && (
                              <pre className="text-[11px] bg-surface-2/80 border border-border/60 p-2 rounded-lg mt-2 font-mono text-muted overflow-x-auto max-w-xl">
                                {JSON.stringify(log.extra, null, 2)}
                              </pre>
                            )}
                          </div>
                        </div>
                        <span className="text-xs text-muted font-mono whitespace-nowrap">{format(new Date(log.ts), 'MMM d, yyyy HH:mm:ss')}</span>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            </div>
          )}
          {/* ── Knowledge Graph Tab ── */}
          {activeTab === 'graph' && (
            <div className="p-6 flex flex-col h-full" style={{ minHeight: '750px' }}>
              {/* Header */}
              <div className="flex flex-wrap items-center justify-between gap-4 mb-4">
                <div>
                  <h2 className="text-xl font-bold text-white flex items-center gap-2">
                    <Network className="w-5 h-5 text-brand-400" />
                    Knowledge Graph
                  </h2>
                  <p className="text-sm text-muted mt-1">
                    {graphData.nodes.length} file nodes · {graphData.links.length} edges
                    {graphData.nodes.length === 0 && ' — upload and process files to populate the graph'}
                  </p>
                </div>
                <div className="flex items-center gap-2">
                  <button
                    onClick={() => setShowAddNodeModal(true)}
                    className="btn-secondary"
                  >
                    <Plus className="w-4 h-4" />
                    Add Node
                  </button>
                  <button
                    onClick={() => {
                      setEdgeMode(!edgeMode)
                      setSelectedSourceNode(null)
                      setSelectedTargetNode(null)
                    }}
                    className={`btn ${edgeMode ? 'bg-amber-500 text-white font-semibold' : 'btn-secondary'}`}
                  >
                    <Plus className="w-4 h-4" />
                    {edgeMode ? 'Cancel Edge Mode' : 'Add Custom Edge'}
                  </button>
                  <button
                    onClick={loadGraph}
                    disabled={graphLoading}
                    className="btn-secondary"
                  >
                    {graphLoading
                      ? <Loader2 className="w-4 h-4 animate-spin" />
                      : <RefreshCw className="w-4 h-4" />}
                    Refresh
                  </button>
                </div>
              </div>

              {/* Edge Mode Banner */}
              {edgeMode && (
                <div className="mb-4 p-3.5 bg-amber-500/10 border border-amber-500/40 rounded-xl flex items-center justify-between text-xs text-amber-300">
                  <div className="flex items-center gap-2.5">
                    <AlertCircle className="w-4 h-4 text-amber-400 shrink-0" />
                    <span>
                      <strong>Edge Creation Mode Active:</strong>{' '}
                      {!selectedSourceNode
                        ? 'Click the FIRST file node on the graph (Source).'
                        : `Source node selected (${selectedSourceNode.name}). Now click the SECOND file node (Target).`}
                    </span>
                  </div>
                  {selectedSourceNode && (
                    <button
                      onClick={() => setSelectedSourceNode(null)}
                      className="text-amber-400 hover:underline font-semibold"
                    >
                      Reset Source
                    </button>
                  )}
                </div>
              )}

              {/* Branch Color Legend & Edge Type Legend */}
              <div className="flex flex-wrap items-center justify-between gap-4 mb-4 p-3 bg-surface-1 border border-border rounded-xl text-xs">
                <div className="flex flex-wrap items-center gap-3">
                  <span className="text-muted font-medium uppercase tracking-wider">Branch Colors:</span>
                  {uniqueBranches.map(branchName => (
                    <span key={branchName} className="flex items-center gap-1.5 bg-surface-2 px-2.5 py-1 rounded-md border border-border/60">
                      <span className="w-2.5 h-2.5 rounded-full shadow-sm" style={{ backgroundColor: getBranchColor(branchName) }} />
                      <span className="text-white font-medium">{branchName}</span>
                    </span>
                  ))}
                </div>
                <div className="flex items-center gap-4 border-l border-border pl-4">
                  <span className="flex items-center gap-1.5 text-muted">
                    <span className="w-4 h-0.5 bg-slate-400/60 inline-block" />
                    System Edge
                  </span>
                  <span className="flex items-center gap-1.5 text-pink-400 font-medium">
                    <span className="w-4 h-0.5 bg-pink-400 border-b border-dashed border-pink-400 inline-block" />
                    User Custom Edge
                  </span>
                </div>
              </div>

              {/* Graph canvas */}
              <div
                ref={graphContainerRef}
                className="flex-1 bg-surface-1 border border-border rounded-xl overflow-hidden relative"
                style={{ minHeight: '520px' }}
              >
                {graphLoading && (
                  <div className="absolute inset-0 flex items-center justify-center bg-surface-1/70 z-10 backdrop-blur-sm">
                    <div className="flex flex-col items-center gap-3">
                      <Loader2 className="w-8 h-8 animate-spin text-brand-400" />
                      <p className="text-sm text-muted">Loading knowledge graph…</p>
                    </div>
                  </div>
                )}

                {!graphLoading && graphData.nodes.length === 0 ? (
                  <div className="absolute inset-0 flex flex-col items-center justify-center gap-3">
                    <Network className="w-16 h-16 text-muted opacity-20" />
                    <h3 className="text-lg font-semibold text-white">Graph is empty</h3>
                    <p className="text-sm text-muted text-center max-w-sm">
                      Upload documents and wait for processing to complete.
                      The graph will populate automatically with files and their relationships.
                    </p>
                    <button onClick={() => setActiveTab('files')} className="btn-primary mt-2">
                      <Upload className="w-4 h-4" /> Go to Documents
                    </button>
                  </div>
                ) : (
                  <ForceGraph2D
                    graphData={graphData}
                    width={graphDimensions.width}
                    height={graphDimensions.height}
                    nodeColor={(node: any) => getBranchColor(node.branch || 'Root')}
                    nodeRelSize={6}
                    nodeLabel={(node: any) => `${node.group ? node.group.toUpperCase() : 'FILE'}: ${node.name}\nBranch: ${node.branch || 'Root'}\nClick to ${edgeMode ? 'connect' : 'view'}`}
                    linkDirectionalArrowLength={5}
                    linkDirectionalArrowRelPos={1}
                    linkColor={(link: any) => link.edge_source === 'user' ? '#f472b6' : 'rgba(148,163,184,0.35)'}
                    linkWidth={(link: any) => link.edge_source === 'user' ? 2.5 : 1.2}
                    linkLineDash={(link: any) => link.edge_source === 'user' ? [4, 2] : null}
                    backgroundColor="transparent"
                    onNodeClick={(node: any) => {
                      if (edgeMode) {
                        if (!selectedSourceNode) {
                          setSelectedSourceNode(node)
                        } else if (selectedSourceNode.id !== node.id) {
                          setSelectedTargetNode(node)
                          setShowAddEdgeModal(true)
                        }
                      } else {
                        // View node details or switch tab
                        router.push(`/workspace/${workspaceId}/file/${node.external_id || node.id}`)
                      }
                    }}
                    onLinkClick={(link: any) => {
                      setSelectedLinkDetails(link)
                    }}
                  />
                )}
              </div>

              {/* User Custom Edges & Comments Section below Graph */}
              {graphMutations && graphMutations.length > 0 && (
                <div className="mt-6 bg-surface-1 border border-border rounded-xl p-5">
                  <h3 className="text-sm font-semibold text-white flex items-center justify-between mb-3">
                    <span className="flex items-center gap-2">
                      <MessageSquare className="w-4 h-4 text-pink-400" />
                      User Custom Edges & Comments ({graphMutations.filter((m: any) => m.action === 'ADD' || m.action === 'add').length})
                    </span>
                  </h3>
                  <div className="grid grid-cols-1 md:grid-cols-2 gap-3 max-h-64 overflow-y-auto pr-1">
                    {graphMutations.filter((m: any) => m.action === 'ADD' || m.action === 'add').map((mut: any) => {
                      const fromNode = graphData.nodes.find((n: any) => n.id === mut.from_node_id)
                      const toNode = graphData.nodes.find((n: any) => n.id === mut.to_node_id)
                      return (
                        <div key={mut.mutation_id} className="bg-surface-2 border border-border/80 rounded-lg p-3 flex flex-col justify-between gap-2 text-xs">
                          <div>
                            <div className="flex items-center justify-between font-medium text-white mb-1">
                              <span className="text-pink-400 truncate max-w-[150px]" title={fromNode?.name || mut.from_node_id}>
                                {fromNode?.name || mut.from_node_id.slice(0, 8)}
                              </span>
                              <span className="text-muted text-[10px] uppercase bg-surface-0 px-1.5 py-0.5 rounded border border-border">
                                {mut.label || 'related'}
                              </span>
                              <span className="text-brand-300 truncate max-w-[150px]" title={toNode?.name || mut.to_node_id}>
                                {toNode?.name || mut.to_node_id.slice(0, 8)}
                              </span>
                            </div>
                            {mut.comment && (
                              <p className="text-muted/90 italic bg-surface-0/60 p-2 rounded mt-1 border border-border/40">
                                "{mut.comment}"
                              </p>
                            )}
                          </div>
                          <div className="flex items-center justify-between pt-1 border-t border-border/40 text-[11px] text-muted">
                            <span>Weight: {(mut.weight ?? 0.8).toFixed(2)}</span>
                            <button
                              onClick={() => doDeleteMutation(mut.mutation_id)}
                              className="text-red-400 hover:text-red-300 hover:underline flex items-center gap-1 font-medium"
                            >
                              <Trash2 className="w-3 h-3" /> Delete
                            </button>
                          </div>
                        </div>
                      )
                    })}
                  </div>
                </div>
              )}
            </div>
          )}

          {/* ── Calendar Tab ── */}
          {activeTab === 'calendar' && (
            <div className="p-6 space-y-6">
              {/* Header */}
              <div className="flex items-center justify-between flex-wrap gap-3">
                <div>
                  <h2 className="text-xl font-bold text-white flex items-center gap-2"><Calendar className="w-5 h-5 text-emerald-400" /> Maintenance Calendar</h2>
                  <p className="text-xs text-muted mt-1">Events extracted from documents or created via AI commands.</p>
                </div>
                <div className="flex items-center gap-2 flex-wrap">
                  <button onClick={() => setCalendarView(calendarView === 'list' ? 'expanded' : 'list')} className="btn-secondary text-xs">
                    <CalendarClock className="w-3.5 h-3.5" />
                    {calendarView === 'list' ? 'Expanded view' : 'Raw events'}
                  </button>
                  <button onClick={() => {
                    setCalendarLoading(true)
                    Promise.all([
                      calendarApi.listEvents(workspaceId, calendarTypeFilter ? { event_type: calendarTypeFilter } : undefined),
                      calendarApi.listExpanded(workspaceId, 6)
                    ]).then(([evRes, exRes]) => { setCalendarEvents(evRes.data); setCalendarExpanded(exRes.data) })
                    .catch(console.error).finally(() => setCalendarLoading(false))
                  }} className="btn-secondary text-xs">
                    <RefreshCw className={`w-3.5 h-3.5 ${calendarLoading ? 'animate-spin' : ''}`} /> Refresh
                  </button>
                  <button onClick={() => setShowCreateEvent(true)} className="btn-primary text-xs">
                    <CalendarPlus className="w-3.5 h-3.5" /> Add Event
                  </button>
                </div>
              </div>

              {/* AI Calendar Query */}
              <div className="bg-surface-1 border border-border rounded-2xl p-4">
                <h3 className="text-sm font-semibold text-white flex items-center gap-2 mb-3"><Bot className="w-4 h-4 text-brand-400" /> AI Calendar Command</h3>
                <div className="flex gap-2">
                  <input
                    type="text"
                    value={calendarQuery}
                    onChange={e => setCalendarQuery(e.target.value)}
                    placeholder='e.g. "Add monthly vibration analysis for compressor C-17"'
                    className="input flex-1 text-sm"
                    onKeyDown={async e => {
                      if (e.key === 'Enter' && calendarQuery.trim() && !calendarQuerying) {
                        setCalendarQuerying(true)
                        try {
                          await calendarApi.queryCalendar(workspaceId, { query: calendarQuery })
                          setCalendarQuery('')
                          const [evRes, exRes] = await Promise.all([calendarApi.listEvents(workspaceId), calendarApi.listExpanded(workspaceId, 6)])
                          setCalendarEvents(evRes.data); setCalendarExpanded(exRes.data)
                        } catch (err) { alert(getErrorMsg(err, 'Failed to process calendar command')) }
                        finally { setCalendarQuerying(false) }
                      }
                    }}
                  />
                  <button disabled={!calendarQuery.trim() || calendarQuerying} onClick={async () => {
                    setCalendarQuerying(true)
                    try {
                      await calendarApi.queryCalendar(workspaceId, { query: calendarQuery })
                      setCalendarQuery('')
                      const [evRes, exRes] = await Promise.all([calendarApi.listEvents(workspaceId), calendarApi.listExpanded(workspaceId, 6)])
                      setCalendarEvents(evRes.data); setCalendarExpanded(exRes.data)
                    } catch (err) { alert(getErrorMsg(err, 'Failed to process calendar command')) }
                    finally { setCalendarQuerying(false) }
                  }} className="btn-primary text-xs px-4">
                    {calendarQuerying ? <Loader2 className="w-4 h-4 animate-spin" /> : <Send className="w-4 h-4" />}
                  </button>
                </div>
                <p className="text-xs text-muted mt-2">Press Enter or Send. e.g. "Add quarterly inspection for pump P-101" will create events via AI.</p>
              </div>

              {/* Filter bar */}
              <div className="flex items-center gap-2 flex-wrap">
                <span className="text-xs text-muted">Filter:</span>
                {['', 'preventive', 'shutdown', 'inspection', 'calibration', 'test', 'other'].map(t => (
                  <button key={t} onClick={() => setCalendarTypeFilter(t)}
                    className={`text-xs px-2.5 py-1 rounded-lg border transition-all ${calendarTypeFilter === t ? 'bg-emerald-500/20 border-emerald-500/50 text-emerald-400' : 'border-border text-muted hover:text-white'}`}>
                    {t === '' ? 'All' : t.charAt(0).toUpperCase() + t.slice(1)}
                  </button>
                ))}
              </div>

              {/* Empty state */}
              {calendarEvents.length === 0 && !calendarLoading && (
                <div className="text-center py-16 text-muted">
                  <Calendar className="w-12 h-12 mx-auto mb-3 opacity-30" />
                  <p className="text-sm font-medium">No calendar events yet.</p>
                  <p className="text-xs mt-1">Upload maintenance documents or use the AI command above.</p>
                  <button className="btn-secondary text-xs mt-4" onClick={() => {
                    setCalendarLoading(true)
                    Promise.all([calendarApi.listEvents(workspaceId), calendarApi.listExpanded(workspaceId, 6)])
                      .then(([evRes, exRes]) => { setCalendarEvents(evRes.data); setCalendarExpanded(exRes.data) })
                      .catch(console.error).finally(() => setCalendarLoading(false))
                  }}><RefreshCw className="w-3.5 h-3.5" /> Load Events</button>
                </div>
              )}

              {calendarLoading && <div className="flex items-center justify-center py-12"><Loader2 className="w-6 h-6 animate-spin text-emerald-400" /></div>}

              {/* Events list */}
              <div className="space-y-3">
                {!calendarLoading && (calendarView === 'list' ? calendarEvents : calendarExpanded)
                  .filter((ev: any) => !calendarTypeFilter || ev.event_type === calendarTypeFilter)
                  .map((ev: any, idx: number) => {
                    const startDt = ev.start_at ? new Date(ev.start_at) : null
                    const typeColors: Record<string, string> = {
                      preventive: 'text-emerald-400 bg-emerald-500/10 border-emerald-500/30',
                      shutdown: 'text-red-400 bg-red-500/10 border-red-500/30',
                      inspection: 'text-blue-400 bg-blue-500/10 border-blue-500/30',
                      calibration: 'text-amber-400 bg-amber-500/10 border-amber-500/30',
                      test: 'text-purple-400 bg-purple-500/10 border-purple-500/30',
                      other: 'text-slate-400 bg-slate-500/10 border-slate-500/30',
                    }
                    const confColor = ev.confidence === 'high' ? 'text-emerald-400' : ev.confidence === 'medium' ? 'text-amber-400' : 'text-red-400'
                    return (
                      <div key={ev.event_id + '-' + idx} className={`bg-surface-1 border border-border rounded-xl p-4 hover:border-emerald-500/40 transition-all group ${ev.is_expanded_instance ? 'border-dashed opacity-80' : ''}`}>
                        <div className="flex items-start justify-between gap-3">
                          <div className="flex-1 min-w-0">
                            <div className="flex items-center gap-2 flex-wrap mb-1.5">
                              <span className={`text-xs px-2 py-0.5 rounded-full border font-medium ${typeColors[ev.event_type] || typeColors.other}`}>{ev.event_type}</span>
                              {ev.equipment_id && <span className="text-xs px-2 py-0.5 rounded-full border border-cyan-500/30 bg-cyan-500/10 text-cyan-400 font-mono">{ev.equipment_id}</span>}
                              <span className={`text-xs font-medium ${confColor}`}>{ev.confidence}</span>
                              {ev.is_expanded_instance && <span className="text-xs text-muted bg-surface-0 px-1.5 py-0.5 rounded border border-border">Recurrence #{ev.instance_number}</span>}
                              {ev.source_type === 'query' && <span className="text-xs text-pink-400 bg-pink-500/10 px-1.5 py-0.5 rounded border border-pink-500/30">AI Command</span>}
                              {ev.source_type === 'document' && <span className="text-xs text-blue-400 bg-blue-500/10 px-1.5 py-0.5 rounded border border-blue-500/30">From Document</span>}
                            </div>
                            <h4 className="font-semibold text-white text-sm">{ev.title}</h4>
                            {ev.description && <p className="text-xs text-muted mt-1 line-clamp-2">{ev.description}</p>}
                          </div>
                          <div className="text-right flex-shrink-0 space-y-0.5">
                            {startDt && <div className="text-xs text-white font-medium">{format(startDt, 'dd MMM yyyy')}</div>}
                            {ev.repeat_rule && <div className="text-xs text-muted">🔄 {ev.repeat_rule}</div>}
                            {!ev.is_expanded_instance && (
                              <button onClick={async () => {
                                if (!confirm('Delete this event?')) return
                                try {
                                  await calendarApi.deleteEvent(workspaceId, ev.event_id)
                                  setCalendarEvents(prev => prev.filter(e => e.event_id !== ev.event_id))
                                  setCalendarExpanded(prev => prev.filter(e => e.event_id !== ev.event_id))
                                } catch (err) { alert(getErrorMsg(err, 'Failed to delete event')) }
                              }} className="mt-1.5 text-xs text-red-400 hover:text-red-300 opacity-0 group-hover:opacity-100 transition-opacity flex items-center gap-1 ml-auto">
                                <Trash2 className="w-3 h-3" /> Delete
                              </button>
                            )}
                          </div>
                        </div>
                      </div>
                    )
                  })
                }
              </div>

              {/* Create Event Modal */}
              {showCreateEvent && (
                <div className="fixed inset-0 bg-black/60 backdrop-blur-sm z-50 flex items-center justify-center p-4">
                  <div className="bg-surface-1 border border-border rounded-2xl w-full max-w-lg shadow-glow animate-slide-up overflow-hidden">
                    <div className="p-5 border-b border-border flex items-center justify-between">
                      <h3 className="font-semibold text-white flex items-center gap-2"><CalendarPlus className="w-5 h-5 text-emerald-400" /> New Maintenance Event</h3>
                      <button onClick={() => setShowCreateEvent(false)} className="text-muted hover:text-white"><X className="w-5 h-5" /></button>
                    </div>
                    <form onSubmit={async e => {
                      e.preventDefault(); setCreatingEvent(true)
                      try {
                        await calendarApi.createEvent(workspaceId, { ...newEventForm, workspace_id: workspaceId, source_type: 'manual', source_id: 'manual-entry', start_at: newEventForm.start_at || undefined })
                        setShowCreateEvent(false)
                        setNewEventForm({ title: '', equipment_id: '', event_type: 'preventive', start_at: '', repeat_rule: '', description: '', confidence: 'high' })
                        const [evRes, exRes] = await Promise.all([calendarApi.listEvents(workspaceId), calendarApi.listExpanded(workspaceId, 6)])
                        setCalendarEvents(evRes.data); setCalendarExpanded(exRes.data)
                      } catch (err) { alert(getErrorMsg(err, 'Failed to create event')) }
                      finally { setCreatingEvent(false) }
                    }} className="p-5 space-y-4">
                      <div>
                        <label className="label">Title *</label>
                        <input required value={newEventForm.title} onChange={e => setNewEventForm({...newEventForm, title: e.target.value})} className="input w-full" placeholder="e.g. Quarterly inspection – Pump P-101" />
                      </div>
                      <div className="grid grid-cols-2 gap-3">
                        <div>
                          <label className="label">Equipment ID / Tag</label>
                          <input value={newEventForm.equipment_id} onChange={e => setNewEventForm({...newEventForm, equipment_id: e.target.value})} className="input w-full" placeholder="P-101" />
                        </div>
                        <div>
                          <label className="label">Event Type</label>
                          <select value={newEventForm.event_type} onChange={e => setNewEventForm({...newEventForm, event_type: e.target.value})} className="input w-full">
                            {['preventive','shutdown','inspection','calibration','test','other'].map(t => <option key={t} value={t}>{t}</option>)}
                          </select>
                        </div>
                      </div>
                      <div className="grid grid-cols-2 gap-3">
                        <div>
                          <label className="label">Start Date / Time</label>
                          <input type="datetime-local" value={newEventForm.start_at} onChange={e => setNewEventForm({...newEventForm, start_at: e.target.value})} className="input w-full" />
                        </div>
                        <div>
                          <label className="label">Recurrence Rule</label>
                          <input value={newEventForm.repeat_rule} onChange={e => setNewEventForm({...newEventForm, repeat_rule: e.target.value})} className="input w-full" placeholder='every 3 months' />
                        </div>
                      </div>
                      <div>
                        <label className="label">Description / Source Reference</label>
                        <textarea value={newEventForm.description} onChange={e => setNewEventForm({...newEventForm, description: e.target.value})} className="input w-full h-20 resize-none" placeholder="Source section / page citation..." />
                      </div>
                      <div>
                        <label className="label">Confidence</label>
                        <select value={newEventForm.confidence} onChange={e => setNewEventForm({...newEventForm, confidence: e.target.value})} className="input w-full">
                          <option value="high">High</option>
                          <option value="medium">Medium</option>
                          <option value="low">Low</option>
                        </select>
                      </div>
                      <div className="flex gap-3 pt-2">
                        <button type="button" onClick={() => setShowCreateEvent(false)} className="btn-secondary flex-1 justify-center">Cancel</button>
                        <button type="submit" disabled={creatingEvent} className="btn-primary flex-1 justify-center">
                          {creatingEvent ? <Loader2 className="w-4 h-4 animate-spin" /> : <CalendarPlus className="w-4 h-4" />} Create Event
                        </button>
                      </div>
                    </form>
                  </div>
                </div>
              )}
            </div>
          )}

          {/* ── Settings Tab ── */}
          {activeTab === 'settings' && (
            <div className="p-6 max-w-2xl mx-auto mt-8">
              <h2 className="text-xl font-bold text-white mb-6">Workspace Settings</h2>
              
              <div className="bg-red-500/10 border border-red-500/30 rounded-xl p-6">
                <h3 className="text-red-400 font-semibold mb-2">Danger Zone</h3>
                <p className="text-sm text-red-400/80 mb-4">
                  Deleting this workspace will soft-delete all associated files, folders, and roles. This action can only be reversed by a system administrator.
                </p>
                <form onSubmit={doDeleteWorkspace}>
                  <label className="block text-xs font-medium text-red-400 mb-2">
                    Type <strong>{workspace?.name}</strong> to confirm.
                  </label>
                  <div className="flex gap-3">
                    <input
                      className="input bg-surface-0 border-red-500/30 focus:border-red-500 flex-1 text-white"
                      placeholder={workspace?.name || ''}
                      value={deleteConfirmation}
                      onChange={e => setDeleteConfirmation(e.target.value)}
                    />
                    <button
                      type="submit"
                      disabled={deleteConfirmation !== workspace?.name || deletingWorkspace}
                      className="btn bg-red-500 hover:bg-red-600 text-white disabled:opacity-50 disabled:cursor-not-allowed px-4 rounded-lg font-medium"
                    >
                      {deletingWorkspace ? <Loader2 className="w-4 h-4 animate-spin" /> : <Trash2 className="w-4 h-4 mr-2 inline" />}
                      Delete Workspace
                    </button>
                  </div>
                </form>
              </div>
            </div>
          )}
        </main>
      </div>

      {/* Upload Modal */}
      {showUpload && (
        <div className="fixed inset-0 bg-black/60 backdrop-blur-sm z-50 flex items-center justify-center p-4">
          <div className="bg-surface-1 border border-border rounded-2xl w-full max-w-lg shadow-glow animate-slide-up">
            <div className="p-5 border-b border-border flex items-center justify-between">
              <h2 className="text-lg font-semibold text-white">Upload Document</h2>
              <button onClick={() => { setShowUpload(false); setUploadFile(null) }} className="btn-ghost p-2"><X className="w-4 h-4" /></button>
            </div>
            <form onSubmit={doUpload} className="p-5 space-y-4">
              {!uploadFile ? (
                <label className="block border-2 border-dashed border-border rounded-xl p-8 text-center cursor-pointer hover:border-brand-500/50 hover:bg-brand-900/10 transition-all">
                  <input type="file" className="hidden" onChange={e => { const f = e.target.files?.[0]; if (f) { setUploadFile(f); setUploadForm(x => ({ ...x, title: f.name })) } }} />
                  <Upload className="w-8 h-8 text-muted mx-auto mb-2" />
                  <p className="text-sm text-white">Drop file or click to browse</p>
                  <p className="text-xs text-muted mt-1">PDF, DOCX, PPTX, XLSX, CSV, Images, Audio, CAD files</p>
                </label>
              ) : (
                <div className="flex items-center gap-3 p-3 rounded-lg bg-surface-2 border border-border">
                  <FileText className="w-6 h-6 text-brand-400 flex-shrink-0" />
                  <div className="flex-1 min-w-0">
                    <p className="text-sm text-white font-medium truncate">{uploadFile.name}</p>
                    <p className="text-xs text-muted">{(uploadFile.size / 1024).toFixed(1)} KB</p>
                  </div>
                  <button type="button" onClick={() => setUploadFile(null)} className="btn-ghost p-1"><X className="w-3.5 h-3.5" /></button>
                </div>
              )}

              <div><label className="label">Title</label><input className="input" placeholder="Document title" value={uploadForm.title} onChange={e => setUploadForm(x => ({ ...x, title: e.target.value }))} /></div>
              <div><label className="label">Description</label><textarea className="input h-16 resize-none" placeholder="Brief description…" value={uploadForm.description} onChange={e => setUploadForm(x => ({ ...x, description: e.target.value }))} /></div>
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="label">Tags (comma-separated)</label>
                  <input className="input" placeholder="pump, maintenance" value={uploadForm.tags} onChange={e => setUploadForm(x => ({ ...x, tags: e.target.value }))} />
                </div>
                <div>
                  <label className="label">
                    Restrict to level ≤
                    <span className="text-xs opacity-60 ml-1">(blank = all members)</span>
                  </label>
                  <div className="relative">
                    <Shield className="absolute left-3 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-muted" />
                    <select
                      className="input pl-8"
                      value={uploadForm.min_access_level}
                      onChange={e => setUploadForm(x => ({ ...x, min_access_level: e.target.value }))}
                    >
                      <option value="">All members</option>
                      {roles.map(r => (
                        <option key={r.role_id} value={r.level}>Level ≤ {r.level} ({r.name})</option>
                      ))}
                    </select>
                  </div>
                </div>
              </div>
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="label">Status</label>
                  <select className="input" value={uploadForm.status} onChange={e => setUploadForm(x => ({ ...x, status: e.target.value }))}>
                    <option value="draft">Draft</option>
                    <option value="approved">Approved</option>
                    <option value="archived">Archived</option>
                  </select>
                </div>
                <div>
                  <label className="label">Replacing existing document? <span className="text-xs opacity-60">(paste Document ID)</span></label>
                  <input className="input font-mono text-xs" placeholder="document_id (optional)" value={uploadForm.document_id} onChange={e => setUploadForm(x => ({ ...x, document_id: e.target.value }))} />
                </div>
              </div>

              {uploading && (
                <div>
                  <div className="h-1 bg-surface-3 rounded-full overflow-hidden">
                    <div className="h-full bg-gradient-brand transition-all duration-300 rounded-full" style={{ width: `${uploadProgress}%` }} />
                  </div>
                  <p className="text-xs text-muted mt-1">Uploading and queuing for processing…</p>
                </div>
              )}
              <div className="flex gap-3 pt-1">
                <button type="button" onClick={() => { setShowUpload(false); setUploadFile(null) }} className="btn-secondary flex-1 justify-center">Cancel</button>
                <button type="submit" disabled={!uploadFile || uploading} className="btn-primary flex-1 justify-center">
                  {uploading ? <Loader2 className="w-4 h-4 animate-spin" /> : <Upload className="w-4 h-4" />}
                  {uploading ? 'Uploading…' : 'Upload'}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* Create Role Modal */}
      {showCreateRole && (
        <div className="fixed inset-0 bg-black/60 backdrop-blur-sm z-50 flex items-center justify-center p-4">
          <div className="bg-surface-1 border border-border rounded-2xl w-full max-w-md shadow-glow animate-slide-up">
            <div className="p-5 border-b border-border flex items-center justify-between">
              <h2 className="text-lg font-semibold text-white">Add Role Level</h2>
              <button onClick={() => setShowCreateRole(false)} className="btn-ghost p-2"><X className="w-4 h-4" /></button>
            </div>
            <form onSubmit={createRole} className="p-5 space-y-4">
              <div className="p-3 rounded-lg bg-brand-900/20 border border-brand-700/40 text-xs text-muted">
                <p><span className="text-brand-300 font-medium">Level 1</span> = highest authority (admin). Higher numbers = lower priority.</p>
                <p className="mt-1">Each level must be unique within this workspace.</p>
              </div>
              <div>
                <label className="label">Role Name</label>
                <input className="input" placeholder='e.g. "Senior Engineer" or "Field Operator"' value={newRole.name} onChange={e => setNewRole(x => ({ ...x, name: e.target.value }))} required autoFocus />
              </div>
              <div>
                <label className="label">Level Number</label>
                <input className="input" type="number" min="1" placeholder="e.g. 2, 5, 10…" value={newRole.level} onChange={e => setNewRole(x => ({ ...x, level: e.target.value }))} required />
                {newRole.level && (
                  <p className="text-xs text-muted mt-1">
                    Level {newRole.level} = {parseInt(newRole.level) === 1 ? 'highest authority' : `lower than levels 1–${parseInt(newRole.level) - 1}`}
                  </p>
                )}
              </div>
              <div>
                <label className="label">Branch / Department <span className="opacity-60">(optional)</span></label>
                <select
                  className="input"
                  value={Array.from(new Set(['Main', ...folders.map(f => f.name), ...roles.map(r => r.branch || 'Main')])).includes(newRole.branch || 'Main') ? (newRole.branch || 'Main') : '__custom__'}
                  onChange={e => {
                    const val = e.target.value
                    if (val === '__custom__') setNewRole(x => ({ ...x, branch: '' }))
                    else setNewRole(x => ({ ...x, branch: val }))
                  }}
                >
                  {Array.from(new Set(['Main', ...folders.map(f => f.name), ...roles.map(r => r.branch || 'Main')])).filter(Boolean).map(bName => (
                    <option key={bName} value={bName}>{bName}</option>
                  ))}
                  <option value="__custom__">+ Add New Custom Branch…</option>
                </select>
                {(!Array.from(new Set(['Main', ...folders.map(f => f.name), ...roles.map(r => r.branch || 'Main')])).includes(newRole.branch || 'Main')) && (
                  <input
                    className="input mt-2"
                    placeholder="Type new custom branch name…"
                    value={newRole.branch}
                    onChange={e => setNewRole(x => ({ ...x, branch: e.target.value }))}
                    autoFocus
                  />
                )}
              </div>
              <div>
                <label className="label">Parent Role <span className="opacity-60">(optional tree hierarchy)</span></label>
                <select className="input" value={newRole.parent_role_id} onChange={e => setNewRole(x => ({ ...x, parent_role_id: e.target.value }))}>
                  <option value="">-- No parent (Root level in branch) --</option>
                  {roles.map(r => (
                    <option key={r.role_id} value={r.role_id}>
                      {r.name} (Level {r.level} · Branch: {r.branch || 'Main'})
                    </option>
                  ))}
                </select>
              </div>
              <div>
                <label className="label">Description <span className="opacity-60">(optional)</span></label>
                <input className="input" placeholder="What does this role do?" value={newRole.description} onChange={e => setNewRole(x => ({ ...x, description: e.target.value }))} />
              </div>
              <div className="flex items-center gap-2 pt-1">
                <input
                  type="checkbox"
                  id="create_can_modify_graph"
                  checked={newRole.level === '1' || newRole.can_modify_graph}
                  onChange={e => setNewRole(x => ({ ...x, can_modify_graph: e.target.checked }))}
                  disabled={newRole.level === '1'}
                  className="rounded border-border text-brand-500 focus:ring-brand-500 bg-surface-2"
                />
                <label htmlFor="create_can_modify_graph" className="text-xs text-white select-none">
                  Can Modify Knowledge Graph (add/delete nodes & edges)
                  {newRole.level === '1' && <span className="text-brand-300 ml-1 font-medium">(Default True for L1)</span>}
                </label>
              </div>
              <div className="flex gap-3 pt-1">
                <button type="button" onClick={() => setShowCreateRole(false)} className="btn-secondary flex-1 justify-center">Cancel</button>
                <button type="submit" disabled={creatingRole} className="btn-primary flex-1 justify-center">
                  {creatingRole ? <Loader2 className="w-4 h-4 animate-spin" /> : <Plus className="w-4 h-4" />}
                  {creatingRole ? 'Creating…' : 'Create Role'}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* Invite Member Modal */}
      {showInvite && (
        <div className="fixed inset-0 bg-black/60 backdrop-blur-sm z-50 flex items-center justify-center p-4">
          <div className="bg-surface-1 border border-border rounded-2xl w-full max-w-md shadow-glow animate-slide-up">
            <div className="p-5 border-b border-border flex items-center justify-between">
              <h2 className="text-lg font-semibold text-white">Invite Team Member</h2>
              <button onClick={() => setShowInvite(false)} className="btn-ghost p-2"><X className="w-4 h-4" /></button>
            </div>
            <form onSubmit={doInvite} className="p-5 space-y-4">
              <div>
                <label className="label">Email Address</label>
                <input className="input" type="email" placeholder="colleague@company.com" value={inviteEmail} onChange={e => setInviteEmail(e.target.value)} required autoFocus />
                <p className="text-xs text-muted mt-1">The user must already have an ETAIR account.</p>
              </div>
              <div>
                <label className="label">Assign Role Level</label>
                {roles.length === 0 ? (
                  <p className="text-sm text-amber-400">Create at least one role first.</p>
                ) : (
                  <select className="input" value={inviteRoleId} onChange={e => setInviteRoleId(e.target.value)} required>
                    <option value="">Select a role…</option>
                    {roles.map(r => (
                      <option key={r.role_id} value={r.role_id}>
                        Level {r.level} — {r.name} ({r.member_count} member{r.member_count !== 1 ? 's' : ''})
                      </option>
                    ))}
                  </select>
                )}
              </div>
              <div className="flex gap-3 pt-1">
                <button type="button" onClick={() => setShowInvite(false)} className="btn-secondary flex-1 justify-center">Cancel</button>
                <button type="submit" disabled={inviting || !inviteEmail || !inviteRoleId} className="btn-primary flex-1 justify-center">
                  {inviting ? <Loader2 className="w-4 h-4 animate-spin" /> : <Plus className="w-4 h-4" />}
                  {inviting ? 'Inviting…' : 'Send Invite'}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* Create Branch / Folder Modal */}
      {showCreateFolder && (
        <div className="fixed inset-0 bg-black/60 backdrop-blur-sm z-50 flex items-center justify-center p-4">
          <div className="bg-surface-1 border border-border rounded-2xl w-full max-w-lg shadow-glow animate-slide-up">
            <div className="p-5 border-b border-border flex items-center justify-between">
              <h2 className="text-lg font-semibold text-white flex items-center gap-2">
                <FolderPlus className="w-5 h-5 text-amber-400" /> Create Branch / Folder
              </h2>
              <button onClick={() => setShowCreateFolder(false)} className="btn-ghost p-2"><X className="w-4 h-4" /></button>
            </div>
            <form onSubmit={createFolder} className="p-5 space-y-4">
              <div>
                <label className="label">Branch / Folder Name</label>
                <input className="input" placeholder='e.g. "Turbines", "Specifications", or "Q3 Audits"' value={newFolder.name} onChange={e => setNewFolder(x => ({ ...x, name: e.target.value }))} required autoFocus />
                {currentFolderId && (
                  <p className="text-xs text-brand-300 mt-1">Creating inside current branch: {folderPath[folderPath.length - 1]?.name}</p>
                )}
              </div>
              <div>
                <label className="label">Description <span className="opacity-60">(optional)</span></label>
                <input className="input" placeholder="What is organized in this branch?" value={newFolder.description} onChange={e => setNewFolder(x => ({ ...x, description: e.target.value }))} />
              </div>
              <div className="p-4 bg-surface-2/60 border border-border rounded-xl space-y-3">
                <div className="flex items-center justify-between">
                  <div>
                    <p className="text-sm font-medium text-white">Inherit Parent Permissions</p>
                    <p className="text-xs text-muted">Use group access rules from the parent workspace/branch by default.</p>
                  </div>
                  <input
                    type="checkbox"
                    checked={newFolder.is_inherited}
                    onChange={e => setNewFolder(x => ({ ...x, is_inherited: e.target.checked }))}
                    className="w-4 h-4 rounded border-border bg-surface-1 text-brand-500 focus:ring-0"
                  />
                </div>
              </div>
              {!newFolder.is_inherited && (
                <div className="space-y-3 p-4 bg-surface-2/40 border border-amber-500/30 rounded-xl">
                  <p className="text-xs font-semibold text-amber-400 uppercase tracking-wider">Explicit Access Control</p>
                  <div>
                    <label className="label text-xs">Allowed Groups (Roles)</label>
                    <div className="grid grid-cols-2 gap-2 max-h-36 overflow-y-auto p-2 bg-surface-1 border border-border rounded-lg">
                      {roles.map(r => (
                        <label key={r.role_id} className="flex items-center gap-2 text-xs text-white cursor-pointer p-1.5 rounded hover:bg-surface-2">
                          <input
                            type="checkbox"
                            checked={newFolder.allowed_role_ids.includes(r.role_id)}
                            onChange={e => {
                              if (e.target.checked) {
                                setNewFolder(x => ({ ...x, allowed_role_ids: [...x.allowed_role_ids, r.role_id] }))
                              } else {
                                setNewFolder(x => ({ ...x, allowed_role_ids: x.allowed_role_ids.filter(id => id !== r.role_id) }))
                              }
                            }}
                            className="rounded border-border text-brand-500"
                          />
                          <span>{r.name} (L{r.level})</span>
                        </label>
                      ))}
                    </div>
                  </div>
                </div>
              )}
              <div className="flex gap-3 pt-2">
                <button type="button" onClick={() => setShowCreateFolder(false)} className="btn-secondary flex-1 justify-center">Cancel</button>
                <button type="submit" disabled={creatingFolder || !newFolder.name.trim()} className="btn-primary flex-1 justify-center">
                  {creatingFolder ? <Loader2 className="w-4 h-4 animate-spin" /> : <FolderPlus className="w-4 h-4" />}
                  {creatingFolder ? 'Creating…' : 'Create Branch'}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* Access Control & Governance ACL Modal */}
      {showAclModal && (
        <div className="fixed inset-0 bg-black/60 backdrop-blur-sm z-50 flex items-center justify-center p-4">
          <div className="bg-surface-1 border border-border rounded-2xl w-full max-w-lg shadow-glow animate-slide-up">
            <div className="p-5 border-b border-border flex items-center justify-between">
              <div>
                <h2 className="text-lg font-semibold text-white flex items-center gap-2">
                  <Shield className="w-5 h-5 text-brand-400" /> Security Governance & ACL
                </h2>
                <p className="text-xs text-muted mt-0.5">Editing access policy for {showAclModal.type}: <strong className="text-white">{showAclModal.name}</strong></p>
              </div>
              <button onClick={() => setShowAclModal(null)} className="btn-ghost p-2"><X className="w-4 h-4" /></button>
            </div>
            <form onSubmit={doUpdateAcl} className="p-5 space-y-4">
              <div className="p-4 bg-surface-2/60 border border-border rounded-xl flex items-center justify-between">
                <div>
                  <p className="text-sm font-medium text-white">Inherit Parent Permissions</p>
                  <p className="text-xs text-muted">When enabled, access rules flow automatically from the enclosing folder or workspace.</p>
                </div>
                <input
                  type="checkbox"
                  checked={showAclModal.is_inherited}
                  onChange={e => setShowAclModal(x => x ? { ...x, is_inherited: e.target.checked } : null)}
                  className="w-4 h-4 rounded border-border bg-surface-1 text-brand-500"
                />
              </div>

              {!showAclModal.is_inherited && (
                <div className="space-y-3 p-4 bg-surface-2/40 border border-brand-500/30 rounded-xl">
                  <div className="flex items-center justify-between">
                    <p className="text-xs font-semibold text-brand-300 uppercase tracking-wider">Group Access List (Allowed Roles)</p>
                    <span className="badge-purple text-[10px]">Level 1 Admins always bypass</span>
                  </div>
                  <p className="text-xs text-muted">Only members belonging to selected groups can view or query this {showAclModal.type}.</p>
                  <div className="grid grid-cols-2 gap-2 max-h-40 overflow-y-auto p-2 bg-surface-1 border border-border rounded-lg">
                    {roles.map(r => (
                      <label key={r.role_id} className="flex items-center gap-2 text-xs text-white cursor-pointer p-1.5 rounded hover:bg-surface-2">
                        <input
                          type="checkbox"
                          checked={showAclModal.allowed_role_ids.includes(r.role_id)}
                          onChange={e => {
                            if (!showAclModal) return
                            if (e.target.checked) {
                              setShowAclModal({ ...showAclModal, allowed_role_ids: [...showAclModal.allowed_role_ids, r.role_id] })
                            } else {
                              setShowAclModal({ ...showAclModal, allowed_role_ids: showAclModal.allowed_role_ids.filter(id => id !== r.role_id) })
                            }
                          }}
                          className="rounded border-border text-brand-500"
                        />
                        <span>{r.name} (L{r.level})</span>
                      </label>
                    ))}
                  </div>
                </div>
              )}

              <div>
                <label className="label text-xs">Clearance Tier Override (Min Access Level)</label>
                <select
                  className="input"
                  value={showAclModal.min_access_level || ''}
                  onChange={e => {
                    if (!showAclModal) return
                    const val = e.target.value ? parseInt(e.target.value) : null
                    setShowAclModal({ ...showAclModal, min_access_level: val })
                  }}
                >
                  <option value="">No minimum level restriction (open to all authorized groups)</option>
                  {roles.map(r => (
                    <option key={r.role_id} value={r.level}>Only Level ≤ {r.level} ({r.name} clearance or above)</option>
                  ))}
                </select>
                <p className="text-[11px] text-muted mt-1">If set, users must ALSO meet this numerical clearance tier level.</p>
              </div>

              <div className="flex gap-3 pt-2">
                <button type="button" onClick={() => setShowAclModal(null)} className="btn-secondary flex-1 justify-center">Cancel</button>
                <button type="submit" disabled={updatingAcl} className="btn-primary flex-1 justify-center">
                  {updatingAcl ? <Loader2 className="w-4 h-4 animate-spin" /> : <Check className="w-4 h-4" />}
                  {updatingAcl ? 'Saving Policy…' : 'Save Governance Policy'}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* Add Custom Node Modal */}
      {showAddNodeModal && (
        <div className="fixed inset-0 bg-black/60 backdrop-blur-sm z-50 flex items-center justify-center p-4">
          <div className="bg-surface-1 border border-border rounded-2xl w-full max-w-md shadow-glow animate-slide-up">
            <div className="p-5 border-b border-border flex items-center justify-between">
              <h2 className="text-lg font-semibold text-white">Add Graph Node</h2>
              <button onClick={() => setShowAddNodeModal(false)} className="btn-ghost p-1.5 text-muted hover:text-white">✕</button>
            </div>
            <form onSubmit={doAddNode} className="p-5 space-y-4 text-sm">
              <div>
                <label className="label">Node Label / Name</label>
                <input className="input" placeholder="e.g. Pump-101 or ISO-9001" value={newNodeData.label} onChange={e => setNewNodeData({ ...newNodeData, label: e.target.value })} required autoFocus />
              </div>
              <div>
                <label className="label">Node Type</label>
                <select className="input" value={newNodeData.node_type} onChange={e => setNewNodeData({ ...newNodeData, node_type: e.target.value })}>
                  <option value="entity">Entity</option>
                  <option value="asset">Asset / Equipment</option>
                  <option value="concept">Concept</option>
                </select>
              </div>
              <div>
                <label className="label">Branch <span className="opacity-60">(optional)</span></label>
                <input className="input" placeholder="Main" value={newNodeData.branch} onChange={e => setNewNodeData({ ...newNodeData, branch: e.target.value })} />
              </div>
              <div>
                <label className="label">Description <span className="opacity-60">(optional)</span></label>
                <input className="input" placeholder="Additional info..." value={newNodeData.description} onChange={e => setNewNodeData({ ...newNodeData, description: e.target.value })} />
              </div>
              <div className="flex gap-3 pt-2">
                <button type="button" onClick={() => setShowAddNodeModal(false)} className="btn-secondary flex-1 justify-center">Cancel</button>
                <button type="submit" disabled={addingNode} className="btn-primary flex-1 justify-center">
                  {addingNode ? <Loader2 className="w-4 h-4 animate-spin" /> : <Plus className="w-4 h-4" />}
                  {addingNode ? 'Adding...' : 'Add Node'}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* Node Details Modal */}
      {selectedNodeDetails && (
        <div className="fixed inset-0 bg-black/60 backdrop-blur-sm z-50 flex items-center justify-center p-4">
          <div className="bg-surface-1 border border-border rounded-2xl w-full max-w-md shadow-glow animate-slide-up">
            <div className="p-5 border-b border-border flex items-center justify-between">
              <h2 className="text-lg font-semibold text-white">Node Details</h2>
              <button onClick={() => setSelectedNodeDetails(null)} className="btn-ghost p-1.5 text-muted hover:text-white">✕</button>
            </div>
            <div className="p-5 space-y-3 text-sm">
              <div>
                <span className="text-xs text-muted font-medium">Node Label:</span>
                <p className="text-white font-semibold text-base">{selectedNodeDetails.name || selectedNodeDetails.label || selectedNodeDetails.id}</p>
              </div>
              <div className="flex gap-4">
                <div>
                  <span className="text-xs text-muted font-medium">Type:</span>
                  <p className="text-brand-300 capitalize">{selectedNodeDetails.type || selectedNodeDetails.node_type || 'entity'}</p>
                </div>
                {selectedNodeDetails.branch && (
                  <div>
                    <span className="text-xs text-muted font-medium">Branch:</span>
                    <p className="text-slate-300">{selectedNodeDetails.branch}</p>
                  </div>
                )}
              </div>
              <div className="flex gap-3 pt-3">
                <button onClick={() => setSelectedNodeDetails(null)} className="btn-secondary flex-1 justify-center">Close</button>
                {(selectedNodeDetails.type === 'file' || selectedNodeDetails.node_type === 'file') && (
                  <button
                    onClick={() => {
                      const fid = selectedNodeDetails.external_id || selectedNodeDetails.id
                      router.push(`/workspace/${workspaceId}/file/${fid}`)
                    }}
                    className="btn-primary flex-1 justify-center"
                  >
                    View File Details
                  </button>
                )}
                {isAdmin && (
                  <button
                    onClick={async () => {
                      if (!confirm(`Are you sure you want to delete this node (${selectedNodeDetails.name || selectedNodeDetails.id}) from the graph?`)) return
                      try {
                        await graphApi.deleteNode(selectedNodeDetails.id, workspaceId)
                        setSelectedNodeDetails(null)
                        loadGraph()
                      } catch (err: any) {
                        alert(getErrorMsg(err, 'Failed to delete node'))
                      }
                    }}
                    className="btn bg-red-500 hover:bg-red-600 text-white flex-1 justify-center rounded-lg font-medium text-xs"
                  >
                    <Trash2 className="w-4 h-4 mr-1.5 inline" />
                    Delete Node
                  </button>
                )}
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Add Custom Edge Modal */}
      {showAddEdgeModal && selectedSourceNode && selectedTargetNode && (
        <div className="fixed inset-0 bg-black/60 backdrop-blur-sm z-50 flex items-center justify-center p-4">
          <div className="bg-surface-1 border border-border rounded-2xl w-full max-w-md shadow-glow animate-slide-up overflow-hidden">
            <div className="p-5 border-b border-border flex items-center justify-between">
              <h3 className="font-semibold text-white flex items-center gap-2">
                <Network className="w-5 h-5 text-pink-400" />
                Add Custom Edge & Comment
              </h3>
              <button onClick={() => setShowAddEdgeModal(false)} className="text-muted hover:text-white">
                <X className="w-5 h-5" />
              </button>
            </div>
            <form onSubmit={doAddEdge} className="p-5 space-y-4">
              <div className="bg-surface-2 p-3 rounded-xl border border-border/60 text-xs space-y-1">
                <div className="flex justify-between">
                  <span className="text-muted">Source:</span>
                  <span className="text-white font-medium truncate max-w-[220px]">{selectedSourceNode.name}</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-muted">Target:</span>
                  <span className="text-white font-medium truncate max-w-[220px]">{selectedTargetNode.name}</span>
                </div>
              </div>

              <div>
                <label className="label">Relationship Label</label>
                <input
                  className="input"
                  placeholder="e.g. referenced by, supersedes, attached to"
                  value={newEdgeData.label}
                  onChange={e => setNewEdgeData({ ...newEdgeData, label: e.target.value })}
                />
              </div>

              <div>
                <label className="label">Comment / Annotation <span className="text-muted font-normal">(optional)</span></label>
                <textarea
                  className="input min-h-[80px]"
                  placeholder="Why are these files linked? Add note or explanation..."
                  value={newEdgeData.comment}
                  onChange={e => setNewEdgeData({ ...newEdgeData, comment: e.target.value })}
                />
              </div>

              <div>
                <label className="label">Relevance Weight ({newEdgeData.weight})</label>
                <input
                  type="range"
                  min="0.1"
                  max="1.0"
                  step="0.05"
                  value={newEdgeData.weight}
                  onChange={e => setNewEdgeData({ ...newEdgeData, weight: parseFloat(e.target.value) })}
                  className="w-full accent-pink-400"
                />
                <div className="flex justify-between text-[11px] text-muted mt-1">
                  <span>Low link (0.1)</span>
                  <span>Strong link (1.0)</span>
                </div>
              </div>

              <div className="flex gap-3 pt-3">
                <button
                  type="button"
                  onClick={() => setShowAddEdgeModal(false)}
                  className="btn-secondary flex-1 justify-center"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={addingEdge}
                  className="btn bg-pink-500 hover:bg-pink-600 text-white flex-1 justify-center rounded-lg font-medium"
                >
                  {addingEdge ? <Loader2 className="w-4 h-4 animate-spin mr-2 inline" /> : <Plus className="w-4 h-4 mr-2 inline" />}
                  Save Edge
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* Selected Edge Details Modal */}
      {selectedLinkDetails && (
        <div className="fixed inset-0 bg-black/60 backdrop-blur-sm z-50 flex items-center justify-center p-4">
          <div className="bg-surface-1 border border-border rounded-2xl w-full max-w-md shadow-glow animate-slide-up overflow-hidden">
            <div className="p-5 border-b border-border flex items-center justify-between">
              <h3 className="font-semibold text-white flex items-center gap-2">
                <GitBranch className="w-5 h-5 text-brand-400" />
                Edge Details
              </h3>
              <button onClick={() => setSelectedLinkDetails(null)} className="text-muted hover:text-white">
                <X className="w-5 h-5" />
              </button>
            </div>
            <div className="p-5 space-y-4 text-sm">
              <div className="space-y-2 bg-surface-2 p-3.5 rounded-xl border border-border/80">
                <div className="flex justify-between text-xs">
                  <span className="text-muted">Edge Type:</span>
                  <span className="font-semibold text-white uppercase bg-surface-0 px-2 py-0.5 rounded border border-border">
                    {selectedLinkDetails.name || 'LINK'}
                  </span>
                </div>
                <div className="flex justify-between text-xs">
                  <span className="text-muted">Origin:</span>
                  <span className={selectedLinkDetails.edge_source === 'user' ? 'text-pink-400 font-semibold' : 'text-slate-400'}>
                    {selectedLinkDetails.edge_source === 'user' ? 'User Custom Edge' : 'System / LLM Edge'}
                  </span>
                </div>
                <div className="pt-2 border-t border-border/60 text-xs space-y-1">
                  <div>
                    <span className="text-muted block">From:</span>
                    <span className="text-white font-medium">{selectedLinkDetails.source?.name || selectedLinkDetails.source}</span>
                  </div>
                  <div className="mt-1">
                    <span className="text-muted block">To:</span>
                    <span className="text-white font-medium">{selectedLinkDetails.target?.name || selectedLinkDetails.target}</span>
                  </div>
                </div>
              </div>

              {selectedLinkDetails.comment ? (
                <div>
                  <span className="text-xs text-muted font-medium block mb-1">User Comment:</span>
                  <div className="bg-surface-0/80 p-3 rounded-xl border border-border text-white/90 italic text-xs">
                    "{selectedLinkDetails.comment}"
                  </div>
                </div>
              ) : (
                <p className="text-xs text-muted italic">No comment recorded for this edge.</p>
              )}

              <div className="flex gap-3 pt-3">
                <button
                  onClick={() => setSelectedLinkDetails(null)}
                  className="btn-secondary flex-1 justify-center"
                >
                  Close
                </button>
                {selectedLinkDetails.edge_source === 'user' && selectedLinkDetails.id && (
                  <button
                    onClick={() => doDeleteMutation(selectedLinkDetails.id)}
                    className="btn bg-red-500 hover:bg-red-600 text-white flex-1 justify-center rounded-lg font-medium text-xs"
                  >
                    <Trash2 className="w-4 h-4 mr-1.5 inline" />
                    Delete Edge
                  </button>
                )}
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
