import Foundation
import Testing

@testable import HubModels

// Round trip over the golden fixtures. The manifest (fixture, schema, expected union member) is
// written by tools/codegen/tests/test_codegen.py; the results are compared there against the
// projection of each fixture, so Python, Swift and Kotlin share one comparison.

private struct ManifestEntry: Decodable {
    let fixture: String
    let schema: String
    let union: String?
}

private struct Result: Encodable {
    var decoded = false
    var error: String?
    var violations: [String] = []
    var output: JSONValue?
    var unionMember: String?
    var unionError: String?
    var unionOutput: JSONValue?
}

@Test func goldenFixturesRoundTrip() throws {
    let env = ProcessInfo.processInfo.environment
    guard let manifestPath = env["ROUNDTRIP_MANIFEST"], let outPath = env["ROUNDTRIP_OUT"],
          let root = env["CONTRACTS_ROOT"]
    else {
        print("ROUNDTRIP_MANIFEST/ROUNDTRIP_OUT/CONTRACTS_ROOT not set; skipped (run via test_codegen.py)")
        return
    }
    let manifest = try JSONDecoder().decode([ManifestEntry].self, from: Data(contentsOf: URL(fileURLWithPath: manifestPath)))
    let encoder = JSONEncoder()
    var results: [String: Result] = [:]
    for entry in manifest {
        let data = try Data(contentsOf: URL(fileURLWithPath: root).appendingPathComponent(entry.fixture))
        var r = Result()
        do {
            let value = try ContractSchemaRegistry.decode(entry.schema, from: data)
            r.decoded = true
            r.violations = value.validate().map(\.description)
            r.output = try JSONDecoder().decode(JSONValue.self, from: encoder.encode(value))
        } catch {
            r.error = String(describing: error)
        }
        if let union = entry.union {
            do {
                let value = try ContractSchemaRegistry.decode(union, from: data)
                let payload: any ContractValue
                switch value {
                case let m as ServerMessage: payload = m.value
                case let m as ClientMessage: payload = m.value
                default: payload = value
                }
                r.unionMember = String(describing: type(of: payload))
                r.unionOutput = try JSONDecoder().decode(JSONValue.self, from: encoder.encode(value))
            } catch {
                r.unionError = String(describing: error)
            }
        }
        results[entry.fixture] = r
    }
    let out = JSONEncoder()
    out.outputFormatting = [.sortedKeys, .prettyPrinted]
    try out.encode(results).write(to: URL(fileURLWithPath: outPath))
}

// MARK: - Tolerance and robustness

private func decode<T: Decodable>(_ type: T.Type, _ json: String) throws -> T {
    try JSONDecoder().decode(type, from: Data(json.utf8))
}

private func encodeString<T: Encodable>(_ value: T) throws -> String {
    let e = JSONEncoder()
    e.outputFormatting = .sortedKeys
    return String(decoding: try e.encode(value), as: UTF8.self)
}

@Test func unknownEnumValueIsKeptAndReported() throws {
    let v = try decode(ControlMode.self, #""turbo""#)
    #expect(v == .unknown("turbo"))
    #expect(!v.isKnown)
    #expect(try encodeString(v) == #""turbo""#)
    #expect(v.validate().count == 1)
    #expect(ControlMode(rawValue: "full") == .full)
    #expect(ControlMode.unknown("full") == .full)  // equality by raw value
}

@Test func unknownMessageTypeDecodesToUnknown() throws {
    let m = try decode(ServerMessage.self, #"{"type":"future_thing","x":1}"#)
    guard case .unknown(let raw) = m else {
        Issue.record("expected .unknown, got \(m)")
        return
    }
    #expect(raw["x"] == .int(1))
    #expect(try encodeString(m) == #"{"type":"future_thing","x":1}"#)
    let c = try decode(ServerMessage.self, #"{"type":"command","command":"teleport"}"#)
    if case .unknown = c {} else { Issue.record("unknown command must decode to .unknown") }
}

@Test func unknownFieldsAreIgnored() throws {
    let m = try decode(ServerError.self, #"{"type":"error","message":"x","extra":{"a":[1,2]}}"#)
    #expect(m.message == "x")
}

@Test func wrongDiscriminatorThrows() {
    #expect(throws: DecodingError.self) { try decode(ServerError.self, #"{"type":"pong","message":"x"}"#) }
}

@Test func integerOverflowThrowsInsteadOfTrapping() {
    #expect(throws: DecodingError.self) {
        try decode(ServerAuthRequired.self, #"{"type":"auth_required","message":"m","timeout":99999999999999999999}"#)
    }
    #expect(throws: DecodingError.self) {
        try decode(ServerAuthRequired.self, #"{"type":"auth_required","message":"m","timeout":1e300}"#)
    }
    #expect(throws: DecodingError.self) {
        try decode(ServerAuthRequired.self, #"{"type":"auth_required","message":"m","timeout":1.5}"#)
    }
}

@Test func nonFiniteNumbersAreRejected() throws {
    // JSON has no NaN/Infinity literal, a huge exponent does not fit Double, and encoding a
    // non-finite Double throws (JSONEncoder default strategy) instead of writing invalid JSON
    #expect(throws: (any Error).self) { try decode(JSONValue.self, #"NaN"#) }
    #expect(throws: (any Error).self) { try decode(Double.self, #"1e400"#) }
    #expect(throws: EncodingError.self) { try JSONEncoder().encode(JSONValue.double(.nan)) }
    #expect(throws: EncodingError.self) { try JSONEncoder().encode(JSONValue.double(.infinity)) }
    var v: [ContractViolation] = []
    ContractCheck.finite(&v, "/x", .infinity)
    #expect(v.count == 1)
}

@Test func typeMismatchThrows() throws {
    // like known deviation D3 (tls_port as string): a wrong JSON type is a hard error, not a silent nil
    #expect(throws: DecodingError.self) {
        try decode(ClientStatus.self, #"{"type":"client_status","battery_level":"80"}"#)
    }
    #expect(try decode(ClientStatus.self, #"{"type":"client_status","battery_level":80}"#).batteryLevel == 80)
}

@Test func boolishKeepsWireForm() throws {
    #expect(try decode(Boolish.self, "1") == Boolish(true, isNumeric: true))
    #expect(try decode(Boolish.self, "true") == Boolish(true))
    #expect(try encodeString(try decode(Boolish.self, "0")) == "0")
    #expect(throws: DecodingError.self) { try decode(Boolish.self, "2") }
}

@Test func requiredNullableNeedsTheKeyButAcceptsNull() throws {
    // detail is required and nullable: null is fine, a missing key is not
    let base = #""id":1,"client_id":"3f2b8c1e-5d4a-4e6f-9a7b-1c2d3e4f5a6b","ts":"2026-11-18T08:00:00+00:00","event":"paired""#
    let m = try decode(DeviceActivity.self, "{" + base + #","detail":null}"#)
    #expect(m.detail == nil)
    #expect(try encodeString(m).contains(#""detail":null"#))
    #expect(throws: DecodingError.self) {
        try decode(DeviceActivity.self, "{" + base + "}")
    }
}

@Test func validationFindsPatternAndDependencyViolations() throws {
    let pair = try decode(ClientPair.self, #"{"type":"pair","pin":"1234-5678\n","client_name":"x","protocol_version":1,"platform":"ios","app_version":"2026.12.0"}"#)
    #expect(pair.validate().count == 1, "trailing newline must not satisfy ^...$")
    let txt = try decode(BonjourTxtRecord.self, #"{"ws_path":"/api/ws","api_path":"/api","iid":"i","version":"2026.12.0","pv":"1","pv_min":"1","tls":"1"}"#)
    #expect(txt.validate().count == 2)
}

@Test func builtMessagesCarryTheirDiscriminator() throws {
    let m = ClientMessage.clientGetAreas(ClientGetAreas())
    #expect(try encodeString(m) == #"{"type":"get_areas"}"#)
    let cmd = CommandRefresh()
    #expect(try encodeString(cmd) == #"{"command":"refresh","type":"command"}"#)
}

@Test func sensitiveFieldsAreRedactedInDebugOutput() {
    let ok = ServerPairOk(
        clientId: "c", clientName: "n", secret: String(repeating: "ab", count: 32),
        protocolVersion: 1, minProtocolVersion: 1, minAppVersion: MinAppVersion()
    )
    #expect(!String(describing: ok).contains("abab"))
    #expect(!String(reflecting: ok).contains("abab"))
    var dumped = ""
    dump(ok, to: &dumped)
    #expect(!dumped.contains("abab"))
}
