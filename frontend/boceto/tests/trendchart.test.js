import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { trendChart, crossText } from '../js/trendchart.js';

const example = JSON.parse(readFileSync(new URL('../../../contracts/assessment.example.json', import.meta.url))).trends[0];

test('draws every point the engine fitted, and nothing else', () => {
  const html = trendChart(example, { levelName: (l) => ['Nominal', 'Watch', 'Alert', 'Critical'][l] });
  assert.equal((html.match(/class="tobserved"/g) ?? []).length, example.points.length);
  assert.match(html, /Glucose · 7 readings/);
  assert.match(html, /Reaches 99 mg\/dL \(Watch\) in about 1 more check/);
  assert.match(html, /−6 CHECKS/);
  assert.match(html, /\+7 CHECKS/);
});

test('sensor trends use seconds', () => {
  const t = { ...example, indicator: 'heart_rate_bpm', label: 'Heart rate', unit: 'bpm', basis: 'time', x_unit: 's',
    points: [[-12, 96], [-10, 98], [-8, 100], [-6, 102], [-4, 104], [-2, 106], [0, 108]],
    slope: 1, intercept: 108, horizon: 60, projected: 168, threshold: 120, threshold_level: 2, crosses_in: 12 };
  assert.equal(crossText(t), 'in 12 s');
  const html = trendChart(t, { levelName: () => 'Alert' });
  assert.match(html, /−60 S/);           // eje fijo: el último minuto
  assert.match(html, /\+60 S/);
  assert.match(html, /IN 60 S/);
});

test('a trend that does not cross says so', () => {
  const html = trendChart({ ...example, crosses_in: null }, { levelName: () => 'Watch' });
  assert.match(html, /Does not reach 99 mg\/dL within 7 checks/);
  assert.match(html, /NOT REACHED/);
});
