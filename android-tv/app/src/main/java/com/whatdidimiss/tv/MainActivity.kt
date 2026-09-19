package com.whatdidimiss.tv

import android.content.Intent
import android.os.Bundle
import android.view.View
import android.widget.Button
import android.widget.LinearLayout
import android.widget.TextView
import androidx.appcompat.app.AppCompatActivity
import androidx.lifecycle.lifecycleScope
import kotlinx.coroutines.launch

class MainActivity : AppCompatActivity() {

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_main)
        val status = findViewById<TextView>(R.id.status)
        val row = findViewById<LinearLayout>(R.id.titles)

        lifecycleScope.launch {
            val titles = try {
                CompanionApi.titles()
            } catch (e: Exception) {
                status.text = getString(R.string.titles_error, CompanionApi.endpoint) + "\n" + e.message
                return@launch
            }
            status.visibility = View.GONE
            titles.forEach { t ->
                val button = layoutInflater.inflate(R.layout.item_title, row, false) as Button
                button.text = "${t.name}\n${t.kind}"
                button.setOnClickListener {
                    startActivity(
                        Intent(this@MainActivity, PlayerActivity::class.java)
                            .putExtra(PlayerActivity.EXTRA_TITLE_ID, t.id)
                            .putExtra(PlayerActivity.EXTRA_TITLE_NAME, t.name)
                            .putExtra(PlayerActivity.EXTRA_VIDEO_URL, t.videoUrl)
                    )
                }
                row.addView(button)
            }
            row.getChildAt(0)?.requestFocus()
        }
    }
}
