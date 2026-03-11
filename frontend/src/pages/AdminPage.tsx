/**
 * AdminPage - Verwaltungsoberfläche für Admins.
 *
 * Tabs:
 * - Benutzer: Erstellen, bearbeiten, löschen, Gruppen zuordnen
 * - Gruppen: Erstellen, bearbeiten, Mitglieder verwalten
 * - Collections: Erstellen, bearbeiten, Gruppenzugriff verwalten
 */

import { useState, useEffect, useCallback } from 'react'
import { usersApi, groupsApi } from '../services/api'
import type { UserDetail, Group } from '../types'

type Tab = 'users' | 'groups' | 'collections'

export default function AdminPage() {
  const [activeTab, setActiveTab] = useState<Tab>('users')

  const tabs: { key: Tab; label: string }[] = [
    { key: 'users', label: 'Benutzer' },
    { key: 'groups', label: 'Gruppen' },
    { key: 'collections', label: 'Collections' },
  ]

  return (
    <div className="p-6">
      <h1 className="text-2xl font-bold mb-6">Administration</h1>

      {/* Tab-Navigation */}
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

      {/* Tab-Inhalt */}
      <div className="max-w-4xl">
        {activeTab === 'users' && <UsersTab />}
        {activeTab === 'groups' && <GroupsTab />}
        {activeTab === 'collections' && <CollectionsTab />}
      </div>
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
        <button
          onClick={openCreate}
          className="px-4 py-2 bg-atlas-600 text-white rounded hover:bg-atlas-700 text-sm"
        >
          Neuer Benutzer
        </button>
      </div>

      {error && <div className="bg-red-50 text-red-600 p-3 rounded text-sm mb-4">{error}</div>}

      {/* Benutzer-Tabelle */}
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
                    <button
                      onClick={() => openEdit(user)}
                      className="text-atlas-600 hover:text-atlas-800 text-xs font-medium"
                    >
                      Bearbeiten
                    </button>
                    <button
                      onClick={() => handleDelete(user)}
                      className="text-red-600 hover:text-red-800 text-xs font-medium"
                    >
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

      {/* Benutzer-Formular Dialog */}
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
                <input
                  type="text"
                  value={formData.username}
                  onChange={(e) => setFormData({ ...formData, username: e.target.value })}
                  disabled={!!editingUser}
                  className="w-full p-2 border rounded text-sm focus:ring-2 focus:ring-atlas-500 outline-none disabled:bg-gray-100"
                />
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">Voller Name</label>
                <input
                  type="text"
                  value={formData.full_name}
                  onChange={(e) => setFormData({ ...formData, full_name: e.target.value })}
                  className="w-full p-2 border rounded text-sm focus:ring-2 focus:ring-atlas-500 outline-none"
                />
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">E-Mail</label>
                <input
                  type="email"
                  value={formData.email}
                  onChange={(e) => setFormData({ ...formData, email: e.target.value })}
                  className="w-full p-2 border rounded text-sm focus:ring-2 focus:ring-atlas-500 outline-none"
                />
              </div>
              {!editingUser && (
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-1">Passwort</label>
                  <input
                    type="password"
                    value={formData.password}
                    onChange={(e) => setFormData({ ...formData, password: e.target.value })}
                    className="w-full p-2 border rounded text-sm focus:ring-2 focus:ring-atlas-500 outline-none"
                  />
                </div>
              )}
              <div className="flex items-center gap-2">
                <input
                  type="checkbox"
                  id="is_admin"
                  checked={formData.is_admin}
                  onChange={(e) => setFormData({ ...formData, is_admin: e.target.checked })}
                  className="rounded border-gray-300"
                />
                <label htmlFor="is_admin" className="text-sm text-gray-700">Administrator</label>
              </div>
            </div>
            <div className="flex justify-end gap-2 mt-6">
              <button
                onClick={() => setShowForm(false)}
                className="px-4 py-2 border rounded text-sm text-gray-600 hover:bg-gray-50"
              >
                Abbrechen
              </button>
              <button
                onClick={handleSave}
                disabled={saving}
                className="px-4 py-2 bg-atlas-600 text-white rounded text-sm hover:bg-atlas-700 disabled:opacity-50"
              >
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
      const [groupsData, usersData] = await Promise.all([
        groupsApi.list(),
        usersApi.list(),
      ])
      setGroups(groupsData)
      setAllUsers(usersData)
    } catch {
      setError('Daten konnten nicht geladen werden')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    loadData()
  }, [loadData])

  const openCreate = () => {
    setEditingGroup(null)
    setFormData(emptyGroupForm)
    setError('')
    setShowForm(true)
  }

  const openEdit = (group: Group) => {
    setEditingGroup(group)
    setFormData({ name: group.name, description: group.description || '' })
    setError('')
    setShowForm(true)
  }

  const handleSave = async () => {
    setError('')
    setSaving(true)
    try {
      if (editingGroup) {
        await groupsApi.update(editingGroup.id, { ...formData })
      } else {
        await groupsApi.create(formData)
      }
      setShowForm(false)
      await loadData()
    } catch (err: unknown) {
      const msg = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      setError(msg || 'Fehler beim Speichern')
    } finally {
      setSaving(false)
    }
  }

  const handleDelete = async (group: Group) => {
    if (!confirm(`Gruppe "${group.name}" wirklich löschen?`)) return
    try {
      await groupsApi.delete(group.id)
      await loadData()
    } catch (err: unknown) {
      const msg = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      setError(msg || 'Fehler beim Löschen')
    }
  }

  const openMemberManagement = (group: Group) => {
    setManagingMembers(group)
    setGroupMembers(group.members?.map((m) => m.id) || [])
    setError('')
  }

  const handleMemberToggle = (userId: number) => {
    setGroupMembers((prev) =>
      prev.includes(userId) ? prev.filter((id) => id !== userId) : [...prev, userId]
    )
  }

  const saveMemberChanges = async () => {
    if (!managingMembers) return
    setSaving(true)
    setError('')
    try {
      const currentMembers = managingMembers.members?.map((m) => m.id) || []
      const toAdd = groupMembers.filter((id) => !currentMembers.includes(id))
      const toRemove = currentMembers.filter((id) => !groupMembers.includes(id))

      if (toAdd.length > 0) {
        await groupsApi.addMembers(managingMembers.id, toAdd)
      }
      for (const userId of toRemove) {
        await groupsApi.removeMember(managingMembers.id, userId)
      }
      setManagingMembers(null)
      await loadData()
    } catch {
      setError('Fehler beim Aktualisieren der Mitglieder')
    } finally {
      setSaving(false)
    }
  }

  if (loading) return <div className="text-gray-500">Laden...</div>

  return (
    <div>
      <div className="flex justify-between items-center mb-4">
        <h2 className="text-lg font-semibold">Gruppen</h2>
        <button
          onClick={openCreate}
          className="px-4 py-2 bg-atlas-600 text-white rounded hover:bg-atlas-700 text-sm"
        >
          Neue Gruppe
        </button>
      </div>

      {error && <div className="bg-red-50 text-red-600 p-3 rounded text-sm mb-4">{error}</div>}

      {/* Gruppen-Tabelle */}
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
                  <button
                    onClick={() => openMemberManagement(group)}
                    className="text-atlas-600 hover:text-atlas-800 text-xs font-medium"
                  >
                    {group.members?.length || 0} Mitglieder
                  </button>
                </td>
                <td className="px-4 py-3">
                  <div className="flex gap-2">
                    <button
                      onClick={() => openEdit(group)}
                      className="text-atlas-600 hover:text-atlas-800 text-xs font-medium"
                    >
                      Bearbeiten
                    </button>
                    <button
                      onClick={() => handleDelete(group)}
                      className="text-red-600 hover:text-red-800 text-xs font-medium"
                    >
                      Löschen
                    </button>
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        {groups.length === 0 && (
          <div className="text-center py-8 text-gray-500 text-sm">Keine Gruppen vorhanden</div>
        )}
      </div>

      {/* Gruppen-Formular Dialog */}
      {showForm && (
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50">
          <div className="bg-white rounded-lg shadow-xl p-6 w-full max-w-md">
            <h3 className="text-lg font-semibold mb-4">
              {editingGroup ? 'Gruppe bearbeiten' : 'Neue Gruppe'}
            </h3>
            {error && <div className="bg-red-50 text-red-600 p-3 rounded text-sm mb-4">{error}</div>}
            <div className="space-y-3">
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">Name</label>
                <input
                  type="text"
                  value={formData.name}
                  onChange={(e) => setFormData({ ...formData, name: e.target.value })}
                  className="w-full p-2 border rounded text-sm focus:ring-2 focus:ring-atlas-500 outline-none"
                />
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">Beschreibung</label>
                <textarea
                  value={formData.description}
                  onChange={(e) => setFormData({ ...formData, description: e.target.value })}
                  rows={3}
                  className="w-full p-2 border rounded text-sm focus:ring-2 focus:ring-atlas-500 outline-none resize-none"
                />
              </div>
            </div>
            <div className="flex justify-end gap-2 mt-6">
              <button
                onClick={() => setShowForm(false)}
                className="px-4 py-2 border rounded text-sm text-gray-600 hover:bg-gray-50"
              >
                Abbrechen
              </button>
              <button
                onClick={handleSave}
                disabled={saving}
                className="px-4 py-2 bg-atlas-600 text-white rounded text-sm hover:bg-atlas-700 disabled:opacity-50"
              >
                {saving ? 'Speichern...' : 'Speichern'}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Mitglieder-Verwaltung Dialog */}
      {managingMembers && (
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50">
          <div className="bg-white rounded-lg shadow-xl p-6 w-full max-w-md">
            <h3 className="text-lg font-semibold mb-4">
              Mitglieder: {managingMembers.name}
            </h3>
            {error && <div className="bg-red-50 text-red-600 p-3 rounded text-sm mb-4">{error}</div>}
            <div className="max-h-64 overflow-y-auto space-y-2">
              {allUsers.filter((u) => u.is_active).map((user) => (
                <label
                  key={user.id}
                  className="flex items-center gap-3 p-2 rounded hover:bg-gray-50 cursor-pointer"
                >
                  <input
                    type="checkbox"
                    checked={groupMembers.includes(user.id)}
                    onChange={() => handleMemberToggle(user.id)}
                    className="rounded border-gray-300"
                  />
                  <div>
                    <div className="text-sm font-medium">{user.full_name}</div>
                    <div className="text-xs text-gray-500">{user.username}</div>
                  </div>
                </label>
              ))}
            </div>
            <div className="flex justify-end gap-2 mt-6">
              <button
                onClick={() => setManagingMembers(null)}
                className="px-4 py-2 border rounded text-sm text-gray-600 hover:bg-gray-50"
              >
                Abbrechen
              </button>
              <button
                onClick={saveMemberChanges}
                disabled={saving}
                className="px-4 py-2 bg-atlas-600 text-white rounded text-sm hover:bg-atlas-700 disabled:opacity-50"
              >
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
// Collections Tab (Platzhalter - Phase 3)
// =============================================================================

function CollectionsTab() {
  return (
    <div>
      <div className="flex justify-between items-center mb-4">
        <h2 className="text-lg font-semibold">Collections</h2>
        <button className="px-4 py-2 bg-atlas-600 text-white rounded hover:bg-atlas-700 text-sm opacity-50 cursor-not-allowed" disabled>
          Neue Collection
        </button>
      </div>
      <p className="text-gray-500 text-sm">
        Collections gruppieren ähnliche Dokumente (z.B. Normen, Datenblätter, Anfragen).
        Hier kann der Zugriff für Gruppen konfiguriert werden.
        Diese Funktion wird in Phase 3 implementiert.
      </p>
    </div>
  )
}
