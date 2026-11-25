// Compile check and round trip for the generated Kotlin models (tools/codegen/tests/test_codegen.py, KotlinRoundTrip).
// Versions follow the Android apps (Kotlin and kotlinx.serialization, Gradle 9.9.1, JDK 21).
pluginManagement {
    repositories {
        gradlePluginPortal()
        mavenCentral()
    }
}

dependencyResolutionManagement {
    repositoriesMode = RepositoriesMode.FAIL_ON_PROJECT_REPOS
    repositories {
        mavenCentral()
    }
}

rootProject.name = "codegen-kotlin-check"
