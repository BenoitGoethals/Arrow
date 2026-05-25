package com.arrow.tactical.ui

import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.material.icons.filled.KeyboardArrowDown
import androidx.compose.material.icons.filled.KeyboardArrowUp
import androidx.compose.ui.unit.dp
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.AdminPanelSettings
import androidx.compose.material.icons.filled.Adjust
import androidx.compose.material.icons.filled.Email
import androidx.compose.material.icons.filled.EmojiFlags
import androidx.compose.material.icons.filled.Flag
import androidx.compose.material.icons.filled.Description
import androidx.compose.material.icons.filled.Map
import androidx.compose.material.icons.filled.Place
import androidx.compose.material.icons.filled.Settings
import androidx.compose.material.icons.filled.Warning
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.NavigationBar
import androidx.compose.material3.NavigationBarItem
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.navigation.NavGraph.Companion.findStartDestination
import androidx.navigation.NavType
import androidx.navigation.compose.NavHost
import androidx.navigation.compose.composable
import androidx.navigation.compose.currentBackStackEntryAsState
import androidx.navigation.compose.rememberNavController
import androidx.navigation.navArgument
import com.arrow.tactical.admin.ui.AdminScreen
import com.arrow.tactical.alerts.ui.AlertsScreen
import com.arrow.tactical.auth.ui.LoginScreen
import com.arrow.tactical.di.AppContainer
import com.arrow.tactical.firemission.ui.FireMissionScreen
import com.arrow.tactical.firemission.ui.MortarScreen
import com.arrow.tactical.map.ui.MapScreen
import com.arrow.tactical.map.ui.MarkEnemyScreen
import com.arrow.tactical.admin.ui.VisibilitySettingsScreen
import com.arrow.tactical.kml.ui.KmlLayersScreen
import com.arrow.tactical.map.ui.OfflineMapsScreen
import com.arrow.tactical.messaging.ui.MessagingScreen
import com.arrow.tactical.objectives.ui.ObjectivesScreen
import com.arrow.tactical.opord.ui.OpordDetailScreen
import com.arrow.tactical.opord.ui.OpordListScreen
import com.arrow.tactical.reports.ui.ReportsScreen
import com.arrow.tactical.settings.ui.SettingsScreen
import kotlinx.coroutines.launch

private sealed class Tab(val route: String, val label: String, val icon: ImageVector) {
    data object Map : Tab("tab/map", "Map", Icons.Filled.Map)
    data object Mark : Tab("tab/mark", "Mark", Icons.Filled.Place)
    data object Alerts : Tab("tab/alerts", "Alerts", Icons.Filled.Warning)
    data object Chat : Tab("tab/chat", "Chat", Icons.Filled.Email)
    data object Reports : Tab("tab/reports", "Reports", Icons.Filled.Flag)
    data object Mortar : Tab("tab/mortar", "Mortar FDC", Icons.Filled.Adjust)
    data object Objectives : Tab("tab/objectives", "Objectives", Icons.Filled.EmojiFlags)
    data object Opord : Tab("tab/opord", "OPORD", Icons.Filled.Description)
    data object Admin : Tab("tab/admin", "Admin", Icons.Filled.AdminPanelSettings)
    data object Settings : Tab("tab/settings", "Settings", Icons.Filled.Settings)
}

private val TABS_BASE = listOf(Tab.Map, Tab.Mark, Tab.Alerts, Tab.Chat, Tab.Reports, Tab.Opord, Tab.Mortar, Tab.Objectives, Tab.Settings)
// Admin tab is appended only when the signed-in user has the ADMIN role.
private val TABS_ADMIN = TABS_BASE + Tab.Admin

object Routes {
    const val LOGIN = "login"
    const val MAIN = "main"
}

@Composable
fun ArrowNavGraph(container: AppContainer, isAuthenticated: Boolean) {
    val rootNav = rememberNavController()

    // Always start on the main shell — login is optional (from Settings).
    NavHost(navController = rootNav, startDestination = Routes.MAIN) {
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
                isAuthenticated = isAuthenticated,
                onNavigateToLogin = { rootNav.navigate(Routes.LOGIN) },
                onLogout = {
                    rootNav.navigate(Routes.MAIN) { popUpTo(0) }
                },
            )
        }
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun MainShell(
    container: AppContainer,
    isAuthenticated: Boolean,
    onNavigateToLogin: () -> Unit,
    onLogout: () -> Unit,
) {
    val tabNav = rememberNavController()
    val backStackEntry by tabNav.currentBackStackEntryAsState()
    val currentRoute = backStackEntry?.destination?.route
    val scope = rememberCoroutineScope()

    val role by container.tokenStore.roleFlow.collectAsState(initial = null)
    val tabs = if (role == "ADMIN") TABS_ADMIN else TABS_BASE

    // Drawer is opened only from the SitaWare hamburger button; bottom nav
    // bar stays visible on every tab including the map.
    val drawerState = androidx.compose.material3.rememberDrawerState(
        initialValue = androidx.compose.material3.DrawerValue.Closed,
    )

    LaunchedEffect(Unit) {
        container.navigateToChatFlow.collect {
            tabNav.navigate(Tab.Chat.route) {
                popUpTo(tabNav.graph.findStartDestination().id) { saveState = true }
                launchSingleTop = true
                restoreState = true
            }
        }
    }

    fun goTab(route: String) {
        tabNav.navigate(route) {
            popUpTo(tabNav.graph.findStartDestination().id) { saveState = true }
            launchSingleTop = true
            restoreState = true
        }
    }

    androidx.compose.material3.ModalNavigationDrawer(
        drawerState = drawerState,
        gesturesEnabled = drawerState.isOpen,   // no swipe-to-open from map
        drawerContent = {
            androidx.compose.material3.ModalDrawerSheet {
                Text(
                    "ARROW",
                    modifier = androidx.compose.ui.Modifier.padding(16.dp),
                    style = androidx.compose.material3.MaterialTheme.typography.titleLarge,
                )
                androidx.compose.material3.HorizontalDivider()
                tabs.forEach { tab ->
                    androidx.compose.material3.NavigationDrawerItem(
                        icon = { Icon(tab.icon, contentDescription = tab.label) },
                        label = { Text(tab.label) },
                        selected = currentRoute?.startsWith(tab.route) == true,
                        onClick = {
                            goTab(tab.route)
                            scope.launch { drawerState.close() }
                        },
                        modifier = androidx.compose.ui.Modifier.padding(horizontal = 12.dp),
                    )
                }
            }
        },
    ) {
    var bottomBarExpanded by remember { mutableStateOf(true) }
    Scaffold(
        bottomBar = {
            Column {
                // Collapse handle — always visible; tap to toggle the full bar.
                Row(
                    modifier = Modifier
                        .fillMaxWidth()
                        .background(MaterialTheme.colorScheme.surfaceContainer)
                        .clickable { bottomBarExpanded = !bottomBarExpanded }
                        .padding(vertical = 2.dp),
                    horizontalArrangement = Arrangement.Center,
                    verticalAlignment = androidx.compose.ui.Alignment.CenterVertically,
                ) {
                    Icon(
                        if (bottomBarExpanded) Icons.Filled.KeyboardArrowDown
                        else                   Icons.Filled.KeyboardArrowUp,
                        contentDescription = if (bottomBarExpanded) "Collapse menu" else "Expand menu",
                        modifier = Modifier.size(20.dp),
                        tint = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                }
                if (bottomBarExpanded) {
                    NavigationBar {
                        tabs.forEach { tab ->
                            val selected = currentRoute?.startsWith(tab.route) == true
                            NavigationBarItem(
                                selected = selected,
                                onClick = { goTab(tab.route) },
                                icon = { Icon(tab.icon, contentDescription = tab.label) },
                                label = { Text(tab.label) },
                            )
                        }
                    }
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
                    onReport     = { lat, lon -> tabNav.navigate("${Tab.Reports.route}?lat=$lat&lon=$lon") },
                    onOpenMortar = { lat, lon -> tabNav.navigate("mortar?lat=$lat&lon=$lon") },
                    onOpenDrawer = { scope.launch { drawerState.open() } },
                )
            }
            composable(
                "fire-mission?lat={lat}&lon={lon}",
                arguments = listOf(
                    navArgument("lat") { type = NavType.StringType },
                    navArgument("lon") { type = NavType.StringType },
                ),
            ) { entry ->
                FireMissionScreen(
                    container  = container,
                    presetLat  = entry.arguments?.getString("lat")?.toDoubleOrNull(),
                    presetLon  = entry.arguments?.getString("lon")?.toDoubleOrNull(),
                    onBack     = { tabNav.popBackStack() },
                    onOpenMortar = { lat, lon ->
                        if (lat == null || lon == null) tabNav.navigate("mortar")
                        else tabNav.navigate("mortar?lat=$lat&lon=$lon")
                    },
                )
            }
            composable("fire-mission") {
                FireMissionScreen(
                    container = container,
                    onBack    = { tabNav.popBackStack() },
                    onOpenMortar = { lat, lon ->
                        if (lat == null || lon == null) tabNav.navigate("mortar")
                        else tabNav.navigate("mortar?lat=$lat&lon=$lon")
                    },
                )
            }
            composable(
                "mortar?lat={lat}&lon={lon}",
                arguments = listOf(
                    navArgument("lat") { type = NavType.StringType },
                    navArgument("lon") { type = NavType.StringType },
                ),
            ) { entry ->
                MortarScreen(
                    container = container,
                    presetLat = entry.arguments?.getString("lat")?.toDoubleOrNull(),
                    presetLon = entry.arguments?.getString("lon")?.toDoubleOrNull(),
                    onBack    = { tabNav.popBackStack() },
                )
            }
            composable("mortar") {
                MortarScreen(container = container, onBack = { tabNav.popBackStack() })
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
            composable(Tab.Mortar.route) {
                MortarScreen(container = container, onBack = { tabNav.popBackStack() })
            }
            composable(Tab.Chat.route) { MessagingScreen(container) }
            composable(
                "${Tab.Reports.route}?lat={lat}&lon={lon}",
                arguments = listOf(
                    navArgument("lat") { type = NavType.StringType },
                    navArgument("lon") { type = NavType.StringType },
                ),
            ) { entry ->
                ReportsScreen(
                    repo      = container.reportRepository,
                    container = container,
                    presetLat = entry.arguments?.getString("lat")?.toDoubleOrNull(),
                    presetLon = entry.arguments?.getString("lon")?.toDoubleOrNull(),
                )
            }
            composable(Tab.Reports.route) {
                ReportsScreen(repo = container.reportRepository, container = container)
            }
            composable(Tab.Objectives.route) { ObjectivesScreen(container) }
            composable(Tab.Opord.route) {
                OpordListScreen(container = container, onOpen = { id -> tabNav.navigate("opord/$id") })
            }
            composable(
                "opord/{id}",
                arguments = listOf(navArgument("id") { type = NavType.IntType }),
            ) { entry ->
                val id = entry.arguments?.getInt("id") ?: 0
                OpordDetailScreen(container = container, opordId = id, onBack = { tabNav.popBackStack() })
            }
            composable(Tab.Admin.route) { AdminScreen(container.logRepository) }
            composable(Tab.Settings.route) {
                SettingsScreen(
                    repo = container.settingsRepository,
                    isAuthenticated = isAuthenticated,
                    onLogin = onNavigateToLogin,
                    onLogout = {
                        scope.launch { container.authRepository.logout() }
                        onLogout()
                    },
                    onOpenOfflineMaps = { tabNav.navigate("offline-maps") },
                    onOpenKmlLayers   = { tabNav.navigate("kml-layers") },
                    onOpenVisibility  = { tabNav.navigate("visibility") },
                )
            }
            composable("offline-maps") {
                OfflineMapsScreen(
                    container = container,
                    onBack    = { tabNav.popBackStack() },
                )
            }
            composable("kml-layers") {
                KmlLayersScreen(
                    container = container,
                    onBack    = { tabNav.popBackStack() },
                )
            }
            composable("visibility") {
                VisibilitySettingsScreen(
                    container = container,
                    onBack    = { tabNav.popBackStack() },
                )
            }
        }
    }
    }   // ModalNavigationDrawer
}
