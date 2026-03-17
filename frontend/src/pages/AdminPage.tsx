/**
 * AdminPage - Verwaltungsoberfläche für Admins.
 *
 * Tabs:
 * - Benutzer: Erstellen, bearbeiten, löschen, Gruppen zuordnen
 * - Gruppen: Erstellen, bearbeiten, Mitglieder verwalten
 * - Collections: Erstellen, bearbeiten, Gruppenzugriff verwalten
 * - Docker & System: Container, Images, Volumes verwalten
 */

import { useState, useEffect, useCallback } from 'react'
import { usersApi, groupsApi, collectionsApi, dockerApi } from '../services/api'
import type {
  UserDetail, Group, Collection, AccessInfo,
  DockerContainer, DockerImage, DockerVolume, BulkActionResult,
} from '../types'

type Tab = 'users' | 'groups' | 'collections' | 'docker'

export default function AdminPage() {
  const [activeTab, setActiveTab] = useState<Tab>('users')

  const tabs: { key: Tab; label: string }[] = [
    { key: 'users', label: 'Benutzer' },
    { key: 'groups', label: 'Gruppen' },
    { key: 'collections', label: 'Collections' },
    { key: 'docker', label: 'Docker & System' },
  ]

  return (
    <div className="p-6">
      <h1 className="text-2xl font-bold mb-6">Administration</h1>

      <div className="flex gap-1 mb-6 border-b">
        {tabs.map((tab) => (
          <button
            key={tab.key}
            onClick={() => setActiveTab(tab.key)}
            className={`px-4 py-2 text-sm font-medium border-b-2 transition ${
              activeTab === tab.key
                ? 'border-atlas-600 text-atlas-600'
                : 'border-transparent text-gray-500 hover:text-gray-700'
            }`}
          >
            {tab.label}
          </button>
        ))}
      </div>

      <div className="max-w-5xl">
        {activeTab === 'users' && <UsersTab />}
        {activeTab === 'groups' && <GroupsTab />}
        {activeTab === 'collections' && <CollectionsTab />}
        {activeTab === 'docker' && <DockerTab />}
      </div>
    </div>
  )
}

// =============================================================================
// Docker & System Tab
// =============================================================================

function DockerTab() {
  const [containers, setContainers] = useState<DockerContainer[]>([])
  const [images, setImages] = useState<DockerImage[]>([])
  const [volumes, setVolumes] = useState<DockerVolume[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [actionResults, setActionResults] = useState<BulkActionResult[]>([])
  const [selectedContainers, setSelectedContainers] = useState<Set<string>>(new Set())
  const [selectedImages, setSelectedImages] = useState<Set<string>>(new Set())
  const [selectedVolumes, setSelectedVolumes] = useState<Set<string>>(new Set())
  const [actionLoading, setActionLoading] = useState(false)

  const loadData = useCallback(async () => {
    try {
      setLoading(true)
      setError('')
      const [c, i, v] = await Promise.all([
        dockerApi.listContainers(),
        dockerApi.listImages(),
        dockerApi.listVolumes(),
      ])
      setContainers(c)
      setImages(i)
      setVolumes(v)
    } catch (err: unknown) {
      const msg = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      setError(msg || 'Docker-Daten konnten nicht geladen werden')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    loadData()
  }, [loadData])

  const toggleContainer = (id: string) => {
    setSelectedContainers((prev) => {
      const next = new Set(prev)
      next.has(id) ? next.delete(id) : next.add(id)
      return next
    })
  }

  const toggleImage = (id: string) => {
    setSelectedImages((prev) => {
      const next = new Set(prev)
      next.has(id) ? next.delete(id) : next.add(id)
      return next
    })
  }

  const toggleVolume = (name: string) => {
    setSelectedVolumes((prev) => {
      const next = new Set(prev)
      next.has(name) ? next.delete(name) : next.add(name)
      return next
    })
  }

  const handleRestartContainers = async () => {
    if (selectedContainers.size === 0) return
    setActionLoading(true)
    setActionResults([])
    try {
      const result = await dockerApi.restartContainers([...selectedContainers])
      setActionResults(result.results)
      setSelectedContainers(new Set())
      await loadData()
    } catch {
      setError('Fehler beim Neustarten')
    } finally {
      setActionLoading(false)
    }
  }

  const handleRebuildImages = async () => {
    if (selectedImages.size === 0) return
    setActionLoading(true)
    setActionResults([])
    try {
      const result = await dockerApi.rebuildImages([...selectedImages])
      setActionResults(result.results)
      setSelectedImages(new Set())
      await loadData()
    } catch {
      setError('Fehler beim Neubauen')
    } finally {
      setActionLoading(false)
    }
  }

  const handleDeleteVolumes = async () => {
    if (selectedVolumes.size === 0) return
    if (!confirm(`${selectedVolumes.size} Volume(s) wirklich löschen?`)) return
    setActionLoading(true)
    setActionResults([])
    try {
      const result = await dockerApi.deleteVolumes([...selectedVolumes])
      setActionResults(result.results)
      setSelectedVolumes(new Set())
      await loadData()
    } catch {
      setError('Fehler beim Löschen')
    } finally {
      setActionLoading(false)
    }
  }

  const formatSize = (bytes: number) => {
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} KB`
    if (bytes < 1024 * 1024 * 1024) return `${(bytes / 1024 / 1024).toFixed(1)} MB`
    return `${(bytes / 1024 / 1024 / 1024).toFixed(2)} GB`
  }

  const stateColor = (state: string) => {
    if (state === 'running') return 'bg-green-100 text-green-700'
    if (state === 'exited') return 'bg-red-100 text-red-700'
    return 'bg-yellow-100 text-yellow-700'
  }

  if (loading) return <div className="text-gray-500">Docker-Daten laden...</div>

  return (
    <div className="space-y-8">
      {error && <div className="bg-red-50 text-red-600 p-3 rounded text-sm">{error}</div>}

      {/* Action Results */}
      {actionResults.length > 0 && (
        <div className="bg-blue-50 border border-blue-200 rounded p-3 text-sm space-y-1">
          {actionResults.map((r, i) => (
            <div key={i} className={`flex items-center gap-2 ${r.status === 'error' ? 'text-red-600' : 'text-green-700'}`}>
              <span>{r.status === 'error' ? '✗' : '✓'}</span>
              <span>{r.message}</span>
            </div>
          ))}
          <button onClick={() => setActionResults([])} className="text-xs text-blue-500 hover:text-blue-700 mt-1">
            Schließen
          </button>
        </div>
      )}

      {/* Containers */}
      <section>
        <div className="flex items-center justify-between mb-3">
          <h2 className="text-lg font-semibold">Container ({containers.length})</h2>
          <div className="flex gap-2">
            <button
              onClick={loadData}
              className="px-3 py-1.5 text-xs border rounded hover:bg-gray-50"
            >
              Aktualisieren
            </button>
            <button
              onClick={handleRestartContainers}
              disabled={selectedContainers.size === 0 || actionLoading}
              className="px-3 py-1.5 text-xs bg-atlas-600 text-white rounded hover:bg-atlas-700 disabled:opacity-50"
            >
              {actionLoading ? 'Läuft...' : `Neustarten (${selectedContainers.size})`}
            </button>
          </div>
        </div>
        <div className="bg-white rounded-lg shadow overflow-hidden">
          <table className="w-full text-sm">
            <thead className="bg-gray-50 text-left">
              <tr>
                <th className="px-3 py-2 w-8"></th>
                <th className="px-3 py-2 font-medium text-gray-600">Name</th>
                <th className="px-3 py-2 font-medium text-gray-600">Image</th>
                <th className="px-3 py-2 font-medium text-gray-600">Status</th>
              </tr>
            </thead>
            <tbody className="divide-y">
              {containers.map((c) => (
                <tr key={c.id} className="hover:bg-gray-50">
                  <td className="px-3 py-2">
                    <input
                      type="checkbox"
                      checked={selectedContainers.has(c.id)}
                      onChange={() => toggleContainer(c.id)}
                      className="rounded border-gray-300"
                    />
                  </td>
                  <td className="px-3 py-2 font-medium">{c.name}</td>
                  <td className="px-3 py-2 text-gray-500 text-xs truncate max-w-[200px]">{c.image}</td>
                  <td className="px-3 py-2">
                    <span className={`px-2 py-0.5 rounded text-xs font-medium ${stateColor(c.state)}`}>
                      {c.state}
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      {/* Images */}
      <section>
        <div className="flex items-center justify-between mb-3">
          <h2 className="text-lg font-semibold">Images ({images.length})</h2>
          <button
            onClick={handleRebuildImages}
            disabled={selectedImages.size === 0 || actionLoading}
            className="px-3 py-1.5 text-xs bg-atlas-600 text-white rounded hover:bg-atlas-700 disabled:opacity-50"
          >
            {actionLoading ? 'Läuft...' : `Neu bauen (${selectedImages.size})`}
          </button>
        </div>
        <div className="bg-white rounded-lg shadow overflow-hidden">
          <table className="w-full text-sm">
            <thead className="bg-gray-50 text-left">
              <tr>
                <th className="px-3 py-2 w-8"></th>
                <th className="px-3 py-2 font-medium text-gray-600">Tags</th>
                <th className="px-3 py-2 font-medium text-gray-600">Größe</th>
                <th className="px-3 py-2 font-medium text-gray-600">ID</th>
              </tr>
            </thead>
            <tbody className="divide-y">
              {images.map((img) => (
                <tr key={img.id} className="hover:bg-gray-50">
                  <td className="px-3 py-2">
                    <input
                      type="checkbox"
                      checked={selectedImages.has(img.id)}
                      onChange={() => toggleImage(img.id)}
                      className="rounded border-gray-300"
                    />
                  </td>
                  <td className="px-3 py-2">
                    {img.tags.length > 0 ? (
                      <div className="flex flex-wrap gap-1">
                        {img.tags.map((tag) => (
                          <span key={tag} className="bg-gray-100 px-1.5 py-0.5 rounded text-xs">{tag}</span>
                        ))}
                      </div>
                    ) : (
                      <span className="text-gray-400 text-xs">&lt;untagged&gt;</span>
                    )}
                  </td>
                  <td className="px-3 py-2 text-gray-500">{formatSize(img.size)}</td>
                  <td className="px-3 py-2 text-gray-400 text-xs font-mono">{img.id}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      {/* Volumes */}
      <section>
        <div className="flex items-center justify-between mb-3">
          <h2 className="text-lg font-semibold">Volumes ({volumes.length})</h2>
          <button
            onClick={handleDeleteVolumes}
            disabled={selectedVolumes.size === 0 || actionLoading}
            className="px-3 py-1.5 text-xs bg-red-600 text-white rounded hover:bg-red-700 disabled:opacity-50"
          >
            {actionLoading ? 'Läuft...' : `Löschen (${selectedVolumes.size})`}
          </button>
        </div>
        <div className="bg-white rounded-lg shadow overflow-hidden">
          <table className="w-full text-sm">
            <thead className="bg-gray-50 text-left">
              <tr>
                <th className="px-3 py-2 w-8"></th>
                <th className="px-3 py-2 font-medium text-gray-600">Name</th>
                <th className="px-3 py-2 font-medium text-gray-600">Driver</th>
                <th className="px-3 py-2 font-medium text-gray-600">Mountpoint</th>
              </tr>
            </thead>
            <tbody className="divide-y">
              {volumes.map((vol) => (
                <tr key={vol.name} className="hover:bg-gray-50">
                  <td className="px-3 py-2">
                    <input
                      type="checkbox"
                      checked={selectedVolumes.has(vol.name)}
                      onChange={() => toggleVolume(vol.name)}
                      className="rounded border-gray-300"
                    />
                  </td>
                  <td className="px-3 py-2 font-medium">{vol.name}</td>
                  <td className="px-3 py-2 text-gray-500">{vol.driver}</td>
                  <td className="px-3 py-2 text-gray-400 text-xs font-mono truncate max-w-[300px]">{vol.mountpoint}</td>
                </tr>
              ))}
            </tbody>
          </table>
          {volumes.length === 0 && (
            <div className="text-center py-6 text-gray-500 text-sm">Keine Volumes vorhanden</div>
          )}
        </div>
      </section>
    </div>
  )
}

// =============================================================================
// Users Tab
// =============================================================================

interface UserFormData {
  username: string
  email: string
  password: string
  full_name: string
  is_admin: boolean
}

const emptyUserForm: UserFormData = {
  username: '',
  email: '',
  password: '',
  full_name: '',
  is_admin: false,
}

function UsersTab() {
  const [users, setUsers] = useState<UserDetail[]>([])
  const [loading, setLoading] = useState(true)
  const [showForm, setShowForm] = useState(false)
  const [editingUser, setEditingUser] = useState<UserDetail | null>(null)
  const [formData, setFormData] = useState<UserFormData>(emptyUserForm)
  const [error, setError] = useState('')
  const [saving, setSaving] = useState(false)

  const loadUsers = useCallback(async () => {
    try {
      setLoading(true)
      const data = await usersApi.list()
      setUsers(data)
    } catch {
      setError('Benutzer konnten nicht geladen werden')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    loadUsers()
  }, [loadUsers])

  const openCreate = () => {
    setEditingUser(null)
    setFormData(emptyUserForm)
    setError('')
    setShowForm(true)
  }

  const openEdit = (user: UserDetail) => {
    setEditingUser(user)
    setFormData({
      username: user.username,
      email: user.email,
      password: '',
      full_name: user.full_name,
      is_admin: user.is_admin,
    })
    setError('')
    setShowForm(true)
  }

  const handleSave = async () => {
    setError('')
    setSaving(true)
    try {
      if (editingUser) {
        const updateData: Record<string, unknown> = {
          email: formData.email,
          full_name: formData.full_name,
          is_admin: formData.is_admin,
        }
        await usersApi.update(editingUser.id, updateData)
      } else {
        if (!formData.password) {
          setError('Passwort ist erforderlich')
          setSaving(false)
          return
        }
        await usersApi.create(formData)
      }
      setShowForm(false)
      await loadUsers()
    } catch (err: unknown) {
      const msg = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      setError(msg || 'Fehler beim Speichern')
    } finally {
      setSaving(false)
    }
  }

  const handleDelete = async (user: UserDetail) => {
    if (!confirm(`Benutzer "${user.username}" wirklich löschen?`)) return
    try {
      await usersApi.delete(user.id)
      await loadUsers()
    } catch (err: unknown) {
      const msg = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      setError(msg || 'Fehler beim Löschen')
    }
  }

  const handleToggleActive = async (user: UserDetail) => {
    try {
      await usersApi.update(user.id, { is_active: !user.is_active })
      await loadUsers()
    } catch {
      setError('Fehler beim Ändern des Status')
    }
  }

  if (loading) return <div className="text-gray-500">Laden...</div>

  return (
    <div>
      <div className="flex justify-between items-center mb-4">
        <h2 className="text-lg font-semibold">Benutzer</h2>
        <button onClick={openCreate} className="px-4 py-2 bg-atlas-600 text-white rounded hover:bg-atlas-700 text-sm">
          Neuer Benutzer
        </button>
      </div>

      {error && <div className="bg-red-50 text-red-600 p-3 rounded text-sm mb-4">{error}</div>}

      <div className="bg-white rounded-lg shadow overflow-hidden">
        <table className="w-full text-sm">
          <thead className="bg-gray-50 text-left">
            <tr>
              <th className="px-4 py-3 font-medium text-gray-600">Benutzername</th>
              <th className="px-4 py-3 font-medium text-gray-600">Name</th>
              <th className="px-4 py-3 font-medium text-gray-600">E-Mail</th>
              <th className="px-4 py-3 font-medium text-gray-600">Rolle</th>
              <th className="px-4 py-3 font-medium text-gray-600">Status</th>
              <th className="px-4 py-3 font-medium text-gray-600">Aktionen</th>
            </tr>
          </thead>
          <tbody className="divide-y">
            {users.map((user) => (
              <tr key={user.id} className="hover:bg-gray-50">
                <td className="px-4 py-3 font-medium">{user.username}</td>
                <td className="px-4 py-3">{user.full_name}</td>
                <td className="px-4 py-3 text-gray-500">{user.email}</td>
                <td className="px-4 py-3">
                  <span className={`px-2 py-1 rounded text-xs font-medium ${
                    user.is_admin ? 'bg-purple-100 text-purple-700' : 'bg-gray-100 text-gray-600'
                  }`}>
                    {user.is_admin ? 'Admin' : 'Benutzer'}
                  </span>
                </td>
                <td className="px-4 py-3">
                  <button
                    onClick={() => handleToggleActive(user)}
                    className={`px-2 py-1 rounded text-xs font-medium ${
                      user.is_active ? 'bg-green-100 text-green-700' : 'bg-red-100 text-red-700'
                    }`}
                  >
                    {user.is_active ? 'Aktiv' : 'Inaktiv'}
                  </button>
                </td>
                <td className="px-4 py-3">
                  <div className="flex gap-2">
                    <button onClick={() => openEdit(user)} className="text-atlas-600 hover:text-atlas-800 text-xs font-medium">
                      Bearbeiten
                    </button>
                    <button onClick={() => handleDelete(user)} className="text-red-600 hover:text-red-800 text-xs font-medium">
                      Löschen
                    </button>
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        {users.length === 0 && (
          <div className="text-center py-8 text-gray-500 text-sm">Keine Benutzer vorhanden</div>
        )}
      </div>

      {showForm && (
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50">
          <div className="bg-white rounded-lg shadow-xl p-6 w-full max-w-md">
            <h3 className="text-lg font-semibold mb-4">
              {editingUser ? 'Benutzer bearbeiten' : 'Neuer Benutzer'}
            </h3>
            {error && <div className="bg-red-50 text-red-600 p-3 rounded text-sm mb-4">{error}</div>}
            <div className="space-y-3">
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">Benutzername</label>
                <input type="text" value={formData.username} onChange={(e) => setFormData({ ...formData, username: e.target.value })}
                  disabled={!!editingUser} className="w-full p-2 border rounded text-sm focus:ring-2 focus:ring-atlas-500 outline-none disabled:bg-gray-100" />
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">Voller Name</label>
                <input type="text" value={formData.full_name} onChange={(e) => setFormData({ ...formData, full_name: e.target.value })}
                  className="w-full p-2 border rounded text-sm focus:ring-2 focus:ring-atlas-500 outline-none" />
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">E-Mail</label>
                <input type="email" value={formData.email} onChange={(e) => setFormData({ ...formData, email: e.target.value })}
                  className="w-full p-2 border rounded text-sm focus:ring-2 focus:ring-atlas-500 outline-none" />
              </div>
              {!editingUser && (
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-1">Passwort</label>
                  <input type="password" value={formData.password} onChange={(e) => setFormData({ ...formData, password: e.target.value })}
                    className="w-full p-2 border rounded text-sm focus:ring-2 focus:ring-atlas-500 outline-none" />
                </div>
              )}
              <div className="flex items-center gap-2">
                <input type="checkbox" id="is_admin" checked={formData.is_admin}
                  onChange={(e) => setFormData({ ...formData, is_admin: e.target.checked })} className="rounded border-gray-300" />
                <label htmlFor="is_admin" className="text-sm text-gray-700">Administrator</label>
              </div>
            </div>
            <div className="flex justify-end gap-2 mt-6">
              <button onClick={() => setShowForm(false)} className="px-4 py-2 border rounded text-sm text-gray-600 hover:bg-gray-50">
                Abbrechen
              </button>
              <button onClick={handleSave} disabled={saving} className="px-4 py-2 bg-atlas-600 text-white rounded text-sm hover:bg-atlas-700 disabled:opacity-50">
                {saving ? 'Speichern...' : 'Speichern'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

// =============================================================================
// Groups Tab
// =============================================================================

interface GroupFormData {
  name: string
  description: string
}

const emptyGroupForm: GroupFormData = { name: '', description: '' }

function GroupsTab() {
  const [groups, setGroups] = useState<Group[]>([])
  const [allUsers, setAllUsers] = useState<UserDetail[]>([])
  const [loading, setLoading] = useState(true)
  const [showForm, setShowForm] = useState(false)
  const [editingGroup, setEditingGroup] = useState<Group | null>(null)
  const [formData, setFormData] = useState<GroupFormData>(emptyGroupForm)
  const [error, setError] = useState('')
  const [saving, setSaving] = useState(false)
  const [managingMembers, setManagingMembers] = useState<Group | null>(null)
  const [groupMembers, setGroupMembers] = useState<number[]>([])

  const loadData = useCallback(async () => {
    try {
      setLoading(true)
      const [groupsData, usersData] = await Promise.all([groupsApi.list(), usersApi.list()])
      setGroups(groupsData)
      setAllUsers(usersData)
    } catch {
      setError('Daten konnten nicht geladen werden')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { loadData() }, [loadData])

  const openCreate = () => { setEditingGroup(null); setFormData(emptyGroupForm); setError(''); setShowForm(true) }
  const openEdit = (group: Group) => {
    setEditingGroup(group); setFormData({ name: group.name, description: group.description || '' }); setError(''); setShowForm(true)
  }

  const handleSave = async () => {
    setError(''); setSaving(true)
    try {
      if (editingGroup) { await groupsApi.update(editingGroup.id, { ...formData }) }
      else { await groupsApi.create(formData) }
      setShowForm(false); await loadData()
    } catch (err: unknown) {
      const msg = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      setError(msg || 'Fehler beim Speichern')
    } finally { setSaving(false) }
  }

  const handleDelete = async (group: Group) => {
    if (!confirm(`Gruppe "${group.name}" wirklich löschen?`)) return
    try { await groupsApi.delete(group.id); await loadData() }
    catch (err: unknown) {
      const msg = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      setError(msg || 'Fehler beim Löschen')
    }
  }

  const openMemberManagement = (group: Group) => {
    setManagingMembers(group); setGroupMembers(group.members?.map((m) => m.id) || []); setError('')
  }

  const handleMemberToggle = (userId: number) => {
    setGroupMembers((prev) => prev.includes(userId) ? prev.filter((id) => id !== userId) : [...prev, userId])
  }

  const saveMemberChanges = async () => {
    if (!managingMembers) return
    setSaving(true); setError('')
    try {
      const currentMembers = managingMembers.members?.map((m) => m.id) || []
      const toAdd = groupMembers.filter((id) => !currentMembers.includes(id))
      const toRemove = currentMembers.filter((id) => !groupMembers.includes(id))
      if (toAdd.length > 0) { await groupsApi.addMembers(managingMembers.id, toAdd) }
      for (const userId of toRemove) { await groupsApi.removeMember(managingMembers.id, userId) }
      setManagingMembers(null); await loadData()
    } catch { setError('Fehler beim Aktualisieren der Mitglieder') }
    finally { setSaving(false) }
  }

  if (loading) return <div className="text-gray-500">Laden...</div>

  return (
    <div>
      <div className="flex justify-between items-center mb-4">
        <h2 className="text-lg font-semibold">Gruppen</h2>
        <button onClick={openCreate} className="px-4 py-2 bg-atlas-600 text-white rounded hover:bg-atlas-700 text-sm">Neue Gruppe</button>
      </div>
      {error && <div className="bg-red-50 text-red-600 p-3 rounded text-sm mb-4">{error}</div>}
      <div className="bg-white rounded-lg shadow overflow-hidden">
        <table className="w-full text-sm">
          <thead className="bg-gray-50 text-left">
            <tr>
              <th className="px-4 py-3 font-medium text-gray-600">Name</th>
              <th className="px-4 py-3 font-medium text-gray-600">Beschreibung</th>
              <th className="px-4 py-3 font-medium text-gray-600">Mitglieder</th>
              <th className="px-4 py-3 font-medium text-gray-600">Aktionen</th>
            </tr>
          </thead>
          <tbody className="divide-y">
            {groups.map((group) => (
              <tr key={group.id} className="hover:bg-gray-50">
                <td className="px-4 py-3 font-medium">{group.name}</td>
                <td className="px-4 py-3 text-gray-500">{group.description || '-'}</td>
                <td className="px-4 py-3">
                  <button onClick={() => openMemberManagement(group)} className="text-atlas-600 hover:text-atlas-800 text-xs font-medium">
                    {group.members?.length || 0} Mitglieder
                  </button>
                </td>
                <td className="px-4 py-3">
                  <div className="flex gap-2">
                    <button onClick={() => openEdit(group)} className="text-atlas-600 hover:text-atlas-800 text-xs font-medium">Bearbeiten</button>
                    <button onClick={() => handleDelete(group)} className="text-red-600 hover:text-red-800 text-xs font-medium">Löschen</button>
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        {groups.length === 0 && <div className="text-center py-8 text-gray-500 text-sm">Keine Gruppen vorhanden</div>}
      </div>

      {showForm && (
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50">
          <div className="bg-white rounded-lg shadow-xl p-6 w-full max-w-md">
            <h3 className="text-lg font-semibold mb-4">{editingGroup ? 'Gruppe bearbeiten' : 'Neue Gruppe'}</h3>
            {error && <div className="bg-red-50 text-red-600 p-3 rounded text-sm mb-4">{error}</div>}
            <div className="space-y-3">
              <div><label className="block text-sm font-medium text-gray-700 mb-1">Name</label>
                <input type="text" value={formData.name} onChange={(e) => setFormData({ ...formData, name: e.target.value })}
                  className="w-full p-2 border rounded text-sm focus:ring-2 focus:ring-atlas-500 outline-none" /></div>
              <div><label className="block text-sm font-medium text-gray-700 mb-1">Beschreibung</label>
                <textarea value={formData.description} onChange={(e) => setFormData({ ...formData, description: e.target.value })}
                  rows={3} className="w-full p-2 border rounded text-sm focus:ring-2 focus:ring-atlas-500 outline-none resize-none" /></div>
            </div>
            <div className="flex justify-end gap-2 mt-6">
              <button onClick={() => setShowForm(false)} className="px-4 py-2 border rounded text-sm text-gray-600 hover:bg-gray-50">Abbrechen</button>
              <button onClick={handleSave} disabled={saving} className="px-4 py-2 bg-atlas-600 text-white rounded text-sm hover:bg-atlas-700 disabled:opacity-50">
                {saving ? 'Speichern...' : 'Speichern'}</button>
            </div>
          </div>
        </div>
      )}

      {managingMembers && (
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50">
          <div className="bg-white rounded-lg shadow-xl p-6 w-full max-w-md">
            <h3 className="text-lg font-semibold mb-4">Mitglieder: {managingMembers.name}</h3>
            {error && <div className="bg-red-50 text-red-600 p-3 rounded text-sm mb-4">{error}</div>}
            <div className="max-h-64 overflow-y-auto space-y-2">
              {allUsers.filter((u) => u.is_active).map((user) => (
                <label key={user.id} className="flex items-center gap-3 p-2 rounded hover:bg-gray-50 cursor-pointer">
                  <input type="checkbox" checked={groupMembers.includes(user.id)} onChange={() => handleMemberToggle(user.id)} className="rounded border-gray-300" />
                  <div><div className="text-sm font-medium">{user.full_name}</div><div className="text-xs text-gray-500">{user.username}</div></div>
                </label>
              ))}
            </div>
            <div className="flex justify-end gap-2 mt-6">
              <button onClick={() => setManagingMembers(null)} className="px-4 py-2 border rounded text-sm text-gray-600 hover:bg-gray-50">Abbrechen</button>
              <button onClick={saveMemberChanges} disabled={saving} className="px-4 py-2 bg-atlas-600 text-white rounded text-sm hover:bg-atlas-700 disabled:opacity-50">
                {saving ? 'Speichern...' : 'Speichern'}</button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

// =============================================================================
// Collections Tab
// =============================================================================

interface CollectionFormData {
  name: string
  description: string
}

const emptyCollectionForm: CollectionFormData = { name: '', description: '' }

function CollectionsTab() {
  const [collections, setCollections] = useState<Collection[]>([])
  const [groups, setGroups] = useState<Group[]>([])
  const [loading, setLoading] = useState(true)
  const [showForm, setShowForm] = useState(false)
  const [editingCollection, setEditingCollection] = useState<Collection | null>(null)
  const [formData, setFormData] = useState<CollectionFormData>(emptyCollectionForm)
  const [error, setError] = useState('')
  const [saving, setSaving] = useState(false)
  const [managingAccess, setManagingAccess] = useState<Collection | null>(null)
  const [accessList, setAccessList] = useState<AccessInfo[]>([])
  const [accessLoading, setAccessLoading] = useState(false)

  const loadData = useCallback(async () => {
    try {
      setLoading(true)
      const [colsData, groupsData] = await Promise.all([collectionsApi.list(), groupsApi.list()])
      setCollections(colsData)
      setGroups(groupsData)
    } catch { setError('Daten konnten nicht geladen werden') }
    finally { setLoading(false) }
  }, [])

  useEffect(() => { loadData() }, [loadData])

  const openCreate = () => { setEditingCollection(null); setFormData(emptyCollectionForm); setError(''); setShowForm(true) }
  const openEdit = (col: Collection) => {
    setEditingCollection(col); setFormData({ name: col.name, description: col.description || '' }); setError(''); setShowForm(true)
  }

  const handleSave = async () => {
    setError(''); setSaving(true)
    try {
      if (editingCollection) { await collectionsApi.update(editingCollection.id, { ...formData }) }
      else { await collectionsApi.create(formData) }
      setShowForm(false); await loadData()
    } catch (err: unknown) {
      const msg = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      setError(msg || 'Fehler beim Speichern')
    } finally { setSaving(false) }
  }

  const handleDelete = async (col: Collection) => {
    if (!confirm(`Collection "${col.name}" wirklich löschen? Alle Dokumente und Chunks werden ebenfalls gelöscht.`)) return
    try { await collectionsApi.delete(col.id); await loadData() }
    catch (err: unknown) {
      const msg = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      setError(msg || 'Fehler beim Löschen')
    }
  }

  const openAccessManagement = async (col: Collection) => {
    setManagingAccess(col); setAccessLoading(true); setError('')
    try { const data = await collectionsApi.getAccess(col.id); setAccessList(data) }
    catch { setAccessList([]) }
    finally { setAccessLoading(false) }
  }

  const handleAccessChange = async (groupId: number, canRead: boolean, canWrite: boolean) => {
    if (!managingAccess) return
    try {
      await collectionsApi.setAccess(managingAccess.id, groupId, canRead, canWrite)
      const data = await collectionsApi.getAccess(managingAccess.id)
      setAccessList(data)
    } catch { setError('Fehler beim Aktualisieren der Zugriffsrechte') }
  }

  const handleRemoveAccess = async (groupId: number) => {
    if (!managingAccess) return
    try {
      await collectionsApi.removeAccess(managingAccess.id, groupId)
      setAccessList((prev) => prev.filter((a) => a.group_id !== groupId))
    } catch { setError('Fehler beim Entfernen der Zugriffsrechte') }
  }

  if (loading) return <div className="text-gray-500">Laden...</div>

  return (
    <div>
      <div className="flex justify-between items-center mb-4">
        <h2 className="text-lg font-semibold">Collections</h2>
        <button onClick={openCreate} className="px-4 py-2 bg-atlas-600 text-white rounded hover:bg-atlas-700 text-sm">Neue Collection</button>
      </div>
      {error && <div className="bg-red-50 text-red-600 p-3 rounded text-sm mb-4">{error}</div>}
      <div className="bg-white rounded-lg shadow overflow-hidden">
        <table className="w-full text-sm">
          <thead className="bg-gray-50 text-left">
            <tr>
              <th className="px-4 py-3 font-medium text-gray-600">Name</th>
              <th className="px-4 py-3 font-medium text-gray-600">Beschreibung</th>
              <th className="px-4 py-3 font-medium text-gray-600">Dokumente</th>
              <th className="px-4 py-3 font-medium text-gray-600">Zugriff</th>
              <th className="px-4 py-3 font-medium text-gray-600">Aktionen</th>
            </tr>
          </thead>
          <tbody className="divide-y">
            {collections.map((col) => (
              <tr key={col.id} className="hover:bg-gray-50">
                <td className="px-4 py-3 font-medium">{col.name}</td>
                <td className="px-4 py-3 text-gray-500">{col.description || '-'}</td>
                <td className="px-4 py-3">{col.document_count}</td>
                <td className="px-4 py-3">
                  <button onClick={() => openAccessManagement(col)} className="text-atlas-600 hover:text-atlas-800 text-xs font-medium">Zugriff verwalten</button>
                </td>
                <td className="px-4 py-3">
                  <div className="flex gap-2">
                    <button onClick={() => openEdit(col)} className="text-atlas-600 hover:text-atlas-800 text-xs font-medium">Bearbeiten</button>
                    <button onClick={() => handleDelete(col)} className="text-red-600 hover:text-red-800 text-xs font-medium">Löschen</button>
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        {collections.length === 0 && <div className="text-center py-8 text-gray-500 text-sm">Keine Collections vorhanden</div>}
      </div>

      {showForm && (
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50">
          <div className="bg-white rounded-lg shadow-xl p-6 w-full max-w-md">
            <h3 className="text-lg font-semibold mb-4">{editingCollection ? 'Collection bearbeiten' : 'Neue Collection'}</h3>
            {error && <div className="bg-red-50 text-red-600 p-3 rounded text-sm mb-4">{error}</div>}
            <div className="space-y-3">
              <div><label className="block text-sm font-medium text-gray-700 mb-1">Name</label>
                <input type="text" value={formData.name} onChange={(e) => setFormData({ ...formData, name: e.target.value })}
                  placeholder="z.B. Normen, Datenblätter" className="w-full p-2 border rounded text-sm focus:ring-2 focus:ring-atlas-500 outline-none" /></div>
              <div><label className="block text-sm font-medium text-gray-700 mb-1">Beschreibung</label>
                <textarea value={formData.description} onChange={(e) => setFormData({ ...formData, description: e.target.value })}
                  rows={3} placeholder="Beschreiben Sie den Zweck dieser Collection..." className="w-full p-2 border rounded text-sm focus:ring-2 focus:ring-atlas-500 outline-none resize-none" /></div>
            </div>
            <div className="flex justify-end gap-2 mt-6">
              <button onClick={() => setShowForm(false)} className="px-4 py-2 border rounded text-sm text-gray-600 hover:bg-gray-50">Abbrechen</button>
              <button onClick={handleSave} disabled={saving} className="px-4 py-2 bg-atlas-600 text-white rounded text-sm hover:bg-atlas-700 disabled:opacity-50">
                {saving ? 'Speichern...' : 'Speichern'}</button>
            </div>
          </div>
        </div>
      )}

      {managingAccess && (
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50">
          <div className="bg-white rounded-lg shadow-xl p-6 w-full max-w-lg">
            <h3 className="text-lg font-semibold mb-2">Zugriff: {managingAccess.name}</h3>
            <p className="text-xs text-gray-500 mb-4">Legen Sie fest, welche Gruppen auf diese Collection zugreifen dürfen.</p>
            {error && <div className="bg-red-50 text-red-600 p-3 rounded text-sm mb-4">{error}</div>}
            {accessLoading ? (
              <div className="text-gray-500 text-sm py-4">Laden...</div>
            ) : (
              <div className="space-y-4">
                {accessList.length > 0 && (
                  <div>
                    <h4 className="text-sm font-medium text-gray-700 mb-2">Aktuelle Zugriffe</h4>
                    <div className="space-y-2">
                      {accessList.map((access) => (
                        <div key={access.group_id} className="flex items-center gap-3 p-2 bg-gray-50 rounded">
                          <span className="text-sm font-medium flex-1">{access.group_name}</span>
                          <label className="flex items-center gap-1 text-xs">
                            <input type="checkbox" checked={access.can_read}
                              onChange={(e) => handleAccessChange(access.group_id, e.target.checked, access.can_write)} className="rounded border-gray-300" />Lesen</label>
                          <label className="flex items-center gap-1 text-xs">
                            <input type="checkbox" checked={access.can_write}
                              onChange={(e) => handleAccessChange(access.group_id, access.can_read, e.target.checked)} className="rounded border-gray-300" />Schreiben</label>
                          <button onClick={() => handleRemoveAccess(access.group_id)} className="text-red-500 hover:text-red-700 text-xs">Entfernen</button>
                        </div>
                      ))}
                    </div>
                  </div>
                )}
                {groups.filter((g) => !accessList.some((a) => a.group_id === g.id)).length > 0 && (
                  <div>
                    <h4 className="text-sm font-medium text-gray-700 mb-2">Gruppe hinzufügen</h4>
                    <div className="space-y-1">
                      {groups.filter((g) => !accessList.some((a) => a.group_id === g.id)).map((group) => (
                        <div key={group.id} className="flex items-center justify-between p-2 rounded hover:bg-gray-50">
                          <span className="text-sm">{group.name}</span>
                          <button onClick={() => handleAccessChange(group.id, true, false)} className="text-atlas-600 hover:text-atlas-800 text-xs font-medium">Zugriff gewähren</button>
                        </div>
                      ))}
                    </div>
                  </div>
                )}
                {groups.length === 0 && <p className="text-sm text-gray-500">Erstellen Sie zuerst Gruppen im Gruppen-Tab.</p>}
              </div>
            )}
            <div className="flex justify-end mt-6">
              <button onClick={() => { setManagingAccess(null); loadData() }}
                className="px-4 py-2 bg-atlas-600 text-white rounded text-sm hover:bg-atlas-700">Fertig</button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
