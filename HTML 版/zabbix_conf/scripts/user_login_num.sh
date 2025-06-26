#!/bin/bash

# 是否輸出為 JSON 格式
OUTPUT_JSON=0

# 處理傳入參數
for arg in "$@"; do
  if [ "$arg" == "json" ]; then
    OUTPUT_JSON=1
  fi
done

# === 設定參數 ===
CONTAINER_DB="postgresql"
CONTAINER_APP="core"
DB_USER="docker"
DB_PASSWORD="docker"
EXPORT_FILE="my_table_export.csv"
LOGDIR="/tmp"

# === 自動判斷目前年月 ===
DATE_TAG=$(date +%Y%m)
ACCOUNT_FILE="$LOGDIR/${DATE_TAG}_account.csv"
PREV_TAG=$(date -d "$(date +%Y-%m-01) -1 month" +%Y%m)
PREV_FILE="$LOGDIR/${PREV_TAG}_account.csv"

# === 判斷是否需要重新產生 CSV ===
NEED_EXPORT=0

if [ ! -f "$ACCOUNT_FILE" ]; then
  echo "⚠ 找不到本月帳號檔案：$ACCOUNT_FILE"
  NEED_EXPORT=1
elif [ -f "$PREV_FILE" ] && [ "$ACCOUNT_FILE" -ot "$PREV_FILE" ]; then
  echo "⚠ 本月帳號檔案較舊，或仍是上月版本：$PREV_FILE"
  NEED_EXPORT=1
else
  echo "✅ 已存在本月帳號檔案：$ACCOUNT_FILE"
fi

# === 匯出 PostgreSQL 使用者資料 ===
if [ "$NEED_EXPORT" -eq 1 ]; then
  echo "[1] 重新匯出 PostgreSQL 使用者資料..."
  docker exec -e PGPASSWORD="$DB_PASSWORD" -i $CONTAINER_DB \
    psql -h localhost -U $DB_USER -c "\copy (SELECT id,username,firstname || lastname AS user_name FROM sec_user) TO '$EXPORT_FILE' WITH CSV HEADER"

  if [ $? -ne 0 ]; then
    echo "❌ 匯出失敗"
    exit 1
  fi

  echo "[2] 複製 CSV 並覆蓋為：$ACCOUNT_FILE"
  docker cp $CONTAINER_DB:/$EXPORT_FILE "$ACCOUNT_FILE"
else
  echo "✅ 跳過資料匯出，使用現有帳號檔案：$ACCOUNT_FILE"
fi

# === 取得登入紀錄並分析 ===
echo "[3] 分析使用者登入紀錄..."
mkdir -p "$LOGDIR"
docker exec $CONTAINER_APP grep 'Success' /var/log/tomcat7/catalina.out | grep user > "$LOGDIR/user_login.log"

# 統計登入 user:id 次數
awk '{match($0, /user:[0-9]+/, arr); if (arr[0] != "") count[substr(arr[0],6)]++ }
     END { for (id in count) print id, count[id] }' "$LOGDIR/user_login.log" > "$LOGDIR/user_count.log"

# 轉換格式
sed -i 's/ /,/g' "$LOGDIR/user_count.log"
sed -i 's/ /_/g' "$ACCOUNT_FILE"

# 合併帳號與統計數據
total=$(awk -F',' '{sum += $2} END {print sum}' "$LOGDIR/user_count.log")

awk -F', *' '
NR==FNR { id = $1 + 0; accounts[id]=$2; names[id]=$3; next }
{ id = $1 + 0; print ( id in accounts ? accounts[id] : "Unknown" ),
( id in names ? names[id] : "Unknown" ), $2
}' "$ACCOUNT_FILE" "$LOGDIR/user_count.log" > "$LOGDIR/user_login_num.log"

# 排序前 11 名，加入表頭與統計期間
sort -r -k3 "$LOGDIR/user_login_num.log" | head -n 11 > "$LOGDIR/user_login_num2.log"
sed -i '1i User_ID Username Count' "$LOGDIR/user_login_num2.log"
date_start=$(head -n 1 "$LOGDIR/user_login.log" | awk '{print $1 "_" $2}')
date_to=$(tail -n 1 "$LOGDIR/user_login.log" | awk '{print $1 "_" $2}')
period="$date_start ~ $date_to"
sed -i "1i $period" "$LOGDIR/user_login_num2.log"

# 顯示結果
if [ "$OUTPUT_JSON" -eq 1 ]; then
  echo "["
  total_lines=$(($(wc -l < "$LOGDIR/user_login_num2.log") - 2))  # 扣掉 header 兩行
  tail -n +3 "$LOGDIR/user_login_num2.log" | awk -v total="$total_lines" '
    {
      user_id = $1;
      username = $2;
      count = $3;
      printf "  {\"User_ID\": \"%s\", \"Username\": \"%s\", \"Count\": %s}", user_id, username, count;
      if (NR < total) print ","; else print ""
    }
  '
  echo "]"
else
  echo "✅ 完成，總登入數：$total"
  column -t "$LOGDIR/user_login_num2.log"
fi
