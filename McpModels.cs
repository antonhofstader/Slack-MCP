using System.Text.Json.Serialization;

namespace SlackMcpServer.Models;

// ── JSON-RPC 2.0 ───────────────────────────────────────────────────────────────

public sealed class JsonRpcRequest
{
    [JsonPropertyName("jsonrpc")] public string  Jsonrpc { get; set; } = "2.0";
    [JsonPropertyName("id")]      public object? Id      { get; set; }
    [JsonPropertyName("method")]  public string  Method  { get; set; } = "";
    [JsonPropertyName("params")]  public System.Text.Json.JsonElement? Params { get; set; }
}

public sealed class JsonRpcResponse
{
    [JsonPropertyName("jsonrpc")] public string       Jsonrpc { get; set; } = "2.0";
    [JsonPropertyName("id")]      public object?      Id      { get; set; }
    [JsonPropertyName("result")]  public object?      Result  { get; set; }
    [JsonPropertyName("error")]   public JsonRpcError? Error  { get; set; }
}

public sealed class JsonRpcError
{
    [JsonPropertyName("code")]    public int     Code    { get; set; }
    [JsonPropertyName("message")] public string  Message { get; set; } = "";
    [JsonPropertyName("data")]    public object? Data    { get; set; }
}

// ── MCP protocol ───────────────────────────────────────────────────────────────

public sealed class InitializeResult
{
    [JsonPropertyName("protocolVersion")] public string             ProtocolVersion { get; set; } = "2024-11-05";
    [JsonPropertyName("capabilities")]    public ServerCapabilities Capabilities    { get; set; } = new();
    [JsonPropertyName("serverInfo")]      public ServerInfo         ServerInfo      { get; set; } = new();
}

public sealed class ServerCapabilities
{
    [JsonPropertyName("tools")] public ToolsCapability? Tools { get; set; }
}

public sealed class ToolsCapability
{
    [JsonPropertyName("listChanged")] public bool ListChanged { get; set; } = false;
}

public sealed class ServerInfo
{
    [JsonPropertyName("name")]    public string Name    { get; set; } = "slack-mcp-server";
    [JsonPropertyName("version")] public string Version { get; set; } = "2.0.0";
}

public sealed class ListToolsResult
{
    [JsonPropertyName("tools")] public List<Tool> Tools { get; set; } = [];
}

public sealed class Tool
{
    [JsonPropertyName("name")]        public string      Name        { get; set; } = "";
    [JsonPropertyName("description")] public string      Description { get; set; } = "";
    [JsonPropertyName("inputSchema")] public InputSchema InputSchema { get; set; } = new();
}

public sealed class InputSchema
{
    [JsonPropertyName("type")]       public string                              Type       { get; set; } = "object";
    [JsonPropertyName("properties")] public Dictionary<string, SchemaProperty> Properties { get; set; } = [];
    [JsonPropertyName("required")]   public List<string>                       Required   { get; set; } = [];
}

public sealed class SchemaProperty
{
    [JsonPropertyName("type")]        public string        Type        { get; set; } = "string";
    [JsonPropertyName("description")] public string        Description { get; set; } = "";
    [JsonPropertyName("enum")]        public List<string>? Enum        { get; set; }
}

public sealed class CallToolResult
{
    [JsonPropertyName("content")] public List<ContentItem> Content { get; set; } = [];
    [JsonPropertyName("isError")] public bool              IsError { get; set; } = false;
}

public sealed class ContentItem
{
    [JsonPropertyName("type")] public string Type { get; set; } = "text";
    [JsonPropertyName("text")] public string Text { get; set; } = "";
}
