package ru.sanaterra.schedule

import android.Manifest
import android.annotation.SuppressLint
import android.content.ClipData
import android.content.ClipboardManager
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.graphics.Bitmap
import android.net.Uri
import android.os.Build
import android.os.Bundle
import android.view.Gravity
import android.view.View
import android.webkit.CookieManager
import android.webkit.JavascriptInterface
import android.webkit.ValueCallback
import android.webkit.WebChromeClient
import android.webkit.WebResourceError
import android.webkit.WebResourceRequest
import android.webkit.WebView
import android.webkit.WebViewClient
import android.widget.Button
import android.widget.FrameLayout
import android.widget.LinearLayout
import android.widget.ProgressBar
import android.widget.ScrollView
import android.widget.TextView
import androidx.activity.OnBackPressedCallback
import androidx.activity.result.contract.ActivityResultContracts
import androidx.appcompat.app.AppCompatActivity
import com.google.firebase.messaging.FirebaseMessaging

/** Тонкая обертка: WebView + мост для адреса установки + открытие URL из пуша. */
class MainActivity : AppCompatActivity() {

    companion object {
        // Тест: локальный Django на этом же Wi-Fi. ВНИМАНИЕ: 127.0.0.1 сюда
        // ставить нельзя — на телефоне это адрес самого телефона.
        // Позже заменить на https-домен.
        const val BASE_URL = "http://192.168.0.103:8000/"
        const val EXTRA_URL = "target_url"
    }

    private lateinit var webView: WebView
    private lateinit var progressBar: ProgressBar
    private lateinit var errorBox: LinearLayout
    private lateinit var pushBadge: TextView
    private var pageFailed: Boolean = false
    private var cachedRegistration: String = ""

    private val permissionRequest = registerForActivityResult(
        ActivityResultContracts.RequestPermission()
    ) { }

    // Выбор файла для <input type="file"> (загрузка расписания).
    // Без этого WebView молча игнорирует нажатие на поле файла.
    private var fileChooserCallback: ValueCallback<Array<Uri>>? = null
    private val fileChooserLauncher =
        registerForActivityResult(ActivityResultContracts.StartActivityForResult()) { result ->
            val uris = WebChromeClient.FileChooserParams.parseResult(
                result.resultCode, result.data
            )
            fileChooserCallback?.onReceiveValue(uris)
            fileChooserCallback = null
        }

    /** Мост, который видит страница: только отдача адреса, ничего лишнего. */
    inner class AndroidBridge {
        @JavascriptInterface
        fun getPushRegistration(): String = cachedRegistration
    }

    @SuppressLint("SetJavaScriptEnabled")
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        val root = FrameLayout(this)

        webView = WebView(this)
        root.addView(webView, FrameLayout.LayoutParams(
            FrameLayout.LayoutParams.MATCH_PARENT,
            FrameLayout.LayoutParams.MATCH_PARENT
        ))

        // Бейдж загрузки: крутится, пока страница грузится.
        progressBar = ProgressBar(this)
        root.addView(progressBar, FrameLayout.LayoutParams(
            FrameLayout.LayoutParams.WRAP_CONTENT,
            FrameLayout.LayoutParams.WRAP_CONTENT,
            Gravity.CENTER
        ))

        // Экран «нет соединения» с кнопкой повтора.
        errorBox = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            gravity = Gravity.CENTER
            visibility = View.GONE
        }
        val errorText = TextView(this).apply {
            text = "Нет соединения с сервером"
            gravity = Gravity.CENTER
        }
        val retryButton = Button(this).apply {
            text = "Повторить"
            setOnClickListener { retryLoad() }
        }
        errorBox.addView(errorText)
        errorBox.addView(retryButton)
        root.addView(errorBox, FrameLayout.LayoutParams(
            FrameLayout.LayoutParams.MATCH_PARENT,
            FrameLayout.LayoutParams.MATCH_PARENT,
            Gravity.CENTER
        ))

        // Бейдж статуса пуш-токена: видно, выдал ли Firebase номер.
        // Тап: есть токен — показать его, нет — запросить заново.
        pushBadge = TextView(this).apply {
            text = "Push: жду токен…"
            textSize = 12f
            setPadding(24, 12, 24, 12)
            setOnClickListener {
                if (cachedRegistration.isNotEmpty()) {
                    showTokenDialog()
                } else {
                    refreshRegistration()
                }
            }
        }
        root.addView(pushBadge, FrameLayout.LayoutParams(
            FrameLayout.LayoutParams.WRAP_CONTENT,
            FrameLayout.LayoutParams.WRAP_CONTENT,
            Gravity.TOP or Gravity.CENTER_HORIZONTAL
        ))

        setContentView(root)

        askNotificationPermission()

        webView.settings.javaScriptEnabled = true
        webView.settings.domStorageEnabled = true
        // Куки сессии должны жить на диске, иначе после убийства процесса
        // (MIUI это делает регулярно) вход придется повторять каждый раз.
        CookieManager.getInstance().setAcceptCookie(true)
        webView.webViewClient = object : WebViewClient() {
            override fun onPageStarted(view: WebView, url: String, favicon: Bitmap?) {
                pageFailed = false
                errorBox.visibility = View.GONE
                progressBar.visibility = View.VISIBLE
            }

            override fun onPageFinished(view: WebView, url: String) {
                if (!pageFailed) {
                    progressBar.visibility = View.GONE
                }
            }

            override fun onReceivedError(
                view: WebView,
                request: WebResourceRequest,
                error: WebResourceError
            ) {
                // Показываем ошибку только если упала сама страница,
                // а не какая-то картинка внутри нее.
                if (request.isForMainFrame) {
                    pageFailed = true
                    progressBar.visibility = View.GONE
                    errorBox.visibility = View.VISIBLE
                }
            }
        }
        webView.webChromeClient = object : WebChromeClient() {
            override fun onShowFileChooser(
                view: WebView,
                callback: ValueCallback<Array<Uri>>,
                params: FileChooserParams
            ): Boolean {
                fileChooserCallback?.onReceiveValue(null)
                fileChooserCallback = callback
                return try {
                    fileChooserLauncher.launch(params.createIntent())
                    true
                } catch (e: Exception) {
                    fileChooserCallback = null
                    false
                }
            }
        }
        // Мост открыт только нашему сайту: другие URL в этот WebView не грузим.
        webView.addJavascriptInterface(AndroidBridge(), "AndroidBridge")

        // Системная кнопка «назад»: сначала назад по истории страниц,
        // наружу выходим только когда истории нет.
        onBackPressedDispatcher.addCallback(this, object : OnBackPressedCallback(true) {
            override fun handleOnBackPressed() {
                if (webView.canGoBack()) {
                    webView.goBack()
                } else {
                    isEnabled = false
                    onBackPressedDispatcher.onBackPressed()
                }
            }
        })

        refreshRegistration()

        val startUrl = intent.getStringExtra(EXTRA_URL)
            ?: intent.data?.toString()
            ?: BASE_URL
        openUrl(startUrl)
    }

    override fun onNewIntent(intent: Intent) {
        super.onNewIntent(intent)
        intent.getStringExtra(EXTRA_URL)?.let { openUrl(it) }
    }

    override fun onResume() {
        super.onResume()
        refreshRegistration()
    }

    override fun onPause() {
        // Сбросить куки на диск: без этого сессия живет только в памяти
        // и умирает вместе с процессом.
        CookieManager.getInstance().flush()
        super.onPause()
    }

    private fun openUrl(url: String) {        val full = if (url.startsWith("http")) url else BASE_URL.trimEnd('/') + url
        // Загружаем только наш сервер, чужое не открываем.
        if (full.startsWith(BASE_URL)) {
            webView.loadUrl(full)
        } else {
            webView.loadUrl(BASE_URL)
        }
    }

    private fun retryLoad() {
        pageFailed = false
        errorBox.visibility = View.GONE
        progressBar.visibility = View.VISIBLE
        webView.reload()
    }

    private fun refreshRegistration() {
        FirebaseMessaging.getInstance().token.addOnCompleteListener { task ->
            if (task.isSuccessful) {
                cachedRegistration = task.result ?: ""
            }
            runOnUiThread { updatePushBadge() }
        }
    }

    private fun updatePushBadge() {
        pushBadge.text = if (cachedRegistration.isNotEmpty()) {
            "Push: токен получен (нажми — показать)"
        } else {
            "Push: нет токена (нажми — повторить)"
        }
    }

    private fun showTokenDialog() {
        val scroll = ScrollView(this).apply {
            addView(TextView(this@MainActivity).apply {
                text = cachedRegistration
                textSize = 12f
                setPadding(48, 24, 48, 24)
                setTextIsSelectable(true)
            })
        }
        androidx.appcompat.app.AlertDialog.Builder(this)
            .setTitle("FCM токен")
            .setView(scroll)
            .setPositiveButton("Копировать") { _, _ -> copyToken() }
            .setNegativeButton("Закрыть", null)
            .show()
    }

    private fun copyToken() {
        val cm = getSystemService(Context.CLIPBOARD_SERVICE) as ClipboardManager
        cm.setPrimaryClip(ClipData.newPlainText("FCM token", cachedRegistration))
    }

    private fun askNotificationPermission() {
        if (Build.VERSION.SDK_INT >= 33 &&
            checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS) != PackageManager.PERMISSION_GRANTED
        ) {
            permissionRequest.launch(Manifest.permission.POST_NOTIFICATIONS)
        }
    }
}
