export const ACCEPTED_IMAGE_TYPES = [
  'image/jpeg',
  'image/png',
  'image/webp',
]

export const DEFAULT_MAX_UPLOAD_BYTES = 8 * 1024 * 1024


function configuredMaximum() {
  const value = Number(import.meta.env.VITE_MAX_UPLOAD_BYTES)

  return Number.isFinite(value) && value > 0
    ? value
    : DEFAULT_MAX_UPLOAD_BYTES
}


function apiBaseUrl() {
  return String(
    import.meta.env.VITE_API_BASE_URL || ''
  ).replace(/\/$/, '')
}


export function isAnalysisEnabled() {
  const value = String(
    import.meta.env.VITE_ANALYSIS_ENABLED ?? 'true',
  )
    .trim()
    .toLowerCase()

  return !['false', '0', 'off', 'no'].includes(value)
}


/* ============================================================
   FILE SIZE / IMAGE COMPRESSION
   ============================================================ */

export function formatBytes(bytes) {
  if (bytes < 1024) {
    return `${bytes} B`
  }

  if (bytes < 1024 * 1024) {
    return `${(bytes / 1024).toFixed(1)} KB`
  }

  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}


export function validateImage(file) {
  if (!file) {
    return 'Choose a food-label image to continue.'
  }

  if (!ACCEPTED_IMAGE_TYPES.includes(file.type)) {
    return 'Use a JPEG, PNG, or WEBP image.'
  }

  if (file.size === 0) {
    return 'The selected image is empty.'
  }

  /*
   * Do NOT reject large images here.
   *
   * Camera photos can be larger than 8 MB.
   * They will be compressed automatically before upload.
   */

  return null
}


/**
 * Compress an image when it is larger than the configured
 * maximum upload size.
 *
 * Small images are returned unchanged.
 *
 * Large camera photos are:
 *   1. Loaded in the browser
 *   2. Resized if necessary
 *   3. Converted to JPEG
 *   4. Compressed until they are <= 8 MB
 */
async function compressImage(
  file,
  maximum = configuredMaximum(),
) {
  if (file.size <= maximum) {
    return file
  }

  const imageUrl = URL.createObjectURL(file)

  try {
    const image = await new Promise((resolve, reject) => {
      const img = new Image()

      img.onload = () => resolve(img)

      img.onerror = () => reject(
        new Error(
          'Could not read the selected image.',
        ),
      )

      img.src = imageUrl
    })

    /*
     * Food-label OCR does not normally need
     * an extremely large camera image.
     */
    const MAX_DIMENSION = 2400

    let width = image.naturalWidth
    let height = image.naturalHeight

    if (!width || !height) {
      throw new Error(
        'Could not determine image dimensions.',
      )
    }

    /*
     * Resize while keeping the original aspect ratio.
     */
    if (
      width > MAX_DIMENSION ||
      height > MAX_DIMENSION
    ) {
      const scale = Math.min(
        MAX_DIMENSION / width,
        MAX_DIMENSION / height,
      )

      width = Math.max(
        1,
        Math.round(width * scale),
      )

      height = Math.max(
        1,
        Math.round(height * scale),
      )
    }

    const canvas = document.createElement('canvas')

    canvas.width = width
    canvas.height = height

    const context = canvas.getContext('2d')

    if (!context) {
      throw new Error(
        'Could not prepare the image for upload.',
      )
    }

    /*
     * Draw the image onto the canvas.
     */
    context.drawImage(
      image,
      0,
      0,
      width,
      height,
    )

    /*
     * Try progressively lower JPEG quality
     * until the image is <= maximum size.
     */
    let quality = 0.85
    let blob = null

    while (quality >= 0.40) {
      blob = await new Promise((resolve) => {
        canvas.toBlob(
          resolve,
          'image/jpeg',
          quality,
        )
      })

      if (
        blob &&
        blob.size <= maximum
      ) {
        break
      }

      quality -= 0.05
    }

    if (
      !blob ||
      blob.size > maximum
    ) {
      throw new Error(
        `The image could not be compressed below ${formatBytes(maximum)}. Please take a clearer, closer photo of the food label.`,
      )
    }

    return new File(
      [blob],
      'compressed-food-label.jpg',
      {
        type: 'image/jpeg',
        lastModified: Date.now(),
      },
    )
  } finally {
    URL.revokeObjectURL(imageUrl)
  }
}


/* ============================================================
   RESPONSE ADAPTER
   Current backend -> Team frontend response format
   ============================================================ */

function numberOrNull(value) {
  const number = Number(value)

  return Number.isFinite(number)
    ? number
    : null
}


function arrayOrEmpty(value) {
  return Array.isArray(value)
    ? value
    : []
}


/* ------------------------------------------------------------
   Nutrition
   ------------------------------------------------------------ */

function adaptNutrition(nutrition = {}) {
  const result = {}

  const mappings = [
    ['energy_kcal', 'energy_kcal_100g'],
    ['protein_g', 'proteins_100g'],
    ['carbohydrate_g', 'carbohydrates_100g'],
    ['sugar_g', 'sugars_100g'],
    ['fat_g', 'fat_100g'],
    ['saturated_fat_g', 'saturated_fat_100g'],
    ['trans_fat_g', 'trans_fat_100g'],
    ['fiber_g', 'fiber_100g'],
    ['salt_g', 'salt_100g'],
    ['sodium_mg', 'sodium_100g'],
    ['cholesterol_mg', 'cholesterol_100g'],
    ['calcium_mg', 'calcium_100g'],
  ]

  for (const [
    sourceKey,
    frontendKey,
  ] of mappings) {
    const value = numberOrNull(
      nutrition[sourceKey],
    )

    /*
     * Never convert missing nutrition to zero.
     */
    if (value !== null) {
      result[frontendKey] = value
    }
  }

  return result
}


function adaptNutritionDetails(nutrition = {}) {
  const details = {}

  const keys = [
    ['energy_kcal', 'energy_kcal_100g', 'kcal'],
    ['protein_g', 'proteins_100g', 'g'],
    ['carbohydrate_g', 'carbohydrates_100g', 'g'],
    ['sugar_g', 'sugars_100g', 'g'],
    ['fat_g', 'fat_100g', 'g'],
    ['saturated_fat_g', 'saturated_fat_100g', 'g'],
    ['trans_fat_g', 'trans_fat_100g', 'g'],
    ['fiber_g', 'fiber_100g', 'g'],
    ['salt_g', 'salt_100g', 'g'],
    ['sodium_mg', 'sodium_100g', 'mg'],
    ['cholesterol_mg', 'cholesterol_100g', 'mg'],
    ['calcium_mg', 'calcium_100g', 'mg'],
  ]

  for (const [
    sourceKey,
    frontendKey,
    unit,
  ] of keys) {
    const value = numberOrNull(
      nutrition[sourceKey],
    )

    if (value !== null) {
      details[frontendKey] = {
        value,
        unit,
        basis: nutrition.basis || 'unknown',
      }
    }
  }

  return details
}


/* ------------------------------------------------------------
   Health score
   ------------------------------------------------------------ */

function adaptHealth(
  healthScore = {},
  healthRisk = {},
  nutrition = {},
) {
  const score = numberOrNull(
    healthScore.health_score ??
      healthScore.score,
  )

  const category =
    healthScore.category ||
    healthScore.label ||
    healthScore.status ||
    null

  const riskLevel =
    healthRisk.risk_level ||
    healthRisk.predicted_class ||
    healthRisk.class ||
    null

  const probabilities =
    healthRisk.probabilities &&
    typeof healthRisk.probabilities === 'object'
      ? healthRisk.probabilities
      : {}

  const hasScore = score !== null

  const hasRisk =
    Boolean(riskLevel) &&
    Object.keys(probabilities).length > 0

  return {
    status:
      hasScore || hasRisk
        ? 'available'
        : 'unavailable',

    health_score:
      hasScore
        ? score
        : null,

    score_level: category,

    nutrition_score: {
      available: hasScore,

      value:
        hasScore
          ? score
          : null,

      basis:
        nutrition.basis ||
        'unknown',

      detail:
        hasScore
          ? `Calculated health score: ${score}/100`
          : 'Required nutrition data was not available.',

      reasons:
        Array.isArray(
          healthScore.reasons,
        )
          ? healthScore.reasons
          : [],

      warnings:
        Array.isArray(
          healthScore.warnings,
        )
          ? healthScore.warnings
          : [],

      missing_nutrients:
        Array.isArray(
          healthScore.missing_nutrients,
        )
          ? healthScore.missing_nutrients
          : [],
    },

    ingredient_risk: {
      available: hasRisk,

      risk_level: riskLevel,

      probabilities,

      detail:
        hasRisk
          ? 'Model prediction — not a medical safety assessment'
          : 'Ingredient-risk model output was not available.',
    },
  }
}


/* ------------------------------------------------------------
   Recommendations
   ------------------------------------------------------------ */

function adaptRecommendations(source) {
  if (!source) {
    return {
      status: 'unavailable',
      items: [],
      omissions: [],
      disclaimer: null,
    }
  }

  const items =
    Array.isArray(
      source.recommendations,
    )
      ? source.recommendations
      : Array.isArray(source.items)
        ? source.items
        : []

  const omissions =
    Array.isArray(source.omissions)
      ? source.omissions
      : []

  return {
    status:
      items.length > 0
        ? 'available'
        : 'unavailable',

    items,

    omissions,

    disclaimer:
      source.disclaimer ||
      null,
  }
}


/* ------------------------------------------------------------
   XAI
   ------------------------------------------------------------ */

function adaptModelAttribution(xai = {}) {
  const features =
    xai.top_features ||
    xai.features ||
    xai.feature_importance ||
    []

  return {
    status:
      Array.isArray(features) &&
      features.length
        ? 'available'
        : 'unavailable',

    features:
      Array.isArray(features)
        ? features
        : [],

    top_features:
      Array.isArray(features)
        ? features
        : [],

    method:
      xai.method ||
      'Random Forest feature importance',

    disclaimer:
      xai.disclaimer ||
      'Feature importance indicates model contribution, not causation.',
  }
}


/* ------------------------------------------------------------
   Main adapter
   ------------------------------------------------------------ */

function adaptBackendResponse(payload) {
  const backendAnalysis =
    payload?.analysis || {}

  const nlp =
    backendAnalysis.nlp || {}

  const healthRisk =
    backendAnalysis.health_risk || {}

  const healthScore =
    backendAnalysis.health_score || {}

  const xai =
    backendAnalysis.xai || {}

  const backendRecommendations =
    backendAnalysis.recommendations

  const nutrition =
    nlp.nutrition || {}

  const ingredients =
    nlp.normalized_ingredients?.length
      ? nlp.normalized_ingredients
      : arrayOrEmpty(nlp.ingredients)

  const allergens =
    arrayOrEmpty(nlp.allergens)

  const additives =
    arrayOrEmpty(nlp.additives)

  const health = adaptHealth(
    healthScore,
    healthRisk,
    nutrition,
  )

  const recommendations =
    adaptRecommendations(
      backendRecommendations,
    )

  const modelAttribution =
    adaptModelAttribution(xai)

  const ocr = {
    engine: 'EasyOCR',
    confidence: null,
    rotation: null,
  }

  const integrations = {
    ocr: {
      status: 'available',
      provider: 'EasyOCR',
    },

    nlp: {
      status: 'available',
      provider: 'NutriLens NLP',
    },

    ml: {
      status: 'available',
      provider: 'Random Forest + TF-IDF',
    },

    xai: {
      status:
        modelAttribution.features.length > 0
          ? 'available'
          : 'unavailable',

      provider:
        'Random Forest feature importance',
    },
  }

  const explanation = {
    status:
      recommendations.items.length ||
      modelAttribution.features.length
        ? 'available'
        : 'unavailable',

    recommendations,

    knowledge_base: {
      status: 'unavailable',

      matches: [],

      detail:
        'No separate verified knowledge-base result was returned by the current API.',
    },

    model_attribution:
      modelAttribution,

    rag: {
      status: 'unavailable',

      answer: null,

      sources: [],

      disclaimer:
        'No separate source-grounded generative answer was returned by the current API.',
    },
  }

  return {
    ...payload,

    request_id:
      payload.request_id ||
      null,

    status:
      payload.status ||
      'success',

    analysis: {
      ...backendAnalysis,

      ingredients,

      normalized_ingredients:
        arrayOrEmpty(
          nlp.normalized_ingredients,
        ),

      allergens,

      additives,

      nutrition,

      nutrition_details:
        adaptNutritionDetails(
          nutrition,
        ),

      nutrition_values:
        adaptNutrition(
          nutrition,
        ),

      basis:
        nutrition.basis ||
        'unknown',

      integration: {
        status: 'available',
      },

      ingredient_quality: {
        status:
          ingredients.length > 0
            ? 'available'
            : 'unavailable',

        reasons:
          ingredients.length > 0
            ? [
                'Ingredients were extracted and normalized from OCR text.',
              ]
            : [],
      },
    },

    health,

    explanation,

    ocr,

    integrations,

    warnings: [],

    ocr_text:
      payload.ocr_text ||
      '',
  }
}


/* ============================================================
   API REQUEST
   ============================================================ */

export async function analyzeImage(
  file,
  fetchImplementation = fetch,
) {
  if (!isAnalysisEnabled()) {
    throw new Error(
      'Image analysis is disabled by the application configuration.',
    )
  }

  /*
   * Validate file type/content.
   *
   * Large files are intentionally NOT rejected here.
   */
  const validationError =
    validateImage(file)

  if (validationError) {
    throw new Error(validationError)
  }

  /*
   * Automatically compress large camera photos.
   */
  let uploadFile

  try {
    uploadFile = await compressImage(
      file,
      configuredMaximum(),
    )
  } catch (error) {
    throw new Error(
      error instanceof Error
        ? error.message
        : 'Could not prepare the image for upload.',
    )
  }

  /*
   * Safety check:
   * the final file must not exceed the
   * configured maximum.
   */
  if (
    uploadFile.size >
    configuredMaximum()
  ) {
    throw new Error(
      `The image must be smaller than ${formatBytes(configuredMaximum())}.`,
    )
  }

  const body = new FormData()

  /*
   * Current FastAPI endpoint expects "file".
   */
  body.append(
    'file',
    uploadFile,
  )

  let response

  try {
    response =
      await fetchImplementation(
        `${apiBaseUrl()}/api/v1/analyze`,
        {
          method: 'POST',
          body,
        },
      )
  } catch {
    throw new Error(
      'The analysis service could not be reached. Check that the backend is running.',
    )
  }

  let payload

  try {
    payload =
      await response.json()
  } catch {
    throw new Error(
      `The analysis service returned an unreadable response (HTTP ${response.status}).`,
    )
  }

  if (!response.ok) {
    throw new Error(
      payload?.error?.message ||
        payload?.detail ||
        `Analysis failed with HTTP ${response.status}.`,
    )
  }

  return adaptBackendResponse(
    payload,
  )
}
