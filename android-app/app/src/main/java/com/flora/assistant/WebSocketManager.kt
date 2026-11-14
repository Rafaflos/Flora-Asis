package com.flora.assistant

import android.os.Handler
import android.os.Looper
import android.util.Log
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.Response
import okhttp3.WebSocket
import okhttp3.WebSocketListener
import okio.ByteString.Companion.toByteString
import org.json.JSONObject
import java.util.concurrent.TimeUnit
import kotlin.math.min

/** Acción crítica en espera de que el usuario la apruebe (tarjeta de confirmación). */
data class ConfirmationRequest(
    val actionId: String,
    val tool: String,
    val summary: String,
    val origin: String,
    val expiresInSeconds: Int,
)

/** Orden del Cerebro Central para ejecutar algo nativo en este teléfono. */
data class DeviceAction(
    val actionId: String,
    val action: String,
    val params: JSONObject,
    val confirmed: Boolean,
)

/**
 * Cliente WebSocket hacia el Cerebro Central (la Mac en la red privada).
 * Reconecta solo, con espera exponencial. Los callbacks llegan en el hilo principal.
 */
class WebSocketManager(
    private val url: String,
    private val token: String,
    private val deviceId: String,
    private val listener: Listener,
) {
    interface Listener {
        fun onConnectionChanged(connected: Boolean)
        fun onTranscript(text: String) {}
        fun onReply(text: String)
        fun onConfirmationRequest(request: ConfirmationRequest)
        fun onConfirmationResolved(actionId: String, approved: Boolean, detail: String)
        fun onExecuteAction(action: DeviceAction)
        fun onError(detail: String) {}
    }

    private val client = OkHttpClient.Builder()
        .pingInterval(20, TimeUnit.SECONDS)
        .readTimeout(0, TimeUnit.MILLISECONDS)
        .build()
    private val main = Handler(Looper.getMainLooper())

    @Volatile private var socket: WebSocket? = null
    @Volatile private var ready = false
    @Volatile private var closedByUser = false
    private var attempt = 0

    val isReady: Boolean get() = ready

    fun connect() {
        closedByUser = false
        openSocket()
    }

    fun disconnect() {
        closedByUser = true
        main.removeCallbacksAndMessages(null)
        socket?.close(1000, "bye")
        socket = null
        ready = false
    }

    // ── Envíos ──

    fun sendUtterance(text: String): Boolean =
        send(JSONObject().put("type", "utterance").put("text", text))

    /** PCM16 mono 16 kHz. Llama a [sendAudioEnd] al terminar la frase. */
    fun sendAudioChunk(pcm: ByteArray, length: Int = pcm.size): Boolean =
        ready && socket?.send(pcm.toByteString(0, length)) == true

    fun sendAudioEnd(): Boolean = send(JSONObject().put("type", "audio_end"))

    fun sendConfirmation(actionId: String, approved: Boolean): Boolean =
        send(JSONObject().put("type", "confirmation").put("action_id", actionId).put("approved", approved))

    fun sendActionResult(actionId: String, ok: Boolean, detail: String): Boolean =
        send(
            JSONObject().put("type", "action_result").put("action_id", actionId)
                .put("ok", ok).put("detail", detail)
        )

    private fun send(json: JSONObject): Boolean = ready && socket?.send(json.toString()) == true

    // ── Conexión ──

    private fun openSocket() {
        socket = client.newWebSocket(Request.Builder().url(url).build(), SocketListener())
    }

    private fun scheduleReconnect() {
        if (closedByUser) return
        val delayMs = min(30_000L, 1_000L shl min(attempt, 5))
        attempt++
        main.postDelayed({ if (!closedByUser) openSocket() }, delayMs)
    }

    private inner class SocketListener : WebSocketListener() {
        override fun onOpen(webSocket: WebSocket, response: Response) {
            // El token viaja en el primer mensaje, no en la URL, para que no quede en logs.
            webSocket.send(
                JSONObject().put("type", "hello").put("token", token)
                    .put("device_id", deviceId).put("kind", "android").toString()
            )
        }

        override fun onMessage(webSocket: WebSocket, text: String) {
            val msg = try {
                JSONObject(text)
            } catch (e: Exception) {
                return
            }
            main.post { dispatch(msg) }
        }

        override fun onClosed(webSocket: WebSocket, code: Int, reason: String) {
            if (code == 4401) {
                Log.e(TAG, "Token rechazado por el backend")
                closedByUser = true
                main.post { listener.onError("Token rechazado: revisa flora.token") }
            }
            handleDrop(webSocket)
        }

        override fun onFailure(webSocket: WebSocket, t: Throwable, response: Response?) {
            Log.w(TAG, "Conexión caída: ${t.message}")
            handleDrop(webSocket)
        }

        private fun handleDrop(webSocket: WebSocket) {
            if (socket !== webSocket) return
            socket = null
            if (ready) {
                ready = false
                main.post { listener.onConnectionChanged(false) }
            }
            scheduleReconnect()
        }
    }

    private fun dispatch(msg: JSONObject) {
        when (msg.optString("type")) {
            "ready" -> {
                ready = true
                attempt = 0
                listener.onConnectionChanged(true)
            }
            "transcript" -> listener.onTranscript(msg.optString("text"))
            "reply" -> listener.onReply(msg.optString("text"))
            "confirmation_request" -> listener.onConfirmationRequest(
                ConfirmationRequest(
                    actionId = msg.getString("action_id"),
                    tool = msg.optString("tool"),
                    summary = msg.optString("summary"),
                    origin = msg.optString("origin"),
                    expiresInSeconds = msg.optInt("expires_in", 120),
                )
            )
            "confirmation_resolved" -> listener.onConfirmationResolved(
                msg.getString("action_id"), msg.optBoolean("approved"), msg.optString("detail")
            )
            "execute_action" -> listener.onExecuteAction(
                DeviceAction(
                    actionId = msg.getString("action_id"),
                    action = msg.getString("action"),
                    params = msg.optJSONObject("params") ?: JSONObject(),
                    confirmed = msg.optBoolean("confirmed", false),
                )
            )
            "error" -> listener.onError(msg.optString("detail"))
        }
    }

    private companion object {
        const val TAG = "FloraWS"
    }
}
