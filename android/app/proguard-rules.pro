# Keep the application ViewModel constructor used by Android's factory.
-keep class com.thread.app.ThreadModel { public <init>(android.app.Application); }

# ONNX JNI finds Java tensor/value classes and their members by name.
# https://onnxruntime.ai/docs/build/android.html#note-proguard-rules-for-r8-minimization-android-app-builds-to-work
-keep class ai.onnxruntime.** { *; }
