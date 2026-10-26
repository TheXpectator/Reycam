package com.example.webcam

import android.Manifest
import android.content.Intent
import android.content.pm.PackageManager
import android.graphics.Typeface
import android.graphics.drawable.GradientDrawable
import android.net.Uri
import android.os.Build
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.os.PowerManager
import android.provider.Settings
import android.view.Gravity
import android.view.ViewGroup
import android.widget.Button
import android.widget.LinearLayout
import android.widget.ScrollView
import android.widget.TextView
import androidx.appcompat.app.AppCompatActivity
import androidx.core.content.ContextCompat

class MainActivity : AppCompatActivity() {
    private lateinit var status: TextView
    private lateinit var vCamera: TextView
    private lateinit var vRes: TextView
    private lateinit var vFps: TextView
    private lateinit var vClients: TextView
    private lateinit var note: TextView
    private lateinit var btn: Button
    private var noteColor = 0
    private var fromPc = false
    private val handler = Handler(Looper.getMainLooper())
    private val ticker = object : Runnable {
        override fun run() { refresh(); handler.postDelayed(this, 500) }
    }

    private fun dp(v: Int) = (v * resources.displayMetrics.density).toInt()

    override fun onCreate(b: Bundle?) {
        super.onCreate(b)
        val root = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(dp(24), dp(48), dp(24), dp(24))
        }
        root.addView(TextView(this).apply {
            text = "Phone Webcam"; textSize = 28f; setTypeface(typeface, Typeface.BOLD)
        })
        status = TextView(this).apply { textSize = 16f; setPadding(0, dp(8), 0, dp(24)) }
        root.addView(status)

        val card = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(dp(20), dp(12), dp(20), dp(12))
            background = GradientDrawable().apply { cornerRadius = dp(16).toFloat(); setColor(0x22808080) }
        }
        vCamera = row(card, "Kamera")
        vRes = row(card, "Resolusi")
        vFps = row(card, "FPS")
        vClients = row(card, "PC terhubung")
        root.addView(card, ViewGroup.LayoutParams(
            ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT))

        btn = Button(this).apply { setOnClickListener { toggle() } }
        root.addView(btn, LinearLayout.LayoutParams(
            ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT
        ).apply { topMargin = dp(24) })

        note = TextView(this).apply { textSize = 13f; alpha = 0.75f; setPadding(0, dp(16), 0, 0) }
        noteColor = note.currentTextColor
        root.addView(note)

        setContentView(ScrollView(this).apply { addView(root) })
        handleIntent(intent)
    }

    private fun row(card: LinearLayout, label: String): TextView {
        val value = TextView(this).apply { textSize = 15f; gravity = Gravity.END }
        val l = TextView(this).apply { text = label; textSize = 15f; alpha = 0.6f }
        card.addView(LinearLayout(this).apply {
            orientation = LinearLayout.HORIZONTAL
            setPadding(0, dp(6), 0, dp(6))
            addView(l, LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f))
            addView(value, LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f))
        })
        return value
    }

    override fun onNewIntent(intent: Intent) {
        super.onNewIntent(intent)
        setIntent(intent)
        handleIntent(intent)
    }

    private fun handleIntent(i: Intent?) {
        if (i?.getBooleanExtra("autostart", false) == true && !WebcamService.running) {
            fromPc = true
            toggle()
        }
    }

    override fun onResume() { super.onResume(); handler.post(ticker) }
    override fun onPause() { super.onPause(); handler.removeCallbacks(ticker) }

    private fun setStatus(text: String, color: Int) { status.text = text; status.setTextColor(color) }

    private fun refresh() {
        val on = WebcamService.running
        val n = WebcamService.clients
        when {
            !on -> setStatus("● Tidak aktif", 0xFF9E9E9E.toInt())
            n > 0 -> setStatus("● Terhubung ke PC", 0xFF2E9E5B.toInt())
            else -> setStatus("● Menunggu PC lewat USB", 0xFFE0A800.toInt())
        }
        val live = on && n > 0
        vCamera.text = if (live) WebcamService.camera else "—"
        vRes.text = if (live) WebcamService.resolution else "—"
        vFps.text = if (live) WebcamService.fps.toString() else "—"
        vClients.text = n.toString()
        btn.text = if (on) "Hentikan" else "Mulai"
        val err = WebcamService.error
        note.text = err ?: "Colokkan kabel USB, aktifkan USB debugging, lalu buka PhoneWebcam.exe " +
                "di PC. Layar HP boleh dimatikan. Kamera hanya menyala saat PC terhubung."
        note.setTextColor(if (err != null) 0xFFE53935.toInt() else noteColor)
    }

    private fun toggle() {
        if (WebcamService.running) {
            stopService(Intent(this, WebcamService::class.java))
            WebcamService.running = false
            refresh()
            return
        }
        val need = mutableListOf(Manifest.permission.CAMERA)
        if (Build.VERSION.SDK_INT >= 33) need.add(Manifest.permission.POST_NOTIFICATIONS)
        val missing = need.filter {
            ContextCompat.checkSelfPermission(this, it) != PackageManager.PERMISSION_GRANTED
        }
        if (missing.isNotEmpty()) requestPermissions(missing.toTypedArray(), 1) else start()
    }

    override fun onRequestPermissionsResult(c: Int, p: Array<out String>, r: IntArray) {
        super.onRequestPermissionsResult(c, p, r)
        val i = p.indexOf(Manifest.permission.CAMERA)
        if (i >= 0 && r[i] == PackageManager.PERMISSION_GRANTED) start()
    }

    private fun start() {
        try {
            WebcamService.error = null
            ContextCompat.startForegroundService(this, Intent(this, WebcamService::class.java))
            WebcamService.running = true
        } catch (e: Exception) {
            WebcamService.error = "Gagal memulai: ${e.message}"
        }
        refresh()
        // Jika dibuka manual, minta pengecualian hemat baterai (dari PC sudah diatur otomatis)
        if (!fromPc) {
            val pm = getSystemService(POWER_SERVICE) as PowerManager
            if (!pm.isIgnoringBatteryOptimizations(packageName)) {
                startActivity(Intent(
                    Settings.ACTION_REQUEST_IGNORE_BATTERY_OPTIMIZATIONS,
                    Uri.parse("package:$packageName")
                ))
            }
        }
    }
}
