@file:OptIn(ExperimentalSerializationApi::class)

package __PACKAGE__

import kotlinx.serialization.ExperimentalSerializationApi
import kotlinx.serialization.KSerializer
import kotlinx.serialization.SerializationException
import kotlinx.serialization.descriptors.PrimitiveKind
import kotlinx.serialization.descriptors.PrimitiveSerialDescriptor
import kotlinx.serialization.descriptors.SerialDescriptor
import kotlinx.serialization.encoding.Decoder
import kotlinx.serialization.encoding.Encoder
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonDecoder
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonEncoder
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.booleanOrNull
import kotlinx.serialization.json.longOrNull

// Runtime support for the generated contract models (copied verbatim by the generator).
//
// Decoding is tolerant where the protocol needs forward compatibility (unknown keys are ignored
// via ContractJson, unknown enum values decode to Unknown(raw), unknown message types to
// UnknownMessage) and strict about JSON types. Everything JSON Schema expresses beyond types is
// checked by validate().

/** The Json configuration the generated models are made for. */
val ContractJson: Json = Json {
    ignoreUnknownKeys = true
    encodeDefaults = false
    explicitNulls = true
    isLenient = false
    allowSpecialFloatingPointValues = false
}

data class ContractViolation(val path: String, val message: String) {
    override fun toString(): String = "${path.ifEmpty { "/" }}: $message"
}

/** Every generated model, enum and union member. */
interface ContractValue {
    /** Violations of the JSON Schema beyond types (patterns, ranges, const, dependencies, ...). */
    fun validate(path: String = ""): List<ContractViolation>
}

/** Generated string enums: known values plus Unknown(raw). */
interface ContractEnum : ContractValue {
    val value: String
    val isKnown: Boolean

    override fun validate(path: String): List<ContractViolation> =
        if (isKnown) emptyList() else listOf(ContractViolation(path, "unknown value '$value'"))
}

/** A message type (or command) this contract version does not know; kept verbatim. */
data class UnknownMessage(val raw: JsonObject) : __UNKNOWN_SUPERTYPES__ {
    val type: String? get() = (raw["type"] as? JsonPrimitive)?.takeIf { it.isString }?.content

    override fun validate(path: String): List<ContractViolation> = emptyList()
}

/** SQLite boolean as delivered today: JSON boolean or integer 0/1 (known deviation D4 of the contract). */
@kotlinx.serialization.Serializable(with = BoolishSerializer::class)
data class Boolish(val value: Boolean, val isNumeric: Boolean = false)

object BoolishSerializer : KSerializer<Boolish> {
    override val descriptor: SerialDescriptor = PrimitiveSerialDescriptor("__PACKAGE__.Boolish", PrimitiveKind.STRING)

    override fun deserialize(decoder: Decoder): Boolish {
        val input = decoder as? JsonDecoder ?: throw SerializationException("Boolish needs the JSON format")
        val p = input.decodeJsonElement() as? JsonPrimitive ?: throw SerializationException("boolish must be a primitive")
        if (!p.isString) {
            p.booleanOrNull?.let { return Boolish(it) }
            when (p.longOrNull) {
                0L -> return Boolish(false, isNumeric = true)
                1L -> return Boolish(true, isNumeric = true)
                else -> Unit
            }
        }
        throw SerializationException("boolish must be true/false/0/1, got $p")
    }

    override fun serialize(encoder: Encoder, value: Boolish) {
        val output = encoder as? JsonEncoder ?: throw SerializationException("Boolish needs the JSON format")
        output.encodeJsonElement(if (value.isNumeric) JsonPrimitive(if (value.value) 1 else 0) else JsonPrimitive(value.value))
    }
}

// kotlinx.serialization accepts quoted numbers and booleans ("80", "true") even with
// isLenient = false. The contract is strict about JSON types (known deviation D3), so numbers and booleans of the
// generated models go through these serializers.

/** Long that must be a JSON number without fraction. */
typealias StrictLong = @kotlinx.serialization.Serializable(with = StrictLongSerializer::class) Long

/** Double that must be a finite JSON number. */
typealias StrictDouble = @kotlinx.serialization.Serializable(with = StrictDoubleSerializer::class) Double

/** Boolean that must be a JSON true/false literal. */
typealias StrictBoolean = @kotlinx.serialization.Serializable(with = StrictBooleanSerializer::class) Boolean

private fun unquoted(decoder: Decoder, what: String): JsonPrimitive {
    val input = decoder as? JsonDecoder ?: throw SerializationException("$what needs the JSON format")
    val p = input.decodeJsonElement() as? JsonPrimitive
    if (p == null || p.isString || p is JsonNull) throw SerializationException("expected $what, got ${p ?: "non-primitive"}")
    return p
}

object StrictLongSerializer : KSerializer<Long> {
    override val descriptor: SerialDescriptor = PrimitiveSerialDescriptor("__PACKAGE__.StrictLong", PrimitiveKind.LONG)
    override fun deserialize(decoder: Decoder): Long {
        val p = unquoted(decoder, "an integer")
        return p.content.toLongOrNull() ?: throw SerializationException("expected an integer in Long range, got ${p.content}")
    }
    override fun serialize(encoder: Encoder, value: Long) = encoder.encodeLong(value)
}

object StrictDoubleSerializer : KSerializer<Double> {
    override val descriptor: SerialDescriptor = PrimitiveSerialDescriptor("__PACKAGE__.StrictDouble", PrimitiveKind.DOUBLE)
    override fun deserialize(decoder: Decoder): Double {
        val p = unquoted(decoder, "a number")
        val d = p.content.toDoubleOrNull()
        if (d == null || !d.isFinite()) throw SerializationException("expected a finite number, got ${p.content}")
        return d
    }
    override fun serialize(encoder: Encoder, value: Double) = encoder.encodeDouble(value)
}

object StrictBooleanSerializer : KSerializer<Boolean> {
    override val descriptor: SerialDescriptor = PrimitiveSerialDescriptor("__PACKAGE__.StrictBoolean", PrimitiveKind.BOOLEAN)
    override fun deserialize(decoder: Decoder): Boolean =
        unquoted(decoder, "a boolean").booleanOrNull ?: throw SerializationException("expected true/false")
    override fun serialize(encoder: Encoder, value: Boolean) = encoder.encodeBoolean(value)
}

/** Base serializer of generated string enums. */
abstract class ContractEnumSerializer<T : ContractEnum>(name: String, private val of: (String) -> T) : KSerializer<T> {
    override val descriptor: SerialDescriptor = PrimitiveSerialDescriptor(name, PrimitiveKind.STRING)

    override fun deserialize(decoder: Decoder): T = of(decoder.decodeString())

    override fun serialize(encoder: Encoder, value: T) = encoder.encodeString(value.value)
}

internal object ContractUnions {
    fun obj(decoder: Decoder): Pair<Json, JsonObject> {
        val input = decoder as? JsonDecoder ?: throw SerializationException("messages need the JSON format")
        val element = input.decodeJsonElement() as? JsonObject ?: throw SerializationException("message must be a JSON object")
        return input.json to element
    }

    fun stringField(obj: JsonObject, key: String): String? =
        (obj[key] as? JsonPrimitive)?.takeIf { it.isString }?.content

    fun <T> firstOf(json: Json, obj: JsonObject, vararg serializers: KSerializer<out T>): T {
        var error: Exception? = null
        for (s in serializers) {
            try {
                return json.decodeFromJsonElement(s, obj)
            } catch (e: SerializationException) {
                error = error ?: e
            } catch (e: IllegalArgumentException) {
                error = error ?: e
            }
        }
        throw SerializationException("no member accepts the payload: ${error?.message}", error)
    }

    fun encodeRaw(encoder: Encoder, raw: JsonElement) {
        val output = encoder as? JsonEncoder ?: throw SerializationException("messages need the JSON format")
        output.encodeJsonElement(raw)
    }
}

/** Validation helpers used by the generated validate() functions. */
object ContractCheck {
    class StringRule(
        val pattern: Regex? = null,
        val minLength: Int? = null,
        val maxLength: Int? = null,
        val format: String? = null,
        val oneOf: List<String>? = null,
    ) {
        fun violations(value: String, path: String): List<ContractViolation> = buildList {
            if (oneOf != null && value !in oneOf) add(ContractViolation(path, "'$value' is not one of $oneOf"))
            if (pattern != null && !pattern.containsMatchIn(value)) add(ContractViolation(path, "'$value' does not match ${pattern.pattern}"))
            val length = value.codePointCount(0, value.length)
            if (minLength != null && length < minLength) add(ContractViolation(path, "shorter than $minLength"))
            if (maxLength != null && length > maxLength) add(ContractViolation(path, "longer than $maxLength"))
            if (format == "date-time" && !DATE_TIME.containsMatchIn(value)) add(ContractViolation(path, "not an RFC 3339 date-time"))
            if (format == "ipv4" && !IPV4.containsMatchIn(value)) add(ContractViolation(path, "not an IPv4 address"))
        }
    }

    private val DATE_TIME = Regex("^\\d{4}-\\d{2}-\\d{2}[Tt ]\\d{2}:\\d{2}:\\d{2}(\\.\\d+)?([Zz]|[+-]\\d{2}:\\d{2})\\z")
    private val IPV4 = Regex("^((25[0-5]|2[0-4]\\d|1\\d\\d|[1-9]?\\d)\\.){3}(25[0-5]|2[0-4]\\d|1\\d\\d|[1-9]?\\d)\\z")

    fun string(
        out: MutableList<ContractViolation>, path: String, value: String?, rule: StringRule? = null,
        alternatives: List<StringRule>? = null, const: String? = null,
    ) {
        if (value == null) return
        if (const != null && value != const) out += ContractViolation(path, "must be '$const'")
        if (rule != null) out += rule.violations(value, path)
        if (alternatives != null && alternatives.none { it.violations(value, path).isEmpty() }) {
            out += ContractViolation(path, "'$value' matches none of the allowed forms")
        }
    }

    fun long(out: MutableList<ContractViolation>, path: String, value: Long?, minimum: Long? = null, maximum: Long? = null, const: Long? = null) {
        if (value == null) return
        if (const != null && value != const) out += ContractViolation(path, "must be $const")
        if (minimum != null && value < minimum) out += ContractViolation(path, "below minimum $minimum")
        if (maximum != null && value > maximum) out += ContractViolation(path, "above maximum $maximum")
    }

    fun double(out: MutableList<ContractViolation>, path: String, value: Double?, minimum: Double? = null, maximum: Double? = null) {
        if (value == null) return
        if (!value.isFinite()) out += ContractViolation(path, "must be a finite number")
        if (minimum != null && value < minimum) out += ContractViolation(path, "below minimum $minimum")
        if (maximum != null && value > maximum) out += ContractViolation(path, "above maximum $maximum")
    }

    fun bool(out: MutableList<ContractViolation>, path: String, value: Boolean?, const: Boolean) {
        if (value != null && value != const) out += ContractViolation(path, "must be $const")
    }

    fun items(out: MutableList<ContractViolation>, path: String, value: List<*>?, minItems: Int? = null, maxItems: Int? = null, unique: Boolean = false) {
        if (value == null) return
        if (minItems != null && value.size < minItems) out += ContractViolation(path, "fewer than $minItems items")
        if (maxItems != null && value.size > maxItems) out += ContractViolation(path, "more than $maxItems items")
        if (unique && value.toSet().size != value.size) out += ContractViolation(path, "items must be unique")
    }

    fun map(out: MutableList<ContractViolation>, path: String, value: JsonObject?, maxProperties: Int? = null, required: List<String> = emptyList()) {
        if (value == null) return
        if (maxProperties != null && value.size > maxProperties) out += ContractViolation(path, "more than $maxProperties properties")
        for (key in required) if (key !in value) out += ContractViolation(path, "'$key' is required")
    }

    fun nested(out: MutableList<ContractViolation>, path: String, value: ContractValue?) {
        if (value != null) out += value.validate(path)
    }

    fun nested(out: MutableList<ContractViolation>, path: String, value: List<ContractValue>?) {
        value?.forEachIndexed { i, item -> out += item.validate("$path/$i") }
    }

    class Conditional(
        val matched: Boolean,
        val thenRequired: List<String> = emptyList(),
        val thenForbidden: List<String> = emptyList(),
        val elseRequired: List<String> = emptyList(),
        val elseForbidden: List<String> = emptyList(),
    )

    /** Object-level rules. present: keys with a non-null value (null and absent look the same here). */
    fun obj(
        out: MutableList<ContractViolation>, path: String, present: Set<String>,
        dependentRequired: Map<String, List<String>> = emptyMap(), anyOfRequired: List<List<String>> = emptyList(),
        forbidden: List<String> = emptyList(), conditionals: List<Conditional> = emptyList(),
    ) {
        for ((key, needed) in dependentRequired.toSortedMap()) {
            if (key !in present) continue
            for (n in needed) if (n !in present) out += ContractViolation(path, "'$n' is required when '$key' is present")
        }
        if (anyOfRequired.isNotEmpty() && anyOfRequired.none { group -> group.all { it in present } }) {
            out += ContractViolation(path, "one of $anyOfRequired is required")
        }
        for (n in forbidden) if (n in present) out += ContractViolation("$path/$n", "must not be present")
        for (c in conditionals) {
            val req = if (c.matched) c.thenRequired else c.elseRequired
            val forb = if (c.matched) c.thenForbidden else c.elseForbidden
            for (n in req) if (n !in present) out += ContractViolation(path, "'$n' is required here")
            for (n in forb) if (n in present) out += ContractViolation("$path/$n", "must not be present here")
        }
    }
}
