export const ROAD_DISTANCE_FACTOR = 1.35;
export const AVERAGE_SPEED_KMH = 15;
export const RANGE_RESERVE_RATIO = 0.8;

const toRadians = degrees => degrees * Math.PI / 180;

export function haversineKm(a, b) {
  const dLat = toRadians(b.lat - a.lat);
  const dLon = toRadians(b.lon - a.lon);
  const value = Math.sin(dLat / 2) ** 2
    + Math.cos(toRadians(a.lat)) * Math.cos(toRadians(b.lat)) * Math.sin(dLon / 2) ** 2;
  return 6371 * 2 * Math.atan2(Math.sqrt(value), Math.sqrt(1 - value));
}

export function assessStation(station, origin, remainingRangeKm) {
  const roadKm = haversineKm(origin, station) * ROAD_DISTANCE_FACTOR;
  return {
    ...station,
    roadKm,
    minutes: Math.max(2, Math.round(roadKm / AVERAGE_SPEED_KMH * 60)),
    reachable: roadKm <= remainingRangeKm * RANGE_RESERVE_RATIO,
  };
}

export function rankStations(stations, origin, remainingRangeKm) {
  return stations
    .map(station => assessStation(station, origin, remainingRangeKm))
    .sort((a, b) => a.minutes - b.minutes);
}

export function chooseBestStation(rankedStations) {
  return rankedStations.find(station => station.reachable) || rankedStations[0];
}
