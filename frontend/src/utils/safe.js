export function asArray(value) {
  return Array.isArray(value) ? value : [];
}

export function asString(value, fallback = '') {
  return typeof value === 'string' ? value : fallback;
}

