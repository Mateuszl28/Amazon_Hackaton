package com.whatdidimiss.tv

import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import org.json.JSONObject
import java.io.IOException
import java.util.concurrent.TimeUnit

data class Title(val id: String, val name: String, val kind: String, val videoUrl: String)

data class Character(val id: String, val name: String, val firstSeenS: Double)

data class Answer(
    val headline: String,
    val text: String,
    val character: Character?,
    val positionS: Double,
    val durationS: Double,
    val markers: List<KnowledgeBarView.Marker>,
    val range: ClosedFloatingPointRange<Double>?,
)

object CompanionApi {
    private val baseUrl = BuildConfig.COMPANION_URL.trimEnd('/')
    private val json = "application/json; charset=utf-8".toMediaType()
    private val http = OkHttpClient.Builder()
        .connectTimeout(5, TimeUnit.SECONDS)
        .readTimeout(30, TimeUnit.SECONDS)
        .build()

    val endpoint: String get() = baseUrl

    suspend fun titles(): List<Title> = withContext(Dispatchers.IO) {
        val body = execute(Request.Builder().url("$baseUrl/titles").build())
        val arr = body.getJSONArray("titles")
        (0 until arr.length()).map { i ->
            val t = arr.getJSONObject(i)
            val url = t.optString("video_url")
            // Relative URLs are served by the companion backend itself (local media on the LAN).
            Title(t.getString("title_id"), t.optString("title"), t.optString("kind"),
                if (url.startsWith("/")) baseUrl + url else url)
        }
    }

    suspend fun ask(
        titleId: String,
        positionS: Double,
        mode: String,
        question: String? = null,
        frameJpegB64: String? = null,
        fromS: Double? = null,
    ): Answer = withContext(Dispatchers.IO) {
        val payload = JSONObject()
            .put("title_id", titleId)
            .put("position_s", positionS)
            .put("mode", mode)
        question?.let { payload.put("question", it) }
        frameJpegB64?.let { payload.put("frame_jpeg_b64", it) }
        fromS?.let { payload.put("from_s", it) }
        val body = execute(
            Request.Builder().url("$baseUrl/ask").post(payload.toString().toRequestBody(json)).build()
        )
        Answer(
            headline = body.optString("headline"),
            text = body.optString("answer"),
            character = body.optJSONObject("character")?.let {
                Character(it.getString("id"), it.getString("name"), it.getDouble("first_seen"))
            },
            positionS = body.optDouble("position_s", positionS),
            durationS = body.optDouble("duration_s", 0.0),
            markers = body.optJSONArray("markers")?.let { arr ->
                (0 until arr.length()).map { i ->
                    val m = arr.getJSONObject(i)
                    KnowledgeBarView.Marker(m.getDouble("t"), m.getString("kind"))
                }
            }.orEmpty(),
            range = body.optJSONObject("range")?.let { it.getDouble("from")..it.getDouble("to") },
        )
    }

    private fun execute(request: Request): JSONObject =
        http.newCall(request).execute().use { resp ->
            val text = resp.body?.string().orEmpty()
            if (!resp.isSuccessful) throw IOException("HTTP ${resp.code}: $text")
            JSONObject(text)
        }
}
