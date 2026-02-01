# WirePlumber Audio Stability Configuration

## Problem: Audio Disconnection During Meetings

When using audio/video conferencing applications (Google Meet, Zoom, Teams), users may experience sudden audio disconnection or the application showing "Mic not found" / "Speaker not found" errors.

### Root Cause

WirePlumber, the session manager for PipeWire, automatically manages audio device routing. By default, it will:

1. **Re-evaluate default devices** when the audio graph changes
2. **Move existing streams** to follow the new default device
3. **Respond to device state changes** (power saving, suspend, disconnect)

This behavior causes problems in several scenarios:

| Scenario | What Happens |
|----------|--------------|
| **Bluetooth device power saving** | Headset enters low-power mode → WirePlumber sees it as "unavailable" → moves streams to laptop mic/speaker |
| **USB audio device suspend** | USB microphone suspends after idle → WirePlumber re-evaluates priorities → may switch default |
| **New device connected** | Plugging in headphones → WirePlumber may move existing streams to new device |
| **Virtual device creation** | Software creates virtual audio device → triggers graph re-evaluation → disrupts existing streams |

The key setting responsible is `linking.follow-default-target`, which when enabled (default), causes streams to automatically move when the default device changes.

### Symptoms

- Audio suddenly stops working mid-call
- Application shows "Mic not found" even though device is connected
- Need to manually re-select audio device in application settings
- Audio works after refresh but breaks again later
- Issue correlates with Bluetooth headset going idle or USB device power cycling

## Solution

Disable automatic stream following so existing connections remain stable:

```bash
wpctl settings --save linking.follow-default-target false
```

This setting:
- **Persists across reboots** (saved to WirePlumber state)
- **Prevents stream disruption** when devices change state
- **Still allows manual switching** via application dropdowns or system settings
- **Does not affect new streams** - they still connect to the default device initially

### Verify the Setting

```bash
# Check current value
wpctl settings | grep follow-default-target

# Should show:
# Value: false  [Saved: false]
```

### What This Changes

| Behavior | Before (default) | After (disabled) |
|----------|------------------|------------------|
| Bluetooth headset sleeps | Streams move to laptop speaker | Streams stay connected, resume when headset wakes |
| USB mic suspends | May switch to built-in mic | Stays on USB mic |
| New device plugged in | May move streams to new device | Existing streams unchanged |
| Device unplugged | Streams moved to fallback | Streams disconnected (expected) |

## Alternative: Per-Application Pinning

If you need more granular control, you can pin specific applications to specific devices using PipeWire metadata:

```bash
# Find the stream's node ID
pw-cli ls Node | grep -A5 "Chrome"

# Pin a stream to a specific device (by node serial)
pw-metadata -n default <stream-id> target.object <device-serial>
```

However, the global `follow-default-target` setting is usually sufficient.

## Related Settings

Other WirePlumber settings that affect audio stability:

```bash
# View all linking-related settings
wpctl settings | grep -E "linking|target|move"
```

| Setting | Default | Description |
|---------|---------|-------------|
| `linking.follow-default-target` | true | Streams follow when default changes |
| `linking.allow-moving-streams` | true | Allow runtime stream movement via metadata |
| `linking.pause-playback` | true | Pause media if output device removed |
| `node.stream.restore-target` | true | Remember stream→device associations |

## Troubleshooting

### Check Current Audio Routing

```bash
# Show all audio connections
pw-link -l

# Show stream details
pactl list source-outputs  # Recording streams (mic)
pactl list sink-inputs     # Playback streams (speaker)
```

### Manually Reconnect a Stream

If a stream gets disconnected, you can manually reconnect it:

```bash
# List available sources (microphones)
pactl list sources short

# Move a recording stream to a specific source
pactl move-source-output <stream-id> <source-name>

# List available sinks (speakers)
pactl list sinks short

# Move a playback stream to a specific sink
pactl move-sink-input <stream-id> <sink-name>
```

### Reset to Defaults

If you need to restore default WirePlumber behavior:

```bash
wpctl settings --save linking.follow-default-target true
```

## References

- [WirePlumber Linking Policy](https://pipewire.pages.freedesktop.org/wireplumber/policies/linking.html)
- [WirePlumber Settings](https://pipewire.pages.freedesktop.org/wireplumber/daemon/configuration/settings.html)
- [PipeWire Documentation](https://docs.pipewire.org/)
