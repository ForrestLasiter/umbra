import Foundation

/// The 16-bit one's-complement Internet checksum (RFC 1071), for the IPv4 header
/// and UDP checksum. Pure Swift, so it shares tests with the Android port.
public enum InternetChecksum {

    public static func compute(_ data: [UInt8], _ offset: Int, _ length: Int, seed: UInt64 = 0) -> Int {
        var sum = seed
        var i = offset
        var remaining = length
        while remaining > 1 {
            sum += UInt64((UInt16(data[i]) << 8) | UInt16(data[i + 1]))
            i += 2
            remaining -= 2
        }
        if remaining == 1 {
            sum += UInt64(UInt16(data[i]) << 8)
        }
        while (sum >> 16) != 0 {
            sum = (sum & 0xFFFF) + (sum >> 16)
        }
        return Int((~sum) & 0xFFFF)
    }

    public static func partialSum(_ data: [UInt8], _ offset: Int, _ length: Int) -> UInt64 {
        var sum: UInt64 = 0
        var i = offset
        var remaining = length
        while remaining > 1 {
            sum += UInt64((UInt16(data[i]) << 8) | UInt16(data[i + 1]))
            i += 2
            remaining -= 2
        }
        if remaining == 1 { sum += UInt64(UInt16(data[i]) << 8) }
        return sum
    }
}
