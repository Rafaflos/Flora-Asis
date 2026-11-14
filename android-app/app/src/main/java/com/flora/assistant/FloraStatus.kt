package com.flora.assistant

import android.os.Handler
import android.os.Looper

/** Estado del servicio de escucha, para que MainActivity lo muestre mientras está abierta. */
object FloraStatus {
    @Volatile var text: String = "Detenida"
        private set
    @Volatile var lastReply: String = ""
        private set

    /** Se invoca en el hilo principal cada vez que cambia el estado. */
    var onChange: (() -> Unit)? = null

    private val main = Handler(Looper.getMainLooper())

    fun update(text: String? = null, lastReply: String? = null) {
        text?.let { this.text = it }
        lastReply?.let { this.lastReply = it }
        main.post { onChange?.invoke() }
    }
}
