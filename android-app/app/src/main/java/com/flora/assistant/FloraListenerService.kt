package com.flora.assistant

import android.annotation.SuppressLint
import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.app.Service
import android.content.Context
import android.content.Intent
import android.content.pm.ServiceInfo
import android.media.AudioFormat
import android.media.AudioRecord
import android.media.MediaRecorder
import android.os.Build
import android.os.IBinder
import android.speech.tts.TextToSpeech
import android.speech.tts.UtteranceProgressListener
import android.util.Log
import androidx.core.app.NotificationCompat
import java.util.Locale
import kotlin.concurrent.thread
import kotlin.math.sqrt

/**
 * Servicio en primer plano: escucha la palabra clave, captura la frase, la envía
 * como audio al Cerebro Central, habla las respuestas y muestra las tarjetas de
 * confirmación como notificaciones con botones Aprobar / Cancelar.
 *
 * Debe iniciarse con la app visible (MainActivity): Android no permite arrancar
 * un servicio de micrófono desde segundo plano.
 */
class FloraListenerService : Service(), WebSocketManager.Listener, TextToSpeech.OnInitListener {

    private lateinit var ws: WebSocketManager
    private lateinit var executor: ActionExecutor
    private lateinit var tts: TextToSpeech
    private lateinit var notifications: NotificationManager

    @Volatile private var running = false
    @Volatile private var speaking = false
    private var ttsReady = false
    private var captureThread: Thread? = null

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onCreate() {
        super.onCreate()
        notifications = getSystemService(NotificationManager::class.java)
        createChannels()
        startForegroundCompat(statusNotification("Conectando…"))

        executor = ActionExecutor(this)
        tts = TextToSpeech(this, this)
        ws = WebSocketManager(BuildConfig.FLORA_SERVER_URL, BuildConfig.FLORA_TOKEN, deviceId(), this)
        ws.connect()

        running = true
        captureThread = thread(name = "flora-capture") { captureLoop() }
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        // Botones de la tarjeta de confirmación.
        if (intent?.action == ACTION_CONFIRM) {
            val actionId = intent.getStringExtra(EXTRA_ACTION_ID).orEmpty()
            ws.sendConfirmation(actionId, intent.getBooleanExtra(EXTRA_APPROVED, false))
            notifications.cancel(actionId.hashCode())
        }
        return START_STICKY
    }

    override fun onDestroy() {
        running = false
        captureThread?.join(1000)
        ws.disconnect()
        tts.shutdown()
        super.onDestroy()
    }

    // ── Captura: palabra clave + fin de voz por energía ──

    @SuppressLint("MissingPermission") // RECORD_AUDIO se pide en MainActivity antes de iniciar
    private fun captureLoop() {
        // Mismo modelo «Oye Flora» que el nodo de escritorio, sobre ONNX Runtime (sin cuentas ni claves).
        val detector = try {
            WakeWordDetector(
                melModel = assets.open("melspectrogram.onnx").use { it.readBytes() },
                embeddingModel = assets.open("embedding_model.onnx").use { it.readBytes() },
                wakeModel = assets.open("oye_flora.onnx").use { it.readBytes() },
            )
        } catch (e: Exception) {
            Log.e(TAG, "No se pudo cargar el detector de palabra clave: ${e.message}")
            return
        }
        val frameLength = WakeWordDetector.FRAME_SAMPLES // 1280 muestras = 80 ms
        val minBuffer = AudioRecord.getMinBufferSize(
            SAMPLE_RATE, AudioFormat.CHANNEL_IN_MONO, AudioFormat.ENCODING_PCM_16BIT
        )
        val recorder = AudioRecord(
            MediaRecorder.AudioSource.VOICE_RECOGNITION, SAMPLE_RATE,
            AudioFormat.CHANNEL_IN_MONO, AudioFormat.ENCODING_PCM_16BIT,
            maxOf(minBuffer, frameLength * 2 * 4),
        )
        val frame = ShortArray(frameLength)
        val bytes = ByteArray(frameLength * 2)
        val frameMs = frameLength * 1000 / SAMPLE_RATE

        var recording = false
        var wasSpeaking = false
        var heardSpeech = false
        var silenceMs = 0
        var elapsedMs = 0

        try {
            recorder.startRecording()
            while (running) {
                var read = 0
                while (read < frameLength && running) {
                    val n = recorder.read(frame, read, frameLength - read)
                    if (n <= 0) break
                    read += n
                }
                if (read != frameLength) continue
                if (speaking) { // no escucharse a sí misma
                    wasSpeaking = true
                    continue
                }
                if (wasSpeaking) {
                    detector.reset()
                    wasSpeaking = false
                }

                if (!recording) {
                    if (detector.process(frame) && ws.isReady) {
                        detector.reset()
                        recording = true
                        heardSpeech = false
                        silenceMs = 0
                        elapsedMs = 0
                        updateStatus("Te escucho…")
                    }
                    continue
                }

                for (i in frame.indices) {
                    bytes[2 * i] = (frame[i].toInt() and 0xFF).toByte()
                    bytes[2 * i + 1] = (frame[i].toInt() shr 8).toByte()
                }
                ws.sendAudioChunk(bytes)
                elapsedMs += frameMs

                if (rms(frame) > SPEECH_RMS) {
                    heardSpeech = true
                    silenceMs = 0
                } else {
                    silenceMs += frameMs
                }
                val finished = (heardSpeech && silenceMs >= END_SILENCE_MS) ||
                    (!heardSpeech && elapsedMs >= NO_SPEECH_TIMEOUT_MS) ||
                    elapsedMs >= MAX_UTTERANCE_MS
                if (finished) {
                    recording = false
                    ws.sendAudioEnd() // el backend transcribe con faster-whisper
                    updateStatus("Pensando…")
                }
            }
        } finally {
            recorder.release()
            detector.close()
        }
    }

    private fun rms(frame: ShortArray): Double {
        var sum = 0.0
        for (s in frame) sum += s.toDouble() * s
        return sqrt(sum / frame.size)
    }

    // ── WebSocketManager.Listener (hilo principal) ──

    override fun onConnectionChanged(connected: Boolean) =
        updateStatus(if (connected) "Lista. Di «Oye Flora»." else "Sin conexión con la Mac")

    override fun onReply(text: String) {
        updateStatus("Lista. Di «Oye Flora».")
        speak(text)
    }

    override fun onConfirmationRequest(request: ConfirmationRequest) {
        val id = request.actionId.hashCode()
        val card = NotificationCompat.Builder(this, CHANNEL_CONFIRM)
            .setSmallIcon(android.R.drawable.ic_dialog_alert)
            .setContentTitle("Flora necesita tu confirmación")
            .setContentText(request.summary)
            .setStyle(NotificationCompat.BigTextStyle().bigText(request.summary))
            .setPriority(NotificationCompat.PRIORITY_HIGH)
            .setCategory(NotificationCompat.CATEGORY_CALL)
            .setTimeoutAfter(request.expiresInSeconds * 1000L)
            .setAutoCancel(true)
            .addAction(0, "Aprobar", confirmIntent(request.actionId, approved = true))
            .addAction(0, "Cancelar", confirmIntent(request.actionId, approved = false))
            .build()
        notifications.notify(id, card)
    }

    override fun onConfirmationResolved(actionId: String, approved: Boolean, detail: String) =
        notifications.cancel(actionId.hashCode())

    override fun onExecuteAction(action: DeviceAction) {
        val result = executor.execute(action)
        ws.sendActionResult(action.actionId, result.ok, result.detail)
    }

    override fun onError(detail: String) = updateStatus(detail)

    private fun confirmIntent(actionId: String, approved: Boolean): PendingIntent {
        val intent = Intent(this, FloraListenerService::class.java)
            .setAction(ACTION_CONFIRM)
            .putExtra(EXTRA_ACTION_ID, actionId)
            .putExtra(EXTRA_APPROVED, approved)
        val requestCode = actionId.hashCode() * 2 + if (approved) 1 else 0
        return PendingIntent.getService(
            this, requestCode, intent, PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE
        )
    }

    // ── Voz ──

    override fun onInit(status: Int) {
        if (status != TextToSpeech.SUCCESS) return
        tts.language = Locale("es", "MX")
        tts.setOnUtteranceProgressListener(object : UtteranceProgressListener() {
            override fun onStart(utteranceId: String?) { speaking = true }
            override fun onDone(utteranceId: String?) { speaking = false }
            @Deprecated("Deprecated in Java")
            override fun onError(utteranceId: String?) { speaking = false }
        })
        ttsReady = true
    }

    private fun speak(text: String) {
        if (ttsReady) tts.speak(text, TextToSpeech.QUEUE_ADD, null, "flora-${System.nanoTime()}")
    }

    // ── Notificación persistente ──

    private fun createChannels() {
        notifications.createNotificationChannel(
            NotificationChannel(CHANNEL_STATUS, "Flora escuchando", NotificationManager.IMPORTANCE_LOW)
        )
        notifications.createNotificationChannel(
            NotificationChannel(CHANNEL_CONFIRM, "Confirmaciones", NotificationManager.IMPORTANCE_HIGH)
        )
    }

    private fun statusNotification(text: String): Notification =
        NotificationCompat.Builder(this, CHANNEL_STATUS)
            .setSmallIcon(android.R.drawable.ic_btn_speak_now)
            .setContentTitle("Flora")
            .setContentText(text)
            .setOngoing(true)
            .build()

    private fun updateStatus(text: String) = notifications.notify(STATUS_ID, statusNotification(text))

    private fun startForegroundCompat(notification: Notification) {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
            startForeground(STATUS_ID, notification, ServiceInfo.FOREGROUND_SERVICE_TYPE_MICROPHONE)
        } else {
            startForeground(STATUS_ID, notification)
        }
    }

    private fun deviceId(): String = "android-" + Build.MODEL.lowercase().replace(' ', '-')

    companion object {
        private const val TAG = "FloraService"
        private const val SAMPLE_RATE = 16000
        private const val SPEECH_RMS = 900.0       // umbral de energía; ajústalo a tu micrófono
        private const val END_SILENCE_MS = 800
        private const val NO_SPEECH_TIMEOUT_MS = 4000
        private const val MAX_UTTERANCE_MS = 15000
        private const val STATUS_ID = 1
        private const val CHANNEL_STATUS = "flora_status"
        private const val CHANNEL_CONFIRM = "flora_confirm"
        private const val ACTION_CONFIRM = "com.flora.assistant.CONFIRM"
        private const val EXTRA_ACTION_ID = "action_id"
        private const val EXTRA_APPROVED = "approved"

        fun start(context: Context) {
            context.startForegroundService(Intent(context, FloraListenerService::class.java))
        }
    }
}
