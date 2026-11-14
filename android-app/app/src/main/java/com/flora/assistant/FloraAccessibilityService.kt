package com.flora.assistant

import android.accessibilityservice.AccessibilityService
import android.view.accessibility.AccessibilityEvent
import android.view.accessibility.AccessibilityNodeInfo

/**
 * Estructura base para automatizar la interfaz de otras apps (Fase 2):
 * por ejemplo, pulsar "Enviar" en WhatsApp después de una confirmación.
 *
 * Se activa a mano en Ajustes > Accesibilidad > Flora. Mientras no se use,
 * no observa ningún evento (ver res/xml/accessibility_config.xml).
 */
class FloraAccessibilityService : AccessibilityService() {

    override fun onServiceConnected() {
        instance = this
    }

    override fun onAccessibilityEvent(event: AccessibilityEvent?) {
        // Fase 2: reaccionar a cambios de ventana de las apps permitidas.
    }

    override fun onInterrupt() = Unit

    override fun onDestroy() {
        instance = null
        super.onDestroy()
    }

    /** Pulsa el primer elemento clicable cuyo texto o descripción coincida. */
    fun clickByText(text: String): Boolean {
        val root = rootInActiveWindow ?: return false
        val node = root.findAccessibilityNodeInfosByText(text).firstOrNull() ?: return false
        var target: AccessibilityNodeInfo? = node
        while (target != null && !target.isClickable) target = target.parent
        return target?.performAction(AccessibilityNodeInfo.ACTION_CLICK) == true
    }

    companion object {
        /** Instancia viva si el usuario activó el servicio; null si no. */
        @Volatile
        var instance: FloraAccessibilityService? = null
            private set
    }
}
