/**
 * AdminPage - Verwaltungsoberfläche für Admins.
 *
 * Tabs:
 * - Benutzer: Erstellen, bearbeiten, löschen, Gruppen zuordnen
 * - Gruppen: Erstellen, bearbeiten, Mitglieder verwalten
 * - Collections: Erstellen, bearbeiten, Gruppenzugriff verwalten
 */

import { useState } from 'react'

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

function UsersTab() {
  // TODO: Implementierung mit usersApi
  return (
    <div>
      <div className="flex justify-between items-center mb-4">
        <h2 className="text-lg font-semibold">Benutzer</h2>
        <button className="px-4 py-2 bg-atlas-600 text-white rounded hover:bg-atlas-700 text-sm">
          Neuer Benutzer
        </button>
      </div>
      <p className="text-gray-500 text-sm">
        Hier können Benutzer erstellt, bearbeitet und gelöscht werden.
        Benutzer können mehreren Gruppen zugeordnet werden.
      </p>
      {/* TODO: Benutzer-Tabelle und Formulare */}
    </div>
  )
}

function GroupsTab() {
  // TODO: Implementierung mit groupsApi
  return (
    <div>
      <div className="flex justify-between items-center mb-4">
        <h2 className="text-lg font-semibold">Gruppen</h2>
        <button className="px-4 py-2 bg-atlas-600 text-white rounded hover:bg-atlas-700 text-sm">
          Neue Gruppe
        </button>
      </div>
      <p className="text-gray-500 text-sm">
        Gruppen wie z.B. Konstruktion, Vertrieb oder Service.
        Über Gruppen wird der Zugriff auf Collections gesteuert.
      </p>
      {/* TODO: Gruppen-Tabelle und Formulare */}
    </div>
  )
}

function CollectionsTab() {
  // TODO: Implementierung mit collectionsApi
  return (
    <div>
      <div className="flex justify-between items-center mb-4">
        <h2 className="text-lg font-semibold">Collections</h2>
        <button className="px-4 py-2 bg-atlas-600 text-white rounded hover:bg-atlas-700 text-sm">
          Neue Collection
        </button>
      </div>
      <p className="text-gray-500 text-sm">
        Collections gruppieren ähnliche Dokumente (z.B. Normen, Datenblätter, Anfragen).
        Hier kann der Zugriff für Gruppen konfiguriert werden.
      </p>
      {/* TODO: Collections-Tabelle mit Zugriffskontrolle */}
    </div>
  )
}
