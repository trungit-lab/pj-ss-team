import test from 'node:test';
import assert from 'node:assert/strict';
import { assessStation, chooseBestStation, haversineKm, rankStations } from './fuel-ranking.js';

const origin = { lat: 21.0285, lon: 105.8542 };

test('haversine distance is zero for identical coordinates', () => {
  assert.equal(haversineKm(origin, origin), 0);
});

test('haversine distance is symmetric and plausible for Hanoi locations', () => {
  const other = { lat: 21.0173, lon: 105.8536 };
  assert.equal(haversineKm(origin, other), haversineKm(other, origin));
  assert.ok(haversineKm(origin, other) > 1 && haversineKm(origin, other) < 2);
});

test('station assessment applies road multiplier, time floor, and range reserve', () => {
  const station = { name: 'Near', lat: origin.lat, lon: origin.lon };
  const result = assessStation(station, origin, 10);
  assert.equal(result.roadKm, 0);
  assert.equal(result.minutes, 2);
  assert.equal(result.reachable, true);
  assert.equal(result.name, 'Near');
});

test('rankStations orders stations by estimated travel time', () => {
  const stations = [
    { name: 'Far', lat: 21.05, lon: 105.9 },
    { name: 'Near', lat: 21.028, lon: 105.855 },
    { name: 'Middle', lat: 21.035, lon: 105.87 },
  ];
  assert.deepEqual(rankStations(stations, origin, 50).map(s => s.name), ['Near', 'Middle', 'Far']);
});

test('chooseBestStation prefers the closest feasible station', () => {
  const ranked = [
    { name: 'Fast but out of range', minutes: 2, reachable: false },
    { name: 'Feasible', minutes: 9, reachable: true },
    { name: 'Slow feasible', minutes: 15, reachable: true },
  ];
  assert.equal(chooseBestStation(ranked).name, 'Feasible');
});

test('chooseBestStation falls back to fastest when all candidates exceed range', () => {
  const ranked = [{ name: 'Fastest', minutes: 5, reachable: false }, { name: 'Slower', minutes: 10, reachable: false }];
  assert.equal(chooseBestStation(ranked).name, 'Fastest');
  assert.equal(chooseBestStation([]), undefined);
});
