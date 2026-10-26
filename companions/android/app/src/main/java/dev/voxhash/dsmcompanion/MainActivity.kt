package dev.voxhash.dsmcompanion

import android.os.Bundle
import android.widget.Toast
import androidx.appcompat.app.AppCompatActivity
import androidx.lifecycle.lifecycleScope
import dev.voxhash.dsmcompanion.databinding.ActivityMainBinding
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

class MainActivity : AppCompatActivity() {
    private lateinit var binding: ActivityMainBinding
    private lateinit var store: PairingStore

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        binding = ActivityMainBinding.inflate(layoutInflater)
        setContentView(binding.root)
        store = PairingStore(this)

        binding.inputBaseUrl.setText(store.baseUrl)
        binding.inputToken.setText(store.bearerToken)

        binding.btnSave.setOnClickListener {
            store.baseUrl = binding.inputBaseUrl.text?.toString().orEmpty()
            store.bearerToken = binding.inputToken.text?.toString().orEmpty()
            Toast.makeText(this, "Pairing saved (encrypted prefs)", Toast.LENGTH_SHORT).show()
        }
        binding.btnClear.setOnClickListener {
            store.clearToken()
            binding.inputToken.setText("")
            Toast.makeText(this, "Token cleared", Toast.LENGTH_SHORT).show()
        }
        binding.btnHealth.setOnClickListener { runCall("health") { it.health() } }
        binding.btnConnections.setOnClickListener { runCall("connections") { it.connections() } }
        binding.btnBackups.setOnClickListener { runCall("backups") { it.backups() } }
    }

    private fun runCall(label: String, block: (ApiClient) -> ApiClient.Result) {
        val base = binding.inputBaseUrl.text?.toString()?.trim().orEmpty().ifBlank {
            store.baseUrl
        }
        val token = binding.inputToken.text?.toString()?.trim().orEmpty().ifBlank {
            store.bearerToken
        }
        binding.output.text = "Loading $label…"
        lifecycleScope.launch {
            val result = withContext(Dispatchers.IO) {
                try {
                    block(ApiClient(base, token))
                } catch (ex: Exception) {
                    ApiClient.Result(-1, ex.message ?: ex.toString())
                }
            }
            binding.output.text = "HTTP ${result.code}\n\n${result.body}"
        }
    }
}
