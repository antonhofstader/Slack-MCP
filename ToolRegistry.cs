using System.Text.Json;
using Microsoft.Extensions.Logging;
using SlackMcpServer.Models;
using SlackMcpServer.Services;

namespace SlackMcpServer.Tools;

/// <summary>
/// Layer 3 (server-side) — maps MCP tool definitions to SlackService calls.
///
/// Each of the six tools corresponds 1-to-1 with a Slack capability from
/// the architecture diagram:
///   slack_send_message          → send_message
///   slack_get_channel_history   → get_history
///   slack_list_channels         → list_channels
///   slack_create_channel        → create_channel
///   slack_add_reaction          → add_reaction
///   slack_list_users            → list_users
/// </summary>
public sealed class ToolRegistry(SlackService slack, ILogger<ToolRegistry> logger)
{
    // ── Tool definitions (returned to MCP client on tools/list) ────────────────

    public ListToolsResult GetTools() => new()
    {
        Tools =
        [
            new Tool
            {
                Name        = "slack_send_message",
                Description = "Post a message to a Slack channel or reply in a thread.",
                InputSchema = new()
                {
                    Properties = new()
                    {
                        ["channel"]   = Prop("Channel ID or name (e.g. C012AB3CD)"),
                        ["text"]      = Prop("Message text — supports Slack mrkdwn"),
                        ["thread_ts"] = Prop("Parent message timestamp for thread replies (optional)")
                    },
                    Required = ["channel", "text"]
                }
            },

            new Tool
            {
                Name        = "slack_get_channel_history",
                Description = "Retrieve recent messages from a Slack channel.",
                InputSchema = new()
                {
                    Properties = new()
                    {
                        ["channel"] = Prop("Channel ID (e.g. C012AB3CD)"),
                        ["limit"]   = Prop("Number of messages (default 10, max 100)")
                    },
                    Required = ["channel"]
                }
            },

            new Tool
            {
                Name        = "slack_list_channels",
                Description = "List Slack channels visible to the bot.",
                InputSchema = new()
                {
                    Properties = new()
                    {
                        ["types"] = Prop("Comma-separated channel types",
                            ["public_channel", "private_channel", "mpim", "im"])
                    }
                }
            },

            new Tool
            {
                Name        = "slack_create_channel",
                Description = "Create a new public Slack channel.",
                InputSchema = new()
                {
                    Properties = new()
                    {
                        ["name"] = Prop("Channel name (lowercase, no spaces)")
                    },
                    Required = ["name"]
                }
            },

            new Tool
            {
                Name        = "slack_add_reaction",
                Description = "Add an emoji reaction to a Slack message.",
                InputSchema = new()
                {
                    Properties = new()
                    {
                        ["channel"]   = Prop("Channel ID containing the message"),
                        ["timestamp"] = Prop("Timestamp (ts) of the target message"),
                        ["emoji"]     = Prop("Emoji name without colons (e.g. thumbsup)")
                    },
                    Required = ["channel", "timestamp", "emoji"]
                }
            },

            new Tool
            {
                Name        = "slack_list_users",
                Description = "List all active users in the Slack workspace.",
                InputSchema = new()
            }
        ]
    };

    // ── Dispatcher ─────────────────────────────────────────────────────────────

    public async Task<CallToolResult> CallAsync(string name, JsonElement? args)
    {
        logger.LogInformation("Tool call: {Name}", name);
        try
        {
            return name switch
            {
                "slack_send_message"         => await SendMessage(args),
                "slack_get_channel_history"  => await GetHistory(args),
                "slack_list_channels"        => await ListChannels(args),
                "slack_create_channel"       => await CreateChannel(args),
                "slack_add_reaction"         => await AddReaction(args),
                "slack_list_users"           => await ListUsers(),
                _                            => Error($"Unknown tool: {name}")
            };
        }
        catch (SlackException ex)
        {
            logger.LogError(ex, "Slack error in {Name}", name);
            return Error($"Slack error: {ex.SlackError}");
        }
        catch (Exception ex)
        {
            logger.LogError(ex, "Unexpected error in {Name}", name);
            return Error(ex.Message);
        }
    }

    // ── Tool implementations ───────────────────────────────────────────────────

    private async Task<CallToolResult> SendMessage(JsonElement? a)
    {
        var ts = await slack.SendMessageAsync(Req(a, "channel"), Req(a, "text"), Opt(a, "thread_ts"));
        return Ok($"Message sent. Timestamp: {ts}");
    }

    private async Task<CallToolResult> GetHistory(JsonElement? a)
    {
        var limit = int.TryParse(Opt(a, "limit"), out var l) ? l : 10;
        var msgs  = await slack.GetHistoryAsync(Req(a, "channel"), limit);
        if (msgs.Count == 0) return Ok("No messages found.");
        return Ok(string.Join("\n", msgs.Select(m => $"[{m.Ts}] {m.User}: {m.Text}")));
    }

    private async Task<CallToolResult> ListChannels(JsonElement? a)
    {
        var channels = await slack.ListChannelsAsync(Opt(a, "types") ?? "public_channel");
        if (channels.Count == 0) return Ok("No channels found.");
        return Ok(string.Join("\n", channels.Select(c => $"{c.Id} | #{c.Name}{(c.IsPrivate ? " [private]" : "")}")));
    }

    private async Task<CallToolResult> CreateChannel(JsonElement? a)
    {
        var id = await slack.CreateChannelAsync(Req(a, "name"));
        return Ok($"Channel #{Req(a, "name")} created. ID: {id}");
    }

    private async Task<CallToolResult> AddReaction(JsonElement? a)
    {
        await slack.AddReactionAsync(Req(a, "channel"), Req(a, "timestamp"), Req(a, "emoji"));
        return Ok($"Reaction :{Req(a, "emoji")}: added.");
    }

    private async Task<CallToolResult> ListUsers()
    {
        var users = await slack.ListUsersAsync();
        if (users.Count == 0) return Ok("No users found.");
        return Ok(string.Join("\n", users.Select(u => $"{u.Id} | @{u.Name} ({u.RealName})")));
    }

    // ── Helpers ────────────────────────────────────────────────────────────────

    private static SchemaProperty Prop(string desc, List<string>? @enum = null) =>
        new() { Type = "string", Description = desc, Enum = @enum };

    private static string Req(JsonElement? args, string key)
    {
        if (args is null || !args.Value.TryGetProperty(key, out var val) || val.ValueKind == JsonValueKind.Null)
            throw new ArgumentException($"Missing required argument: {key}");
        return val.GetString() ?? throw new ArgumentException($"Argument '{key}' must be a string.");
    }

    private static string? Opt(JsonElement? args, string key) =>
        args?.TryGetProperty(key, out var val) == true ? val.GetString() : null;

    private static CallToolResult Ok(string text)    => new() { Content = [new() { Text = text }] };
    private static CallToolResult Error(string text) => new() { Content = [new() { Text = text }], IsError = true };
}
