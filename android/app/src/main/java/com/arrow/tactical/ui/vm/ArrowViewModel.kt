package com.arrow.tactical.ui.vm

import androidx.lifecycle.ViewModel
import androidx.lifecycle.ViewModelProvider
import androidx.lifecycle.viewmodel.compose.viewModel
import androidx.compose.runtime.Composable
import com.arrow.tactical.di.AppContainer

/**
 * Bridges the manual [AppContainer] DI to Jetpack [ViewModel]s. Screens obtain a
 * VM with `arrowViewModel { MyViewModel(container) }` — the builder runs once per
 * ViewModelStore (survives recomposition + config changes) and the result is
 * scoped to the calling composable's lifecycle.
 */
@Composable
inline fun <reified VM : ViewModel> arrowViewModel(
    crossinline builder: () -> VM,
): VM = viewModel(
    factory = object : ViewModelProvider.Factory {
        @Suppress("UNCHECKED_CAST")
        override fun <T : ViewModel> create(modelClass: Class<T>): T = builder() as T
    },
)

/** Marker base class so all Arrow view-models read consistently and can share helpers later. */
abstract class ArrowViewModel(protected val container: AppContainer) : ViewModel()
