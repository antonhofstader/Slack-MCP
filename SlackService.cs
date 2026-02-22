using System.Net.Http.Headers;
using System.Text;
using System.Text.Json;
using Microsoft.Extensions.Logging;

namespace SlackMcpServer.Services;

// ── Layer 4 — Slack Web API ────────────────────────────────────────────────────
//
// This service is the deepest layer of the stack.
// It maps directly onto the six Slack capabilities declared in the architecture:
//
//   send_message     → chat.postMessage
//   get_history      → conversations.history
//   list_channels    → conversations.list
//   create_channel   → conversations.create
//   add_reaction     → reactions.add
//   list_users       → users.list
//
// All public methods throw SlackException on API-level failures.

public sealed class SlackService(ILogger<SlackService> logger)
{
    private readonly HttpClient _http = new() { BaseAddress = new Uri("https://slack.com/api/") };

    private string BotToken =>
        Environment.GetEnvironmentVariable("SLACK_BOT_TOKEN")
        ?? throw new InvalidOperationException("SLACK_BOT_TOKEN environment variable is not set.");

    // ── send_message ────────────────────────────────────────────────────────────

    public async Task<string> SendMessageAsync(string channel, string text, string? threadTs = null)
    {
        logger.LogInformation("[Slack] chat.postMessage → {Channel}", channel);
        var payload = new Dictionary<string, object> { ["channel"] = channel, ["text"] = text };
        if (threadTs is not null) payload["thread_ts"] = threadTs;

        var root = await PostAsync("chat.postMessage", payload);
        return root.GetProperty("ts").GetString() ?? "";
    }

    // ── get_history ─────────────────────────────────────────────────────────────

    public async Task<List<SlackMessage>> GetHistoryAsync(string channel, int limit = 10)
    {
        logger.LogInformation("[Slack] conversations.history → {Channel} (limit={Limit})", channel, limit);
        var root = await GetAsync("conversations.history",
            new() { ["channel"] = channel, ["limit"] = limit.ToString() });

        return [.. root.GetProperty("messages").EnumerateArray().Select(m => new SlackMessage(
            User: m.TryGetProperty("user",  out var u)  ? u.GetString()  ?? "" : "bot",
            Text: m.TryGetProperty("text",  out var t)  ? t.GetString()  ?? "" : "",
            Ts:   m.TryGetProperty("ts",    out var ts) ? ts.GetString() ?? "" : ""
        ))];
    }

    // ── list_channels ───────────────────────────────────────────────────────────

    public async Task<List<SlackChannel>> ListChannelsAsync(string types = "public_channel")
    {
        logger.LogInformation("[Slack] conversations.list (types={Types})", types);
        var root = await GetAsync("conversations.list",
            new() { ["types"] = types, ["limit"] = "200" });

        return [.. root.GetProperty("channels").EnumerateArray().Select(c => new SlackChannel(
            Id:        c.GetProperty("id").GetString()   ?? "",
            Name:      c.GetProperty("name").GetString() ?? "",
            IsPrivate: c.TryGetProperty("is_private", out var priv) && priv.GetBoolean()
        ))];
    }

    // ── create_channel ──────────────────────────────────────────────────────────

    public async Task<string> CreateChannelAsync(string name)
    {
        logger.LogInformation("[Slack] conversations.create → #{Name}", name);
        var root = await PostAsync("conversations.create", new { name, is_private = false });
        return root.GetProperty("channel").GetProperty("id").GetString() ?? "";
    }

    // ── add_reaction ────────────────────────────────────────────────────────────

    public async Task AddReactionAsync(string channel, string timestamp, string emoji)
    {
        logger.LogInformation("[Slack] reactions.add :{Emoji}: → {Channel}/{Ts}", emoji, channel, timestamp);
        await PostAsync("reactions.add", new { channel, timestamp, name = emoji });
    }

    // ── list_users ──────────────────────────────────────────────────────────────

    public async Task<List<SlackUser>> ListUsersAsync()
    {
        logger.LogInformation("[Slack] users.list");
        var root = await GetAsync("users.list", new());

        return [.. root.GetProperty("members")
            .EnumerateArray()
            .Where(m => !(m.TryGetProperty("deleted", out var del) && del.GetBoolean()))
            .Select(m => new SlackUser(
                Id:       m.GetProperty("id").GetString()   ?? "",
                Name:     m.GetProperty("name").GetString() ?? "",
                RealName: m.TryGetProperty("real_name", out var rn) ? rn.GetString() ?? "" : ""
            ))];
    }

    // ── HTTP helpers ────────────────────────────────────────────────────────────

    private async Task<JsonElement> PostAsync(string endpoint, object payload)
    {
        var req = new HttpRequestMessage(HttpMethod.Post, endpoint)
        {
            Content = new StringContent(JsonSerializer.Serialize(payload), Encoding.UTF8, "application/json")
        };
        req.Headers.Authorization = new AuthenticationHeaderValue("Bearer", BotToken);
        return await SendAsync(req);
    }

    private async Task<JsonElement> GetAsync(string endpoint, Dictionary<string, string> query)
    {
        var qs  = string.Join("&", query.Select(kv => $"{Uri.EscapeDataString(kv.Key)}={Uri.EscapeDataString(kv.Value)}"));
        var req = new HttpRequestMessage(HttpMethod.Get, $"{endpoint}?{qs}");
        req.Headers.Authorization = new AuthenticationHeaderValue("Bearer", BotToken);
        return await SendAsync(req);
    }

    private async Task<JsonElement> SendAsync(HttpRequestMessage req)
    {
        var resp = await _http.SendAsync(req);
        resp.EnsureSuccessStatusCode();
        var root = JsonDocument.Parse(await resp.Content.ReadAsStringAsync()).RootElement;

        if (root.TryGetProperty("ok", out var ok) && !ok.GetBoolean())
        {
            var err = root.TryGetProperty("error", out var e) ? e.GetString() : "unknown_error";
            throw new SlackException(err ?? "unknown_error");
        }
        return root;
    }
}

// ── DTOs ───────────────────────────────────────────────────────────────────────

public record SlackMessage(string User, string Text, string Ts);
public record SlackChannel(string Id, string Name, bool IsPrivate);
public record SlackUser(string Id, string Name, string RealName);

public sealed class SlackException(string error)
    : Exception($"Slack API error: {error}")
{
    public string SlackError { get; } = error;
}
