/*
 * Layer 3 (server side) — C# MCP Server entry point
 *
 * Responsibilities:
 *   • Read JSON-RPC requests from stdin (one per line)
 *   • Dispatch to ToolRegistry
 *   • Write JSON-RPC responses to stdout (one per line)
 *   • Log everything to stderr so stdout stays clean for the protocol
 */

using System.Text;
using System.Text.Json;
using Microsoft.Extensions.DependencyInjection;
using Microsoft.Extensions.Hosting;
using Microsoft.Extensions.Logging;
using SlackMcpServer.Models;
using SlackMcpServer.Services;
using SlackMcpServer.Tools;

// ── Dependency Injection ───────────────────────────────────────────────────────

var host = Host.CreateDefaultBuilder(args)
    .ConfigureLogging(logging =>
    {
        logging.ClearProviders();
        logging.AddConsole(o => o.LogToStandardErrorThreshold = LogLevel.Trace);
        logging.SetMinimumLevel(LogLevel.Information);
    })
    .ConfigureServices(services =>
    {
        services.AddSingleton<SlackService>();
        services.AddSingleton<ToolRegistry>();
    })
    .Build();

var logger   = host.Services.GetRequiredService<ILogger<Program>>();
var registry = host.Services.GetRequiredService<ToolRegistry>();

logger.LogInformation("Slack MCP Server v2.0 starting (stdio transport)...");

// ── stdio setup ────────────────────────────────────────────────────────────────

Console.InputEncoding  = Encoding.UTF8;
Console.OutputEncoding = Encoding.UTF8;

var jsonOpts = new JsonSerializerOptions
{
    PropertyNamingPolicy   = JsonNamingPolicy.CamelCase,
    DefaultIgnoreCondition = System.Text.Json.Serialization.JsonIgnoreCondition.WhenWritingNull,
    WriteIndented          = false
};

// ── main stdio loop ────────────────────────────────────────────────────────────

while (true)
{
    var line = await Console.In.ReadLineAsync();
    if (line is null) break;
    if (string.IsNullOrWhiteSpace(line)) continue;

    JsonRpcRequest? req;
    try   { req = JsonSerializer.Deserialize<JsonRpcRequest>(line); }
    catch { await WriteErrorAsync(null, -32700, "Parse error"); continue; }

    if (req is null) { await WriteErrorAsync(null, -32600, "Invalid request"); continue; }

    logger.LogDebug("← {Method} id={Id}", req.Method, req.Id);
    await HandleAsync(req);
}

logger.LogInformation("Server shut down.");

// ── request handler ────────────────────────────────────────────────────────────

async Task HandleAsync(JsonRpcRequest req)
{
    try
    {
        object result = req.Method switch
        {
            "initialize"  => BuildInitializeResult(),
            "initialized" => new { },   // notification — no response body needed
            "tools/list"  => registry.GetTools(),
            "tools/call"  => await HandleToolCallAsync(req),
            "ping"        => new { },
            _             => throw new McpMethodNotFoundException(req.Method)
        };
        await WriteResponseAsync(req.Id, result);
    }
    catch (McpMethodNotFoundException ex)
    {
        logger.LogWarning("Unknown method: {Method}", ex.MethodName);
        await WriteErrorAsync(req.Id, -32601, $"Method not found: {ex.MethodName}");
    }
    catch (Exception ex)
    {
        logger.LogError(ex, "Error handling {Method}", req.Method);
        await WriteErrorAsync(req.Id, -32603, ex.Message);
    }
}

async Task<CallToolResult> HandleToolCallAsync(JsonRpcRequest req)
{
    if (req.Params is null) throw new ArgumentException("Missing params for tools/call");

    var name = req.Params.Value.GetProperty("name").GetString()
               ?? throw new ArgumentException("Missing tool name");

    var arguments = req.Params.Value.TryGetProperty("arguments", out var argEl)
        ? argEl : (JsonElement?)null;

    return await registry.CallAsync(name, arguments);
}

InitializeResult BuildInitializeResult() => new()
{
    ServerInfo   = new() { Name = "slack-mcp-server", Version = "2.0.0" },
    Capabilities = new() { Tools = new() }
};

async Task WriteResponseAsync(object? id, object result)
{
    var json = JsonSerializer.Serialize(new JsonRpcResponse { Id = id, Result = result }, jsonOpts);
    await Console.Out.WriteLineAsync(json);
    await Console.Out.FlushAsync();
}

async Task WriteErrorAsync(object? id, int code, string message)
{
    var json = JsonSerializer.Serialize(
        new JsonRpcResponse { Id = id, Error = new JsonRpcError { Code = code, Message = message } },
        jsonOpts);
    await Console.Out.WriteLineAsync(json);
    await Console.Out.FlushAsync();
}

// ── custom exception ───────────────────────────────────────────────────────────

class McpMethodNotFoundException(string methodName)
    : Exception($"Method not found: {methodName}")
{
    public string MethodName { get; } = methodName;
}

public partial class Program { }
