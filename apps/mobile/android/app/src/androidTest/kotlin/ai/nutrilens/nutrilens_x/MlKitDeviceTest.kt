package ai.nutrilens.nutrilens_x

import android.graphics.BitmapFactory
import android.graphics.Matrix
import android.os.SystemClock
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import com.google.android.gms.tasks.Tasks
import com.google.mlkit.vision.common.InputImage
import com.google.mlkit.vision.text.Text
import com.google.mlkit.vision.text.TextRecognition
import com.google.mlkit.vision.text.TextRecognizer
import com.google.mlkit.vision.text.latin.TextRecognizerOptions
import java.io.File
import java.security.MessageDigest
import java.util.concurrent.TimeUnit
import org.json.JSONArray
import org.json.JSONObject
import org.junit.Assert.assertTrue
import org.junit.Test
import org.junit.runner.RunWith

/**
 * Real-device/emulator acceptance harness for the same bundled ML Kit engine
 * used by MainActivity. Fixtures are pushed into externalFilesDir/fixtures by
 * the validation script, so test images never become production APK assets.
 */
@RunWith(AndroidJUnit4::class)
class MlKitDeviceTest {
    @Test
    fun recognizesPushedNutritionFixturesAndRecordsColdWarmEvidence() {
        val context = InstrumentationRegistry.getInstrumentation().targetContext
        val fixtureDirectory = File(context.filesDir, "fixtures")
        val fixtures = fixtureDirectory.listFiles()
            ?.filter { it.isFile && it.extension.lowercase() in setOf("jpg", "jpeg", "png") }
            ?.sortedWith(compareBy({ if (it.name.equals("product3.jpg", ignoreCase = true)) 0 else 1 }, { it.name }))
            .orEmpty()
        assertTrue("Push at least one fixture into ${fixtureDirectory.absolutePath}", fixtures.isNotEmpty())

        val initStartedAt = SystemClock.elapsedRealtime()
        val recognizer = TextRecognition.getClient(TextRecognizerOptions.DEFAULT_OPTIONS)
        val recognizerInitMs = SystemClock.elapsedRealtime() - initStartedAt
        val fixtureResults = JSONArray()

        try {
            fixtures.forEach { fixture ->
                val first = recognize(fixture, recognizer)
                val result = JSONObject()
                    .put("fixture", fixture.name)
                    .put("source_image_sha256", sha256(fixture.readBytes()))
                    .put("recognizer_init_ms", recognizerInitMs)
                    .put("cold", first)

                if (fixture.name.equals("product3.jpg", ignoreCase = true)) {
                    val warm = recognize(fixture, recognizer)
                    result.put("warm", warm)
                    val normalizedText = first.getString("text").lowercase()
                    val expectedAnchors = listOf(
                        "milk",
                        "nutrition",
                        "sodium",
                        "calcium",
                        "sugar",
                    )
                    val matchedAnchors = expectedAnchors.filter(normalizedText::contains)
                    result.put("expected_anchor_matches", JSONArray(matchedAnchors))
                    assertTrue(
                        "Milk fixture should preserve multiple useful nutrition anchors; found $matchedAnchors",
                        matchedAnchors.size >= 3,
                    )
                }

                assertTrue("OCR text must not be empty for ${fixture.name}", first.getString("text").length > 40)
                assertTrue("OCR blocks must be present for ${fixture.name}", first.getJSONArray("blocks").length() > 0)
                fixtureResults.put(result)
            }
        } finally {
            recognizer.close()
        }

        val report = JSONObject()
            .put("client_inference_contract_version", "1.0.0")
            .put("platform", "ANDROID")
            .put("source", "CLIENT_ANDROID_MLKIT")
            .put("ocr_provider", "ML_KIT_TEXT_RECOGNITION_V2")
            .put("ocr_provider_version", "16.0.1")
            .put("fixtures", fixtureResults)
        File(context.filesDir, "mlkit-device-evidence.json")
            .writeText(report.toString(2))
    }

    private fun recognize(fixture: File, recognizer: TextRecognizer): JSONObject {
        val decodeStartedAt = SystemClock.elapsedRealtime()
        val decodedBitmap = requireNotNull(BitmapFactory.decodeFile(fixture.absolutePath)) {
            "Unable to decode ${fixture.absolutePath}"
        }
        val transformation = when {
            fixture.name.startsWith("rotate_", ignoreCase = true) -> "ROTATE_90"
            fixture.name.startsWith("blur_", ignoreCase = true) -> "MODERATE_DOWNSCALE_UPSCALE"
            else -> "NONE"
        }
        val bitmap = when (transformation) {
            "ROTATE_90" -> decodedBitmap.let { source ->
                val matrix = Matrix().apply { postRotate(90f) }
                android.graphics.Bitmap.createBitmap(source, 0, 0, source.width, source.height, matrix, true)
            }
            "MODERATE_DOWNSCALE_UPSCALE" -> {
                val reduced = android.graphics.Bitmap.createScaledBitmap(
                    decodedBitmap,
                    (decodedBitmap.width / 3).coerceAtLeast(1),
                    (decodedBitmap.height / 3).coerceAtLeast(1),
                    true,
                )
                android.graphics.Bitmap.createScaledBitmap(
                    reduced,
                    decodedBitmap.width,
                    decodedBitmap.height,
                    true,
                ).also { reduced.recycle() }
            }
            else -> decodedBitmap
        }
        if (bitmap !== decodedBitmap && !decodedBitmap.isRecycled) {
            decodedBitmap.recycle()
        }
        val decodeMs = SystemClock.elapsedRealtime() - decodeStartedAt
        return try {
            val inferenceStartedAt = SystemClock.elapsedRealtime()
            val text = Tasks.await(
                recognizer.process(InputImage.fromBitmap(bitmap, 0)),
                180,
                TimeUnit.SECONDS,
            )
            val inferenceMs = SystemClock.elapsedRealtime() - inferenceStartedAt
            JSONObject()
                .put("image_width", bitmap.width)
                .put("image_height", bitmap.height)
                .put("orientation_degrees", 0)
                .put("test_transformation", transformation)
                .put("image_decode_ms", decodeMs)
                .put("ocr_inference_ms", inferenceMs)
                .put("text", text.text)
                .put("blocks", blocksPayload(text, bitmap.width, bitmap.height))
        } finally {
            bitmap.recycle()
        }
    }

    private fun blocksPayload(text: Text, imageWidth: Int, imageHeight: Int): JSONArray = JSONArray().also { blocks ->
        text.textBlocks.forEach { block ->
            blocks.put(
                JSONObject()
                    .put("text", block.text)
                    .put("bounds", boundsPayload(block.boundingBox, imageWidth, imageHeight))
                    .put("lines", JSONArray().also { lines ->
                        block.lines.forEach { line ->
                            lines.put(
                                JSONObject()
                                    .put("text", line.text)
                                    .put("bounds", boundsPayload(line.boundingBox, imageWidth, imageHeight)),
                            )
                        }
                    }),
            )
        }
    }

    private fun boundsPayload(
        rect: android.graphics.Rect?,
        imageWidth: Int,
        imageHeight: Int,
    ): Any = rect?.let {
        val left = it.left.coerceIn(0, imageWidth)
        val top = it.top.coerceIn(0, imageHeight)
        val right = it.right.coerceIn(0, imageWidth)
        val bottom = it.bottom.coerceIn(0, imageHeight)
        if (right <= left || bottom <= top) {
            JSONObject.NULL
        } else {
            JSONObject()
                .put("left", left)
                .put("top", top)
                .put("right", right)
                .put("bottom", bottom)
        }
    } ?: JSONObject.NULL

    private fun sha256(bytes: ByteArray): String = MessageDigest
        .getInstance("SHA-256")
        .digest(bytes)
        .joinToString("") { byte -> "%02x".format(byte) }
}
