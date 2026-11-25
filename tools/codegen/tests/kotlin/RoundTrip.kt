// Round-trip harness for the generated Kotlin models (run by tools/codegen/tests/test_codegen.py).
// Usage: RoundTripKt <contracts root> <manifest.json> <results.json>
package harness

import hubcontracts.ClientMessageSerializer
import hubcontracts.ContractJson
import hubcontracts.ContractSchemaRegistry
import hubcontracts.ContractValue
import hubcontracts.ControlMode
import hubcontracts.ServerMessageSerializer
import hubcontracts.UnknownMessage
import kotlinx.serialization.KSerializer
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import kotlinx.serialization.json.put
import java.io.File
import kotlin.system.exitProcess

@Suppress("UNCHECKED_CAST")
private fun serializer(path: String) = ContractSchemaRegistry.serializerFor(path) as KSerializer<ContractValue>

private fun roundTrip(path: String, text: String): Pair<ContractValue, JsonElement> {
    val s = serializer(path)
    val value = ContractJson.decodeFromString(s, text)
    return value to ContractJson.parseToJsonElement(ContractJson.encodeToString(s, value))
}

private fun error(e: Throwable): String = "${e::class.simpleName}: ${e.message}"

private fun selfChecks(): List<String> {
    val failures = mutableListOf<String>()
    fun check(name: String, ok: Boolean) { if (!ok) failures += name }
    val turbo = ContractJson.decodeFromString(ControlMode.serializer(), "\"turbo\"")
    check("unknown enum decodes to Unknown", turbo is ControlMode.Unknown && !turbo.isKnown)
    check("unknown enum re-encodes raw", ContractJson.encodeToString(ControlMode.serializer(), turbo) == "\"turbo\"")
    check("unknown enum reported by validate", turbo.validate().size == 1)
    check("enum equality by value", ControlMode.of("full") == ControlMode.Full && ControlMode.Unknown("full") == ControlMode.Full)
    val unknown = ContractJson.decodeFromString(ServerMessageSerializer, """{"type":"future_thing","x":1}""")
    check("unknown type -> UnknownMessage", unknown is UnknownMessage)
    check("unknown message re-encodes verbatim",
        ContractJson.encodeToString(ServerMessageSerializer, unknown) == """{"type":"future_thing","x":1}""")
    check("unknown command -> UnknownMessage",
        ContractJson.decodeFromString(ServerMessageSerializer, """{"type":"command","command":"teleport"}""") is UnknownMessage)
    fun throws(block: () -> Unit) = try { block(); false } catch (e: Exception) { true }
    val status = serializer("ws/client/client_status")
    check("string for integer throws", throws { ContractJson.decodeFromString(status, """{"type":"client_status","battery_level":"80"}""") })
    check("quoted boolean throws", throws {
        ContractJson.decodeFromString(serializer("integration/owner-token.response"), """{"success":"true","owner_token_configured":true}""")
    })
    check("integer overflow throws", throws { ContractJson.decodeFromString(status, """{"type":"client_status","battery_level":99999999999999999999}""") })
    check("fraction for integer throws", throws { ContractJson.decodeFromString(status, """{"type":"client_status","battery_level":1.5}""") })
    val msg = ContractJson.decodeFromString(ClientMessageSerializer, """{"type":"get_areas"}""")
    check("built message keeps discriminator", ContractJson.encodeToString(ClientMessageSerializer, msg) == """{"type":"get_areas"}""")
    val pair = ContractJson.decodeFromString(serializer("ws/client/pair"), "{\"type\":\"pair\",\"pin\":\"1234-5678\\n\",\"client_name\":\"x\",\"protocol_version\":1,\"platform\":\"ios\",\"app_version\":\"2026.12.0\"}")
    check("trailing newline does not match ^...$", pair.validate().size == 1)
    val pairOk = hubcontracts.ServerPairOk(
        clientId = "c", clientName = "n", secret = "ab".repeat(32),
        protocolVersion = 1L, minProtocolVersion = 1L, minAppVersion = hubcontracts.MinAppVersion(),
    )
    check("sensitive field redacted in toString", !pairOk.toString().contains("abab"))
    return failures
}

fun main(args: Array<String>) {
    val root = File(args[0])
    val manifest = ContractJson.parseToJsonElement(File(args[1]).readText()).jsonArray
    val failures = selfChecks()
    if (failures.isNotEmpty()) {
        System.err.println("self checks failed: $failures")
        exitProcess(1)
    }
    val results = buildJsonObject {
        for (entry in manifest) {
            val e = entry.jsonObject
            val fixture = e["fixture"]!!.jsonPrimitive.content
            val schema = e["schema"]!!.jsonPrimitive.content
            val union = (e["union"] as? JsonPrimitive)?.takeIf { it.isString }?.content
            val text = File(root, fixture).readText()
            put(fixture, buildJsonObject {
                try {
                    val (value, output) = roundTrip(schema, text)
                    put("decoded", true)
                    put("violations", JsonArray(value.validate().map { JsonPrimitive(it.toString()) }))
                    put("output", output)
                } catch (ex: Exception) {
                    put("decoded", false)
                    put("error", error(ex))
                    put("violations", JsonArray(emptyList()))
                }
                if (union != null) {
                    try {
                        val (value, output) = roundTrip(union, text)
                        put("unionMember", value::class.simpleName)
                        put("unionOutput", output)
                    } catch (ex: Exception) {
                        put("unionError", error(ex))
                    }
                } else {
                    put("unionMember", JsonNull)
                }
            })
        }
    }
    File(args[2]).writeText(results.toString())
}
