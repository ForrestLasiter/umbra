plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
    id("org.jetbrains.kotlin.plugin.compose")
    id("org.jetbrains.kotlin.plugin.serialization")
}

android {
    namespace = "com.forrestlasiter.umbra"
    compileSdk = 34

    defaultConfig {
        applicationId = "com.forrestlasiter.umbra"
        minSdk = 26            // Android 8.0 — VPNService per-app + always-on
        targetSdk = 34
        versionCode = 1
        versionName = "0.1.0"  // tracks umbra core; keep in step with spec engine_version
    }

    buildTypes {
        release {
            isMinifyEnabled = true
            proguardFiles(getDefaultProguardFile("proguard-android-optimize.txt"), "proguard-rules.pro")
        }
    }

    buildFeatures { compose = true }
    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
    kotlinOptions { jvmTarget = "17" }
}

dependencies {
    implementation("androidx.core:core-ktx:1.13.1")
    implementation("androidx.lifecycle:lifecycle-runtime-ktx:2.8.4")
    implementation("androidx.lifecycle:lifecycle-viewmodel-compose:2.8.4")
    implementation("androidx.activity:activity-compose:1.9.1")
    implementation(platform("androidx.compose:compose-bom:2024.08.00"))
    implementation("androidx.compose.ui:ui")
    implementation("androidx.compose.material3:material3")
    implementation("org.jetbrains.kotlinx:kotlinx-serialization-json:1.7.1")
    // Official WireGuard userspace backend (libwg-go). minSdk 26 has java.time /
    // Optional natively, so no core-library desugaring is required.
    implementation("com.wireguard.android:tunnel:1.0.20230706")

    testImplementation("junit:junit:4.13.2")
}
