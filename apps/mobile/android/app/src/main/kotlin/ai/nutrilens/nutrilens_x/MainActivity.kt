package ai.nutrilens.nutrilens_x

import android.graphics.BitmapFactory
import android.os.SystemClock
import com.google.mlkit.vision.common.InputImage
import com.google.mlkit.vision.text.Text
import com.google.mlkit.vision.text.TextRecognition
import com.google.mlkit.vision.text.TextRecognizer
import com.google.mlkit.vision.text.latin.TextRecognizerOptions
import io.flutter.embedding.android.FlutterFragmentActivity
import io.flutter.embedding.engine.FlutterEngine
import io.flutter.plugin.common.MethodCall
import io.flutter.plugin.common.MethodChannel
import java.security.MessageDigest
import java.util.concurrent.atomic.AtomicBoolean

class MainActivity : FlutterFragmentActivity() {
    private var inferenceChannel: MethodChannel? = null
    private var textRecognizer: TextRecognizer? = null
    private val firstRecognition = AtomicBoolean(true)

    override fun configureFlutterEngine(flutterEngine: FlutterEngine) {
        super.configureFlutterEngine(flutterEngine)
        inferenceChannel = MethodChannel(
            flutterEngine.dartExecutor.binaryMessenger,
            CLIENT_INFERENCE_CHANNEL,
        ).also { channel ->
            channel.setMethodCallHandler(::handleClientInferenceCall)
        }
    }

    override fun cleanUpFlutterEngine(flutterEngine: FlutterEngine) {
        inferenceChannel?.setMethodCallHandler(null)
        inferenceChannel = null
        textRecognizer?.close()
        textRecognizer = null
        super.cleanUpFlutterEngine(flutterEngine)
    }

    private fun handleClientInferenceCall(call: MethodCall, result: MethodChannel.Result) {
        when (call.method) {
            "recognizeText" -> recognizeText(call, result)
            else -> result.notImplemented()
        }
    }

    private fun recognizeText(call: MethodCall, result: MethodChannel.Result) {
        val bytes = call.argument<ByteArray>("bytes")
        if (bytes == null || bytes.isEmpty()) {
            result.error("INVALID_IMAGE", "Image bytes are required.", null)
            return
        }
        if (bytes.size > MAX_IMAGE_BYTES) {
            result.error("IMAGE_TOO_LARGE", "Image exceeds the 20 MiB on-device limit.", null)
            return
        }

        val boundsOptions = BitmapFactory.Options().apply { inJustDecodeBounds = true }
        BitmapFactory.decodeByteArray(bytes, 0, bytes.size, boundsOptions)
        val width = boundsOptions.outWidth
        val height = boundsOptions.outHeight
        if (width <= 0 || height <= 0) {
            result.error("INVALID_IMAGE", "Image could not be decoded.", null)
            return
        }
        if (width > MAX_IMAGE_SIDE || height > MAX_IMAGE_SIDE || width.toLong() * height > MAX_IMAGE_PIXELS) {
            result.error("IMAGE_DIMENSIONS_UNSAFE", "Image dimensions exceed the on-device safety limit.", null)
            return
        }

        val bitmap = BitmapFactory.decodeByteArray(bytes, 0, bytes.size)
        if (bitmap == null) {
            result.error("INVALID_IMAGE", "Image could not be decoded.", null)
            return
        }

        val coldStart = firstRecognition.getAndSet(false)
        val startedAt = SystemClock.elapsedRealtime()
        val image = InputImage.fromBitmap(bitmap, 0)
        val recognizer = textRecognizer ?: TextRecognition
            .getClient(TextRecognizerOptions.DEFAULT_OPTIONS)
            .also { textRecognizer = it }
        recognizer.process(image)
            .addOnSuccessListener { recognized ->
                val elapsed = SystemClock.elapsedRealtime() - startedAt
                val payload = mapOf(
                    "client_inference_contract_version" to "1.0.0",
                    "platform" to "ANDROID",
                    "app_version" to BuildConfig.VERSION_NAME,
                    "source" to "CLIENT_ANDROID_MLKIT",
                    "ocr_provider" to "ML_KIT_TEXT_RECOGNITION_V2",
                    "ocr_provider_version" to "16.0.1",
                    "detector_provider" to null,
                    "detector_provider_version" to null,
                    "cold_start" to coldStart,
                    "elapsed_ms" to elapsed,
                    "image_width" to width,
                    "image_height" to height,
                    "source_image_sha256" to sha256(bytes),
                    "orientation_degrees" to 0,
                    "text" to recognized.text,
                    "blocks" to recognized.textBlocks.map { block ->
                        blockPayload(block, width, height)
                    },
                    // ML Kit Text Recognition v2 does not expose a numeric
                    // confidence for this API. Do not manufacture one.
                    "confidence" to null,
                )
                result.success(payload)
            }
            .addOnFailureListener { error ->
                result.error("MLKIT_OCR_FAILED", error.message ?: "On-device OCR failed.", null)
            }
            .addOnCompleteListener { bitmap.recycle() }
    }

    private fun blockPayload(
        block: Text.TextBlock,
        imageWidth: Int,
        imageHeight: Int,
    ): Map<String, Any?> = mapOf(
        "text" to block.text,
        "bounds" to boundsPayload(block.boundingBox, imageWidth, imageHeight),
        "corner_points" to block.cornerPoints?.map { point ->
            mapOf("x" to point.x, "y" to point.y)
        },
        "recognized_languages" to block.recognizedLanguage
            .takeIf { it.isNotBlank() }
            ?.let { listOf(it) }
            .orEmpty(),
        "lines" to block.lines.map { line ->
            mapOf(
                "text" to line.text,
                "bounds" to boundsPayload(line.boundingBox, imageWidth, imageHeight),
                "corner_points" to line.cornerPoints?.map { point ->
                    mapOf("x" to point.x, "y" to point.y)
                },
                "recognized_languages" to line.recognizedLanguage
                    .takeIf { it.isNotBlank() }
                    ?.let { listOf(it) }
                    .orEmpty(),
                "confidence" to null,
            )
        },
    )

    private fun boundsPayload(
        rect: android.graphics.Rect?,
        imageWidth: Int,
        imageHeight: Int,
    ): Map<String, Int>? = rect?.let {
        val left = it.left.coerceIn(0, imageWidth)
        val top = it.top.coerceIn(0, imageHeight)
        val right = it.right.coerceIn(0, imageWidth)
        val bottom = it.bottom.coerceIn(0, imageHeight)
        if (right <= left || bottom <= top) {
            null
        } else {
            mapOf("left" to left, "top" to top, "right" to right, "bottom" to bottom)
        }
    }

    private fun sha256(bytes: ByteArray): String = MessageDigest
        .getInstance("SHA-256")
        .digest(bytes)
        .joinToString("") { byte -> "%02x".format(byte) }

    companion object {
        private const val CLIENT_INFERENCE_CHANNEL = "ai.nutrilens/client_inference"
        private const val MAX_IMAGE_BYTES = 20 * 1024 * 1024
        private const val MAX_IMAGE_SIDE = 8192
        private const val MAX_IMAGE_PIXELS = 40_000_000L
    }
}
