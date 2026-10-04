package com.thread.app

import org.junit.Assert.*
import org.junit.Test

class ActionLinksTest {
    @Test fun youtubeHasNativeDestinationAndSameQueryInBrowserFallback() {
        val route = ActionLinks.media("youtube", "Manchester City 115 charges & news")
        assertEquals("com.google.android.youtube", route.appPackage)
        assertEquals(route.url, route.appUrl)
        assertEquals("https://www.youtube.com/results?search_query=Manchester%20City%20115%20charges%20%26%20news", route.url)
    }
    @Test fun whatsappIsOnlyAnEncodedDraftLink() {
        val route = ActionLinks.whatsapp("+1 (202) 555-0123", "Headline & source\nhttps://example.com/news")
        assertEquals("com.whatsapp", route.appPackage)
        assertTrue(route.url.startsWith("https://wa.me/12025550123?text=Headline%20%26%20source%0A"))
        assertTrue(route.url.contains("https%3A%2F%2Fexample.com%2Fnews"))
    }
    @Test fun chromeStoreAndDirectionsUseBoundedPublicRoutes() {
        assertEquals("com.android.chrome", ActionLinks.chrome("https://example.com").appPackage)
        val store = ActionLinks.playStore("Signal & chat")
        assertEquals("market://search?q=Signal%20%26%20chat&c=apps", store.appUrl)
        assertTrue(store.url.startsWith("https://play.google.com/"))
        val maps = ActionLinks.directions("Central Station", "walking")
        assertEquals("com.google.android.apps.maps", maps.appPackage)
        assertTrue(maps.url.endsWith("destination=Central%20Station&travelmode=walking"))
    }
    @Test fun dangerousUrlsAndInvalidModesAreRejected() {
        for (url in listOf("javascript:alert(1)", "intent://anything", "file:///secret", "https://user:pass@example.com/")) {
            try { ActionLinks.chrome(url); fail("Unsafe URL accepted") } catch (_: IllegalArgumentException) { }
        }
        try { ActionLinks.directions("Station", "flying"); fail("Invalid mode accepted") } catch (_: IllegalArgumentException) { }
    }
}
