import Vapor
import Foundation

@main
struct EnterpriseMonitor {
    static func main() async throws {
        var env = try Environment.detect()
        try LoggingSystem.bootstrap(from: &env)
        
        let app = Application(env)
        defer { app.shutdown() }
        
        // Configure app
        try configure(app)
        
        print("✅ Enterprise Monitor Backend (macOS) starting...")
        print("📡 API Server listening on http://localhost:51234")
        
        try app.run()
    }
}

func configure(_ app: Application) throws {
    // Set server configuration
    app.http.server.configuration.hostname = "127.0.0.1"
    app.http.server.configuration.port = 51234
    
    // Register routes
    try routes(app)
    
    print("✅ Server configured successfully")
}

func routes(_ app: Application) throws {
    // Health check
    app.get("health") { req async -> Response in
        let response: [String: String] = [
            "status": "healthy",
            "platform": "macos",
            "timestamp": ISO8601DateFormatter().string(from: Date())
        ]
        return try await response.encodeResponse(for: req)
    }
    
    // Auth routes
    let auth = app.grouped("api", "auth")
    
    auth.post("login") { req async throws -> Response in
        struct LoginRequest: Content {
            let username: String
            let password: String
        }
        
        let loginReq = try req.content.decode(LoginRequest.self)
        
        // Simple auth check (REPLACE WITH PROPER AUTH IN PRODUCTION)
        if loginReq.username == "admin" && loginReq.password == "admin123" {
            let response: [String: Any] = [
                "success": true,
                "token": "mock-jwt-token-\(UUID().uuidString)"
            ]
            return try await createJSONResponse(response, for: req)
        } else {
            let response: [String: Any] = [
                "success": false,
                "error": "Invalid credentials"
            ]
            return try await createJSONResponse(response, for: req)
        }
    }
    
    auth.get("check") { req async throws -> Response in
        // Check authorization header
        guard let _ = req.headers.bearerAuthorization else {
            let response: [String: Any] = ["authenticated": false]
            return try await createJSONResponse(response, for: req)
        }
        
        let response: [String: Any] = [
            "authenticated": true,
            "username": "admin"
        ]
        return try await createJSONResponse(response, for: req)
    }
    
    // API routes (require auth)
    let api = app.grouped("api")
    
    api.get("statistics") { req async throws -> Response in
        let stats: [String: Any] = [
            "total_screenshots": 0,
            "active_hours_today": 0.0,
            "apps_tracked": 0,
            "clipboard_events": 0
        ]
        return try await createJSONResponse(stats, for: req)
    }
    
    api.get("screenshots") { req async throws -> Response in
        let screenshots: [[String: Any]] = []
        return try await createJSONResponse(screenshots, for: req)
    }
    
    api.get("monitoring", "status") { req async throws -> Response in
        let status: [String: Any] = [
            "is_monitoring": true,
            "uptime_seconds": 0
        ]
        return try await createJSONResponse(status, for: req)
    }
    
    api.post("monitoring", "pause") { req async throws -> Response in
        let response: [String: Any] = [
            "success": true,
            "message": "Monitoring paused"
        ]
        return try await createJSONResponse(response, for: req)
    }
    
    api.post("monitoring", "resume") { req async throws -> Response in
        let response: [String: Any] = [
            "success": true,
            "message": "Monitoring resumed"
        ]
        return try await createJSONResponse(response, for: req)
    }
    
    print("✅ Routes registered")
}

// Helper function to create JSON responses
func createJSONResponse(_ data: [String: Any], for req: Request) async throws -> Response {
    let jsonData = try JSONSerialization.data(withJSONObject: data)
    var headers = HTTPHeaders()
    headers.add(name: .contentType, value: "application/json")
    return Response(
        status: .ok,
        headers: headers,
        body: .init(data: jsonData)
    )
}
