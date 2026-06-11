package com.arrow.tactical.network

import okhttp3.OkHttpClient
import java.security.cert.X509Certificate
import javax.net.ssl.SSLContext
import javax.net.ssl.TrustManager
import javax.net.ssl.X509TrustManager

/**
 * Trust-all X509TrustManager for the Arrow server's self-signed certificate.
 * The server regenerates its cert on each deploy so pinning is not viable.
 */
private val TRUST_ALL: X509TrustManager = object : X509TrustManager {
    override fun checkClientTrusted(chain: Array<out X509Certificate>, authType: String) = Unit
    override fun checkServerTrusted(chain: Array<out X509Certificate>, authType: String) = Unit
    override fun getAcceptedIssuers(): Array<X509Certificate> = emptyArray()
}

private val SSL_CTX: SSLContext = SSLContext.getInstance("TLS").also {
    it.init(null, arrayOf<TrustManager>(TRUST_ALL), null)
}

/** Configure this builder to accept the Arrow server's self-signed TLS cert. */
internal fun OkHttpClient.Builder.trustSelfSigned(): OkHttpClient.Builder =
    sslSocketFactory(SSL_CTX.socketFactory, TRUST_ALL)
        .hostnameVerifier { _, _ -> true }
