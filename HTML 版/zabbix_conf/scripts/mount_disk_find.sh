#!/bin/bash
# 發現所有磁碟設備並輸出 JSON 格式
echo "{"
echo "  \"data\": ["
first=1
while read -r mountpoint dev; do
    dev_basename=$(basename "$dev")
    # 找出 dm 名稱對應
    dmname=$(lsblk -no KNAME "$dev" 2>/dev/null | grep ^dm)
    [ -z "$dmname" ] && continue
    [ $first -eq 0 ] && echo ","
    first=0
    echo "    {\"{#DISK}\": \"$dmname\", \"{#MOUNTPOINT}\": \"$mountpoint\"}"
done < <(df --output=target,source | grep ^/ | grep mapper)
echo "  ]"
echo "}"
