package com.example.webcam

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.Context
import android.content.Intent
import android.content.pm.ServiceInfo
import android.os.Build
import android.os.PowerManager
import android.os.SystemClock
import android.util.Size
import androidx.camera.core.CameraSelector
import androidx.camera.core.ImageAnalysis
import androidx.camera.core.ImageProxy
import androidx.camera.core.resolutionselector.AspectRatioStrategy
import androidx.camera.core.resolutionselector.ResolutionSelector
import androidx.camera.core.resolutionselector.ResolutionStrategy
import androidx.camera.lifecycle.ProcessCameraProvider
import androidx.core.app.NotificationCompat
import androidx.core.app.ServiceCompat
import androidx.core.content.ContextCompat
import androidx.lifecycle.LifecycleService
import java.io.ByteArrayOutputStream
import java.net.InetAddress
import java.net.InetSocketAddress
import java.net.ServerSocket
import java.net.Socket
import java.util.concurrent.Executors
import kotlin.concurrent.thread

class WebcamService : LifecycleService() {

    companion object {
        const val PORT = 8080
        @Volatile var running = false
        @Volatile var clients = 0
        @Volatile var fps = 0
        @Volatile var resolution = "—"
        @Volatile var camera = "—"
        @Volatile var error: String? = null
    }

    private data class Cfg(val cam: String, val h: Int, val fps: Int)

    private val lock = Any()
    private var server: ServerSocket? = null
    private var bound: Cfg? = null
    @Volatile private var cfgNow = Cfg("back", 720, 30)
    @Volatile private var quality = 80
    @Volatile private var frame: ByteArray? = null
    @Volatile private var seq = 0L
    private var lastFrameAt = 0L
    private var counted = 0
    private var countStart = 0L
    private val exec = Executors.newSingleThreadExecutor()
    private var wakeLock: PowerManager.WakeLock? = null

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        super.onStartCommand(intent, flags, startId)
        if (running) return START_NOT_STICKY
        try {
            ServiceCompat.startForeground(
                this, 1, buildNotification(),
                if (Build.VERSION.SDK_INT >= 30) ServiceInfo.FOREGROUND_SERVICE_TYPE_CAMERA else 0
            )
        } catch (e: Exception) {
            error = "Tidak bisa berjalan di latar belakang. Buka kunci layar HP, lalu coba lagi."
            stopSelf()
            return START_NOT_STICKY
        }
        running = true
        error = null

        val pm = getSystemService(Context.POWER_SERVICE) as PowerManager
        wakeLock = pm.newWakeLock(PowerManager.PARTIAL_WAKE_LOCK, "webcam:wl").apply { acquire() }

        startServer()
        return START_NOT_STICKY
    }

    private fun buildNotification(): Notification {
        val id = "webcam"
        val nm = getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager
        if (Build.VERSION.SDK_INT >= 26) {
            nm.createNotificationChannel(
                NotificationChannel(id, "Webcam USB", NotificationManager.IMPORTANCE_LOW)
            )
        }
        val open = PendingIntent.getActivity(
            this, 0, Intent(this, MainActivity::class.java), PendingIntent.FLAG_IMMUTABLE
        )
        return NotificationCompat.Builder(this, id)
            .setContentTitle("Webcam USB aktif")
            .setContentText("Kamera menyala hanya saat PC terhubung")
            .setSmallIcon(android.R.drawable.ic_menu_camera)
            .setContentIntent(open)
            .setOngoing(true)
            .build()
    }

    // ---------- Server: hanya 127.0.0.1, jadi hanya bisa diakses lewat kabel USB (adb forward) ----------
    private fun startServer() {
        thread {
            try {
                val s = ServerSocket().apply {
                    reuseAddress = true
                    bind(InetSocketAddress(InetAddress.getByName("127.0.0.1"), PORT))
                }
                server = s
                while (running) {
                    val c = s.accept()
                    thread { serve(c) }
                }
            } catch (e: Exception) {
                if (running) error = "Server gagal: ${e.message}"
            }
        }
    }

    private fun serve(s: Socket) {
        var joined = false
        try {
            s.use {
                it.tcpNoDelay = true
                val rd = it.getInputStream().bufferedReader()
                val first = rd.readLine() ?: return
                while (true) { val l = rd.readLine(); if (l == null || l.isEmpty()) break }

                val qs = (first.split(" ").getOrNull(1) ?: "").substringAfter('?', "")
                val q = qs.split('&').filter { p -> p.contains('=') }
                    .associate { p -> p.substringBefore('=') to p.substringAfter('=') }
                val cfg = Cfg(
                    if (q["cam"] == "front") "front" else "back",
                    q["h"]?.toIntOrNull() ?: 720,
                    (q["fps"]?.toIntOrNull() ?: 30).coerceIn(5, 60)
                )
                quality = (q["q"]?.toIntOrNull() ?: 80).coerceIn(30, 100)

                join(cfg); joined = true
                val o = it.getOutputStream()
                o.write(
                    ("HTTP/1.1 200 OK\r\nContent-Type: multipart/x-mixed-replace; boundary=f\r\n" +
                            "Cache-Control: no-cache\r\n\r\n").toByteArray()
                )
                var last = -1L
                while (running) {
                    val f = frame
                    if (f != null && seq != last) {
                        last = seq
                        o.write("--f\r\nContent-Type: image/jpeg\r\nContent-Length: ${f.size}\r\n\r\n".toByteArray())
                        o.write(f); o.write("\r\n".toByteArray()); o.flush()
                    } else Thread.sleep(4)
                }
            }
        } catch (_: Exception) {
        } finally {
            if (joined) leave()
        }
    }

    private fun join(c: Cfg) = synchronized(lock) {
        clients++
        if (bound != c) bindCamera(c)
    }

    private fun leave() = synchronized(lock) {
        clients = (clients - 1).coerceAtLeast(0)
        if (clients == 0) unbindCamera()
    }

    // ---------- Kamera ----------
    private fun bindCamera(c: Cfg) {
        bound = c
        cfgNow = c
        camera = if (c.cam == "front") "Depan" else "Belakang"
        error = null
        val fut = ProcessCameraProvider.getInstance(this)
        fut.addListener({
            try {
                val provider = fut.get()
                val selector = if (c.cam == "front") CameraSelector.DEFAULT_FRONT_CAMERA
                else CameraSelector.DEFAULT_BACK_CAMERA
                val (size, ratio) = when (c.h) {
                    480 -> Size(640, 480) to AspectRatioStrategy.RATIO_4_3_FALLBACK_AUTO_STRATEGY
                    1080 -> Size(1920, 1080) to AspectRatioStrategy.RATIO_16_9_FALLBACK_AUTO_STRATEGY
                    else -> Size(1280, 720) to AspectRatioStrategy.RATIO_16_9_FALLBACK_AUTO_STRATEGY
                }
                val rs = ResolutionSelector.Builder()
                    .setAspectRatioStrategy(ratio)
                    .setResolutionStrategy(
                        ResolutionStrategy(size, ResolutionStrategy.FALLBACK_RULE_CLOSEST_HIGHER_THEN_LOWER)
                    ).build()
                val analysis = ImageAnalysis.Builder()
                    .setResolutionSelector(rs)
                    .setBackpressureStrategy(ImageAnalysis.STRATEGY_KEEP_ONLY_LATEST)
                    .build()
                analysis.setAnalyzer(exec) { img -> analyze(img) }
                provider.unbindAll()
                provider.bindToLifecycle(this, selector, analysis)
            } catch (e: Exception) {
                error = "Kamera gagal: ${e.message}"
            }
        }, ContextCompat.getMainExecutor(this))
    }

    private fun unbindCamera() {
        bound = null
        frame = null
        fps = 0
        resolution = "—"
        val fut = ProcessCameraProvider.getInstance(this)
        fut.addListener({
            try { fut.get().unbindAll() } catch (_: Exception) {}
        }, ContextCompat.getMainExecutor(this))
    }

    private fun analyze(img: ImageProxy) {
        try {
            val now = SystemClock.elapsedRealtime()
            if (clients > 0 && now - lastFrameAt >= 1000L / cfgNow.fps) {
                lastFrameAt = now
                val bmp = img.toBitmap()           // orientasi sensor; rotasi diatur dari PC
                val out = ByteArrayOutputStream(64 * 1024)
                bmp.compress(android.graphics.Bitmap.CompressFormat.JPEG, quality, out)
                frame = out.toByteArray()
                seq++
                resolution = "${bmp.width}×${bmp.height}"
                counted++
                if (now - countStart >= 1000) { fps = counted; counted = 0; countStart = now }
            }
        } finally {
            img.close()
        }
    }

    override fun onDestroy() {
        running = false
        clients = 0
        fps = 0
        try { server?.close() } catch (_: Exception) {}
        try { ProcessCameraProvider.getInstance(this).get().unbindAll() } catch (_: Exception) {}
        exec.shutdown()
        wakeLock?.let { if (it.isHeld) it.release() }
        super.onDestroy()
    }
}
