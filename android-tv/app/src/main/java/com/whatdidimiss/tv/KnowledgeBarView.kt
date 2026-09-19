package com.whatdidimiss.tv

import android.content.Context
import android.graphics.Canvas
import android.graphics.Color
import android.graphics.Paint
import android.graphics.RectF
import android.util.AttributeSet
import android.view.View
import androidx.core.content.ContextCompat

/**
 * The spoiler fence made visible: the watched part of the title with the moments an answer
 * draws on, a line at the viewer's position, and everything after it hatched out as
 * "hidden from the AI".
 */
class KnowledgeBarView @JvmOverloads constructor(
    context: Context, attrs: AttributeSet? = null,
) : View(context, attrs) {

    private var durationS = 0.0
    private var fenceS = 0.0
    private var markers: List<Marker> = emptyList()
    private var range: ClosedFloatingPointRange<Double>? = null

    private val dp = resources.displayMetrics.density
    private val accent = ContextCompat.getColor(context, R.color.accent)
    private val muted = ContextCompat.getColor(context, R.color.muted)

    private val track = Paint(Paint.ANTI_ALIAS_FLAG).apply { color = Color.argb(40, 255, 255, 255) }
    private val watched = Paint(Paint.ANTI_ALIAS_FLAG).apply { color = Color.argb(120, 255, 255, 255) }
    private val rangePaint = Paint(Paint.ANTI_ALIAS_FLAG).apply { color = accent }
    private val hatch = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        color = Color.argb(70, 255, 255, 255); strokeWidth = 1.5f * dp
    }
    private val fence = Paint(Paint.ANTI_ALIAS_FLAG).apply { color = Color.WHITE; strokeWidth = 2 * dp }
    private val appearanceDot = Paint(Paint.ANTI_ALIAS_FLAG).apply { color = Color.WHITE }
    private val momentDot = Paint(Paint.ANTI_ALIAS_FLAG).apply { color = accent }
    private val dotRing = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        color = Color.BLACK; style = Paint.Style.STROKE; strokeWidth = 1.5f * dp
    }
    private val label = Paint(Paint.ANTI_ALIAS_FLAG).apply { color = muted; textSize = 12 * dp }

    fun bind(durationS: Double, fenceS: Double, markers: List<Marker>, range: ClosedFloatingPointRange<Double>?) {
        this.durationS = durationS
        this.fenceS = fenceS
        this.markers = markers
        this.range = range
        visibility = if (durationS > 0) VISIBLE else GONE
        invalidate()
    }

    override fun onMeasure(widthMeasureSpec: Int, heightMeasureSpec: Int) {
        setMeasuredDimension(MeasureSpec.getSize(widthMeasureSpec), (40 * dp).toInt())
    }

    override fun onDraw(canvas: Canvas) {
        if (durationS <= 0) return
        val w = width.toFloat()
        val barTop = 12 * dp
        val barH = 8 * dp
        val cy = barTop + barH / 2
        fun x(t: Double) = (t / durationS * w).toFloat().coerceIn(0f, w)
        val fx = x(fenceS)

        canvas.drawRoundRect(RectF(0f, barTop, w, barTop + barH), barH / 2, barH / 2, track)
        canvas.drawRoundRect(RectF(0f, barTop, fx, barTop + barH), barH / 2, barH / 2, watched)
        // The part a recap covers: accent and slightly taller so it reads apart from "watched".
        range?.let {
            val r = RectF(x(it.start), barTop - 2 * dp, x(it.endInclusive), barTop + barH + 2 * dp)
            canvas.drawRoundRect(r, 3 * dp, 3 * dp, rangePaint)
        }

        // Hatched future: what the model is never shown.
        canvas.save()
        canvas.clipRect(fx, barTop, w, barTop + barH)
        var hx = fx - barH
        while (hx < w) {
            canvas.drawLine(hx, barTop + barH, hx + barH, barTop, hatch)
            hx += 6 * dp
        }
        canvas.restore()

        // Dots closer than their diameter merge into the earlier one (an appearance wins a tie).
        var lastX = Float.NEGATIVE_INFINITY
        for (m in markers.sortedWith(compareBy({ it.t }, { it.kind != "appearance" }))) {
            val mx = x(m.t)
            if (mx - lastX < 10 * dp) continue
            lastX = mx
            val paint = if (m.kind == "appearance") appearanceDot else momentDot
            canvas.drawCircle(mx, cy, 5 * dp, paint)
            canvas.drawCircle(mx, cy, 5 * dp, dotRing)
        }

        canvas.drawLine(fx, barTop - 6 * dp, fx, barTop + barH + 6 * dp, fence)

        val hidden = context.getString(R.string.hidden_from_ai)
        val hiddenW = label.measureText(hidden)
        if (w - fx > hiddenW + 12 * dp) canvas.drawText(hidden, fx + 8 * dp, barTop + barH + 18 * dp, label)
        val seen = context.getString(R.string.seen_so_far)
        if (fx > label.measureText(seen) + 8 * dp) canvas.drawText(seen, 0f, barTop + barH + 18 * dp, label)
    }

    data class Marker(val t: Double, val kind: String)
}
