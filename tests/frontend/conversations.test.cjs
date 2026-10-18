const test = require('node:test');
const assert = require('node:assert/strict');
const history = require('../../src/datamind/server/static/conversations.js');

function browserStorage() {
  const data = new Map();
  return { localStorage: {
    getItem: (key) => data.get(key) ?? null,
    setItem: (key, value) => data.set(key, value),
    removeItem: (key) => data.delete(key),
  } };
}

test('additional questions retain earlier answers and evidence, including repeated questions', () => {
  const chat = history.create('Revenue');
  const first = history.append(chat, 'What is revenue?');
  const result = { answer: '100 [[Q1:R1]]', evidence: { queries: [{ query_id: 'original', rows: [[100]] }] } };
  history.finish(chat, first.id, result);
  const second = history.append(chat, 'What is revenue?');
  history.finish(chat, second.id, { answer: '200' });
  assert.equal(chat.turns.length, 2);
  assert.notEqual(first.id, second.id);
  assert.deepEqual(chat.turns[0].result, result);
});

test('a response completing after navigation stays attached to its original conversation', () => {
  const firstChat = history.create('First');
  const pending = history.append(firstChat, 'First question');
  const otherChat = history.create('Other');
  history.append(otherChat, 'Other question');
  history.finish(firstChat, pending.id, { answer: 'First answer' });
  assert.equal(firstChat.turns[0].result.answer, 'First answer');
  assert.equal(otherChat.turns[0].result, null);
});

test('reopening storage restores all turns and complete source evidence without execution', async () => {
  const environment = browserStorage();
  const store = history.createStore(environment);
  const chat = history.create('Saved conversation');
  const turn = history.append(chat, 'Revenue?');
  history.finish(chat, turn.id, { answer: '42', chart: { type: 'kpi', kpi_value: 42 }, receipt: { root_hash: 'digest' }, evidence: { queries: [{ sql: 'SELECT 42', rows: [[42]] }] } });
  await store.save(chat);
  const second = history.append(chat, 'Products?');
  history.finish(chat, second.id, { answer: 'Three products' });
  await store.save(chat);
  const reloaded = await history.createStore(environment).load();
  assert.equal(reloaded.length, 1);
  assert.deepEqual(reloaded[0], chat);
});

test('an error is recorded as its own turn without removing the preceding result', () => {
  const chat = history.create('Error handling');
  const first = history.append(chat, 'First');
  history.finish(chat, first.id, { answer: 'Keep this answer' });
  const second = history.append(chat, 'Second');
  history.finish(chat, second.id, null, 'Network unavailable');
  assert.equal(chat.turns[0].result.answer, 'Keep this answer');
  assert.equal(chat.turns[1].status, 'error');
  assert.equal(chat.turns[1].error, 'Network unavailable');
});

test('legacy question-only history is preserved without inventing answers', () => {
  const migrated = history.migrate([{ question: 'Old question', at: 12345 }, null, {}]);
  assert.equal(migrated.length, 1);
  assert.equal(migrated[0].updatedAt, 12345);
  assert.equal(migrated[0].turns[0].status, 'legacy');
  assert.equal(migrated[0].turns[0].result, null);
});

test('clearing saved conversations removes their stored answers', async () => {
  const store = history.createStore(browserStorage());
  await store.save(history.create('First'));
  await store.save(history.create('Second'));
  await store.clear();
  assert.deepEqual(await store.load(), []);
});
