package com.forrestlasiter.umbra.net

/**
 * The 16-bit one's-complement Internet checksum (RFC 1071), used for the IPv4
 * header and the UDP checksum. Kept tiny and dependency-free so it unit-tests on
 * a plain JVM.
 */
object InternetChecksum {

    /** Checksum over [data] in [offset, offset+length), with an optional running
     *  sum seed (used to fold in the UDP pseudo-header). */
    fun compute(data: ByteArray, offset: Int, length: Int, seed: Long = 0L): Int {
        var sum = seed
        var i = offset
        var remaining = length
        while (remaining > 1) {
            val hi = (data[i].toInt() and 0xFF) shl 8
            val lo = data[i + 1].toInt() and 0xFF
            sum += (hi or lo).toLong()
            i += 2
            remaining -= 2
        }
        if (remaining == 1) {                       // odd trailing byte
            sum += ((data[i].toInt() and 0xFF) shl 8).toLong()
        }
        while (sum shr 16 != 0L) {                  // fold carries
            sum = (sum and 0xFFFF) + (sum shr 16)
        }
        return (sum.inv() and 0xFFFF).toInt()
    }

    /** Sum of a byte range without folding/complementing — for pseudo-headers. */
    fun partialSum(data: ByteArray, offset: Int, length: Int): Long {
        var sum = 0L
        var i = offset
        var remaining = length
        while (remaining > 1) {
            sum += (((data[i].toInt() and 0xFF) shl 8) or (data[i + 1].toInt() and 0xFF)).toLong()
            i += 2
            remaining -= 2
        }
        if (remaining == 1) sum += ((data[i].toInt() and 0xFF) shl 8).toLong()
        return sum
    }
}
