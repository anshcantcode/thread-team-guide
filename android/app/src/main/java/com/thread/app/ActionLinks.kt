package com.thread.app

import java.net.URI
import java.net.URLEncoder

/** Public destinations are encoded as data, never interpreted as arbitrary intent URIs. */
object ActionLinks {
    data class Route(val url: String, val appUrl: String = url, val appPackage: String)
    private fun encode(value: String) = URLEncoder.encode(value, "UTF-8").replace("+", "%20")
    fun search(provider: String, query: String, tab: String = "all"): String {
        require(query.isNotBlank() && query.length <= 500 && '\u0000' !in query)
        return when (provider) {
            "google" -> {
                require(tab in listOf("all", "images", "videos", "news"))
                "https://www.google.com/search?q=${encode(query)}" + (mapOf("images" to "isch", "videos" to "vid", "news" to "nws")[tab]?.let { "&tbm=$it" } ?: "")
            }
            "youtube" -> "https://www.youtube.com/results?search_query=${encode(query)}"
            "spotify" -> "https://open.spotify.com/search/${encode(query)}"
            else -> error("Unsupported search provider")
        }
    }
    fun media(provider: String, query: String): Route {
        val url = search(provider, query)
        return when (provider) {
            "youtube" -> Route(url, appPackage = "com.google.android.youtube")
            "spotify" -> Route(url, "spotify:search:${encode(query)}", "com.spotify.music")
            else -> error("Unsupported media provider")
        }
    }
    fun chrome(url: String): Route {
        val uri = URI(url)
        require(url.length <= 4000 && uri.scheme in listOf("http", "https") && !uri.host.isNullOrBlank() && uri.userInfo == null && url.none(Char::isWhitespace))
        return Route(url, appPackage = "com.android.chrome")
    }
    fun whatsapp(number: String, body: String): Route {
        require(Regex("\\+?[0-9 ()-]{7,40}").matches(number))
        val digits = number.filter(Char::isDigit)
        require(Regex("[1-9][0-9]{6,14}").matches(digits) && body.length in 1..4000 && '\u0000' !in body)
        return Route("https://wa.me/$digits?text=${encode(body)}", appPackage = "com.whatsapp")
    }
    fun playStore(query: String): Route {
        require(query.isNotBlank() && query.length <= 200 && '\u0000' !in query)
        return Route("https://play.google.com/store/search?q=${encode(query)}&c=apps", "market://search?q=${encode(query)}&c=apps", "com.android.vending")
    }
    fun directions(destination: String, mode: String): Route {
        require(destination.isNotBlank() && destination.length <= 500 && '\u0000' !in destination)
        require(mode in listOf("driving", "walking", "bicycling", "transit"))
        return Route("https://www.google.com/maps/dir/?api=1&destination=${encode(destination)}&travelmode=$mode", appPackage = "com.google.android.apps.maps")
    }
}
