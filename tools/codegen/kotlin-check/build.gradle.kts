import org.jetbrains.kotlin.gradle.dsl.JvmTarget

// Sources: the generated models (-PgeneratedDir, default the checked-in snapshot) and the round-trip harness.
// Build products go to -PbuildRoot (the test passes a temporary directory), never into the repository.
// Compiler settings as in the Android consumer's JVM modules: JDK 21 toolchain, JDK 17 API and bytecode, -Werror.
plugins {
    kotlin("jvm") version "2.4.21"
    kotlin("plugin.serialization") version "2.4.21"
}

val generatedDir = providers.gradleProperty("generatedDir").orElse(layout.projectDirectory.dir("../snapshots/kotlin").asFile.path)
providers.gradleProperty("buildRoot").orNull?.let { layout.buildDirectory.set(file(it)) }

kotlin {
    jvmToolchain(21)
    compilerOptions {
        jvmTarget.set(JvmTarget.JVM_17)
        freeCompilerArgs.add("-Xjdk-release=17")
        allWarningsAsErrors.set(true)
    }
    sourceSets.named("main") {
        kotlin.setSrcDirs(listOf(generatedDir.get(), "../tests/kotlin"))
    }
}

tasks.withType<JavaCompile>().configureEach {
    sourceCompatibility = "17"
    targetCompatibility = "17"
}

dependencies {
    implementation("org.jetbrains.kotlinx:kotlinx-serialization-json:1.13.0")
}

// RoundTripKt <contracts root> <manifest.json> <results.json>
tasks.register<JavaExec>("roundTrip") {
    description = "Runs the round-trip harness over the fixture manifest."
    classpath = sourceSets["main"].runtimeClasspath
    mainClass.set("harness.RoundTripKt")
    args(
        providers.gradleProperty("contractsRoot").orElse(layout.projectDirectory.dir("../../..").asFile.path).get(),
        providers.gradleProperty("manifest").getOrElse(""),
        providers.gradleProperty("results").getOrElse(""),
    )
}
