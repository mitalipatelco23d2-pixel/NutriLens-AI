const NUTRIENT_LABELS = {
  energy_kj_100g: 'Energy',
  energy_kcal_100g: 'Energy',
  fat_100g: 'Total fat',
  saturated_fat_100g: 'Saturated fat',
  trans_fat_100g: 'Trans fat',
  carbohydrates_100g: 'Carbohydrates',
  sugars_100g: 'Sugars',
  fiber_100g: 'Fibre',
  proteins_100g: 'Protein',
  salt_100g: 'Salt',
  sodium_100g: 'Sodium',
}

function titleCase(value) {
  return String(value || '')
    .replaceAll('_', ' ')
    .replace(/\b\w/g, (character) => character.toUpperCase())
}

export function displayBasis(value) {
  const bases = {
    per_100g: 'Per 100 g',
    per_100ml: 'Per 100 ml',
    per_serving: 'Per serving',
    unknown: 'Basis unknown',
  }
  return bases[value] || titleCase(value || 'unknown')
}

export function formatNutrient(key, value, detail = {}) {
  const numeric = typeof value === 'number' ? value : Number(value)
  const isEnergy = key.includes('energy')
  const isSodium = key === 'sodium_100g'
  const unit = detail.unit || (key.includes('kcal') ? 'kcal' : key.includes('kj') ? 'kJ' : 'g')
  const displayValue = Number.isFinite(numeric)
    ? isSodium && numeric < 1
      ? `${Math.round(numeric * 1000)} mg`
      : `${Number(numeric.toFixed(isEnergy ? 0 : 2))} ${unit}`
    : 'Not available'
  return {
    key,
    label: NUTRIENT_LABELS[key] || titleCase(key),
    value: displayValue,
    basis: displayBasis(detail.basis),
  }
}

export function statusTone(status) {
  if (['available', 'success'].includes(status)) return 'positive'
  if (['partial', 'partial_success', 'insufficient_evidence'].includes(status)) return 'caution'
  if (['unavailable', 'failed', 'error'].includes(status)) return 'negative'
  return 'neutral'
}

export function probabilityEntries(probabilities) {
  return Object.entries(probabilities || {})
    .filter(([, value]) => Number.isFinite(Number(value)))
    .map(([label, value]) => ({ label, value: Number(value) }))
    .sort((a, b) => b.value - a.value)
}

export function sourceByCitation(sources) {
  return Object.fromEntries((sources || []).map((source) => [source.citation_id, source]))
}

export function safeSourceUrl(value) {
  try {
    const url = new URL(String(value))
    return url.protocol === 'https:' ? url.href : null
  } catch {
    return null
  }
}
