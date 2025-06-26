
run_sql() {
    local sql="$1"
    docker exec -i postgresql bash -c "PGPASSWORD='docker' psql -h localhost -U docker -t -A -c \"$sql\""
}

sql="select count(1) from abstract_image;"

value=$(run_sql "$sql") 

echo "num" $value

sql="
WITH
prev_month AS (
  SELECT COUNT(1)::float AS total
  FROM abstract_image
  WHERE created BETWEEN '2025-01-01' AND '2025-01-31'
),
this_month AS (
  SELECT COUNT(1)::float AS total
  FROM abstract_image
  WHERE created BETWEEN '2025-02-01' AND '2025-02-28'
)
SELECT
  this_month.total AS this_month_total,
  prev_month.total AS prev_month_total,
  CASE
    WHEN prev_month.total = 0 THEN NULL
    ELSE ROUND(
      ((this_month.total - prev_month.total) / prev_month.total)::numeric, 2
    )
  END AS growth_rate_percent
FROM this_month, prev_month;
"

value=$(run_sql "$sql")

echo "last $(echo $value | awk -F '|' '{print $2}')"
echo "this $(echo $value | awk -F '|' '{print $1}')"
echo "grow $(echo $value | awk -F '|' '{print $3}')"

