'use strict';

// Store complete conversations, including the evidence returned with each answer.
// IndexedDB avoids the small localStorage limit for tabular query results.
const ConversationHistory = (() => {
  const id = () => globalThis.crypto?.randomUUID?.() || `${Date.now()}-${Math.random().toString(36).slice(2)}`;

  function create(title, dataset = null) {
    const now = Date.now();
    return { id: id(), title, dataset, createdAt: now, updatedAt: now, turns: [] };
  }

  function append(conversation, question) {
    const turn = { id: id(), question, createdAt: Date.now(), status: 'pending', result: null, error: null };
    conversation.turns.push(turn);
    conversation.updatedAt = turn.createdAt;
    return turn;
  }

  function finish(conversation, turnId, result, error = null) {
    const turn = conversation.turns.find((item) => item.id === turnId);
    if (!turn) throw new Error('The conversation turn no longer exists');
    turn.result = result;
    turn.error = error;
    turn.status = result ? 'complete' : 'error';
    conversation.updatedAt = Date.now();
    return turn;
  }

  function migrate(items) {
    return items.filter((item) => typeof item?.question === 'string').map((item) => {
      const conversation = create(item.question);
      const turn = append(conversation, item.question);
      turn.status = 'legacy';
      turn.createdAt = Number(item.at) || Date.now();
      conversation.createdAt = conversation.updatedAt = turn.createdAt;
      return conversation;
    });
  }

  function createStore(environment = globalThis) {
    let database;
    const fallbackKey = 'datamind.conversations.v2';
    const connect = () => {
      if (!database) database = new Promise((resolve) => {
        if (!environment.indexedDB) return resolve(null);
        try {
          const request = environment.indexedDB.open('datamind-conversations', 1);
          request.onupgradeneeded = () => request.result.createObjectStore('conversations', { keyPath: 'id' });
          request.onsuccess = () => resolve(request.result);
          request.onerror = request.onblocked = () => resolve(null);
        } catch { resolve(null); }
      });
      return database;
    };
    const readFallback = () => JSON.parse(environment.localStorage.getItem(fallbackKey) || '[]');
    return {
      async load() {
        const db = await connect();
        if (!db) return readFallback();
        return new Promise((resolve, reject) => {
          const request = db.transaction('conversations', 'readonly').objectStore('conversations').getAll();
          request.onsuccess = () => resolve(request.result);
          request.onerror = () => reject(request.error);
        });
      },
      async save(conversation) {
        const db = await connect();
        if (!db) {
          const items = readFallback().filter((item) => item.id !== conversation.id);
          items.push(conversation);
          environment.localStorage.setItem(fallbackKey, JSON.stringify(items));
          return;
        }
        return new Promise((resolve, reject) => {
          const transaction = db.transaction('conversations', 'readwrite');
          transaction.objectStore('conversations').put(conversation);
          transaction.oncomplete = () => resolve();
          transaction.onerror = transaction.onabort = () => reject(transaction.error || new Error('Could not save conversation'));
        });
      },
      async clear() {
        const db = await connect();
        if (!db) { environment.localStorage.removeItem(fallbackKey); return; }
        return new Promise((resolve, reject) => {
          const transaction = db.transaction('conversations', 'readwrite');
          transaction.objectStore('conversations').clear();
          transaction.oncomplete = () => resolve();
          transaction.onerror = transaction.onabort = () => reject(transaction.error || new Error('Could not clear conversations'));
        });
      },
    };
  }

  return { create, append, finish, migrate, createStore };
})();

if (typeof module !== 'undefined') module.exports = ConversationHistory;
