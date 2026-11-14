import java.util.Properties

plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
}

// Secretos fuera del código: se leen de android-app/local.properties (no se sube a git).
val local = Properties().apply {
    val file = rootProject.file("local.properties")
    if (file.exists()) file.inputStream().use { load(it) }
}
fun secret(key: String, default: String = ""): String = "\"${local.getProperty(key, default)}\""

android {
    namespace = "com.flora.assistant"
    compileSdk = 35

    defaultConfig {
        applicationId = "com.flora.assistant"
        minSdk = 26
        targetSdk = 35
        versionCode = 1
        versionName = "0.1.0"

        buildConfigField("String", "FLORA_SERVER_URL", secret("flora.serverUrl", "ws://192.168.1.50:8765/ws"))
        buildConfigField("String", "FLORA_TOKEN", secret("flora.token"))
        buildConfigField("String", "PICOVOICE_ACCESS_KEY", secret("picovoice.accessKey"))
    }

    buildFeatures { buildConfig = true }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
    kotlinOptions { jvmTarget = "17" }
}

dependencies {
    implementation("androidx.core:core-ktx:1.13.1")
    implementation("androidx.activity:activity-ktx:1.9.3")
    implementation("com.squareup.okhttp3:okhttp:4.12.0")
    implementation("ai.picovoice:porcupine-android:3.0.2")
}
