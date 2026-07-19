import axios from 'axios'

const api = axios.create({
  baseURL: process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8888',
  timeout: 30000,
})

// Attach JWT token to every request
api.interceptors.request.use((config) => {
  if (typeof window !== 'undefined') {
    const token = localStorage.getItem('etair_token')
    if (token) {
      config.headers.Authorization = `Bearer ${token}`
    }
  }
  return config
})

// Handle auth errors globally
api.interceptors.response.use(
  (response) => response,
  (error) => {
    if (error.response?.status === 401 && typeof window !== 'undefined') {
      localStorage.removeItem('etair_token')
      localStorage.removeItem('etair_user')
      window.location.href = '/login'
    }
    return Promise.reject(error)
  }
)

export default api

// ─── Auth ─────────────────────────────────────────────────────────────────────
export const authApi = {
  register: (data: { email: string; password: string; full_name: string }) =>
    api.post('/api/v1/auth/register', data),
  login: (data: { email: string; password: string }) =>
    api.post('/api/v1/auth/login', data),
  me: () => api.get('/api/v1/auth/me'),
}

// ─── Workspaces ───────────────────────────────────────────────────────────────
export const workspaceApi = {
  list: () => api.get('/api/v1/workspaces'),
  listArchived: () => api.get('/api/v1/workspaces/archived'),
  create: (data: { name: string; description?: string; industry?: string; site_location?: string }) =>
    api.post('/api/v1/workspaces', data),
  get: (id: string) => api.get(`/api/v1/workspaces/${id}`),
  delete: (id: string, data: { confirmation_name: string }) => 
    api.post(`/api/v1/workspaces/${id}/delete`, data),
  restore: (id: string) => api.post(`/api/v1/workspaces/${id}/restore`),
  deletePermanent: (id: string) => api.delete(`/api/v1/workspaces/${id}/permanent`),

  // ─ Role management (level-based) ─
  roles: (workspaceId: string) =>
    api.get(`/api/v1/workspaces/${workspaceId}/roles`),
  createRole: (workspaceId: string, data: { name: string; level: number; description?: string; branch?: string; parent_role_id?: string; can_modify_graph?: boolean }) =>
    api.post(`/api/v1/workspaces/${workspaceId}/roles`, data),
  updateRole: (workspaceId: string, roleId: string, data: { name?: string; description?: string; branch?: string; parent_role_id?: string; can_modify_graph?: boolean }) =>
    api.patch(`/api/v1/workspaces/${workspaceId}/roles/${roleId}`, data),
  deleteRole: (workspaceId: string, roleId: string) =>
    api.delete(`/api/v1/workspaces/${workspaceId}/roles/${roleId}`),
  swapLevels: (workspaceId: string, roleIdA: string, roleIdB: string) =>
    api.post(`/api/v1/workspaces/${workspaceId}/roles/swap-levels`, { role_id_a: roleIdA, role_id_b: roleIdB }),

  // ─ Member management ─
  members: (id: string) => api.get(`/api/v1/workspaces/${id}/members`),
  invite: (id: string, data: { email: string; role_id: string }) =>
    api.post(`/api/v1/workspaces/${id}/members`, data),
  updateMemberRole: (workspaceId: string, userId: string, roleId: string) =>
    api.patch(`/api/v1/workspaces/${workspaceId}/members/${userId}/role`, { role_id: roleId }),
  removeMember: (workspaceId: string, userId: string) =>
    api.delete(`/api/v1/workspaces/${workspaceId}/members/${userId}`),

  // ─ Audit / Governance Logs ─
  auditLogs: (workspaceId: string, limit: number = 100) =>
    api.get(`/api/v1/workspaces/${workspaceId}/audit-logs`, { params: { limit } }),
}

// ─── Folders / Branches ───────────────────────────────────────────────────────
export const folderApi = {
  list: (workspaceId: string, parentFolderId?: string | null) =>
    api.get(`/api/v1/workspaces/${workspaceId}/folders`, {
      params: parentFolderId ? { parent_folder_id: parentFolderId } : {},
    }),
  create: (
    workspaceId: string,
    data: {
      name: string
      parent_folder_id?: string | null
      description?: string
      is_inherited?: boolean
      allowed_role_ids?: string[]
      min_access_level?: number | null
    }
  ) => api.post(`/api/v1/workspaces/${workspaceId}/folders`, data),
  update: (
    workspaceId: string,
    folderId: string,
    data: {
      name?: string
      description?: string
      is_inherited?: boolean
      allowed_role_ids?: string[]
      min_access_level?: number | null
    }
  ) => api.patch(`/api/v1/workspaces/${workspaceId}/folders/${folderId}`, data),
  delete: (workspaceId: string, folderId: string) =>
    api.delete(`/api/v1/workspaces/${workspaceId}/folders/${folderId}`),
}

// ─── Files ────────────────────────────────────────────────────────────────────
export const filesApi = {
  list: (workspaceId: string, params?: Record<string, string>) =>
    api.get(`/api/v1/files/workspace/${workspaceId}`, { params }),
  upload: (workspaceId: string, formData: FormData) =>
    api.post(`/api/v1/files/upload/${workspaceId}`, formData, {
      headers: { 'Content-Type': 'multipart/form-data' },
    }),
  updateAcl: (
    fileId: string,
    data: {
      folder_id?: string | null
      is_inherited?: boolean
      allowed_role_ids?: string[]
      min_access_level?: number | null
    }
  ) => api.patch(`/api/v1/files/${fileId}/acl`, data),
  get: (fileId: string) => api.get(`/api/v1/files/${fileId}`),
  downloadUrl: (fileId: string) => api.get(`/api/v1/files/${fileId}/download-url`),
  versions: (fileId: string) => api.get(`/api/v1/files/${fileId}/versions`),
  updateStatus: (fileId: string, status: string) =>
    api.patch(`/api/v1/files/${fileId}/status`, { status }),
  comments: (fileId: string) => api.get(`/api/v1/files/${fileId}/comments`),
  addComment: (fileId: string, content: string, page_number?: number) =>
    api.post(`/api/v1/files/${fileId}/comments`, { content, page_number }),
  deleteFile: (fileId: string) => api.delete(`/api/v1/files/${fileId}`),
  listArchived: (workspaceId: string) => api.get(`/api/v1/files/workspace/${workspaceId}/archived`),
  restore: (fileId: string) => api.post(`/api/v1/files/${fileId}/restore`),
}

// ─── Query ────────────────────────────────────────────────────────────────────
export const queryApi = {
  ask: (data: { query: string; workspace_id: string; top_k?: number }) =>
    api.post('/api/v1/query', data),
}

// ─── Graph ────────────────────────────────────────────────────────────────────
export const graphApi = {
  getWorkspaceGraph: (workspaceId: string) =>
    api.get(`/api/v1/graph/workspace/${workspaceId}`),
  addNode: (data: {
    workspace_id: string
    label: string
    node_type?: string
    branch?: string
    properties?: Record<string, any>
  }) => api.post('/api/v1/graph/node', data),
  deleteNode: (nodeId: string, workspaceId: string) =>
    api.delete(`/api/v1/graph/node/${nodeId}`, { params: { workspace_id: workspaceId } }),
  addEdge: (data: {
    workspace_id: string
    from_node_id: string
    to_node_id: string
    label?: string
    comment?: string
    weight?: number
  }) => api.post('/api/v1/graph/edge', data),
  deleteEdge: (data: {
    workspace_id: string
    from_node_id: string
    to_node_id: string
  }) => api.delete('/api/v1/graph/edge', { data }),
  deleteMutation: (mutationId: string) =>
    api.delete(`/api/v1/graph/mutations/${mutationId}`),
}

// ─── Calendar ─────────────────────────────────────────────────────────────────
export const calendarApi = {
  listEvents: (workspaceId: string, params?: { equipment_id?: string; event_type?: string; source_type?: string }) =>
    api.get(`/api/v1/workspaces/${workspaceId}/calendar/events`, { params }),
  listExpanded: (workspaceId: string, months?: number, equipment_id?: string) =>
    api.get(`/api/v1/workspaces/${workspaceId}/calendar/events/expanded`, { params: { months: months || 6, equipment_id } }),
  createEvent: (workspaceId: string, data: {
    title: string; equipment_id?: string; workspace_id: string; event_type: string;
    start_at?: string; end_at?: string; repeat_rule?: string; description?: string;
    source_type: string; source_id: string; confidence: string;
  }) => api.post(`/api/v1/workspaces/${workspaceId}/calendar/events`, data),
  queryCalendar: (workspaceId: string, data: { query: string; query_id?: string }) =>
    api.post(`/api/v1/workspaces/${workspaceId}/calendar/query`, data),
  deleteEvent: (workspaceId: string, eventId: string) =>
    api.delete(`/api/v1/workspaces/${workspaceId}/calendar/events/${eventId}`),
}

