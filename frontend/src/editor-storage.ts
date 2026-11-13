import { isRemote, remoteDraft, remoteSave } from './backend-api'
import type { ReviewState } from './review-state'
import type { WordLoadTrace } from './word-load-metrics'

export interface EditorDraft {
  version: 1
  blob: Blob
  name: string
  isDemo: boolean
  review: ReviewState
  edited: boolean
}
const database = 'rixin-contract-editor-v1'
async function open() {
  return new Promise<IDBDatabase>((resolve, reject) => {
    const request = indexedDB.open(database, 1)
    request.onupgradeneeded = () => request.result.createObjectStore('drafts')
    request.onsuccess = () => resolve(request.result)
    request.onerror = () => reject(request.error)
  })
}
export async function readDraft(key = 'current', trace?: WordLoadTrace): Promise<EditorDraft | undefined> {
  if(isRemote(key)) return remoteDraft(key, trace)
  const db = await open()
  try {
    return await new Promise((resolve, reject) => {
      const request = db.transaction('drafts').objectStore('drafts').get(key)
      request.onsuccess = () => resolve(request.result)
      request.onerror = () => reject(request.error)
    })
  } finally { db.close() }
}
export async function writeDraft(draft: EditorDraft, key = 'current') {
  if(isRemote(key)) return remoteSave(key,draft)
  const db = await open()
  try {
    await new Promise<void>((resolve, reject) => {
      const tx = db.transaction('drafts', 'readwrite')
      tx.objectStore('drafts').put(draft, key)
      tx.oncomplete = () => resolve()
      tx.onerror = () => reject(tx.error)
      tx.onabort = () => reject(tx.error ?? new Error('保存已中止'))
    })
  } finally { db.close() }
}

export async function readCatalog<T>(): Promise<T | undefined> {
  const db = await open()
  try {
    return await new Promise((resolve, reject) => {
      const request = db.transaction('drafts').objectStore('drafts').get('workbench:catalog')
      request.onsuccess = () => resolve(request.result)
      request.onerror = () => reject(request.error)
    })
  } finally { db.close() }
}

// Store metadata and the original upload atomically; an unsuccessful upload
// must never leave a contract that claims to have an available document.
export async function writeCatalog<T>(catalog: T, document?: {key: string; draft: EditorDraft}) {
  const db = await open()
  try {
    await new Promise<void>((resolve, reject) => {
      const tx = db.transaction('drafts', 'readwrite')
      tx.objectStore('drafts').put(catalog, 'workbench:catalog')
      if (document) tx.objectStore('drafts').put(document.draft, document.key)
      tx.oncomplete = () => resolve()
      tx.onerror = () => reject(tx.error)
      tx.onabort = () => reject(tx.error ?? new Error('保存已中止'))
    })
  } finally { db.close() }
}

export async function readLocalRecord<T>(key: string): Promise<T | undefined> {
  const db = await open()
  try {
    return await new Promise((resolve, reject) => {
      const request = db.transaction('drafts').objectStore('drafts').get(key)
      request.onsuccess = () => resolve(request.result)
      request.onerror = () => reject(request.error)
    })
  } finally { db.close() }
}

export async function writeLocalRecord<T>(key: string, value: T) {
  const db = await open()
  try {
    await new Promise<void>((resolve, reject) => {
      const tx = db.transaction('drafts', 'readwrite')
      tx.objectStore('drafts').put(value, key)
      tx.oncomplete = () => resolve()
      tx.onerror = () => reject(tx.error)
      tx.onabort = () => reject(tx.error ?? new Error('保存已中止'))
    })
  } finally { db.close() }
}
