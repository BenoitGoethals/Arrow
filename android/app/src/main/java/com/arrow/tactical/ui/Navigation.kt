package com.arrow.tactical.ui

import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.size
import androidx.compose.ui.unit.dp
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Email
import androidx.compose.material.icons.filled.Flag
import androidx.compose.material.icons.filled.Map
import androidx.compose.material.icons.filled.Place
import androidx.compose.material.icons.filled.Settings
import androidx.compose.material.icons.filled.Warning
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.NavigationBar
import androidx.compose.material3.NavigationBarItem
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.ui.unit.sp
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.navigation.NavGraph.Companion.findStartDestination
import androidx.navigation.compose.NavHost
import androidx.navigation.compose.composable
import androidx.navigation.compose.currentBackStackEntryAsState
import androidx.navigation.compose.rememberNavController
import com.arrow.tactical.alerts.ui.AlertsScreen
import com.arrow.tactical.auth.ui.LoginScreen
import com.arrow.tactical.di.AppContainer
import com.arrow.tactical.firemission.ui.FireMissionScreen
import com.arrow.tactical.map.ui.MapScreen
import com.arrow.tactical.map.ui.MarkEnemyScreen
import com.arrow.tactical.messaging.ui.MessagingScreen
import com.arrow.tactical.reports.ui.ReportsScreen
import com.arrow.tactical.settings.ui.SettingsScreen
import kotlinx.coroutines.launch

private sealed class Tab(val route: String, val label: String, val icon: ImageVector) {
    data object Map : Tab("tab/map", "Map", Icons.Filled.Map)
    data object Mark : Tab("tab/mark", "Mark", Icons.Filled.Place)
    data object Alerts : Tab("tab/alerts", "Alerts", Icons.Filled.Warning)
    data object Chat : Tab("tab/chat", "Chat", Icons.Filled.Email)
    data object Reports : Tab("tab/reports", "Reports", Icons.Filled.Flag)
    data object Settings : Tab("tab/settings", "Settings", Icons.Filled.Settings)
}

private val TABS = listOf(Tab.Map, Tab.Mark, Tab.Alerts, Tab.Chat, Tab.Reports, Tab.Settings)

object Routes {
    const val LOGIN = "login"
    const val MAIN = "main"
}

@Composable
fun ArrowNavGraph(container: AppContainer, isAuthenticated: Boolean) {
    val rootNav = rememberNavController()
    val start = if (isAuthenticated) Routes.MAIN else Routes.LOGIN

    NavHost(navController = rootNav, startDestination = start) {
        composable(Routes.LOGIN) {
            LoginScreen(
                authRepository = container.authRepository,
                settingsRepository = container.settingsRepository,
                onAuthenticated = {
                    rootNav.navigate(Routes.MAIN) {
                        popUpTo(Routes.LOGIN) { inclusive = true }
                    }
                },
            )
        }
        composable(Routes.MAIN) {
            MainShell(
                container = container,
                onLogout = {
                    rootNav.navigate(Routes.LOGIN) { popUpTo(0) }
                },
            )
        }
    }
}

@Composable
private fun MainShell(container: AppContainer, onLogout: () -> Unit) {
    val tabNav = rememberNavController()
    val backStackEntry by tabNav.currentBackStackEntryAsState()
    val currentRoute = backStackEntry?.destination?.route
    val scope = rememberCoroutineScope()

    LaunchedEffect(Unit) {
        container.navigateToChatFlow.collect {
            tabNav.navigate(Tab.Chat.route) {
                popUpTo(tabNav.graph.findStartDestination().id) { saveState = true }
                launchSingleTop = true
                restoreState = true
            }
        }
    }

    Scaffold(
        bottomBar = {
            NavigationBar(modifier = Modifier.height(48.dp)) {
                TABS.forEach { tab ->
                    val selected = currentRoute?.startsWith(tab.route) == true
                    NavigationBarItem(
                        selected = selected,
                        onClick = {
                            tabNav.navigate(tab.route) {
                                popUpTo(tabNav.graph.findStartDestination().id) { saveState = true }
                                launchSingleTop = true
                                restoreState = true
                            }
                        },
                        icon = {
                            Icon(
                                tab.icon,
                                contentDescription = tab.label,
                                modifier = Modifier.size(18.dp),
                            )
                        },
                        label = {
                            Text(
                                tab.label,
                                style = MaterialTheme.typography.labelSmall.copy(fontSize = 9.sp),
                            )
                        },
                    )
                }
            }
        },
    ) { padding ->
        NavHost(
            navController = tabNav,
            startDestination = Tab.Map.route,
            modifier = Modifier.padding(padding),
        ) {
            composable(Tab.Map.route) {
                MapScreen(
                    container  = container,
                    onCallFire = { lat, lon ->
                        if (lat.isNaN()) tabNav.navigate("fire-mission")
                        else tabNav.navigate("fire-mission?lat=$lat&lon=$lon")
                    },
                    onReport   = { lat, lon -> tabNav.navigate("${Tab.Reports.route}?lat=$lat&lon=$lon") },
                )
            }
            composable("fire-mission?lat={lat}&lon={lon}") { entry ->
                FireMissionScreen(
                    container  = container,
                    presetLat  = entry.arguments?.getString("lat")?.toDoubleOrNull(),
                    presetLon  = entry.arguments?.getString("lon")?.toDoubleOrNull(),
                    onBack     = { tabNav.popBackStack() },
                )
            }
            composable("fire-mission") {
                FireMissionScreen(
                    container = container,
                    onBack    = { tabNav.popBackStack() },
                )
            }
            composable("${Tab.Mark.route}?lat={lat}&lon={lon}") { entry ->
                val lat = entry.arguments?.getString("lat")?.toDoubleOrNull()
                val lon = entry.arguments?.getString("lon")?.toDoubleOrNull()
                MarkEnemyScreen(
                    container = container,
                    presetLat = lat,
                    presetLon = lon,
                    onMarked = { tabNav.popBackStack(Tab.Map.route, inclusive = false) },
                )
            }
            composable(Tab.Mark.route) {
                MarkEnemyScreen(
                    container = container,
                    presetLat = null,
                    presetLon = null,
                    onMarked = { tabNav.popBackStack(Tab.Map.route, inclusive = false) },
                )
            }
            composable(Tab.Alerts.route) { AlertsScreen(container.alertRepository) }
            composable(Tab.Chat.route) { MessagingScreen(container) }
            composable("${Tab.Reports.route}?lat={lat}&lon={lon}") { entry ->
                ReportsScreen(
                    repo      = container.reportRepository,
                    presetLat = entry.arguments?.getString("lat")?.toDoubleOrNull(),
                    presetLon = entry.arguments?.getString("lon")?.toDoubleOrNull(),
                )
            }
            composable(Tab.Reports.route) { ReportsScreen(repo = container.reportRepository) }
            composable(Tab.Settings.route) {
                SettingsScreen(
                    repo = container.settingsRepository,
                    onLogout = {
                        scope.launch { container.authRepository.logout() }
                        onLogout()
                    },
                )
            }
        }
    }
}
