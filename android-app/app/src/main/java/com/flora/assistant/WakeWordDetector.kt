package com.flora.assistant

import ai.onnxruntime.OnnxTensor
import ai.onnxruntime.OrtEnvironment
import ai.onnxruntime.OrtSession
import java.nio.FloatBuffer

/**
 * Detector de palabra clave «Oye Flora» con los modelos de openWakeWord sobre ONNX Runtime.
 * Es el mismo modelo que usa el nodo de escritorio (desktop-node/models/oye_flora.onnx).
 *
 * Cadena por cada bloque de 80 ms (1280 muestras a 16 kHz):
 *   audio -> melspectrogram.onnx -> embedding_model.onnx (ventana de 76 cuadros mel)
 *         -> oye_flora.onnx (últimos 16 embeddings) -> puntuación 0..1
 *
 * No depende de Android: recibe los modelos como bytes, así se puede probar en la JVM.
 */
class WakeWordDetector(
    melModel: ByteArray,
    embeddingModel: ByteArray,
    wakeModel: ByteArray,
    private val threshold: Float = 0.8f,
    private val requiredFrames: Int = 2,
) : AutoCloseable {

    private val env = OrtEnvironment.getEnvironment()
    private val options = OrtSession.SessionOptions().apply {
        setIntraOpNumThreads(1)
        setInterOpNumThreads(1)
    }
    private val mel = env.createSession(melModel, options)
    private val embedding = env.createSession(embeddingModel, options)
    private val wake = env.createSession(wakeModel, options)
    private val melInput = mel.inputNames.first()
    private val embeddingInput = embedding.inputNames.first()
    private val wakeInput = wake.inputNames.first()

    private val raw = FloatArray(FRAME_SAMPLES + MEL_CONTEXT)   // últimas muestras
    private var rawFilled = 0
    private val melFrames = ArrayDeque<FloatArray>()            // cuadros mel de 32 valores
    private val features = ArrayDeque<FloatArray>()             // embeddings de 96 valores
    private var streak = 0

    /** Última puntuación calculada (0 mientras se llena el contexto inicial, ~2,5 s). */
    var lastScore = 0f
        private set

    /** Procesa exactamente [FRAME_SAMPLES] muestras. Devuelve true cuando se detecta la palabra clave. */
    fun process(frame: ShortArray): Boolean {
        require(frame.size == FRAME_SAMPLES) { "Se esperan $FRAME_SAMPLES muestras" }
        lastScore = score(frame)
        streak = if (lastScore >= threshold) streak + 1 else 0
        if (streak >= requiredFrames) {
            streak = 0
            return true
        }
        return false
    }

    /** Olvida el audio anterior (tras hablar Flora o tras una detección). */
    fun reset() {
        rawFilled = 0
        melFrames.clear()
        features.clear()
        streak = 0
        lastScore = 0f
    }

    private fun score(frame: ShortArray): Float {
        // 1. Desplaza el búfer y añade el bloque nuevo (valores int16 como float, sin normalizar).
        System.arraycopy(raw, FRAME_SAMPLES, raw, 0, MEL_CONTEXT)
        for (i in 0 until FRAME_SAMPLES) raw[MEL_CONTEXT + i] = frame[i].toFloat()
        rawFilled = minOf(raw.size, rawFilled + FRAME_SAMPLES)

        // 2. Espectrograma mel del bloque más 30 ms de contexto -> 8 cuadros nuevos.
        val samples = raw.copyOfRange(raw.size - rawFilled, raw.size)
        OnnxTensor.createTensor(env, FloatBuffer.wrap(samples), longArrayOf(1, samples.size.toLong())).use { input ->
            mel.run(mapOf(melInput to input)).use { out ->
                val buffer = (out[0] as OnnxTensor).floatBuffer
                while (buffer.remaining() >= MEL_BINS) {
                    val row = FloatArray(MEL_BINS)
                    buffer.get(row)
                    for (i in row.indices) row[i] = row[i] / 10f + 2f   // misma escala que openWakeWord
                    melFrames.addLast(row)
                }
            }
        }
        while (melFrames.size > MEL_WINDOW) melFrames.removeFirst()
        if (melFrames.size < MEL_WINDOW) return 0f

        // 3. Embedding de los últimos 76 cuadros mel.
        val window = FloatBuffer.allocate(MEL_WINDOW * MEL_BINS)
        for (row in melFrames) window.put(row)
        window.rewind()
        OnnxTensor.createTensor(env, window, longArrayOf(1, MEL_WINDOW.toLong(), MEL_BINS.toLong(), 1)).use { input ->
            embedding.run(mapOf(embeddingInput to input)).use { out ->
                val vector = FloatArray(EMBEDDING_SIZE)
                (out[0] as OnnxTensor).floatBuffer.get(vector)
                features.addLast(vector)
            }
        }
        while (features.size > FEATURE_WINDOW) features.removeFirst()
        if (features.size < FEATURE_WINDOW) return 0f

        // 4. Clasificador sobre los últimos 16 embeddings (~1,3 s).
        val stacked = FloatBuffer.allocate(FEATURE_WINDOW * EMBEDDING_SIZE)
        for (vector in features) stacked.put(vector)
        stacked.rewind()
        OnnxTensor.createTensor(env, stacked, longArrayOf(1, FEATURE_WINDOW.toLong(), EMBEDDING_SIZE.toLong())).use { input ->
            wake.run(mapOf(wakeInput to input)).use { out ->
                return (out[0] as OnnxTensor).floatBuffer.get(0)
            }
        }
    }

    override fun close() {
        mel.close()
        embedding.close()
        wake.close()
        options.close()
    }

    companion object {
        const val SAMPLE_RATE = 16000
        const val FRAME_SAMPLES = 1280          // 80 ms
        private const val MEL_CONTEXT = 480     // 30 ms de solapamiento entre bloques
        private const val MEL_BINS = 32
        private const val MEL_WINDOW = 76
        private const val EMBEDDING_SIZE = 96
        private const val FEATURE_WINDOW = 16
    }
}
