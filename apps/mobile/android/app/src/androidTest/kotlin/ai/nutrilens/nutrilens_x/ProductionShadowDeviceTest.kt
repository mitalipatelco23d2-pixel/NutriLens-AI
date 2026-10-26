package ai.nutrilens.nutrilens_x

import android.graphics.BitmapFactory
import android.os.SystemClock
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import com.google.android.gms.tasks.Tasks
import com.google.mlkit.vision.common.InputImage
import com.google.mlkit.vision.text.Text
import com.google.mlkit.vision.text.TextRecognition
import com.google.mlkit.vision.text.latin.TextRecognizerOptions
import com.it_nomads.fluttersecurestorage.FlutterSecureStorage
import com.it_nomads.fluttersecurestorage.FlutterSecureStorageConfig
import com.it_nomads.fluttersecurestorage.SecurePreferencesCallback
import java.io.BufferedInputStream
import java.io.BufferedOutputStream
import java.io.DataOutputStream
import java.io.File
import java.net.HttpURLConnection
import java.net.URL
import java.security.MessageDigest
import java.util.UUID
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicReference
import org.json.JSONArray
import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test
import org.junit.runner.RunWith

/**
 * Headless authenticated production validation. The bearer token is decrypted
 * and used only inside the target application process; it is never logged or
 * written to the evidence report pulled by the host.
 */
@RunWith(AndroidJUnit4::class)
class ProductionShadowDeviceTest {
    @Test
    fun classifiesClientEvidenceAndCompletesIdempotentAuthoritativeScan() {
        val context = InstrumentationRegistry.getInstrumentation().targetContext
        val output = File(context.filesDir, "production-shadow-evidence.json")
        val report = JSONObject()
            .put("schema_version", "1.0.0")
            .put("environment", "production")
            .put("execution", "HEADLESS_ANDROID_INSTRUMENTATION")
            .put("token_exported", false)
            .put("fixture", "product3.jpg")
        try {
            val token = readSessionToken(context)
            assertTrue("Authenticated NutriLens session is required", token.isNotBlank())
            report.put("authenticated_session_present", true)

            val fixture = File(context.filesDir, "fixtures/product3.jpg")
            assertTrue("Missing internal milk fixture: ${fixture.absolutePath}", fixture.isFile)
            val fixtureBytes = fixture.readBytes()
            report.put("source_image_sha256", sha256(fixtureBytes))

            val bitmap = requireNotNull(BitmapFactory.decodeByteArray(fixtureBytes, 0, fixtureBytes.size))
            val recognizer = TextRecognition.getClient(TextRecognizerOptions.DEFAULT_OPTIONS)
            val evidence: JSONObject
            val clientOcrMs: Long
            try {
                val startedAt = SystemClock.elapsedRealtime()
                val recognized = Tasks.await(
                    recognizer.process(InputImage.fromBitmap(bitmap, 0)),
                    180,
                    TimeUnit.SECONDS,
                )
                clientOcrMs = SystemClock.elapsedRealtime() - startedAt
                evidence = JSONObject()
                    .put("client_inference_contract_version", "1.0.0")
                    .put("platform", "ANDROID")
                    .put("app_version", appVersion(context))
                    .put("source", "CLIENT_ANDROID_MLKIT")
                    .put("ocr_provider", "ML_KIT_TEXT_RECOGNITION_V2")
                    .put("ocr_provider_version", "16.0.1")
                    .put("detector_provider", JSONObject.NULL)
                    .put("detector_provider_version", JSONObject.NULL)
                    .put("cold_start", false)
                    .put("elapsed_ms", clientOcrMs)
                    .put("image_width", bitmap.width)
                    .put("image_height", bitmap.height)
                    .put("source_image_sha256", sha256(fixtureBytes))
                    .put("orientation_degrees", 0)
                    .put("text", recognized.text)
                    .put("blocks", evidenceBlocks(recognized, bitmap.width, bitmap.height))
                    .put("confidence", JSONObject.NULL)
            } finally {
                recognizer.close()
                bitmap.recycle()
            }
            report.put("client_ocr_ms", clientOcrMs)
            report.put("client_canonical_line_count", canonicalLineCount(evidence))

            val capabilities = getJson("$BASE_URL/api/v1/scan/client-inference/capabilities", token)
            report.put("capabilities_http_status", capabilities.status)
            report.put("capabilities", safeObject(capabilities.json))
            assertEquals("Client capabilities authentication failed", 200, capabilities.status)

            val classification = postMultipart(
                url = "$BASE_URL/api/v1/scan/client-evidence/classify",
                token = token,
                fields = mapOf("evidence_json" to evidence.toString()),
                fileField = "file",
                file = fixture,
            )
            report.put("classification_http_status", classification.status)
            report.put("classification_round_trip_ms", classification.elapsedMs)
            report.put("classification", safeObject(classification.json))
            assertEquals("Production client-evidence classification failed", 200, classification.status)
            assertTrue("Client evidence was rejected", classification.json.optBoolean("accepted"))
            assertTrue("Image digest binding failed", classification.json.optBoolean("image_binding_verified"))
            assertTrue(
                "Image dimension binding failed",
                classification.json.optBoolean("dimensions_binding_verified"),
            )

            val runId = instrumentationRunId()
            report.put("run_id", runId)
            val idempotencyKey = "android-shadow-$runId-${sha256(fixtureBytes).take(24)}"
            val accepted = postMultipart(
                url = "$BASE_URL/api/v1/scan/jobs/product",
                token = token,
                fields = mapOf("view_types" to "GENERAL", "languages" to "en"),
                fileField = "files",
                file = fixture,
                idempotencyKey = idempotencyKey,
            )
            report.put("job_accept_http_status", accepted.status)
            report.put("job_acknowledgement_ms", accepted.elapsedMs)
            report.put("accepted_job", safeJobEnvelope(accepted.json, includeResult = false))
            assertEquals("Authoritative production scan was not accepted", 202, accepted.status)
            val jobId = accepted.json.optString("job_id")
            assertTrue("Accepted production scan did not provide a job id", jobId.isNotBlank())

            val duplicate = postMultipart(
                url = "$BASE_URL/api/v1/scan/jobs/product",
                token = token,
                fields = mapOf("view_types" to "GENERAL", "languages" to "en"),
                fileField = "files",
                file = fixture,
                idempotencyKey = idempotencyKey,
            )
            val duplicateJobId = duplicate.json.optString("job_id")
            report.put("duplicate_http_status", duplicate.status)
            report.put("duplicate_acknowledgement_ms", duplicate.elapsedMs)
            report.put("duplicate_same_job_id", duplicateJobId == jobId)
            assertEquals("Duplicate submission was not safely acknowledged", 202, duplicate.status)
            assertEquals("Idempotency created duplicate inference", jobId, duplicateJobId)

            val polling = pollJob(jobId, token, report)
            report.put("final_job", safeJobEnvelope(polling.json, includeResult = true))
            report.put("poll_count", polling.pollCount)
            report.put("end_to_end_poll_ms", polling.elapsedMs)
            report.put("final_http_status", polling.status)
            assertEquals("Final job lookup failed", 200, polling.status)
            assertEquals("Production scan did not complete", "COMPLETE", polling.json.optString("status"))
            assertTrue("Completed production scan has no result", polling.json.optJSONObject("result") != null)

            val acceptance = productionAcceptance(polling.json, classification.json)
            report.put("acceptance", acceptance)
            assertTrue("Detector provenance is contradictory", !acceptance.getBoolean("contradictory_detector_state"))
            assertTrue("Authoritative nutrition basis is wrong", acceptance.getString("nutrition_basis") == "PER_100_ML")
            assertTrue("Authoritative nutrition rows are incomplete", acceptance.getInt("nutrition_row_count") >= 10)
            assertTrue("Explicit allergen evidence is missing", acceptance.getBoolean("explicit_allergen_text_present"))
            assertTrue("A nutrient decimal leaked into date extraction", acceptance.getInt("date_candidate_count") == 0)
            assertTrue("Unsupported brand noise remains", !acceptance.getBoolean("unsupported_brand_candidate_present"))
            assertTrue("Document-section noise remains in product candidates", !acceptance.getBoolean("section_noise_product_candidate_present"))
            report.put("completed", true)
        } catch (error: Throwable) {
            report.put("completed", false)
            report.put("failure_type", error.javaClass.simpleName)
            report.put("failure_message", safeFailureMessage(error.message))
            throw error
        } finally {
            output.writeText(report.toString(2))
        }
    }

    private fun readSessionToken(context: android.content.Context): String {
        val storage = FlutterSecureStorage(context)
        val config = FlutterSecureStorageConfig(HashMap())
        val latch = CountDownLatch(1)
        val failure = AtomicReference<Exception?>()
        storage.initialize(
            config,
            object : SecurePreferencesCallback<Void> {
                override fun onSuccess(result: Void?) = latch.countDown()

                override fun onError(error: Exception) {
                    failure.set(error)
                    latch.countDown()
                }
            },
        )
        assertTrue("Secure session store initialization timed out", latch.await(30, TimeUnit.SECONDS))
        failure.get()?.let { throw it }
        val prefixedKey = storage.addPrefixToKey("nutrilens_access_token")
        return storage.read(prefixedKey).orEmpty()
    }

    private fun appVersion(context: android.content.Context): String {
        val info = context.packageManager.getPackageInfo(context.packageName, 0)
        return "${info.versionName}+${info.longVersionCode}"
    }

    private fun instrumentationRunId(): String {
        val supplied = InstrumentationRegistry.getArguments().getString("run_id").orEmpty()
        val normalized = supplied.replace(Regex("[^A-Za-z0-9_-]"), "").take(24)
        return normalized.ifBlank { "default" }
    }

    private fun evidenceBlocks(text: Text, imageWidth: Int, imageHeight: Int): JSONArray =
        JSONArray().also { blocks ->
            text.textBlocks.forEach { block ->
                blocks.put(
                    JSONObject()
                        .put("text", block.text)
                        .put("bounds", bounds(block.boundingBox, imageWidth, imageHeight))
                        .put("recognized_languages", JSONArray())
                        .put(
                            "lines",
                            JSONArray().also { lines ->
                                block.lines.forEach { line ->
                                    lines.put(
                                        JSONObject()
                                            .put("text", line.text)
                                            .put("bounds", bounds(line.boundingBox, imageWidth, imageHeight))
                                            .put("recognized_languages", JSONArray())
                                            .put("confidence", JSONObject.NULL),
                                    )
                                }
                            },
                        ),
                )
            }
        }

    private fun bounds(rect: android.graphics.Rect?, imageWidth: Int, imageHeight: Int): Any = rect?.let {
        val left = it.left.coerceIn(0, imageWidth)
        val top = it.top.coerceIn(0, imageHeight)
        val right = it.right.coerceIn(0, imageWidth)
        val bottom = it.bottom.coerceIn(0, imageHeight)
        if (right <= left || bottom <= top) {
            JSONObject.NULL
        } else {
            JSONObject().put("left", left).put("top", top).put("right", right).put("bottom", bottom)
        }
    } ?: JSONObject.NULL

    private fun canonicalLineCount(evidence: JSONObject): Int {
        var count = 0
        val blocks = evidence.getJSONArray("blocks")
        for (index in 0 until blocks.length()) {
            count += blocks.getJSONObject(index).getJSONArray("lines").length()
        }
        return count
    }

    private fun postMultipart(
        url: String,
        token: String,
        fields: Map<String, String>,
        fileField: String,
        file: File,
        idempotencyKey: String? = null,
    ): HttpJson {
        val boundary = "NutriLens-${UUID.randomUUID()}"
        val connection = URL(url).openConnection() as HttpURLConnection
        connection.requestMethod = "POST"
        connection.connectTimeout = 30_000
        connection.readTimeout = 90_000
        connection.doOutput = true
        connection.setChunkedStreamingMode(64 * 1024)
        connection.setRequestProperty("Authorization", "Bearer $token")
        connection.setRequestProperty("Accept", "application/json")
        connection.setRequestProperty("Content-Type", "multipart/form-data; boundary=$boundary")
        idempotencyKey?.let { connection.setRequestProperty("Idempotency-Key", it) }
        val startedAt = SystemClock.elapsedRealtime()
        try {
            DataOutputStream(BufferedOutputStream(connection.outputStream)).use { output ->
                fields.forEach { (name, value) ->
                    output.writeUtf8("--$boundary\r\n")
                    output.writeUtf8("Content-Disposition: form-data; name=\"$name\"\r\n")
                    output.writeUtf8("Content-Type: text/plain; charset=UTF-8\r\n\r\n")
                    output.write(value.toByteArray(Charsets.UTF_8))
                    output.writeUtf8("\r\n")
                }
                output.writeUtf8("--$boundary\r\n")
                output.writeUtf8(
                    "Content-Disposition: form-data; name=\"$fileField\"; filename=\"product3.jpg\"\r\n",
                )
                output.writeUtf8("Content-Type: image/jpeg\r\n\r\n")
                file.inputStream().use { input -> input.copyTo(output, 64 * 1024) }
                output.writeUtf8("\r\n--$boundary--\r\n")
            }
            return response(connection, startedAt)
        } finally {
            connection.disconnect()
        }
    }

    private fun getJson(url: String, token: String): HttpJson {
        val connection = URL(url).openConnection() as HttpURLConnection
        connection.requestMethod = "GET"
        connection.connectTimeout = 20_000
        connection.readTimeout = 30_000
        connection.setRequestProperty("Authorization", "Bearer $token")
        connection.setRequestProperty("Accept", "application/json")
        val startedAt = SystemClock.elapsedRealtime()
        return try {
            response(connection, startedAt)
        } finally {
            connection.disconnect()
        }
    }

    private fun response(connection: HttpURLConnection, startedAt: Long): HttpJson {
        val status = connection.responseCode
        val stream = if (status in 200..399) connection.inputStream else connection.errorStream
        val body = stream?.let { BufferedInputStream(it).bufferedReader().use { reader -> reader.readText() } }
            .orEmpty()
        val json = try {
            JSONObject(body)
        } catch (_: Exception) {
            JSONObject().put("non_json_response", body.take(500))
        }
        return HttpJson(status, json, SystemClock.elapsedRealtime() - startedAt)
    }

    private fun pollJob(jobId: String, token: String, report: JSONObject): PollResult {
        val startedAt = SystemClock.elapsedRealtime()
        var count = 0
        var latest = HttpJson(0, JSONObject(), 0)
        val observedStates = JSONArray()
        while (SystemClock.elapsedRealtime() - startedAt < JOB_TIMEOUT_MS) {
            latest = getJson("$BASE_URL/api/v1/scan/jobs/${urlPath(jobId)}", token)
            count += 1
            if (latest.status == 429) {
                Thread.sleep(RATE_LIMIT_BACKOFF_MS)
                continue
            }
            val state = latest.json.optString("status", "UNKNOWN")
            if (observedStates.length() == 0 || observedStates.optString(observedStates.length() - 1) != state) {
                observedStates.put(state)
            }
            if (latest.status != 200 || state in setOf("COMPLETE", "FAILED", "TIMED_OUT")) break
            Thread.sleep(POLL_INTERVAL_MS)
        }
        report.put("observed_job_states", observedStates)
        return PollResult(latest.status, latest.json, count, SystemClock.elapsedRealtime() - startedAt)
    }

    private fun safeJobEnvelope(source: JSONObject, includeResult: Boolean): JSONObject = JSONObject().also { safe ->
        copyKeys(
            source,
            safe,
            "job_id",
            "status",
            "input_kind",
            "created_at",
            "started_at",
            "completed_at",
            "error_code",
            "error_message",
        )
        if (includeResult) source.optJSONObject("result")?.let { safe.put("result", safeScanResult(it)) }
    }

    private fun safeScanResult(source: JSONObject): JSONObject = JSONObject().also { safe ->
        copyKeys(
            source,
            safe,
            "contract_version",
            "pipeline_version",
            "scan_id",
            "status",
            "input_kind",
            "regions",
            "nutrition",
            "ingredients",
            "brand_candidates",
            "product_name_candidates",
            "date_candidates",
            "confidence_summary",
            "warnings",
            "manual_review_fields",
            "models",
            "timings",
            "images_retained",
            "eligible_for_training",
        )
    }

    private fun safeObject(source: JSONObject): JSONObject = JSONObject(source.toString())

    private fun copyKeys(source: JSONObject, target: JSONObject, vararg keys: String) {
        keys.forEach { key -> if (source.has(key)) target.put(key, source.opt(key)) }
    }

    private fun productionAcceptance(job: JSONObject, classification: JSONObject): JSONObject {
        val result = job.optJSONObject("result") ?: JSONObject()
        val warnings = result.optJSONArray("warnings") ?: JSONArray()
        val regions = result.optJSONArray("regions") ?: JSONArray()
        val warningText = (0 until warnings.length()).joinToString("\n") { warnings.optString(it) }
        var customModelRegion = false
        for (index in 0 until regions.length()) {
            if (regions.optJSONObject(index)?.optString("method") == "CUSTOM_MODEL") customModelRegion = true
        }
        val nutrition = result.optJSONObject("nutrition") ?: JSONObject()
        val ingredients = result.optJSONObject("ingredients") ?: JSONObject()
        val brands = result.optJSONArray("brand_candidates") ?: JSONArray()
        val products = result.optJSONArray("product_name_candidates") ?: JSONArray()
        val brandValues = (0 until brands.length()).mapNotNull { index ->
            brands.optJSONObject(index)?.optString("value")?.lowercase()
        }
        val productValues = (0 until products.length()).mapNotNull { index ->
            products.optJSONObject(index)?.optString("value")?.lowercase()
        }
        return JSONObject()
            .put("client_evidence_accepted", classification.optBoolean("accepted"))
            .put("image_binding_verified", classification.optBoolean("image_binding_verified"))
            .put("dimensions_binding_verified", classification.optBoolean("dimensions_binding_verified"))
            .put("nutrition_basis", nutrition.optString("basis", "UNKNOWN"))
            .put("nutrition_row_count", nutrition.optJSONArray("table_rows")?.length() ?: 0)
            .put("ingredient_region_isolated", ingredients.optString("raw_text").length in 1..500)
            .put("explicit_allergen_text_present", ingredients.optString("allergen_text").isNotBlank())
            .put("date_candidate_count", result.optJSONArray("date_candidates")?.length() ?: 0)
            .put("custom_model_region_present", customModelRegion)
            .put("model_not_cached_warning_present", warningText.contains("MODEL_NOT_CACHED"))
            .put(
                "unsupported_brand_candidate_present",
                brandValues.any { value ->
                    "nutrition" in value || "pasteurized" in value || "live bette" in value
                },
            )
            .put(
                "section_noise_product_candidate_present",
                productValues.any { value ->
                    "nutrition facts" in value ||
                        "nutrition information" in value ||
                        "matrientinformation" in value
                },
            )
            .put(
                "contradictory_detector_state",
                customModelRegion && warningText.contains("MODEL_NOT_CACHED"),
            )
    }

    private fun safeFailureMessage(message: String?): String = message.orEmpty()
        .replace(Regex("Bearer\\s+[A-Za-z0-9._~-]+", RegexOption.IGNORE_CASE), "Bearer [REDACTED]")
        .take(1_000)

    private fun sha256(bytes: ByteArray): String = MessageDigest.getInstance("SHA-256")
        .digest(bytes)
        .joinToString("") { byte -> "%02x".format(byte) }

    private fun urlPath(value: String): String = java.net.URLEncoder.encode(value, "UTF-8")

    private fun DataOutputStream.writeUtf8(value: String) = write(value.toByteArray(Charsets.UTF_8))

    private data class HttpJson(val status: Int, val json: JSONObject, val elapsedMs: Long)

    private data class PollResult(
        val status: Int,
        val json: JSONObject,
        val pollCount: Int,
        val elapsedMs: Long,
    )

    private companion object {
        const val BASE_URL = "https://api.nutrilensx.tech"
        const val POLL_INTERVAL_MS = 12_000L
        const val RATE_LIMIT_BACKOFF_MS = 60_000L
        const val JOB_TIMEOUT_MS = 8 * 60 * 1_000L
    }
}
