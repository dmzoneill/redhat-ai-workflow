#!/bin/bash
# Memory monitor for redhat-ai-workflow services
# Checks every 3 minutes for 1 hour (20 samples)
# Outputs timestamped RSS memory in MB for each service

LOG_FILE="/tmp/memory_monitor_$(date +%Y%m%d_%H%M%S).log"
INTERVAL=180  # 3 minutes in seconds
SAMPLES=20    # 20 samples × 3 min = 60 min

echo "=== Memory Monitor Started ===" | tee "$LOG_FILE"
echo "Log file: $LOG_FILE"
echo "Interval: ${INTERVAL}s, Samples: $SAMPLES"
echo "Start time: $(date '+%Y-%m-%d %H:%M:%S')" | tee -a "$LOG_FILE"
echo "" | tee -a "$LOG_FILE"

# Print header
printf "%-20s | %-8s | %-8s | %-8s | %-8s | %-8s | %-8s | %-8s | %-8s | %-8s | %-8s\n" \
    "Timestamp" "Slack" "Meet" "Config" "Stats" "Memory" "Sprint" "Cron" "Slop" "Video" "TOTAL" | tee -a "$LOG_FILE"
printf "%s\n" "$(printf '%.0s-' {1..130})" | tee -a "$LOG_FILE"

for i in $(seq 1 $SAMPLES); do
    TS=$(date '+%H:%M:%S')

    # Get RSS in MB for each service (0 if not running)
    get_rss() {
        local name="$1"
        local pid=$(pgrep -f "python3 -m services\.${name}$" 2>/dev/null | head -1)
        if [ -n "$pid" ]; then
            # RSS from /proc in KB, convert to MB
            local rss_kb=$(awk '/^VmRSS:/ {print $2}' /proc/$pid/status 2>/dev/null)
            if [ -n "$rss_kb" ]; then
                echo $(( rss_kb / 1024 ))
            else
                echo "0"
            fi
        else
            echo "-"
        fi
    }

    SLACK=$(get_rss slack)
    MEET=$(get_rss meet)
    CONFIG=$(get_rss config)
    STATS=$(get_rss stats)
    MEMORY=$(get_rss memory)
    SPRINT=$(get_rss sprint)
    CRON=$(get_rss cron)
    SLOP=$(get_rss slop)
    VIDEO=$(get_rss video)

    # Calculate total (only numeric values)
    TOTAL=0
    for val in $SLACK $MEET $CONFIG $STATS $MEMORY $SPRINT $CRON $SLOP $VIDEO; do
        if [ "$val" != "-" ]; then
            TOTAL=$((TOTAL + val))
        fi
    done

    printf "%-20s | %6sMB | %6sMB | %6sMB | %6sMB | %6sMB | %6sMB | %6sMB | %6sMB | %6sMB | %6sMB\n" \
        "$TS" "$SLACK" "$MEET" "$CONFIG" "$STATS" "$MEMORY" "$SPRINT" "$CRON" "$SLOP" "$VIDEO" "$TOTAL" | tee -a "$LOG_FILE"

    # Don't sleep after the last sample
    if [ $i -lt $SAMPLES ]; then
        sleep $INTERVAL
    fi
done

echo "" | tee -a "$LOG_FILE"
echo "=== Memory Monitor Complete ===" | tee -a "$LOG_FILE"
echo "End time: $(date '+%Y-%m-%d %H:%M:%S')" | tee -a "$LOG_FILE"
echo "Log saved to: $LOG_FILE"
