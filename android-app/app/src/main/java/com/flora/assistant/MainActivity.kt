package com.flora.assistant

import android.Manifest
import android.content.Intent
import android.content.pm.PackageManager
import android.net.Uri
import android.os.Build
import android.os.Bundle
import android.provider.Settings
import android.view.Gravity
import android.widget.Button
import android.widget.LinearLayout
import android.widget.TextView
import androidx.activity.ComponentActivity
import androidx.activity.result.contract.ActivityResultContracts
import androidx.core.content.ContextCompat

/** Pantalla mínima: pide permisos y arranca el servicio de escucha. */
class MainActivity : ComponentActivity() {

    private lateinit var status: TextView

    private val permissionLauncher =
        registerForActivityResult(ActivityResultContracts.RequestMultiplePermissions()) { startIfReady() }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        status = TextView(this).apply { textSize = 16f }
        val overlayButton = Button(this).apply {
            text = "Permitir abrir apps en segundo plano"
            setOnClickListener {
                startActivity(
                    Intent(Settings.ACTION_MANAGE_OVERLAY_PERMISSION, Uri.parse("package:$packageName"))
                )
            }
        }
        setContentView(LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            gravity = Gravity.CENTER
            setPadding(48, 48, 48, 48)
            addView(status)
            addView(overlayButton)
        })
        permissionLauncher.launch(requiredPermissions())
    }

    override fun onResume() {
        super.onResume()
        FloraStatus.onChange = { render() }
        startIfReady()
    }

    override fun onPause() {
        FloraStatus.onChange = null
        super.onPause()
    }

    private fun requiredPermissions(): Array<String> = buildList {
        add(Manifest.permission.RECORD_AUDIO)
        add(Manifest.permission.CALL_PHONE)
        add(Manifest.permission.SEND_SMS)
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) add(Manifest.permission.POST_NOTIFICATIONS)
    }.toTypedArray()

    private fun startIfReady() {
        val micGranted = ContextCompat.checkSelfPermission(this, Manifest.permission.RECORD_AUDIO) ==
            PackageManager.PERMISSION_GRANTED
        if (!micGranted) {
            status.text = "Flora necesita el micrófono para escucharte."
            return
        }
        FloraListenerService.start(this)
        render()
    }

    private fun render() {
        val lines = mutableListOf("Estado: ${FloraStatus.text}", "Servidor: ${BuildConfig.FLORA_SERVER_URL}")
        if (FloraStatus.lastReply.isNotEmpty()) lines += "\nFlora: ${FloraStatus.lastReply}"
        if (!Settings.canDrawOverlays(this)) {
            lines += "\nFalta el permiso para abrir apps y alarmas con la pantalla apagada."
        }
        status.text = lines.joinToString("\n")
    }
}
