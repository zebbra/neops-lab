#!/bin/sh
# Runs via containerlab `exec` AFTER links are wired. Sets the Linux interface
# alias (== description, read by the SDK FRR plugin) for every interface in the
# per-node .iface file. Real data ports (swpN) and stub `dummy` ports already
# exist (containerlab created them); `lo` exists too. The `ip link add ... dummy`
# is a belt-and-suspenders fallback only for a name that somehow isn't present.
IFACE_FILE="/etc/frr/lab-interfaces/$(hostname).iface"
[ -f "$IFACE_FILE" ] || exit 0
while IFS='|' read -r name desc; do
    [ -z "$name" ] && continue
    ip link show "$name" >/dev/null 2>&1 || ip link add "$name" type dummy 2>/dev/null || true
    [ -n "$desc" ] && ip link set dev "$name" alias "$desc" 2>/dev/null || true
    ip link set dev "$name" up 2>/dev/null || true
done < "$IFACE_FILE"
