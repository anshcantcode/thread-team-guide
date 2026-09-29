// Optional release-test helper. Never a dependency or part of the THREAD APK.
plugins { id("com.android.application") }
android {
    namespace = "com.thread.probe"
    compileSdk = 36
    defaultConfig { applicationId = "com.thread.probe"; minSdk = 31; targetSdk = 36; versionCode = 1; versionName = "1" }
}
