package com.forrestlasiter.umbra.system

/*
 * firewall + discovery: the two capabilities that live in the kernel's packet
 * filter.
 *
 * No Android app can write packet-filter rules, however it is signed -- that
 * takes root. So these controls do not try. The OS ships a tiny root service,
 * umbra-net (android/os-integration/), and the two sides talk through system
 * properties:
 *
 *   app  -> persist.umbra.net.inbound_drop / .discovery_drop = "1" or "0"
 *   OS   -> umbra.net.applied = "inbound=1 discovery=0"   (what is really in place)
 *
 * The honesty rule is in enforce(): setting the property is only a REQUEST. The
 * control reports success only after it reads the matching value back from
 * umbra.net.applied. If the service is missing, slow, or failed, that read-back
 * never matches and the control says it failed.
 */

/** Reads/writes Android system properties. An interface so tests can fake it. */
interface PropertyStore {
    fun get(key: String): String
    fun set(key: String, value: String): Boolean
}

/**
 * The real store. android.os.SystemProperties is a hidden class, so it is
 * reached by reflection (a platform-signed app is exempt from the hidden-API
 * blocklist). On a normal install every call fails closed: get() returns "" and
 * set() returns false.
 */
object OsProperties : PropertyStore {

    private val systemProperties: Class<*>? =
        try { Class.forName("android.os.SystemProperties") } catch (e: ReflectiveOperationException) { null }

    override fun get(key: String): String = try {
        systemProperties?.getMethod("get", String::class.java)?.invoke(null, key) as? String ?: ""
    } catch (e: Exception) {
        ""
    }

    override fun set(key: String, value: String): Boolean {
        val cls = systemProperties ?: return false
        return try {
            cls.getMethod("set", String::class.java, String::class.java).invoke(null, key, value)
            true
        } catch (e: Exception) {
            false   // SELinux refused: this OS build has no policy for the property
        }
    }
}

/**
 * One switch in the OS packet-filter service.
 *
 * @param requestKey  the persist.* property the app writes
 * @param statusField the name this switch has inside umbra.net.applied
 * @param settle      how to wait between read-back attempts (replaced in tests)
 */
open class NetHookControl(
    override val capability: String,
    private val requestKey: String,
    private val statusField: String,
    private val props: PropertyStore = OsProperties,
    private val settle: () -> Unit = { Thread.sleep(POLL_MS) },
) : SystemControl {

    /** The service writes a status as soon as it first runs; none means no service. */
    override fun available(): Boolean = applied() != null

    override fun snapshot(): String? = if (available()) wanted() else null

    override fun enforce(): Boolean = request(ON)

    override fun restore(prior: String): Boolean = request(if (prior == ON) ON else OFF)

    override fun isEnforced(): Boolean? = applied()?.let { it == ON }

    /** What the app last asked for ("1" or "0"; unset counts as "0"). */
    private fun wanted(): String = if (props.get(requestKey) == ON) ON else OFF

    /** What the service reports for this switch, or null if it has not reported. */
    private fun applied(): String? = parseStatus(props.get(STATUS_KEY))[statusField]

    /** Ask, then wait for the service to confirm. True only on confirmation. */
    private fun request(value: String): Boolean {
        if (!props.set(requestKey, value)) return false
        repeat(POLL_ATTEMPTS) {
            if (applied() == value) return true
            settle()
        }
        return applied() == value
    }

    companion object {
        const val STATUS_KEY = "umbra.net.applied"
        const val ON = "1"
        const val OFF = "0"
        const val POLL_MS = 100L
        const val POLL_ATTEMPTS = 30      // about three seconds in all

        /** "inbound=1 discovery=0" -> {inbound=1, discovery=0}. "error" or "" -> {}. */
        fun parseStatus(status: String): Map<String, String> =
            status.trim().split(' ')
                .mapNotNull { part -> part.split('=').takeIf { it.size == 2 }?.let { it[0] to it[1] } }
                .toMap()
    }
}

/** firewall -- "Do not be reachable from the local network (default-deny inbound)." */
class FirewallControl(props: PropertyStore = OsProperties) : NetHookControl(
    capability = "firewall",
    requestKey = "persist.umbra.net.inbound_drop",
    statusField = "inbound",
    props = props,
)

/** discovery -- "Emit no local-network discovery chatter (mDNS/LLMNR/NetBIOS/SSDP/WSD)." */
class DiscoveryControl(props: PropertyStore = OsProperties) : NetHookControl(
    capability = "discovery",
    requestKey = "persist.umbra.net.discovery_drop",
    statusField = "discovery",
    props = props,
)
