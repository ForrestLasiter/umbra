import Foundation
import Network

/// Forwards a DNS query to an upstream resolver and returns the reply. In a
/// Packet Tunnel Provider the extension's own sockets egress on the real
/// interface (not the tunnel), so this doesn't loop — the iOS analogue of
/// Android's protect().
final class UDPForwarder {
    private let host: NWEndpoint.Host
    private let port: NWEndpoint.Port

    init(upstream: String = "1.1.1.1", port: UInt16 = 53) {
        self.host = NWEndpoint.Host(upstream)
        self.port = NWEndpoint.Port(rawValue: port)!
    }

    /// Send `query`, deliver the raw reply payload (or nil on timeout/error).
    func forward(_ query: [UInt8], completion: @escaping ([UInt8]?) -> Void) {
        let conn = NWConnection(host: host, port: port, using: .udp)
        var finished = false
        func finish(_ result: [UInt8]?) {
            if finished { return }
            finished = true
            conn.cancel()
            completion(result)
        }
        conn.stateUpdateHandler = { state in
            if case .ready = state {
                conn.send(content: Data(query), completion: .contentProcessed { _ in
                    conn.receiveMessage { data, _, _, _ in
                        finish(data.map { Array($0) })
                    }
                })
            } else if case .failed = state {
                finish(nil)
            }
        }
        conn.start(queue: .global())
        DispatchQueue.global().asyncAfter(deadline: .now() + 5) { finish(nil) }
    }
}
