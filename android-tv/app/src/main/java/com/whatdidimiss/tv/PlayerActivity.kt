package com.whatdidimiss.tv

import android.content.Context
import android.content.Intent
import android.graphics.Bitmap
import android.os.Bundle
import android.os.SystemClock
import android.speech.RecognizerIntent
import android.speech.SpeechRecognizer
import android.util.Base64
import android.view.KeyEvent
import android.view.TextureView
import android.view.View
import android.view.ViewGroup
import android.view.inputmethod.EditorInfo
import android.view.inputmethod.InputMethodManager
import android.widget.Button
import android.widget.EditText
import android.widget.ProgressBar
import android.widget.TextView
import androidx.activity.result.contract.ActivityResultContracts
import androidx.appcompat.app.AppCompatActivity
import androidx.lifecycle.lifecycleScope
import androidx.media3.common.MediaItem
import androidx.media3.common.Player
import androidx.media3.exoplayer.ExoPlayer
import androidx.media3.ui.PlayerView
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch
import kotlin.coroutines.coroutineContext
import kotlinx.coroutines.withContext
import java.io.ByteArrayOutputStream

class PlayerActivity : AppCompatActivity() {

    companion object {
        const val EXTRA_TITLE_ID = "title_id"
        const val EXTRA_TITLE_NAME = "title_name"
        const val EXTRA_VIDEO_URL = "video_url"
        private const val RECAP_WINDOW_S = 300.0
        private const val RESUME_MIN_S = 60.0
        private const val SKIP_MIN_S = 30.0
        private const val SKIP_HINT_MS = 10_000L
        private const val SEEK_BURST_MS = 5_000L
    }

    private lateinit var player: ExoPlayer
    private lateinit var playerView: PlayerView
    private lateinit var chips: View
    private lateinit var card: View
    private lateinit var headline: TextView
    private lateinit var answer: TextView
    private lateinit var badge: TextView
    private lateinit var progress: ProgressBar
    private lateinit var askInput: EditText
    private lateinit var firstSeen: TextView
    private lateinit var menuHint: TextView
    private lateinit var knowledgeBar: KnowledgeBarView
    private lateinit var jumpButton: Button
    private lateinit var titleId: String
    private var pending: Job? = null
    private var skippedFromS: Double? = null
    private var seekOriginMs = 0L
    private var lastSeekAtMs = 0L

    private val prefs by lazy { getSharedPreferences("positions", Context.MODE_PRIVATE) }

    private val speech = registerForActivityResult(ActivityResultContracts.StartActivityForResult()) { res ->
        val text = res.data?.getStringArrayListExtra(RecognizerIntent.EXTRA_RESULTS)?.firstOrNull()
        if (text.isNullOrBlank()) showTypedAsk() else ask("ask", question = text)
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_player)
        titleId = intent.getStringExtra(EXTRA_TITLE_ID)!!

        playerView = findViewById(R.id.player_view)
        chips = findViewById(R.id.chips)
        card = findViewById(R.id.answer_card)
        headline = findViewById(R.id.headline)
        answer = findViewById(R.id.answer)
        badge = findViewById(R.id.spoiler_badge)
        progress = findViewById(R.id.progress)
        askInput = findViewById(R.id.ask_input)
        firstSeen = findViewById(R.id.first_seen)
        menuHint = findViewById(R.id.menu_hint)
        knowledgeBar = findViewById(R.id.knowledge_bar)
        jumpButton = findViewById(R.id.jump_button)

        player = ExoPlayer.Builder(this).build().also { playerView.player = it }
        player.setMediaItem(MediaItem.fromUri(intent.getStringExtra(EXTRA_VIDEO_URL)!!))
        player.prepare()

        val resumeAt = prefs.getFloat(titleId, 0f).toDouble()
        if (resumeAt > RESUME_MIN_S) {
            player.seekTo((resumeAt * 1000).toLong())
            ask("recap", fromS = 0.0, headlineOverride = getString(R.string.previously))
        } else {
            player.play()
        }

        player.addListener(object : Player.Listener {
            override fun onPositionDiscontinuity(
                oldPosition: Player.PositionInfo,
                newPosition: Player.PositionInfo,
                reason: Int,
            ) {
                if (reason != Player.DISCONTINUITY_REASON_SEEK) return
                // Remote seeks come in 15 s steps: treat a burst of them as one skip.
                val now = SystemClock.uptimeMillis()
                if (now - lastSeekAtMs > SEEK_BURST_MS) seekOriginMs = oldPosition.positionMs
                lastSeekAtMs = now
                val jumpS = (newPosition.positionMs - seekOriginMs) / 1000.0
                if (jumpS > SKIP_MIN_S) onSkippedAhead(seekOriginMs / 1000.0, jumpS)
                else if (jumpS <= 0 && skippedFromS != null) resetHint.run()
            }
        })

        findViewById<View>(R.id.chip_who).setOnClickListener { ask("who", withFrame = true) }
        findViewById<View>(R.id.chip_recap).setOnClickListener {
            val from = skippedFromS ?: (positionS() - RECAP_WINDOW_S).coerceAtLeast(0.0)
            skippedFromS = null
            ask("recap", fromS = from)
        }
        findViewById<View>(R.id.chip_explain).setOnClickListener { ask("explain", withFrame = true) }
        findViewById<View>(R.id.chip_back).setOnClickListener {
            showTypedAsk(getString(R.string.ask_back_prefill))
        }
        findViewById<View>(R.id.chip_ask).setOnClickListener { startVoiceAsk() }
        askInput.setOnEditorActionListener { _, actionId, event ->
            val enter = actionId == EditorInfo.IME_ACTION_SEND ||
                (event?.keyCode == KeyEvent.KEYCODE_ENTER && event.action == KeyEvent.ACTION_DOWN)
            if (enter && askInput.text.isNotBlank()) {
                val q = askInput.text.toString()
                askInput.text.clear()
                askInput.visibility = View.GONE
                hideKeyboard()
                ask("ask", question = q, withFrame = true)
            }
            enter
        }
    }

    override fun dispatchKeyEvent(event: KeyEvent): Boolean {
        if (event.action == KeyEvent.ACTION_DOWN) {
            when (event.keyCode) {
                KeyEvent.KEYCODE_MENU -> {
                    if (chips.visibility == View.VISIBLE) hideOverlay() else showChips()
                    return true
                }
                KeyEvent.KEYCODE_BACK -> if (chips.visibility == View.VISIBLE || card.visibility == View.VISIBLE) {
                    hideOverlay()
                    return true
                }
            }
        }
        return super.dispatchKeyEvent(event)
    }

    /** Viewer jumped ahead: offer a recap of exactly the part they skipped. */
    private fun onSkippedAhead(fromS: Double, jumpS: Double) {
        skippedFromS = fromS
        menuHint.text = getString(R.string.hint_skipped, formatTs(jumpS))
        menuHint.removeCallbacks(resetHint)
        menuHint.postDelayed(resetHint, SKIP_HINT_MS)
    }

    private val resetHint = Runnable {
        skippedFromS = null
        menuHint.setText(R.string.hint_menu)
    }

    private fun showChips() {
        playerView.hideController()
        playerView.useController = false
        // Keep D-pad focus inside the overlay instead of the player surface.
        playerView.descendantFocusability = ViewGroup.FOCUS_BLOCK_DESCENDANTS
        playerView.isFocusable = false
        chips.visibility = View.VISIBLE
        menuHint.removeCallbacks(resetHint) // keep the skip range while the overlay is open
        findViewById<View>(if (skippedFromS != null) R.id.chip_recap else R.id.chip_who).requestFocus()
    }

    private fun hideOverlay() {
        pending?.cancel()
        resetHint.run()
        chips.visibility = View.GONE
        card.visibility = View.GONE
        askInput.visibility = View.GONE
        playerView.descendantFocusability = ViewGroup.FOCUS_AFTER_DESCENDANTS
        playerView.isFocusable = true
        playerView.useController = true
        player.play()
    }

    private fun positionS() = player.currentPosition / 1000.0

    private fun ask(
        mode: String,
        question: String? = null,
        withFrame: Boolean = false,
        fromS: Double? = null,
        headlineOverride: String? = null,
    ) {
        player.pause()
        val pos = positionS()
        val focused = currentFocus
        card.visibility = View.VISIBLE
        badge.text = getString(R.string.spoiler_badge, formatTs(pos))
        headline.text = headlineOverride ?: question ?: ""
        answer.text = getString(R.string.thinking)
        firstSeen.visibility = View.GONE
        knowledgeBar.visibility = View.GONE
        jumpButton.visibility = View.GONE
        progress.visibility = View.VISIBLE

        pending?.cancel()
        pending = lifecycleScope.launch {
            try {
                val frame = if (withFrame) captureFrame() else null
                val res = CompanionApi.ask(titleId, pos, mode, question, frame, fromS)
                headline.text = headlineOverride ?: res.headline
                answer.text = res.text
                res.character?.let {
                    firstSeen.text = getString(R.string.first_seen, it.name, formatTs(it.firstSeenS))
                    firstSeen.visibility = View.VISIBLE
                }
                knowledgeBar.bind(res.durationS, res.positionS, res.markers, res.range)
                res.seekToS?.let { target ->
                    jumpButton.text = getString(R.string.jump_to, formatTs(target))
                    jumpButton.visibility = View.VISIBLE
                    jumpButton.setOnClickListener {
                        player.seekTo((target * 1000).toLong())
                        hideOverlay()
                    }
                    jumpButton.requestFocus()
                }
                // Same moments on the player's own seek bar once the overlay is closed.
                playerView.setExtraAdGroupMarkers(
                    res.markers.map { (it.t * 1000).toLong() }.toLongArray(),
                    BooleanArray(res.markers.size) { true },
                )
            } catch (e: Exception) {
                if (e is kotlinx.coroutines.CancellationException) throw e
                answer.text = getString(R.string.error_answer, e.message)
            } finally {
                // A question the viewer replaced must not touch the overlay on its way out:
                // restoring focus here would yank it off whatever they just moved to.
                if (coroutineContext.isActive) {
                    progress.visibility = View.GONE
                    if (chips.visibility == View.VISIBLE && jumpButton.visibility != View.VISIBLE &&
                        focused != null && !focused.isFocused) focused.requestFocus()
                }
            }
        }
    }

    /** Current video frame as base64 JPEG (512px wide), or null if the surface isn't ready. */
    private suspend fun captureFrame(): String? {
        val bitmap: Bitmap = (playerView.videoSurfaceView as? TextureView)?.bitmap ?: return null
        return withContext(Dispatchers.Default) {
            val scaled = Bitmap.createScaledBitmap(bitmap, 512, 512 * bitmap.height / bitmap.width, true)
            val out = ByteArrayOutputStream()
            scaled.compress(Bitmap.CompressFormat.JPEG, 75, out)
            Base64.encodeToString(out.toByteArray(), Base64.NO_WRAP)
        }
    }

    private fun startVoiceAsk() {
        if (!SpeechRecognizer.isRecognitionAvailable(this)) {
            showTypedAsk()
            return
        }
        player.pause()
        val intent = Intent(RecognizerIntent.ACTION_RECOGNIZE_SPEECH)
            .putExtra(RecognizerIntent.EXTRA_LANGUAGE_MODEL, RecognizerIntent.LANGUAGE_MODEL_FREE_FORM)
        try {
            speech.launch(intent)
        } catch (e: Exception) {
            showTypedAsk()
        }
    }

    /** Fallback when no speech recognizer is exposed to apps: the Fire TV keyboard (which has its own mic). */
    private fun showTypedAsk(prefill: String = "") {
        player.pause()
        askInput.visibility = View.VISIBLE
        askInput.setText(prefill)
        askInput.setSelection(prefill.length)
        askInput.requestFocus()
        getSystemService(InputMethodManager::class.java)?.showSoftInput(askInput, InputMethodManager.SHOW_IMPLICIT)
    }

    private fun hideKeyboard() {
        getSystemService(InputMethodManager::class.java)?.hideSoftInputFromWindow(askInput.windowToken, 0)
    }

    private fun formatTs(s: Double): String {
        val t = s.toInt()
        return if (t >= 3600) "%d:%02d:%02d".format(t / 3600, t % 3600 / 60, t % 60)
        else "%d:%02d".format(t / 60, t % 60)
    }

    override fun onStop() {
        super.onStop()
        prefs.edit().putFloat(titleId, positionS().toFloat()).apply()
        player.pause()
    }

    override fun onDestroy() {
        super.onDestroy()
        player.release()
    }
}
