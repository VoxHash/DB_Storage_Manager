package dev.voxhash.dsmcompanion

import org.json.JSONObject
import java.io.BufferedReader
import java.io.InputStreamReader
import java.net.HttpURLConnection
import java.net.URL
import java.nio.charset.StandardCharsets

/**
 * Minimal HTTP client for the desktop REST companion (stdlib HttpURLConnection).
 * Read-only glance endpoints; no Google Play Services.
 */
class ApiClient(
    private val baseUrl: String,
    private val bearerToken: String,
) {
    data class Result(val code: Int, val body: String)

    fun health(): Result = get("/api/v1/health", auth = false)

    fun connections(): Result = get("/api/v1/connections", auth = true)

    fun backups(): Result = get("/api/v1/backups", auth = true)

    fun info(): Result = get("/api/v1/info", auth = true)

    private fun get(path: String, auth: Boolean): Result {
        val url = URL(baseUrl.trimEnd('/') + path)
        val conn = (url.openConnection() as HttpURLConnection).apply {
            requestMethod = "GET"
            connectTimeout = 8_000
            readTimeout = 15_000
            setRequestProperty("Accept", "application/json")
            if (auth && bearerToken.isNotBlank()) {
                setRequestProperty("Authorization", "Bearer $bearerToken")
            }
        }
        return try {
            val code = conn.responseCode
            val stream = if (code in 200..299) conn.inputStream else conn.errorStream
            val body = stream?.use { input ->
                BufferedReader(InputStreamReader(input, StandardCharsets.UTF_8)).readText()
            } ?: ""
            Result(code, pretty(body))
        } finally {
            conn.disconnect()
        }
    }

    private fun pretty(raw: String): String {
        if (raw.isBlank()) return raw
        return try {
            JSONObject(raw).toString(2)
        } catch (_: Exception) {
            raw
        }
    }
}
