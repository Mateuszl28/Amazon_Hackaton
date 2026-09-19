plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
}

val companionUrl: String = (project.findProperty("companionUrl") as String?) ?: "http://10.0.2.2:8080"

android {
    namespace = "com.whatdidimiss.tv"
    compileSdk = 35

    defaultConfig {
        applicationId = "com.whatdidimiss.tv"
        minSdk = 22 // Fire OS 5+
        targetSdk = 35
        versionCode = 1
        versionName = "0.1.0"
        buildConfigField("String", "COMPANION_URL", "\"$companionUrl\"")
    }

    buildFeatures {
        buildConfig = true
    }

    buildTypes {
        release {
            isMinifyEnabled = false
        }
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
    kotlinOptions {
        jvmTarget = "17"
    }
}

dependencies {
    val media3 = "1.6.1"
    implementation("androidx.media3:media3-exoplayer:$media3")
    implementation("androidx.media3:media3-ui:$media3")
    implementation("androidx.appcompat:appcompat:1.7.0")
    implementation("androidx.lifecycle:lifecycle-runtime-ktx:2.8.7")
    implementation("org.jetbrains.kotlinx:kotlinx-coroutines-android:1.10.2")
    implementation("com.squareup.okhttp3:okhttp:4.12.0")
}
