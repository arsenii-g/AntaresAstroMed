import test from 'node:test';
import assert from 'node:assert/strict';
import { mergeReadings, sparkPath } from '../js/data.js';

test('late HTTP history cannot replace newer WebSocket data and retries appear once', () => {
  const newer = { device_id: 'd', ts: '2026-11-14T12:00:05Z', vitals: { heart_rate_bpm: 90 } };
  const older = { device_id: 'd', ts: '2026-11-14T12:00:00Z', vitals: { heart_rate_bpm: 70 } };
  assert.deepEqual(mergeReadings([newer], [older, newer]), [older, newer]);
});

test('missing readings create gaps instead of zero-valued measurements', () => {
  const path = sparkPath([70, null, 90], 50, 110);
  assert.equal((path.match(/M/g) ?? []).length, 2);
  assert.ok(!path.includes('L'));
});

test('history is bounded and ordered by measurement time', () => {
  const samples = Array.from({ length: 60 }, (_, i) => ({ device_id: 'd', ts: new Date(1760000000000 + i * 1000).toISOString() }));
  const merged = mergeReadings([], samples.reverse());
  assert.equal(merged.length, 48);
  assert.ok(Date.parse(merged[0].ts) < Date.parse(merged.at(-1).ts));
});
