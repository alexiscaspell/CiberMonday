package com.cibermonday.server

import android.view.LayoutInflater
import android.view.View
import android.view.ViewGroup
import android.widget.*
import androidx.recyclerview.widget.RecyclerView
import org.json.JSONObject
import java.text.SimpleDateFormat
import java.util.*

data class Client(
    val id: String,
    val name: String,
    val isActive: Boolean,
    val currentSession: SessionInfo?
)

data class SessionInfo(
    val timeLimit: Int,
    val startTime: String,
    val endTime: String,
    val remainingSeconds: Int
)

class ClientAdapter(
    private val onSetTime: (clientId: String, time: Int, unit: String) -> Unit,
    private val onStopSession: (clientId: String) -> Unit,
    private val onDeleteClient: (clientId: String) -> Unit
) : RecyclerView.Adapter<ClientAdapter.ClientViewHolder>() {

    private var clients: List<Client> = emptyList()
    private val timeUnits = arrayOf("Minutos", "Horas")

    fun updateClients(newClients: List<Client>) {
        clients = newClients
        notifyDataSetChanged()
    }

    override fun onCreateViewHolder(parent: ViewGroup, viewType: Int): ClientViewHolder {
        val view = LayoutInflater.from(parent.context)
            .inflate(R.layout.item_client, parent, false)
        return ClientViewHolder(view)
    }

    override fun onBindViewHolder(holder: ClientViewHolder, position: Int) {
        holder.bind(clients[position])
    }

    override fun getItemCount(): Int = clients.size

    inner class ClientViewHolder(itemView: View) : RecyclerView.ViewHolder(itemView) {
        private val tvClientName: TextView = itemView.findViewById(R.id.tvClientName)
        private val tvClientId: TextView = itemView.findViewById(R.id.tvClientId)
        private val tvClientStatus: TextView = itemView.findViewById(R.id.tvClientStatus)
        private val sessionInfoContainer: View = itemView.findViewById(R.id.sessionInfoContainer)
        private val tvTimeLimit: TextView = itemView.findViewById(R.id.tvTimeLimit)
        private val tvTimeRemaining: TextView = itemView.findViewById(R.id.tvTimeRemaining)
        private val tvStartTime: TextView = itemView.findViewById(R.id.tvStartTime)
        private val etTimeValue: EditText = itemView.findViewById(R.id.etTimeValue)
        private val spinnerTimeUnit: Spinner = itemView.findViewById(R.id.spinnerTimeUnit)
        private val btnSetTime: Button = itemView.findViewById(R.id.btnSetTime)
        private val btnStop: Button = itemView.findViewById(R.id.btnStop)
        private val btnDelete: Button = itemView.findViewById(R.id.btnDelete)

        init {
            val adapter = ArrayAdapter(itemView.context, android.R.layout.simple_spinner_item, timeUnits)
            adapter.setDropDownViewResource(android.R.layout.simple_spinner_dropdown_item)
            spinnerTimeUnit.adapter = adapter
        }

        fun bind(client: Client) {
            tvClientName.text = client.name
            tvClientId.text = "ID: ${client.id.take(8)}..."

            // Estado
            if (client.isActive) {
                tvClientStatus.text = "ACTIVO"
                tvClientStatus.setBackgroundResource(R.drawable.status_active_bg)
            } else {
                tvClientStatus.text = "INACTIVO"
                tvClientStatus.setBackgroundResource(R.drawable.status_inactive_bg)
            }

            // Sesión
            val session = client.currentSession
            if (session != null) {
                sessionInfoContainer.visibility = View.VISIBLE
                btnStop.visibility = View.VISIBLE

                tvTimeLimit.text = "Tiempo asignado: ${formatTime(session.timeLimit)}"
                
                val remaining = session.remainingSeconds
                tvTimeRemaining.text = formatTime(remaining)
                
                if (remaining <= 0) {
                    tvTimeRemaining.text = "EXPIRADO"
                    tvTimeRemaining.setTextColor(0xFFF44336.toInt())
                } else {
                    tvTimeRemaining.setTextColor(0xFF667EEA.toInt())
                }

                // Formatear hora de inicio
                try {
                    val isoFormat = SimpleDateFormat("yyyy-MM-dd'T'HH:mm:ss", Locale.getDefault())
                    val date = isoFormat.parse(session.startTime.split(".")[0])
                    val timeFormat = SimpleDateFormat("HH:mm:ss", Locale.getDefault())
                    tvStartTime.text = "Inicio: ${timeFormat.format(date!!)}"
                } catch (e: Exception) {
                    tvStartTime.text = "Inicio: ${session.startTime}"
                }
            } else {
                sessionInfoContainer.visibility = View.GONE
                btnStop.visibility = View.GONE
            }

            // Botones
            btnSetTime.setOnClickListener {
                val timeValue = etTimeValue.text.toString().toIntOrNull() ?: 0
                if (timeValue > 0) {
                    val unit = if (spinnerTimeUnit.selectedItemPosition == 1) "hours" else "minutes"
                    onSetTime(client.id, timeValue, unit)
                }
            }

            btnStop.setOnClickListener {
                onStopSession(client.id)
            }

            btnDelete.setOnClickListener {
                onDeleteClient(client.id)
            }
        }

        private fun formatTime(seconds: Int): String {
            if (seconds <= 0) return "0s"
            
            val hours = seconds / 3600
            val minutes = (seconds % 3600) / 60
            val secs = seconds % 60

            return when {
                hours > 0 -> "${hours}h ${minutes}m ${secs}s"
                minutes > 0 -> "${minutes}m ${secs}s"
                else -> "${secs}s"
            }
        }
    }

    companion object {
        fun parseClientsFromJson(json: String): List<Client> {
            val clients = mutableListOf<Client>()
            try {
                val jsonArray = org.json.JSONArray(json)
                for (i in 0 until jsonArray.length()) {
                    val obj = jsonArray.getJSONObject(i)
                    
                    val session = if (obj.has("current_session") && !obj.isNull("current_session")) {
                        val sessionObj = obj.getJSONObject("current_session")
                        SessionInfo(
                            timeLimit = sessionObj.optInt("time_limit", 0),
                            startTime = sessionObj.optString("start_time", ""),
                            endTime = sessionObj.optString("end_time", ""),
                            remainingSeconds = sessionObj.optInt("remaining_seconds", 0)
                        )
                    } else null

                    clients.add(Client(
                        id = obj.getString("id"),
                        name = obj.optString("name", "Sin nombre"),
                        isActive = obj.optBoolean("is_active", false),
                        currentSession = session
                    ))
                }
            } catch (e: Exception) {
                e.printStackTrace()
            }
            return clients
        }
    }
}
