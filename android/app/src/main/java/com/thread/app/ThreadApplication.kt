package com.thread.app

import android.app.Application
import android.content.Context
import androidx.lifecycle.ViewModelProvider
import androidx.lifecycle.ViewModelStore
import androidx.lifecycle.ViewModelStoreOwner

/** One voice session per process, retained when MainActivity is recreated or dismissed. */
class ThreadApplication : Application(), ViewModelStoreOwner {
    override val viewModelStore = ViewModelStore()
    private val session = lazy {
        ViewModelProvider(viewModelStore, ViewModelProvider.AndroidViewModelFactory(this))[ThreadModel::class.java]
    }
    val model: ThreadModel get() = session.value
    val currentModel: ThreadModel? get() = if (session.isInitialized()) session.value else null
    companion object {
        fun model(context: Context) = (context.applicationContext as ThreadApplication).model
    }
}
