package com.flora.assistant

import android.Manifest
import android.content.ActivityNotFoundException
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.net.Uri
import android.os.Build
import android.os.Bundle
import android.provider.AlarmClock
import android.telecom.TelecomManager
import android.telephony.SmsManager
import androidx.core.content.ContextCompat
import org.json.JSONObject

/**
 * Ejecuta en el teléfono las acciones nativas que pide el Cerebro Central.
 *
 * Segunda capa del Centinela: aunque el backend ya exige confirmación, este
 * ejecutor se niega a llamar o enviar mensajes si la orden no llega marcada
 * como confirmada por el usuario.
 *
 * Nota sobre segundo plano (Android 10+): un servicio no puede abrir Activities
 * salvo que la app tenga el permiso "Mostrar sobre otras apps". Las llamadas no
 * lo necesitan porque usan TelecomManager.placeCall; abrir apps, alarmas y
 * WhatsApp sí. MainActivity pide ese permiso.
 */
class ActionExecutor(private val context: Context) {

    data class Result(val ok: Boolean, val detail: String)

    fun execute(action: DeviceAction): Result {
        if (action.action in CRITICAL_ACTIONS && !action.confirmed) {
            return Result(false, "REQUIRES_CONFIRMATION")
        }
        return try {
            when (action.action) {
                "phone_call" -> placeCall(action.params.getString("number"))
                "send_message" -> sendMessage(
                    number = action.params.getString("number"),
                    body = action.params.getString("body"),
                    channel = action.params.optString("channel", "sms"),
                )
                "open_app" -> openApp(action.params.getString("app"))
                "set_alarm" -> setAlarm(
                    hour = action.params.getInt("hour"),
                    minute = action.params.getInt("minute"),
                    label = action.params.optString("label", "Flora"),
                )
                else -> Result(false, "Acción desconocida: ${action.action}")
            }
        } catch (e: SecurityException) {
            Result(false, "Falta un permiso de Android: ${e.message}")
        } catch (e: ActivityNotFoundException) {
            Result(false, "No hay ninguna app que pueda hacerlo")
        } catch (e: Exception) {
            Result(false, "${e.javaClass.simpleName}: ${e.message}")
        }
    }

    // ── Llamadas ──

    private fun placeCall(number: String): Result {
        val granted = ContextCompat.checkSelfPermission(context, Manifest.permission.CALL_PHONE) ==
            PackageManager.PERMISSION_GRANTED
        if (!granted) return Result(false, "Falta el permiso CALL_PHONE")
        val uri = Uri.fromParts("tel", number, null)
        // placeCall no es un startActivity: funciona con la app en segundo plano.
        val telecom = context.getSystemService(Context.TELECOM_SERVICE) as TelecomManager
        telecom.placeCall(uri, Bundle())
        return Result(true, "Llamando a $number")
    }

    // ── Mensajes ──

    private fun sendMessage(number: String, body: String, channel: String): Result = when (channel) {
        "sms" -> sendSms(number, body)
        "whatsapp" -> openWhatsApp(number, body)
        else -> Result(false, "Canal no soportado: $channel")
    }

    private fun sendSms(number: String, body: String): Result {
        if (!has(Manifest.permission.SEND_SMS)) return Result(false, "Falta el permiso SEND_SMS")
        val sms = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.S) {
            context.getSystemService(SmsManager::class.java)
        } else {
            @Suppress("DEPRECATION") SmsManager.getDefault()
        }
        sms.sendMultipartTextMessage(number, null, sms.divideMessage(body), null, null)
        return Result(true, "SMS enviado a $number")
    }

    /**
     * WhatsApp no tiene API de envío para apps de terceros: se abre el chat con el
     * texto ya escrito y falta pulsar Enviar. En la Fase 2 ese toque puede darlo
     * FloraAccessibilityService.
     */
    private fun openWhatsApp(number: String, body: String): Result {
        val digits = number.filter { it.isDigit() }
        val intent = Intent(Intent.ACTION_VIEW, Uri.parse("https://wa.me/$digits?text=${Uri.encode(body)}"))
            .setPackage("com.whatsapp")
            .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
        context.startActivity(intent)
        return Result(true, "WhatsApp abierto con el mensaje escrito; falta pulsar enviar")
    }

    // ── Apps ──

    private fun openApp(app: String): Result {
        val pm = context.packageManager
        val packageName = if (pm.getLaunchIntentForPackage(app) != null) app else findPackageByLabel(app)
            ?: return Result(false, "No encontré una app llamada '$app'")
        val intent = pm.getLaunchIntentForPackage(packageName)
            ?: return Result(false, "'$app' no se puede abrir")
        context.startActivity(intent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK))
        return Result(true, "Abriendo $app")
    }

    private fun findPackageByLabel(label: String): String? {
        val pm = context.packageManager
        val launcher = Intent(Intent.ACTION_MAIN).addCategory(Intent.CATEGORY_LAUNCHER)
        val apps = pm.queryIntentActivities(launcher, 0)
            .map { it.loadLabel(pm).toString() to it.activityInfo.packageName }
        val wanted = label.trim()
        return (apps.firstOrNull { it.first.equals(wanted, ignoreCase = true) }
            ?: apps.firstOrNull { it.first.contains(wanted, ignoreCase = true) })?.second
    }

    // ── Alarmas ──

    private fun setAlarm(hour: Int, minute: Int, label: String): Result {
        val intent = Intent(AlarmClock.ACTION_SET_ALARM)
            .putExtra(AlarmClock.EXTRA_HOUR, hour)
            .putExtra(AlarmClock.EXTRA_MINUTES, minute)
            .putExtra(AlarmClock.EXTRA_MESSAGE, label)
            .putExtra(AlarmClock.EXTRA_SKIP_UI, true)
            .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
        context.startActivity(intent)
        return Result(true, "Alarma a las %02d:%02d".format(hour, minute))
    }

    private fun has(permission: String): Boolean =
        ContextCompat.checkSelfPermission(context, permission) == PackageManager.PERMISSION_GRANTED

    companion object {
        /** Deben coincidir con las herramientas `critical=True` del backend. */
        val CRITICAL_ACTIONS = setOf("phone_call", "send_message")
    }
}
